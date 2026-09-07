---
name: ui-testing
description: Use this skill when validating user interface behavior and browser-driven flows.
metadata:
  version: 1.0.0
  category: testing
---

# 1. Skill Name and Purpose

**Skill:** `ui-testing`

This skill validates Code Apps and Web Apps across six quality dimensions: functionality, visual design, responsiveness, performance, usability, and accessibility. Playwright MCP assists with browser exploration, locator discovery, screenshot capture, page-structure inspection, and accessibility inspection. Playwright Test with TypeScript is the deterministic execution layer for repeatable, evidence-backed test runs. All findings are evidence-based and classified against defined rubrics or measurable criteria.

---

# 2. Scope

This skill covers:

- **Functionality:** UI components behave correctly under user interaction
- **Visual design:** Layout, styling, and visual appearance conform to specifications or defined rubrics
- **Responsiveness:** UI adapts correctly to defined viewport breakpoints
- **Performance:** Page load, interaction timing, and rendering metrics meet defined thresholds
- **Usability:** User flows are logical, discoverable, and complete without errors
- **Accessibility:** Pages meet WCAG criteria; semantic roles, keyboard navigation, focus management, and assistive-technology labels are correct

Playwright MCP may be used for:
- Browser exploration prior to scripting
- Locator discovery for stable selectors
- Screenshot capture during exploration
- Accessibility snapshot inspection
- Page-structure understanding

Playwright Test is used for:
- Repeatable deterministic execution
- Evidence collection (assertions, screenshots, traces)
- Accessibility assertions via accessibility snapshot or integrated tools

This skill does not:

- Execute scripts from `tests/generated/`
- Generate test cases or Playwright scripts (use `generate-test-cases` and `generate-playwright-scripts`)
- Make subjective claims without a defined rubric or measurable threshold
- Modify the application under test
- Approve scripts or artifacts automatically

---

# 3. When to Use and When Not to Use

**Use this skill when:**

- Approved UI test scripts exist in `tests/ui/` and need to be executed
- Functional, visual, responsive, performance, usability, or accessibility validation of a UI is required
- Playwright MCP exploration is needed to discover locators or page structure before scripting
- Accessibility compliance evidence is required

**Do not use this skill when:**

- Only critical-path availability is needed (use `smoke-testing`)
- API or backend integration testing is the primary concern (use `integration-self-testing`)
- AI feature quality scoring is the primary goal (use `evaluation-testing`)
- No approved UI test scripts exist in `tests/ui/`
- Scripts are still in `tests/generated/` and have not been approved

---

# 4. Required and Optional Inputs

## Required

| Field | Description |
|---|---|
| `target_environment` | Name or identifier of the environment under test |
| `base_url` | HTTP or HTTPS base URL of the application |
| `approved_script_paths` | One or more paths to approved `.spec.ts` files in `tests/ui/` |
| `approval_reference` | Approval record ID confirming each script was approved |
| `run_id` | UUID for this UI test run |
| `test_categories` | One or more `TestCategory` values to indicate which UI quality dimensions are covered |

## Optional

| Field | Description |
|---|---|
| `browser` | `BrowserName`; defaults to `chromium` |
| `headless` | Headless mode; defaults to `True` |
| `viewports` | List of viewport sizes for responsiveness testing (e.g., `[{width: 1280, height: 720}, {width: 375, height: 667}]`) |
| `visual_baseline_path` | Path to visual baseline screenshots under `evals/baselines/` |
| `performance_thresholds` | Dict of metric name to maximum acceptable value |
| `accessibility_standard` | Accessibility standard to evaluate against (e.g., `WCAG_2_1_AA`) |
| `capture_screenshots` | Screenshots on failure; defaults to `True` |
| `capture_traces` | Traces on failure; defaults to `True` |
| `playwright_mcp_exploration` | Whether Playwright MCP is used for pre-execution exploration; defaults to `False` |

---

# 5. Preconditions and Input Validation

