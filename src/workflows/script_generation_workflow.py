"""Deterministic workflow for generating draft Playwright scripts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.models.common import (
    ArtifactMetadata,
    ArtifactReference,
    ErrorDetail,
    WarningDetail,
    utc_now,
)
from src.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    ArtifactType,
    AutomationSuitability,
    FailureSource,
    Severity,
    TestCategory,
    WorkflowOutcome,
    WorkflowStage,
)
from src.models.playwright import (
    GeneratedPlaywrightScript,
    PlaywrightScriptGenerationRequest,
)
from src.models.test_cases import TestCase
from src.models.workflow import WorkflowResult, WorkflowState, WorkflowTransition
from src.tools.artifact_store import ArtifactStore
from src.tools.skill_loader import SkillLoader, SkillLoaderError
from src.workflows.approval_workflow import ApprovalWorkflow


class ScriptGenerationWorkflow:
    """Generate Playwright drafts from approved test cases and gate execution."""

    def __init__(
        self,
        artifact_store: ArtifactStore | None = None,
        skill_loader: SkillLoader | None = None,
        approval_workflow: ApprovalWorkflow | None = None,
    ) -> None:
        """Initialize deterministic dependencies."""

        self._artifact_store = artifact_store or ArtifactStore()
        self._skill_loader = skill_loader or SkillLoader()
        self._approval_workflow = approval_workflow or ApprovalWorkflow()

    def run(self, request: PlaywrightScriptGenerationRequest) -> WorkflowResult:
        """Generate draft scripts and transition to checkpoint B."""

        now = utc_now()
        warnings: list[WarningDetail] = []
        errors: list[ErrorDetail] = []

        try:
            self._skill_loader.load("generate-playwright-scripts")
        except SkillLoaderError as error:
            errors.append(
                ErrorDetail(
                    code="SKILL_LOAD_FAILED",
                    message="Unable to load generate-playwright-scripts skill definition.",
                    failure_source=FailureSource.SKILL,
                    workflow_step="script_generation.load_skill",
                    technical_details=repr(error),
                )
            )
            return self._failed_result(errors, now, "Skill loading failed.")

        grouped_cases: defaultdict[TestCategory, list[TestCase]] = defaultdict(list)
        for test_case in request.approved_test_cases:
            grouped_cases[test_case.category].append(test_case)

        if not grouped_cases:
            errors.append(
                ErrorDetail(
                    code="NO_APPROVED_TEST_CASES",
                    message="No approved test cases available for script generation.",
                    failure_source=FailureSource.APPROVAL,
                    workflow_step="script_generation.group_cases",
                )
            )
            return self._failed_result(errors, now, "No approved test cases provided.")

        produced_artifacts: list[ArtifactReference] = []

        for category, test_cases in grouped_cases.items():
            file_name = f"{request.run_id}-{category.value}.spec.ts"
            relative_path = Path("tests/generated") / file_name
            source_case_ids = [test_case.test_case_id for test_case in test_cases]
            content = self._build_script_content(test_cases)

            metadata = ArtifactMetadata(
                run_id=request.run_id,
                artifact_type=ArtifactType.PLAYWRIGHT_SCRIPT,
                name=file_name,
                status=ArtifactStatus.DRAFT,
                approval_status=ApprovalStatus.PENDING,
                skill_name="generate-playwright-scripts",
                source_references=[category.value],
                parent_artifact_ids=[request.source_collection_id],
                validation_passed=True,
                created_at=now,
                updated_at=now,
            )

            descriptor = GeneratedPlaywrightScript(
                metadata=metadata,
                file_name=file_name,
                relative_path=relative_path,
                source_test_case_ids=source_case_ids,
                content=content,
                generation_warnings=[],
                validation_errors=[],
            )

            persisted = self._artifact_store.create_text(
                metadata=metadata,
                relative_path=relative_path,
                content=descriptor.content,
            )

            if not persisted.success or persisted.artifact is None:
                errors.extend(persisted.errors)
                if not persisted.errors:
                    errors.append(
                        ErrorDetail(
                            code="PLAYWRIGHT_SCRIPT_PERSIST_FAILED",
                            message=f"Failed to persist {file_name}.",
                            failure_source=FailureSource.TOOL,
                            workflow_step="script_generation.persist",
                        )
                    )
                continue

            produced_artifacts.append(persisted.artifact)

            non_automatable = [
                test_case.test_case_id
                for test_case in test_cases
                if test_case.automation_suitability
                in {
                    AutomationSuitability.NOT_SUITABLE,
                    AutomationSuitability.REQUIRES_EXPLORATION,
                }
            ]
            if non_automatable:
                warnings.append(
                    WarningDetail(
                        code="NON_AUTOMATABLE_TESTS_SKIPPED",
                        message=(
                            "One or more test cases were emitted as skipped blocks due to "
                            "automation suitability constraints."
                        ),
                        severity=Severity.MEDIUM,
                        source="script-generation-workflow",
                        suggested_action="Review skipped blocks and perform manual validation.",
                    )
                )

        if not produced_artifacts:
            if not errors:
                errors.append(
                    ErrorDetail(
                        code="NO_SCRIPT_ARTIFACTS_CREATED",
                        message="Script generation did not produce any persisted artifacts.",
                        failure_source=FailureSource.WORKFLOW,
                        workflow_step="script_generation.persist",
                    )
                )
            return self._failed_result(errors, now, "Script generation failed.")

        prepared_state = self._prepared_state(now, produced_artifacts, warnings, errors)

        return self._approval_workflow.create_pending_checkpoint(
            workflow_state=prepared_state,
            name="Checkpoint B - Playwright Script Approval",
            stage=WorkflowStage.AWAITING_SCRIPT_APPROVAL,
            instructions=(
                "Review generated Playwright scripts and approve before any execution "
                "request is allowed."
            ),
            required_artifacts=produced_artifacts,
            triggered_by="script-generation-workflow",
        )

    @staticmethod
    def _build_script_content(test_cases: list[TestCase]) -> str:
        lines = [
            "import { test, expect } from '@playwright/test';",
            "",
            "test.beforeEach(async ({ page }) => {",
            "  await page.goto('/');",
            "});",
            "",
        ]

        for test_case in test_cases:
            title = f"{test_case.title} [{test_case.test_case_id}]"
            skip_case = test_case.automation_suitability in {
                AutomationSuitability.NOT_SUITABLE,
                AutomationSuitability.REQUIRES_EXPLORATION,
            }
            if skip_case:
                lines.append(f"test.skip('{title}', async () => {{")
                lines.append("  // Manual or exploration-required case.")
                lines.append("});")
                lines.append("")
                continue

            lines.append(f"test('{title}', async ({{ page }}) => {{")
            for step in test_case.steps:
                lines.append(f"  // Step {step.step_number}: {step.action}")
                lines.append("  await expect(page).toBeDefined();")
            lines.append("});")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _prepared_state(
        now: datetime,
        produced_artifacts: list[ArtifactReference],
        warnings: list[WarningDetail],
        errors: list[ErrorDetail],
    ) -> WorkflowState:
        transition_a = WorkflowTransition(
            transition_id=uuid4(),
            from_stage=WorkflowStage.INITIALIZED,
            to_stage=WorkflowStage.INPUT_VALIDATED,
            occurred_at=now,
            reason="Validated script generation request.",
            triggered_by="script-generation-workflow",
        )
        transition_b = WorkflowTransition(
            transition_id=uuid4(),
            from_stage=WorkflowStage.INPUT_VALIDATED,
            to_stage=WorkflowStage.PLAYWRIGHT_SCRIPTS_GENERATED,
            occurred_at=now,
            reason="Generated draft Playwright scripts.",
            triggered_by="script-generation-workflow",
            artifact_references=produced_artifacts,
        )

        return WorkflowState(
            workflow_id=uuid4(),
            current_stage=WorkflowStage.PLAYWRIGHT_SCRIPTS_GENERATED,
            outcome=WorkflowOutcome.PENDING,
            checkpoints=[],
            transitions=[transition_a, transition_b],
            input_artifacts=[],
            output_artifacts=produced_artifacts,
            warnings=warnings,
            errors=errors,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _failed_result(
        errors: list[ErrorDetail],
        now: datetime,
        message: str,
    ) -> WorkflowResult:
        failed_state = WorkflowState(
            workflow_id=uuid4(),
            current_stage=WorkflowStage.FAILED,
            outcome=WorkflowOutcome.FAILURE,
            checkpoints=[],
            transitions=[],
            input_artifacts=[],
            output_artifacts=[],
            warnings=[],
            errors=errors,
            created_at=now,
            updated_at=now,
        )

        return WorkflowResult(
            workflow_state=failed_state,
            outcome=WorkflowOutcome.FAILURE,
            message=message,
            produced_artifacts=[],
            warnings=[],
            errors=errors,
        )
