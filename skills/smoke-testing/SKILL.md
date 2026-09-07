---
name: smoke-testing
description: Use this skill when validating core application availability and critical path health.
metadata:
  version: 1.0.0
  category: testing
---

# 1. Skill Name and Purpose

**Skill:** `smoke-testing`

This skill executes approved smoke tests to validate that the essential components of a solution are present, reachable, and functionally operational. It verifies that required pages or services load, required data is accessible, essential navigation works, and critical user paths can be completed end to end. It collects deterministic execution evidence (results, screenshots, traces) and returns a structured smoke run result.

---

# 2. Scope

This skill covers:

- Executing approved Playwright Test scripts located in `tests/smoke/`
- Validating application availability (page loads, HTTP status)
- Validating required data is accessible
- Validating essential navigation paths
- Validating that the application can complete its basic intended critical path
- Collecting execution evidence: results JSON, screenshots, traces
- Classifying failures by likely source
- Returning a structured smoke run result

This skill does not:

- Execute scripts from `tests/generated/` or any unapproved location
- Generate test cases or Playwright scripts
- Evaluate AI-based features
- Compare plan versus implementation
- Modify the application under test
- Run load tests or performance benchmarks

---

# 3. When to Use and When Not to Use

**Use this skill when:**

- A new deployment or environment needs to be validated before further testing
- A critical path health check is required after a change
- Integration or UI testing is gated on a smoke test passing first
- The agent needs deterministic confirmation that the application is reachable

**Do not use this skill when:**

- No approved smoke test scripts exist in `tests/smoke/`
- Deep functional, visual, or accessibility validation is required (use `ui-testing`)
- End-to-end integration of multiple components is the primary concern (use `integration-self-testing`)
- AI feature quality evaluation is required (use `evaluation-testing`)
- Scripts have not been approved (resolve via `generate-playwright-scripts` → approval → promotion)

---

# 4. Required and Optional Inputs

## Required

| Field | Description |
|---|---|
| `target_environment` | Name or identifier of the environment under test (e.g., `local`, `staging`) |
| `base_url` | The HTTP or HTTPS base URL of the application under test |
| `approved_script_paths` | One or more paths to approved `.spec.ts` files in `tests/smoke/` |
| `approval_reference` | The `ApprovalRecord` ID or reference confirming script approval |
| `run_id` | UUID for this smoke run |

## Optional

| Field | Description |
|---|---|
| `browser` | Target browser (`BrowserName`); defaults to `chromium` |
| `headless` | Whether to run headless; defaults to `True` |
| `retry_count` | Number of retries on failure; defaults to `0` |
| `capture_screenshots` | Capture screenshots on failure; defaults to `True` |
| `capture_traces` | Capture traces on failure; defaults to `True` |
| `timeout_ms` | Per-test timeout in milliseconds; defaults to framework default |

---

# 5. Preconditions and Input Validation

Before executing, validate the following:

1. All `approved_script_paths` exist and are located under `tests/smoke/`. Reject any path outside this directory.
2. A valid `approval_reference` exists confirming each script was approved before promotion.
3. `base_url` is a valid HTTP or HTTPS URL. The scheme must not be `file://`.
4. `target_environment` is not `production` unless `ALLOW_LIVE_TEST_EXECUTION=true` is explicitly set in environment configuration.
5. `run_id` is a valid UUID.
6. `ALLOW_LIVE_TEST_EXECUTION` environment variable has been checked; default is `false`.

If any validation step fails, return a structured `OperationResult` with `success=False` and stop without executing any script.

---

# 6. Relevant Existing Domain Models

| Model | Module | Purpose |
|---|---|---|
| `PlaywrightExecutionRequest` | `src.models.playwright` | Full execution request including scripts, environment, browser, evidence settings |
| `PlaywrightExecutionResult` | `src.models.playwright` | Structured result of a deterministic Playwright run |
| `ArtifactMetadata` | `src.models.common` | Traceability metadata for the execution result artifact |
| `EvidenceReference` | `src.models.common` | Reference to screenshot, trace, or result file |
| `ErrorDetail` | `src.models.common` | Structured failure detail |
| `WarningDetail` | `src.models.common` | Non-blocking warning |
| `OperationResult` | `src.models.common` | Unified structured result |
| `ApprovalRecord` | `src.models.common` | Human approval record for a promoted script |
| `ExecutionStatus` | `src.models.enums` | `passed`, `failed`, `timed_out`, `cancelled`, `blocked` |
| `ArtifactStatus` | `src.models.enums` | `passed` or `failed` after execution |
| `ArtifactType` | `src.models.enums` | `ArtifactType.EXECUTION_RESULT` |
| `FailureSource` | `src.models.enums` | Likely origin of a test failure |
| `EvidenceType` | `src.models.enums` | `screenshot`, `trace`, `test_result`, `console_log` |

---

# 7. Detailed Numbered Execution Procedure

