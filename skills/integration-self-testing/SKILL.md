---
name: integration-self-testing
description: Use this skill when validating cross-component behavior and internal consistency checks.
metadata:
  version: 1.0.0
  category: testing
---

# 1. Skill Name and Purpose

**Skill:** `integration-self-testing`

This skill validates two related but distinct concerns:

1. **Integration testing:** Verifies that connected components of the solution work together correctly by executing approved integration test scripts under `tests/integration/`.
2. **Self-testing:** Verifies the testing agent's own process — checking that skills were selected correctly, workflow transitions were valid, approval checkpoints were respected, required artifacts were created and passed schema validation, and failures can be classified by source.

Both modes collect deterministic evidence, classify failures by `FailureSource`, and return structured results. Self-testing may produce improvement recommendations for skills and workflows but must not rewrite or activate them automatically.

---

# 2. Scope

This skill covers:

- Executing approved Playwright Test integration scripts from `tests/integration/`
- Validating that connected components return correct data and state across boundaries
- Inspecting workflow run artifacts to verify: correct skill selection, valid state transitions, checkpoint enforcement, artifact creation, schema validation
- Classifying failure sources: `application`, `test_script`, `environment`, `configuration`, `agent`, `workflow`, `skill`, `tool`, `model_output`
- Generating improvement recommendations for skills or workflows where issues are identified
- Collecting execution evidence: results, screenshots, traces, logs

This skill does not:

- Automatically rewrite any `SKILL.md` file
- Automatically activate updated skills
- Execute scripts from `tests/generated/`
- Generate new test cases or Playwright scripts
- Modify the application under test
- Enable scheduled self-testing (deferred to a future iteration)

---

# 3. When to Use and When Not to Use

**Use this skill when:**

- Integration tests need to be run against connected components (e.g., API → UI, data layer → display layer)
- A completed workflow run needs to be audited for correctness and checkpoint compliance
- A failure in a previous run needs to be traced to a specific agent, tool, skill, or workflow step
- Improvement recommendations for a skill or workflow are needed after observed failures

**Do not use this skill when:**

- Only critical-path availability needs to be checked (use `smoke-testing`)
- Deep UI functional or accessibility testing is required (use `ui-testing`)
- AI feature quality evaluation is the primary goal (use `evaluation-testing`)
- No approved integration scripts exist and no workflow artifacts are available for self-testing

---

# 4. Required and Optional Inputs

## For Integration Testing

| Field | Description |
|---|---|
| `target_environment` | Name or identifier of the environment under test |
| `base_url` | HTTP or HTTPS base URL |
| `approved_script_paths` | One or more paths to approved `.spec.ts` files in `tests/integration/` |
| `approval_reference` | Approval record ID confirming script approval |
| `run_id` | UUID for this integration run |

## For Self-Testing

| Field | Description |
|---|---|
| `workflow_run_id` | UUID of the workflow run to audit |
| `artifact_references` | List of `ArtifactReference` objects produced by the workflow run |
| `workflow_stage_history` | Ordered list of `WorkflowStage` transitions from the run |
| `skill_selection_log` | Log of skill invocations and their inputs/outputs |
| `run_id` | UUID for this self-test run |

## Optional (Both Modes)

| Field | Description |
|---|---|
| `browser` | `BrowserName`; defaults to `chromium` |
| `headless` | Headless flag; defaults to `True` |
| `capture_screenshots` | Screenshots on failure; defaults to `True` |
| `capture_traces` | Traces on failure; defaults to `True` |

---

# 5. Preconditions and Input Validation

### Integration Testing Preconditions

1. All `approved_script_paths` exist within `tests/integration/`.
2. A valid `approval_reference` exists for each script.
3. `base_url` is a valid HTTP or HTTPS URL.
4. `target_environment` is not `production` unless `ALLOW_LIVE_TEST_EXECUTION=true`.
5. `run_id` is a valid UUID.

