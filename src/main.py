"""CLI entry point for the Testing and Evaluation Agent."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from src.agents.testing_agent import TestingEvaluationAgent, create_testing_agent
from src.config import Settings, get_settings
from src.models.common import ArtifactReference
from src.models.conversation import ConversationSession
from src.models.enums import ConversationState, TestCategory
from src.models.playwright import PlaywrightExecutionResult
from src.tools.skill_loader import SkillLoader


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="testing-eval-agent",
        description="Testing and Evaluation Agent command-line interface.",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "healthcheck",
        help="Validate configuration and print runtime health status.",
    )

    subparsers.add_parser(
        "list-skills",
        help="List available skill folders with SKILL.md files.",
    )

    subparsers.add_parser(
        "show-config",
        help="Print safe non-secret runtime configuration.",
    )

    summarize_parser = subparsers.add_parser(
        "summarize",
        help="Summarize user intent using configured model client.",
    )
    summarize_parser.add_argument(
        "--prompt",
        required=True,
        help="User prompt to summarize.",
    )

    chat_parser = subparsers.add_parser(
        "chat",
        help="Start an interactive testing conversation.",
    )
    chat_parser.add_argument(
        "--target-type",
        dest="target_type",
        default=None,
        help="Optional target type hint (e.g. web_app, vscode_extension).",
    )

    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume an existing interactive testing conversation.",
    )
    resume_parser.add_argument(
        "--session-id",
        dest="session_id",
        required=True,
        help="UUID of the session to resume.",
    )

    return parser


def _safe_settings_snapshot(settings: Settings) -> dict[str, object]:
    return {
        "app_name": settings.APP_NAME,
        "app_env": settings.APP_ENV,
        "log_level": settings.LOG_LEVEL,
        "maf_auth_mode": settings.MAF_AUTH_MODE,
        "maf_project_endpoint": settings.MAF_PROJECT_ENDPOINT,
        "maf_model_name": settings.MAF_MODEL_NAME,
        "maf_model_api_key_configured": settings.MAF_MODEL_API_KEY is not None,
        "approval_gates_enabled": settings.approval_gates_enabled,
        "require_test_case_approval": settings.REQUIRE_TEST_CASE_APPROVAL,
        "require_script_approval": settings.REQUIRE_SCRIPT_APPROVAL,
        "require_evaluation_approval": settings.REQUIRE_EVALUATION_APPROVAL,
        "allow_live_test_execution": settings.ALLOW_LIVE_TEST_EXECUTION,
        "allow_destructive_tests": settings.ALLOW_DESTRUCTIVE_TESTS,
        "skills_dir": Path(settings.SKILLS_DIR).as_posix(),
        "generated_specs_dir": Path(settings.GENERATED_SPECS_DIR).as_posix(),
        "approved_specs_dir": Path(settings.APPROVED_SPECS_DIR).as_posix(),
        "generated_tests_dir": Path(settings.GENERATED_TESTS_DIR).as_posix(),
        "reports_dir": Path(settings.REPORTS_DIR).as_posix(),
        "traces_dir": Path(settings.TRACES_DIR).as_posix(),
        "screenshots_dir": Path(settings.SCREENSHOTS_DIR).as_posix(),
        "eval_datasets_dir": Path(settings.EVAL_DATASETS_DIR).as_posix(),
        "eval_rubrics_dir": Path(settings.EVAL_RUBRICS_DIR).as_posix(),
        "eval_baselines_dir": Path(settings.EVAL_BASELINES_DIR).as_posix(),
        "eval_results_dir": Path(settings.EVAL_RESULTS_DIR).as_posix(),
        "target_base_url": settings.TARGET_BASE_URL,
        "playwright_browser": settings.PLAYWRIGHT_BROWSER,
        "playwright_headless": settings.PLAYWRIGHT_HEADLESS,
        "playwright_timeout_ms": settings.PLAYWRIGHT_TIMEOUT_MS,
        "playwright_retries": settings.PLAYWRIGHT_RETRIES,
        "playwright_workers": settings.PLAYWRIGHT_WORKERS,
        "playwright_mcp_enabled": settings.PLAYWRIGHT_MCP_ENABLED,
        "github_mcp_enabled": settings.GITHUB_MCP_ENABLED,
        "github_mcp_mode": (
            "hosted"
            if settings.GITHUB_MCP_URL
            else "stdio"
            if settings.GITHUB_MCP_COMMAND
            else "disabled"
        ),
        "github_mcp_url": settings.GITHUB_MCP_URL,
        "github_mcp_token_configured": settings.GITHUB_MCP_TOKEN is not None,
        "github_mcp_private_repositories_enabled": (
            settings.GITHUB_MCP_ALLOW_PRIVATE_REPOSITORIES
        ),
        "ado_mcp_enabled": settings.ADO_MCP_ENABLED,
    }


def _run_chat(settings: Settings, target_type_hint: str | None) -> int:
    """Interactive terminal chat loop — business logic stays in the agent/workflow layer."""
    from src.agents.conversation_agent import ConversationAgent, ConversationAgentError

    agent = create_testing_agent(settings=settings)
    ca = ConversationAgent(model_client=agent._model_client)

    try:
        session = agent.start_conversation(target_type_hint=target_type_hint)
    except ConversationAgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"\nSession started: {session.session_id}")
    print("Type your answer and press Enter. Type 'quit' to exit.\n")

    while True:
        # Pipeline handoff: conversation confirmed scope, now run tests
        if session.state == ConversationState.GENERATING_TEST_CASES:
            if session.pending_question:
                print(f"\n[Agent]: {session.pending_question}\n")
            return _run_test_pipeline(agent, session, settings)

        if session.is_terminal():
            if session.pending_question:
                print(f"\n[Agent]: {session.pending_question}\n")
            print(f"\nSession {session.state.value}: {session.session_id}")
            return 0

        if session.pending_question:
            print(f"\n[Agent]: {session.pending_question}\n")

        try:
            user_input = input("[You]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession interrupted.", file=sys.stderr)
            return 130

        if user_input.lower() in ("quit", "exit", "q"):
            print("\nSession saved. Resume with:")
            print(f"  python -m src.main resume --session-id {session.session_id}")
            return 0

        try:
            session = ca.respond(session.session_id, user_input)
        except ConversationAgentError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1


def _run_test_pipeline(
    agent: TestingEvaluationAgent,
    session: ConversationSession,
    settings: Settings,
) -> int:
    """Drive the full test-generation → approval → script-generation → execution pipeline."""
    from uuid import uuid4

    from src.models.enums import ApprovalStatus, TestCategory, WorkflowOutcome, WorkflowStage
    from src.models.playwright import PlaywrightScriptGenerationRequest
    from src.models.test_cases import ImplementationInput, TestCaseGenerationRequest
    from src.workflows.approval_workflow import ApprovalWorkflow

    target_name = session.target_name or "unnamed-target"
    browser_url = session.app_url or ""
    repository_url = session.repo_ref or ""
    target_url = browser_url or repository_url
    environment = session.environment_classification or "development"
    scope_str = (
        ", ".join(c.value for c in session.requested_capabilities)
        if session.requested_capabilities
        else "smoke"
    )
    categories = (
        session.requested_capabilities
        if session.requested_capabilities
        else [TestCategory.SMOKE]
    )
    run_id = session.run_id or uuid4()

    user_request = (
        f"Target name: {target_name}. "
        f"Target type: {session.target_type.value if session.target_type else 'generic_repo'}. "
        f"URL / source: {target_url or '(not provided)'}. "
        f"Environment: {environment}. "
        f"Test scope: {scope_str}."
    )
    if session.forbidden_operations:
        user_request += f" Restrictions: {', '.join(session.forbidden_operations)}."

    evidence_notes: list[str] = []
    if repository_url.startswith("https://github.com/"):
        print("\n[Evidence]: Collecting GitHub repository observations…", flush=True)
        evidence_result = agent.collect_github_evidence(repository_url)
        if evidence_result.success:
            observation_count = len(evidence_result.metadata.get("observations", []))
            evidence_notes.append(
                f"GitHub MCP collected {observation_count} read-only observations."
            )
            print(f"[Evidence]: {evidence_notes[-1]}")
        else:
            print("[Evidence]: GitHub MCP observations unavailable; continuing without them.")
            for warning in evidence_result.errors:
                print(f"  {warning.code}: {warning.message}")

    if browser_url and settings.PLAYWRIGHT_MCP_ENABLED:
        print("\n[Evidence]: Collecting Playwright MCP browser observation…", flush=True)
        observation_result = agent.collect_playwright_snapshot(browser_url)
        if observation_result.success:
            observation_count = len(observation_result.metadata.get("observations", []))
            evidence_notes.append(
                f"Playwright MCP collected {observation_count} browser observation."
            )
            print(f"[Evidence]: {evidence_notes[-1]}")
        else:
            print("[Evidence]: Playwright MCP observation unavailable; continuing without it.")
            for warning in observation_result.errors:
                print(f"  {warning.code}: {warning.message}")

    # ---------------------------------------------------------------
    # Step 1 — Generate test cases
    # ---------------------------------------------------------------
    print("\n" + "─" * 60)
    print("[Testing]: Generating test cases…", flush=True)

    impl_input = ImplementationInput(
        title=f"Smoke test – {target_name}",
        original_user_request=(
            user_request + (" " + " ".join(evidence_notes) if evidence_notes else "")
        ),
        target_scope=f"{scope_str} tests for {target_name} ({environment})",
        constraints=session.forbidden_operations or [],
        source_references=[target_url] if target_url else [],
    )
    gen_request = TestCaseGenerationRequest(
        run_id=run_id,
        implementation_input=impl_input,
        requested_categories=categories,
    )

    tc_result = agent.generate_test_cases(gen_request)

    # blocked = awaiting approval checkpoint (expected); failed = error
    if tc_result.outcome not in (WorkflowOutcome.BLOCKED, WorkflowOutcome.SUCCESS):
        print(f"\n[Error]: Test case generation failed — {tc_result.message}", file=sys.stderr)
        for err in tc_result.errors:
            print(f"  • {err.code}: {err.message}", file=sys.stderr)
        return 1

    tc_artifacts = tc_result.produced_artifacts or []
    if not tc_artifacts or tc_artifacts[0].path is None:
        print("[Error]: Test case generation did not produce a readable artifact.", file=sys.stderr)
        return 1

    test_case_artifact = tc_artifacts[0]
    tc_path = test_case_artifact.path
    assert tc_path is not None
    print(f"[Testing]: Test cases saved → {tc_path}")
    try:
            data = json.loads(tc_path.read_text(encoding="utf-8"))
            cases = data.get("test_cases", [])
            print(f"[Testing]: Generated {len(cases)} test case(s):\n")
            for i, tc in enumerate(cases, 1):
                cat = tc.get("category", "").upper()
                title = tc.get("title", "(untitled)")
                priority = tc.get("priority", "?")
                steps = len(tc.get("steps", []))
                print(f"  {i}. [{cat}] {title}")
                print(f"     Priority: {priority}  |  Steps: {steps}")
    except Exception:
        print("[Testing]: (Could not preview — see saved file)")

    # ---------------------------------------------------------------
    # Approval gate A
    # ---------------------------------------------------------------
    print()
    try:
        approve_tc = input("[Approve test cases? (yes / no / view)]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return 130

    if approve_tc == "view":
        try:
            print("\n" + tc_path.read_text(encoding="utf-8")[:3000])
        except Exception as exc:
            print(f"Could not read file: {exc}")
        try:
            approve_tc = input("[Approve test cases? (yes/no)]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 130

    if approve_tc not in ("yes", "y"):
        print("\n[Testing]: Test case approval declined.")
        _print_summary(session, tc_artifacts, [], settings)
        return 0

    print("[Testing]: Test cases approved. ✓")

    # Record approval so the approval store knows these are approved
    if tc_result.pending_checkpoint:
        approval_wf = ApprovalWorkflow()
        approval_wf.record_decision(
            workflow_state=tc_result.workflow_state,
            checkpoint_id=tc_result.pending_checkpoint.checkpoint_id,
            artifact_reference=test_case_artifact,
            status=ApprovalStatus.APPROVED,
            reviewer="cli-user",
            comments="Approved interactively via CLI",
            next_stage_on_approval=WorkflowStage.TEST_CASES_APPROVED,
            revision_stage_on_rejection=WorkflowStage.AWAITING_TEST_CASE_APPROVAL,
            triggered_by="cli-chat",
        )

    # ---------------------------------------------------------------
    # Step 2 — Generate Playwright scripts
    # ---------------------------------------------------------------
    print("\n[Testing]: Generating Playwright test scripts…", flush=True)

    approved_cases = []
    try:
        from src.models.test_cases import TestCaseCollection

        raw = tc_path.read_text(encoding="utf-8")
        approved_cases = TestCaseCollection.model_validate_json(raw).test_cases
    except Exception as exc:
        print(f"[Warning]: Could not load test cases: {exc}")

    if not approved_cases:
        print("[Testing]: No test cases available for script generation.")
        _print_summary(session, tc_artifacts, [], settings)
        return 0

    # Mark all test cases as APPROVED (user approved them in the CLI gate above)
    from src.models.enums import ApprovalStatus as _AS
    for tc in approved_cases:
        object.__setattr__(tc, "approval_status", _AS.APPROVED)

    script_request = PlaywrightScriptGenerationRequest(
        run_id=run_id,
        source_collection_id=test_case_artifact.artifact_id,
        approved_test_cases=approved_cases,
        approval_reference_id=uuid4(),
    )

    script_result = agent.generate_playwright_scripts(script_request)
    script_artifacts = script_result.produced_artifacts or []

    if not script_artifacts or script_artifacts[0].path is None:
        print("[Error]: Script generation did not produce a readable artifact.", file=sys.stderr)
        return 1

    script_artifact = script_artifacts[0]
    script_path = script_artifact.path
    assert script_path is not None
    print(f"[Testing]: Scripts saved → {script_path}")

    # ---------------------------------------------------------------
    # Approval gate B
    # ---------------------------------------------------------------
    print()
    try:
        approve_sc = input("[Approve scripts and run tests? (yes / no / view)]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return 130

    if approve_sc == "view":
        try:
            print("\n" + script_path.read_text(encoding="utf-8")[:3000])
        except Exception as exc:
            print(f"Could not read file: {exc}")
        try:
            approve_sc = input("[Approve scripts and run tests? (yes/no)]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 130

    if approve_sc not in ("yes", "y"):
        print("\n[Testing]: Script approval declined. Scripts saved for manual review.")
        _print_summary(session, tc_artifacts, script_artifacts, settings)
        return 0

    print("[Testing]: Scripts approved. ✓")
    if script_result.pending_checkpoint is None:
        print("[Error]: Script approval checkpoint or script artifact is missing.", file=sys.stderr)
        return 1

    approval_wf = ApprovalWorkflow()
    script_approval = approval_wf.record_decision(
        workflow_state=script_result.workflow_state,
        checkpoint_id=script_result.pending_checkpoint.checkpoint_id,
        artifact_reference=script_artifact,
        status=ApprovalStatus.APPROVED,
        reviewer="cli-user",
        comments="Approved interactively via CLI",
        next_stage_on_approval=WorkflowStage.PLAYWRIGHT_SCRIPTS_APPROVED,
        revision_stage_on_rejection=WorkflowStage.AWAITING_SCRIPT_APPROVAL,
        triggered_by="cli-chat",
    )
    if script_approval.outcome is not WorkflowOutcome.SUCCESS:
        print(
            f"[Error]: Script approval could not be persisted — {script_approval.message}",
            file=sys.stderr,
        )
        return 1

    try:
        approved_script = _promote_approved_script(script_artifact, categories)
    except (OSError, ValueError) as exc:
        print(f"[Error]: Could not promote approved script — {exc}", file=sys.stderr)
        return 1
    print(f"[Testing]: Approved script ready → {approved_script.path}")

    # ---------------------------------------------------------------
    # Step 3 — Execute or show manual run instructions
    # ---------------------------------------------------------------
    if not settings.ALLOW_LIVE_TEST_EXECUTION:
        print("\n" + "─" * 60)
        print("[Testing]: Live execution is disabled (ALLOW_LIVE_TEST_EXECUTION=False).")
        print("[Testing]: To run these tests, execute:")
        print(f"\n  npx playwright test {approved_script.path}\n")
        _print_summary(session, tc_artifacts, [approved_script], settings)
        return 0

    if not browser_url:
        print(
            "\n[Testing]: Live execution was not started because no browser app URL was provided."
        )
        print(
            "[Testing]: Repository evidence can inform generation, "
            "but it cannot supply a test target."
        )
        _print_summary(session, tc_artifacts, [approved_script], settings)
        return 0

    from src.models.playwright import PlaywrightExecutionRequest
    from src.tools.approval_store import ApprovalStore
    from src.tools.playwright_runner import PlaywrightRunner

    if approved_script.path is None:
        print("[Error]: Approved script does not include an executable path.", file=sys.stderr)
        return 1
    spec_path = approved_script.path
    print(f"\n[Testing]: Running tests… ({spec_path.name})", flush=True)
    approval_record = ApprovalStore().read(approved_script)

    exec_request = PlaywrightExecutionRequest(
        run_id=run_id,
        script_artifact_id=approved_script.artifact_id,
        script_path=spec_path,
        approval_reference_id=approval_record.approval_id,
        target_environment=environment,
        base_url=browser_url,
        browser=settings.PLAYWRIGHT_BROWSER,
        headless=settings.PLAYWRIGHT_HEADLESS,
        retries=settings.PLAYWRIGHT_RETRIES,
        workers=settings.PLAYWRIGHT_WORKERS,
        timeout_ms=settings.PLAYWRIGHT_TIMEOUT_MS,
        capture_screenshot_on_failure=settings.SAVE_SCREENSHOTS_ON_FAILURE,
        capture_trace_on_failure=settings.SAVE_TRACE_ON_FAILURE,
        capture_video_on_failure=settings.SAVE_VIDEO_ON_FAILURE,
        live_execution_approved=True,
    )
    exec_result = PlaywrightRunner(settings=settings).run(exec_request)
    _print_execution_results(exec_result)
    _print_summary(session, tc_artifacts, [approved_script], settings)
    return 0


def _promote_approved_script(
    script_artifact: ArtifactReference,
    categories: Sequence[TestCategory],
) -> ArtifactReference:
    """Copy one approved draft into its executable test directory without overwriting files."""
    from shutil import copy2

    from src.models.common import ArtifactReference
    from src.models.enums import ArtifactStatus, TestCategory
    from src.tools.approval_store import ApprovalStore

    if script_artifact.path is None:
        raise ValueError("Generated script artifact does not include a path.")

    if TestCategory.SMOKE in categories:
        destination_dir = Path("tests/smoke")
    elif TestCategory.INTEGRATION in categories:
        destination_dir = Path("tests/integration")
    else:
        destination_dir = Path("tests/ui")

    destination = destination_dir / script_artifact.path.name
    source = Path(script_artifact.path)
    if destination.exists():
        raise ValueError(f"Approved script already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    copy2(source, destination)
    approved = ArtifactReference(
        artifact_id=script_artifact.artifact_id,
        artifact_type=script_artifact.artifact_type,
        name=script_artifact.name,
        path=destination,
        status=ArtifactStatus.APPROVED,
        created_at=script_artifact.created_at,
    )
    record = ApprovalStore().read(script_artifact)
    ApprovalStore().save(approved, record)
    return approved


def _print_execution_results(result: PlaywrightExecutionResult) -> None:
    """Print a human-readable summary of Playwright execution results."""
    print("\n" + "─" * 60)
    status = result.status
    print(f"[Results]: Execution status: {status}")

    passed = result.passed_tests
    failed = result.failed_tests
    total = passed + failed

    if total:
        print(f"[Results]: {passed}/{total} tests passed")
        if failed:
            print(f"[Results]: {failed} test(s) FAILED")

    if result.errors:
        print("[Results]: Errors:")
        for error in result.errors[:5]:
            print(f"  • {error.message}")


def _print_summary(
    session: ConversationSession,
    tc_artifacts: Sequence[ArtifactReference],
    script_artifacts: Sequence[ArtifactReference],
    settings: Settings,
) -> None:
    """Print a final summary of all saved artifacts."""
    print("\n" + "═" * 60)
    print("[Done]: Session complete.")
    print(f"  Session ID : {session.session_id}")
    print(f"  Target     : {session.target_name} ({getattr(session.target_type, 'value', '?')})")
    print(f"  Scope      : {', '.join(c.value for c in session.requested_capabilities)}")
    print()
    if tc_artifacts:
        print(f"  Test cases : {tc_artifacts[0].path}")
    if script_artifacts:
        print(f"  Scripts    : {script_artifacts[0].path}")
    print()
    print("  To reuse these assets in a future session:")
    print(f"    python -m src.main resume --session-id {session.session_id}")
    print("═" * 60)


def _run_resume(settings: Settings, session_id: UUID) -> int:
    """Resume an existing chat session and continue the interactive loop."""
    from src.agents.conversation_agent import ConversationAgent, ConversationAgentError

    try:
        ca = ConversationAgent()
        session = ca.resume_session(session_id)
    except ConversationAgentError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"\nResuming session: {session.session_id} (state: {session.state})")
    print("Type your answer and press Enter. Type 'quit' to exit.\n")

    if session.pending_question:
        print(f"\n[Agent]: {session.pending_question}\n")

    while not session.is_terminal():
        try:
            user_input = input("[You]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession interrupted.", file=sys.stderr)
            return 130

        if user_input.lower() in ("quit", "exit", "q"):
            print("Session saved. Resume with:")
            print(f"  testing-eval-agent resume --session-id {session.session_id}")
            return 0

        try:
            session = ca.respond(session.session_id, user_input)
        except ConversationAgentError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if session.pending_question:
            print(f"\n[Agent]: {session.pending_question}\n")

    print(f"\nSession {session.state}: {session.session_id}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        settings = get_settings()
        settings.ensure_output_directories()

        command = args.command or "healthcheck"

        if command == "healthcheck":
            agent = create_testing_agent(settings=settings)
            print(json.dumps(agent.health_snapshot(), indent=2, sort_keys=True))
            return 0

        if command == "list-skills":
            skill_loader = SkillLoader(settings=settings)
            print(json.dumps(skill_loader.list_skill_names(), indent=2))
            return 0

        if command == "show-config":
            print(json.dumps(_safe_settings_snapshot(settings), indent=2, sort_keys=True))
            return 0

        if command == "summarize":
            agent = create_testing_agent(settings=settings)
            summary = agent.summarize_intent(args.prompt)
            print(summary)
            return 0

        if command == "chat":
            return _run_chat(settings, target_type_hint=getattr(args, "target_type", None))

        if command == "resume":
            session_id_str = getattr(args, "session_id", None)
            if not session_id_str:
                print("Error: --session-id is required for resume.", file=sys.stderr)
                return 2
            try:
                session_id = UUID(session_id_str)
            except ValueError:
                print(f"Error: Invalid session ID: {session_id_str}", file=sys.stderr)
                return 2
            return _run_resume(settings, session_id)

        parser.print_help()
        return 2
    except Exception as error:  # pragma: no cover - CLI guardrail
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