1. All `approved_script_paths` exist within `tests/ui/`.
2. A valid `approval_reference` exists for each script.
3. `base_url` is a valid HTTP or HTTPS URL.
4. `target_environment` is not `production` unless `ALLOW_LIVE_TEST_EXECUTION=true`.
5. `run_id` is a valid UUID.
6. All `TestCategory` values in `test_categories` are valid `TestCategory` enum members.
7. If `visual_baseline_path` is provided, it must exist under `evals/baselines/`.
8. If `playwright_mcp_exploration` is `True`, `PLAYWRIGHT_MCP_ENABLED` environment variable must be `true`.

Return `OperationResult(success=False)` and stop on any precondition failure.

---

# 6. Relevant Existing Domain Models

| Model | Module | Purpose |
|---|---|---|
| `PlaywrightExecutionRequest` | `src.models.playwright` | Execution request with scripts, browser, evidence settings |
| `PlaywrightExecutionResult` | `src.models.playwright` | Per-test execution result |
| `ArtifactMetadata` | `src.models.common` | Traceability metadata |
| `EvidenceReference` | `src.models.common` | Reference to screenshot, trace, accessibility snapshot |
| `ErrorDetail` | `src.models.common` | Structured failure detail |
| `WarningDetail` | `src.models.common` | Non-blocking warning |
| `OperationResult` | `src.models.common` | Unified structured result |
| `ApprovalRecord` | `src.models.common` | Approval confirmation for promoted script |
| `ExecutionStatus` | `src.models.enums` | Per-test execution state |
| `ArtifactType` | `src.models.enums` | `ArtifactType.EXECUTION_RESULT` |
| `FailureSource` | `src.models.enums` | Failure origin classification |
| `TestCategory` | `src.models.enums` | UI quality dimensions: `functional_ui`, `visual_ui`, `responsive_ui`, `performance`, `usability`, `accessibility` |
| `EvidenceType` | `src.models.enums` | `screenshot`, `trace`, `accessibility_snapshot`, `console_log`, `network_log` |
| `BrowserName` | `src.models.enums` | Target browser |

---

# 7. Detailed Numbered Execution Procedure

### Phase A: Pre-Execution Exploration (Optional, Playwright MCP)

1. **Check Playwright MCP availability.** If `playwright_mcp_exploration` is `True` and `PLAYWRIGHT_MCP_ENABLED=true`, proceed. Otherwise skip to Phase B.
2. **Launch browser via Playwright MCP.** Navigate to `base_url`.
3. **Inspect page structure.** Use Playwright MCP to capture accessibility tree, semantic roles, and page structure.
4. **Discover locators.** Record stable locators for elements referenced in test scripts.
5. **Capture accessibility snapshot.** Record as `EvidenceType.ACCESSIBILITY_SNAPSHOT`.
6. **Capture screenshots.** Record as `EvidenceType.SCREENSHOT`.
7. **Record findings.** Store MCP exploration results as `EvidenceReference` objects. These inform execution but do not replace it.
8. **Close MCP session.** Playwright MCP must not be left open during Playwright Test execution.

### Phase B: Deterministic Execution (Playwright Test)

1. **Validate all preconditions.** Confirm scripts exist in `tests/ui/` with valid approval references.
2. **Confirm script locations.** Every script path must resolve within `tests/ui/`.
3. **Build execution request.** Populate `PlaywrightExecutionRequest` with validated scripts, environment, browser, viewports (if provided), evidence settings, and run ID.
4. **Execute scripts.** Invoke the Playwright Test runner via `src/tools/playwright_runner.py`.
5. **Collect raw results.** Capture exit code, stdout, stderr, JSON results, timing.
6. **Deserialize results.** Build `PlaywrightExecutionResult` records.
7. **Collect evidence.** For each failing test, record `EvidenceReference` for: screenshots (`screenshots/`), traces (`traces/`), accessibility snapshots, console logs.
8. **Classify failures.** Assign `FailureSource` to each failing test. For UI testing, distinguish:
   - `structural_failure`: DOM element missing or wrong type
   - `functional_failure`: interaction did not produce expected result (classify as `FailureSource.APPLICATION`)
   - `responsive_layout_failure`: viewport-specific layout breakage (classify as `FailureSource.APPLICATION`)
   - `visual_difference`: pixel-level or structural difference from baseline (classify as `FailureSource.APPLICATION`)
   - `missing_baseline`: no visual baseline exists (classify as `FailureSource.CONFIGURATION`, record warning)
   - `rendering_instability`: intermittent rendering issue (classify as `FailureSource.APPLICATION`, note as flaky)