### Self-Testing Preconditions

1. `workflow_run_id` is a valid UUID.
2. At least one `ArtifactReference` is provided.
3. `workflow_stage_history` contains at least the `INITIALIZED` stage.
4. `skill_selection_log` is non-empty if skill audit is requested.

Return `OperationResult(success=False)` and stop if any precondition fails.

---

# 6. Relevant Existing Domain Models

| Model | Module | Purpose |
|---|---|---|
| `PlaywrightExecutionRequest` | `src.models.playwright` | Integration test execution request |
| `PlaywrightExecutionResult` | `src.models.playwright` | Per-test execution result |
| `ArtifactReference` | `src.models.common` | Reference to a workflow artifact under audit |
| `ArtifactMetadata` | `src.models.common` | Lifecycle and traceability metadata |
| `EvidenceReference` | `src.models.common` | Evidence supporting a finding |
| `ErrorDetail` | `src.models.common` | Structured error |
| `WarningDetail` | `src.models.common` | Non-blocking warning |
| `OperationResult` | `src.models.common` | Unified structured result |
| `ApprovalRecord` | `src.models.common` | Human approval confirmation |
| `ExecutionStatus` | `src.models.enums` | Per-test execution state |
| `WorkflowStage` | `src.models.enums` | Expected stage transition values |
| `WorkflowOutcome` | `src.models.enums` | Overall workflow outcome |
| `FailureSource` | `src.models.enums` | Failure origin classification |
| `ArtifactStatus` | `src.models.enums` | Lifecycle state of each artifact |
| `ArtifactType` | `src.models.enums` | Type classification for results |

---

# 7. Detailed Numbered Execution Procedure

## Integration Testing Path

1. **Validate inputs.** Check all integration testing preconditions. Return failure and stop if any fail.
2. **Confirm approval.** Verify each script has a valid `ApprovalRecord` with `ApprovalStatus.APPROVED`.
3. **Confirm script locations.** All paths must be within `tests/integration/`.
4. **Build execution request.** Populate `PlaywrightExecutionRequest` with scripts, environment, browser, evidence settings, and run ID.
5. **Execute scripts.** Invoke the Playwright Test runner via `src/tools/playwright_runner.py`.
6. **Collect results.** Parse exit code, stdout, stderr, JSON results, and timing.
7. **Deserialize results.** Build `PlaywrightExecutionResult` records.
8. **Collect evidence.** Record `EvidenceReference` for screenshots (`screenshots/`), traces (`traces/`), and logs for failing tests.
9. **Classify failures.** For each failing test, assign a `FailureSource`.
10. **Build failure summaries.** For each failure: failed step, expected result, actual result, error detail, evidence references, suggested action.
11. **Persist result.** Save to `reports/<run_id>-integration-results.json`.
12. **Return `OperationResult`.** Include overall status, per-test results, evidence, warnings, errors.

## Self-Testing Path

1. **Validate inputs.** Check all self-testing preconditions. Return failure and stop if any fail.
2. **Inspect workflow stage history.** Verify stages transitioned in the expected order per `WorkflowStage` enum. Record any out-of-order or missing transition as a finding.
3. **Audit skill selection.** For each skill invocation in the log, verify: correct skill was selected for the input type, inputs passed Pydantic validation, outputs passed schema validation. Record discrepancies as findings.
4. **Audit approval checkpoints.** Verify:
   - `generate-playwright-scripts` was not invoked before `ApprovalStatus.APPROVED` was recorded for the test case collection
   - Execution did not proceed before `ApprovalStatus.APPROVED` was recorded for scripts
   - Evaluation findings were reviewed before downstream proposals
   Record any checkpoint bypass as a critical finding.