1. **Validate inputs.** Check all preconditions. Return `OperationResult(success=False)` on any failure and stop.

2. **Confirm approval.** Verify that each script in `approved_script_paths` has an associated `ApprovalRecord` with `ApprovalStatus.APPROVED`. Reject any unapproved script.

3. **Confirm script locations.** Every script path must resolve within `tests/smoke/`. Reject paths outside this directory.

4. **Prepare execution request.** Build a `PlaywrightExecutionRequest` with the validated scripts, environment, base URL, browser, headless mode, retry policy, evidence settings, and run ID.

5. **Execute scripts.** Invoke the Playwright Test runner through `src/tools/playwright_runner.py` using the prepared execution request. This is a deterministic, external process invocation — not model inference.

6. **Collect raw results.** Capture the process exit code, stdout, stderr, JSON results file (if configured), and timing information.

7. **Parse execution results.** Deserialize the results into `PlaywrightExecutionResult` records. For each test: record `test_case_id`, `script_path`, `start_time`, `end_time`, `status`, error detail, retry count.

8. **Collect evidence references.** For each failing test: record `EvidenceReference` entries for screenshots saved to `screenshots/`, traces saved to `traces/`, and console logs. Confirm each referenced file exists.

9. **Classify failures.** For each failing test, classify the likely `FailureSource`:
   - HTTP load failure, timeout → `FailureSource.APPLICATION` or `FailureSource.ENVIRONMENT`
   - Assertion mismatch on known locator → `FailureSource.APPLICATION`
   - Locator not found → `FailureSource.TEST_SCRIPT` or `FailureSource.APPLICATION`
   - Environment variable missing → `FailureSource.CONFIGURATION`
   - Unexpected exception in script → `FailureSource.TEST_SCRIPT`
   - Process launch failure → `FailureSource.ENVIRONMENT`

10. **Determine overall run status.** If all tests pass, set `ExecutionStatus.PASSED`. If any test fails, set `ExecutionStatus.FAILED`. If the runner could not start, set `ExecutionStatus.BLOCKED`.

11. **Build failure summaries.** For each failing test: record failed step or assertion, expected result, actual result, error message, evidence references, and suggested next action.

12. **Persist execution result.** Save a `PlaywrightExecutionResult` summary to `reports/<run_id>-smoke-results.json`.

13. **Assemble `OperationResult`.** Include: run ID, overall status, per-test results, evidence references, failure summaries, warnings, errors.

14. **Return result.** Return the `OperationResult` to the workflow. The workflow transitions to `WorkflowStage.EXECUTION_COMPLETED`.

---

# 8. Decision Rules

- If any script path is not in `tests/smoke/`, reject the entire request and stop.
- If `target_environment` is `production` and `ALLOW_LIVE_TEST_EXECUTION` is not `true`, reject and stop.
- If the Playwright runner process fails to start, classify as `FailureSource.ENVIRONMENT` and stop further execution.
- If a test times out, classify as `ExecutionStatus.TIMED_OUT` and record it as a failure with `FailureSource.ENVIRONMENT` or `FailureSource.APPLICATION`.
- If a screenshot or trace file is referenced but does not exist on disk, record a `WarningDetail` and continue.
- Never report a test as passed unless its `ExecutionStatus` is `PASSED` from the deterministic runner output.

---

# 9. Structured Output Requirements

The skill must return an `OperationResult` containing:

- `success`: `True` if the runner completed without a process-level error (even if individual tests failed)
- `run_id`: UUID
- `overall_status`: `ExecutionStatus` value
- `test_results`: list of `PlaywrightExecutionResult` (one per test)
- `evidence`: list of `EvidenceReference` (screenshots, traces, result files)
- `failure_summaries`: structured list of per-test failure details
- `warnings`: list of `WarningDetail`
- `errors`: list of `ErrorDetail`
- `message`: human-readable summary

---

# 10. Artifact Location and Traceability Rules

- Execution results are saved to: `reports/<run_id>-smoke-results.json`
- Screenshots are saved to: `screenshots/`
- Traces are saved to: `traces/`
- Scripts must reside in: `tests/smoke/` (read-only by this skill)
- Every `ArtifactMetadata` must include: `artifact_id`, `run_id`, `skill_name` (`smoke-testing`), `artifact_type` (`ArtifactType.EXECUTION_RESULT`), `artifact_status` (set after execution), parent script artifact IDs

---

# 11. Evidence Requirements

For each failing test, the following evidence must be collected and referenced:

- Screenshot of the browser state at failure (if `capture_screenshots=True`)
- Playwright trace file (if `capture_traces=True`)
- Assertion error message with expected and actual values
- Relevant console log entries
- Test start time, end time, and retry count

For passing tests, at minimum record the test result status and timing.

---

# 12. Human Approval Requirements

Smoke test execution does not require a human approval checkpoint after the run. However:

- Scripts must have been through Checkpoint B (script approval) before reaching this skill
- If the smoke run produces failures that suggest a blocking issue, the workflow should surface the result to a human reviewer before proceeding to `evaluation-testing` or `plan-vs-implementation`
- Checkpoint C (evaluation approval) applies downstream

---

# 13. Safety Guardrails

- Never execute scripts from `tests/generated/` or any unapproved location.
- Never run against a production environment by default.
- Never perform destructive actions (form submissions that delete data, account deletions, purchases).
- Never modify the application under test.
- Never commit or log secrets, credentials, or tokens.
- Never claim a test passed without deterministic `ExecutionStatus.PASSED` from the runner.
- Never overwrite approved scripts.
- Never activate Azure DevOps MCP or App Factory connections.

---

# 14. Failure Handling and Failure Classification

| Failure | Classification | Action |
|---|---|---|
| Script path outside `tests/smoke/` | `FailureSource.CONFIGURATION` | Record in `ErrorDetail`, stop |
| No approval record found | `FailureSource.APPROVAL` | Record in `ErrorDetail`, stop |
| Production environment without explicit flag | `FailureSource.CONFIGURATION` | Record in `ErrorDetail`, stop |
| Playwright runner process fails to start | `FailureSource.ENVIRONMENT` | Record in `ErrorDetail`, return blocked result, stop |
| Individual test assertion failure | `FailureSource.APPLICATION` or `FailureSource.TEST_SCRIPT` | Record in result, continue other tests |
| Evidence file not found after execution | `FailureSource.TOOL` | Record as `WarningDetail`, continue |
| Result JSON cannot be deserialized | `FailureSource.TOOL` | Record in `ErrorDetail`, flag result as `ArtifactStatus.INCOMPLETE` |

---

# 15. Warning and Uncertainty Handling

Record a `WarningDetail` for:

- Evidence files referenced but not found on disk
- Tests that were retried and passed on a later attempt (flakiness signal)
- Tests that were skipped by the runner
- Environment variables that were expected but not set (non-blocking)
- Smoke test set covers fewer than the expected number of critical paths

---

# 16. Acceptance Criteria

The skill is considered successful when:

1. All scripts originated from `tests/smoke/` with confirmed approval records.
2. The Playwright runner was invoked and completed (or timed out with a recorded result).
3. Every test has a recorded `ExecutionStatus`.
4. Failing tests have structured failure summaries with evidence references.
5. The execution result has been persisted to `reports/<run_id>-smoke-results.json`.
6. `OperationResult` has been returned with an accurate `overall_status`.

---

# 17. Completion Criteria

This skill is complete when:

- The Playwright runner process has exited
- All test results have been parsed and persisted
- `OperationResult` has been returned to the workflow
- The workflow has transitioned to `WorkflowStage.EXECUTION_COMPLETED`

---

# 18. Workflow Handoff

On all-pass: workflow transitions to `WorkflowStage.EXECUTION_COMPLETED`. Downstream steps (`evaluation-testing`, `plan-vs-implementation`, report generation) may proceed.

On failures: workflow transitions to `WorkflowStage.EXECUTION_COMPLETED` with failures recorded. The structured failure summaries are surfaced for human review before proceeding. Dependent steps that require a passing smoke run must be blocked until the failures are resolved.

---

# 19. Valid Example

**Input:**
- `target_environment`: `staging`
- `base_url`: `http://staging.internal:3000`
- `approved_script_paths`: `["tests/smoke/run-abc123-smoke.spec.ts"]`
- `approval_reference`: `APPR-0042`
- `run_id`: `run-smoke-001`

**Outcome:**
- Playwright runner invoked against staging
- 3 smoke tests executed: all pass
- `ExecutionStatus.PASSED` for each test
- Overall status: `ExecutionStatus.PASSED`
- Result persisted: `reports/run-smoke-001-smoke-results.json`
- No screenshots or traces (no failures)
- `OperationResult(success=True, overall_status=PASSED)`
- Workflow transitions to `WorkflowStage.EXECUTION_COMPLETED`

---

# 20. Blocked or Failure Example

**Input:**
- `target_environment`: `staging`
- `base_url`: `http://staging.internal:3000`
- `approved_script_paths`: `["tests/generated/run-abc123-smoke.spec.ts"]` (wrong directory)
- `approval_reference`: `APPR-0042`

**Outcome:**
- Precondition check: `tests/generated/run-abc123-smoke.spec.ts` is not under `tests/smoke/`
- `ErrorDetail` recorded: `"Script path 'tests/generated/run-abc123-smoke.spec.ts' is not in the approved tests/smoke/ directory. Execution blocked."`
- `OperationResult(success=False)` returned
- Workflow remains at `WorkflowStage.PLAYWRIGHT_SCRIPTS_APPROVED`
- Recommended action: Have a human reviewer promote the script from `tests/generated/` to `tests/smoke/` after confirming approval, then re-invoke this skill