9. **Evaluate accessibility results.** Parse accessibility assertion failures. Map violations to WCAG criteria if `accessibility_standard` was provided. Record violation count, affected elements, and recommended remediation per violation.
10. **Evaluate performance results.** If `performance_thresholds` were provided, compare captured timing metrics to thresholds. Record pass/fail per metric.
11. **Determine overall run status.** `ExecutionStatus.PASSED` if all tests pass; `ExecutionStatus.FAILED` if any test fails.
12. **Build failure summaries.** For each failure: dimension category, failed step or assertion, expected vs actual, evidence references, suggested action.
13. **Persist execution result.** Save to `reports/<run_id>-ui-results.json`.
14. **Return `OperationResult`.** Include overall status, per-test results, evidence, failure summaries, accessibility findings, performance findings, warnings, errors.

---

# 8. Decision Rules

- If any script path is not in `tests/ui/`, reject the request and stop.
- Never make subjective visual quality claims without a baseline or defined rubric.
- For accessibility findings, prefer machine-readable evidence (accessibility snapshot, assertion output) over subjective description.
- Distinguish clearly between `structural_failure`, `functional_failure`, `responsive_layout_failure`, `visual_difference`, `missing_baseline`, and `rendering_instability` in every failure record.
- A `missing_baseline` is a warning, not a test failure, unless the test was explicitly designed to compare against a baseline.
- Never claim a test passed without `ExecutionStatus.PASSED` from the deterministic runner.
- Playwright MCP results are exploration evidence only and do not constitute test execution evidence.

---

# 9. Structured Output Requirements

The skill must return an `OperationResult` containing:

- `success`: `True` if the runner completed without a process-level error
- `run_id`: UUID
- `overall_status`: `ExecutionStatus`
- `test_results`: list of `PlaywrightExecutionResult`
- `failure_summaries`: structured per-test failure details with UI failure type classification
- `accessibility_findings`: list of accessibility violations with WCAG criterion, affected element, severity, and recommendation
- `performance_findings`: list of metric results versus thresholds (if thresholds were provided)
- `visual_findings`: list of visual difference findings with baseline comparison status
- `evidence`: list of `EvidenceReference`
- `warnings`: list of `WarningDetail`
- `errors`: list of `ErrorDetail`
- `message`: human-readable summary

---

# 10. Artifact Location and Traceability Rules

- UI execution results: `reports/<run_id>-ui-results.json`
- Screenshots: `screenshots/`
- Traces: `traces/`
- Visual baselines (read-only): `evals/baselines/`
- Scripts read from (not written to): `tests/ui/`
- Every result must include `ArtifactMetadata`: `skill_name` (`ui-testing`), `artifact_type` (`ArtifactType.EXECUTION_RESULT`), `run_id`, `created_at`, parent script artifact IDs

---

# 11. Evidence Requirements

For each failing test:
- Screenshot at the point of failure
- Playwright trace file
- Assertion error with expected and actual values
- Relevant console logs
- For accessibility failures: accessibility snapshot excerpt showing the affected node
- For visual failures: both actual and baseline screenshot references

For passing tests: at minimum, recorded `ExecutionStatus.PASSED` with timing.

---

# 12. Human Approval Requirements

UI test execution does not require a post-run approval checkpoint. However:

- Scripts must have completed Checkpoint B before reaching this skill
- If UI failures indicate significant quality concerns, the workflow should surface them to a human reviewer before proceeding to `evaluation-testing` or `plan-vs-implementation`
- Checkpoint C applies to any downstream recommendations based on UI findings

---

# 13. Safety Guardrails

- Never execute scripts from `tests/generated/` or any unapproved location.
- Never run against production without explicit flag.
- Never modify the application under test.
- Never make subjective visual quality claims without a defined rubric or baseline.
- Never treat Playwright MCP exploration output as deterministic test execution evidence.
- Never commit or log credentials.
- Never activate Azure DevOps MCP or App Factory.
- Never overwrite approved scripts.

---

# 14. Failure Handling and Failure Classification