5. **Audit artifact creation.** For each expected artifact type, verify: artifact exists at the correct path, has the correct `ArtifactStatus`, has valid `ArtifactMetadata`. Record missing or malformed artifacts as findings.
6. **Validate artifact schemas.** Deserialize each artifact against its Pydantic model. Record deserialization failures as findings with `FailureSource.TOOL` or `FailureSource.WORKFLOW`.
7. **Classify findings by failure source.** Assign `FailureSource` to each finding.
8. **Assess skill instructions.** If any findings suggest a skill instruction was ambiguous, incomplete, or led to incorrect behavior, record an improvement recommendation. Do not modify the skill file.
9. **Build self-test report.** Summarize: workflow completeness, checkpoint compliance, artifact integrity, schema validity, classified failures, improvement recommendations.
10. **Persist self-test result.** Save to `reports/<run_id>-self-test-results.json`.
11. **Return `OperationResult`.** Include findings, recommendations, warnings, errors.

---

# 8. Decision Rules

- If any script path is not in `tests/integration/`, reject the request and stop.
- If a workflow audit finds a checkpoint bypass, classify it as a critical finding and include it in the result; do not suppress it.
- Self-testing must not modify any `SKILL.md`, `src/` file, or workflow configuration.
- If a skill instruction was ambiguous, the recommendation must describe the specific ambiguity and propose a correction for human review.
- Scheduled self-testing is not enabled in this version; do not implement or invoke a scheduler.
- Never claim a workflow succeeded if evidence shows a checkpoint was bypassed.

---

# 9. Structured Output Requirements

The skill must return an `OperationResult` containing:

- `success`: `True` if the runner completed or the self-test audit completed without a blocking error
- `run_id`: UUID
- `mode`: `"integration"` or `"self_test"` or `"both"`
- `overall_status`: `ExecutionStatus` or `WorkflowOutcome`
- `test_results` (integration mode): list of `PlaywrightExecutionResult`
- `self_test_findings` (self-test mode): list of structured findings with `FailureSource`, description, evidence, and recommendation
- `improvement_recommendations`: list of skill or workflow improvement suggestions
- `evidence`: list of `EvidenceReference`
- `warnings`: list of `WarningDetail`
- `errors`: list of `ErrorDetail`
- `message`: human-readable summary

---

# 10. Artifact Location and Traceability Rules

- Integration results: `reports/<run_id>-integration-results.json`
- Self-test results: `reports/<run_id>-self-test-results.json`
- Screenshots: `screenshots/`
- Traces: `traces/`
- Scripts read from (not written to): `tests/integration/`
- Every result artifact must include `ArtifactMetadata` with: `skill_name` (`integration-self-testing`), `artifact_type` (`ArtifactType.EXECUTION_RESULT`), `run_id`, `created_at`

---

# 11. Evidence Requirements

For integration test failures: screenshot at failure, Playwright trace, assertion error, console logs, timing.

For self-test findings: artifact path references, schema validation errors, workflow stage log entries, skill selection log excerpts.

All evidence must be referenced via `EvidenceReference` with `evidence_type`, `source`, and `path` or `locator`.

---

# 12. Human Approval Requirements

Integration test execution does not require a post-run approval checkpoint. However:

- Scripts must have completed Checkpoint B before reaching this skill
- Self-test improvement recommendations must be reviewed by a human before any skill or workflow file is modified (Checkpoint C equivalent for self-testing)
- If findings indicate a critical checkpoint was bypassed in a prior run, a human must review the finding before the workflow is permitted to resume

---

# 13. Safety Guardrails

- Never execute scripts from `tests/generated/` or any unapproved location.
- Never run against production without explicit flag.
- Never modify any `SKILL.md`, `src/` source file, or workflow configuration automatically.
- Never activate a revised skill without human review.
- Never hide checkpoint bypass findings.
- Never claim a process step succeeded without artifact or log evidence.
- Never connect to Azure DevOps MCP or App Factory.
- Never perform destructive application actions.

---

# 14. Failure Handling and Failure Classification

| Failure | Classification | Action |
|---|---|---|
| Script path outside `tests/integration/` | `FailureSource.CONFIGURATION` | Stop, record error |
| No approval record | `FailureSource.APPROVAL` | Stop, record error |
| Runner process fails to start | `FailureSource.ENVIRONMENT` | Record blocked result, stop |
| Approval checkpoint bypass found in audit | `FailureSource.WORKFLOW` | Record critical finding, surface to human |
| Artifact schema validation failure | `FailureSource.TOOL` | Record finding, flag artifact as `INCOMPLETE` |
| Skill instruction ambiguity | `FailureSource.SKILL` | Record recommendation, do not auto-fix |
| Missing expected artifact | `FailureSource.WORKFLOW` | Record finding, continue audit |

---

# 15. Warning and Uncertainty Handling

Record a `WarningDetail` for:

- Retried tests that eventually passed (flakiness signal)
- Skipped tests
- Evidence files referenced but not found
- Self-test scope limited because workflow stage history was incomplete
- Skill selection log was empty (reduces audit confidence)

---

# 16. Acceptance Criteria

The skill is considered successful when:

1. All integration scripts originated from `tests/integration/` with confirmed approval.
2. All test results are recorded with `ExecutionStatus`.
3. All self-test findings are classified with `FailureSource`.
4. Improvement recommendations are recorded (even if empty).
5. No checkpoint bypass was silently suppressed.
6. Results are persisted to `reports/`.
7. `OperationResult` returned with accurate status.

---

# 17. Completion Criteria

This skill is complete when:

- Runner has exited (integration path) or audit is complete (self-test path)
- Results are persisted
- `OperationResult` returned to workflow
- No hidden findings

---

# 18. Workflow Handoff

On success: workflow transitions to `WorkflowStage.EXECUTION_COMPLETED`. Downstream evaluation and plan comparison may proceed.

On self-test critical findings: findings are surfaced for human review before any downstream action is permitted.

On failure: caller receives structured failure result. Dependent steps are blocked.

---

# 19. Valid Example

**Self-test input:**
- `workflow_run_id`: `run-wf-001`
- Artifacts: `specs/approved/run-001-test-cases.json` (`APPROVED`), `tests/generated/run-001-smoke.spec.ts` (`AWAITING_APPROVAL`)
- Stage history: `INITIALIZED` → `TEST_CASES_GENERATED` → `AWAITING_TEST_CASE_APPROVAL` → `TEST_CASES_APPROVED` → `PLAYWRIGHT_SCRIPTS_GENERATED` → `AWAITING_SCRIPT_APPROVAL`

**Outcome:**
- All stage transitions valid and in expected order
- Both artifacts exist, schemas valid
- No checkpoint bypasses detected
- Workflow at `AWAITING_SCRIPT_APPROVAL` — correctly halted
- Self-test finding: none critical
- `OperationResult(success=True, overall_status=WorkflowOutcome.SUCCESS)`

---

# 20. Blocked or Failure Example

**Self-test input:**
- `workflow_run_id`: `run-wf-002`
- Stage history: `INITIALIZED` → `TEST_CASES_GENERATED` → `PLAYWRIGHT_SCRIPTS_GENERATED` (missing `AWAITING_TEST_CASE_APPROVAL` and `TEST_CASES_APPROVED`)

**Outcome:**
- Audit detects missing stages: `AWAITING_TEST_CASE_APPROVAL` and `TEST_CASES_APPROVED` never recorded
- Finding: `"Playwright script generation proceeded without recorded test-case approval. Checkpoint A was bypassed."`
- `FailureSource.WORKFLOW`
- Recommendation: `"Enforce that WorkflowStage.TEST_CASES_APPROVED is recorded before invoking generate-playwright-scripts."`
- `OperationResult(success=True)` (audit completed) but critical finding surfaces
- Finding must be reviewed by a human before any further workflow action is permitted