| Failure | Classification | Action |
|---|---|---|
| Script path outside `tests/ui/` | `FailureSource.CONFIGURATION` | Stop, record error |
| No approval record | `FailureSource.APPROVAL` | Stop, record error |
| Runner process fails to start | `FailureSource.ENVIRONMENT` | Record blocked result, stop |
| Functional assertion failure | `FailureSource.APPLICATION` | Record with evidence, continue |
| Responsive layout failure | `FailureSource.APPLICATION` | Record with viewport details, continue |
| Visual baseline missing | `FailureSource.CONFIGURATION` | Record as warning, not failure |
| Accessibility violation | `FailureSource.APPLICATION` | Record with WCAG criterion, continue |
| Performance threshold exceeded | `FailureSource.APPLICATION` | Record metric vs threshold, continue |
| Evidence file not found | `FailureSource.TOOL` | Record as warning, continue |

---

# 15. Warning and Uncertainty Handling

Record a `WarningDetail` for:

- Visual baseline not found (cannot perform visual comparison)
- Playwright MCP exploration used but `PLAYWRIGHT_MCP_ENABLED` is `false` (exploration skipped)
- Tests retried and passed on later attempt (flakiness signal)
- Skipped tests
- Performance thresholds not provided (performance dimension not evaluated)
- Accessibility standard not specified (violations detected but not mapped to a standard)

---

# 16. Acceptance Criteria

The skill is considered successful when:

1. All scripts originated from `tests/ui/` with confirmed approval.
2. Every test has a recorded `ExecutionStatus`.
3. All failures have structured summaries with evidence references and UI failure type classification.
4. Accessibility, performance, and visual findings are distinct sections.
5. Execution result persisted to `reports/`.
6. `OperationResult` returned with accurate `overall_status`.

---

# 17. Completion Criteria

This skill is complete when:

- Playwright runner has exited
- All results parsed and persisted
- `OperationResult` returned to workflow
- Workflow transitioned to `WorkflowStage.EXECUTION_COMPLETED`

---

# 18. Workflow Handoff

On all-pass: workflow transitions to `WorkflowStage.EXECUTION_COMPLETED`. Downstream `evaluation-testing` and `plan-vs-implementation` may proceed.

On failures: workflow transitions to `WorkflowStage.EXECUTION_COMPLETED` with failures recorded. Human review of significant failures is recommended before downstream steps.

---

# 19. Valid Example

**Input:**
- `target_environment`: `staging`
- `base_url`: `http://staging.internal:3000`
- `approved_script_paths`: `["tests/ui/run-abc123-functional_ui.spec.ts", "tests/ui/run-abc123-accessibility.spec.ts"]`
- `test_categories`: `[functional_ui, accessibility]`
- `accessibility_standard`: `WCAG_2_1_AA`
- `approval_reference`: `APPR-0055`
- `run_id`: `run-ui-001`

**Outcome:**
- 4 functional UI tests executed: all pass
- 2 accessibility tests executed: 1 passes, 1 fails with 2 violations (missing `aria-label` on icon button, insufficient color contrast)
- `ExecutionStatus.PASSED` for functional tests; `ExecutionStatus.FAILED` for accessibility test
- Accessibility findings: `WCAG-1.4.3` (color contrast), `WCAG-4.1.2` (name, role, value)
- Evidence: screenshot + accessibility snapshot captured for failing test
- Overall status: `ExecutionStatus.FAILED`
- Persisted: `reports/run-ui-001-ui-results.json`

---

# 20. Blocked or Failure Example

**Input:**
- `approved_script_paths`: `["tests/generated/run-abc123-functional_ui.spec.ts"]` (unapproved directory)

**Outcome:**
- Precondition check: `tests/generated/run-abc123-functional_ui.spec.ts` is not under `tests/ui/`
- `ErrorDetail`: `"Script path 'tests/generated/run-abc123-functional_ui.spec.ts' is not in the approved tests/ui/ directory. UI test execution blocked."`
- `OperationResult(success=False)` returned
- Workflow remains at `WorkflowStage.PLAYWRIGHT_SCRIPTS_APPROVED`
- Recommended action: Obtain human approval and promote the script to `tests/ui/`, then re-invoke this skill
