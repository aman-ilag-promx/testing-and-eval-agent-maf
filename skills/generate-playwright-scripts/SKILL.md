---
name: generate-playwright-scripts
description: Use this skill when converting approved test cases into Playwright script drafts.
metadata:
  version: 1.0.0
  category: testing
---

# 1. Skill Name and Purpose

**Skill:** `generate-playwright-scripts`

This skill generates TypeScript Playwright Test scripts from approved test cases. Each generated script maps directly to one or more approved `TestCase` records, uses accessible locators, applies Playwright assertions, captures evidence on failure, and is saved as a draft to `tests/generated/`. The skill stops after saving and requests human approval before any execution can occur.

---

# 2. Scope

This skill covers:

- Reading approved `TestCase` records from `specs/approved/`
- Generating one `.spec.ts` file per test category group or per individual test case
- Mapping every generated `test()` block to its source `test_case_id`
- Applying locator preference order: `getByRole`, `getByLabel`, `getByPlaceholder`, `getByText`, `getByTestId`, stable CSS, XPath as last resort
- Using `expect()` assertions from `@playwright/test`
- Producing fixture reuse patterns for shared setup
- Saving all output under `tests/generated/`
- Presenting the draft scripts for human approval

This skill does not:

- Execute any generated script
- Approve scripts automatically
- Modify `tests/smoke/`, `tests/integration/`, or `tests/ui/`
- Read from or write to `specs/generated/`
- Connect to Playwright MCP for execution
- Modify the application under test

---

# 3. When to Use and When Not to Use

**Use this skill when:**

- Human-approved test cases exist in `specs/approved/` and Playwright scripts have not yet been generated
- Approved test cases have been updated after a revision cycle and new scripts are required
- Coverage gaps require new scripts for an existing approved test case set

**Do not use this skill when:**

- Test cases have not yet been approved (use `generate-test-cases` first)
- Scripts already exist and are approved; only execution is needed (use `smoke-testing`, `ui-testing`, or `integration-self-testing`)
- Browser exploration or locator discovery is needed without scripting (use Playwright MCP directly)
- No `TestCase` records with `ApprovalStatus.APPROVED` exist

---

# 4. Required and Optional Inputs

## Required

| Field | Model | Description |
|---|---|---|
| `approved_test_case_collection_path` | `PlaywrightScriptGenerationRequest` | Path to an approved `TestCaseCollection` in `specs/approved/` |
| `base_url` | `PlaywrightGenerationConstraints` | Target base URL for the test environment |
| `output_directory` | `PlaywrightGenerationConstraints` | Must resolve to `tests/generated/` |

## Optional

| Field | Model | Description |
|---|---|---|
| `browser` | `PlaywrightGenerationConstraints.browser` | Target browser; defaults to `BrowserName.CHROMIUM` |
| `headless` | `PlaywrightGenerationConstraints.headless` | Headless mode flag; defaults to `True` |
| `capture_screenshots_on_failure` | `PlaywrightGenerationConstraints` | Capture screenshot on test failure; defaults to `True` |
| `capture_traces_on_failure` | `PlaywrightGenerationConstraints` | Capture trace on test failure; defaults to `True` |
| `categories_filter` | caller-supplied list of `TestCategory` | Limit generation to specific categories |
| `run_id` | UUID | Caller-supplied run identifier |

---

# 5. Preconditions and Input Validation

Before generating scripts, validate the following:

1. The `approved_test_case_collection_path` exists and is located under `specs/approved/`.
2. The collection deserializes as a valid `TestCaseCollection`.
3. Every `TestCase` in the collection has `ApprovalStatus.APPROVED`. If any case has a different status, exclude it, record a `WarningDetail`, and continue with the approved subset.
4. At least one approved `TestCase` remains after filtering.
5. `output_directory` resolves to `tests/generated/` and does not traverse outside the repository root.
6. `base_url` is a valid HTTP or HTTPS URL. Do not use a production URL unless explicitly permitted by environment configuration.
7. No `TestCase` in the collection contains embedded credentials or secrets in test data fields.

If validation fails, return a structured `OperationResult` with `success=False` and stop.

---

# 6. Relevant Existing Domain Models

| Model | Module | Purpose |
|---|---|---|
| `TestCase` | `src.models.test_cases` | Source test case including steps and evidence requirements |
| `TestStep` | `src.models.test_cases` | Ordered step used to generate each test action |
| `TestCaseCollection` | `src.models.test_cases` | Approved collection of test cases |
| `PlaywrightGenerationConstraints` | `src.models.playwright` | Generation configuration (browser, URL, paths, evidence settings) |
| `PlaywrightScriptGenerationRequest` | `src.models.playwright` | Full generation request |
| `GeneratedPlaywrightScript` | `src.models.playwright` | Descriptor for one generated `.spec.ts` file |
| `ArtifactMetadata` | `src.models.common` | Traceability and lifecycle metadata |
| `WarningDetail` | `src.models.common` | Non-blocking warning |
| `ErrorDetail` | `src.models.common` | Structured failure detail |
| `OperationResult` | `src.models.common` | Unified structured result |
| `ApprovalStatus` | `src.models.enums` | Must be `APPROVED` for input test cases |
| `ArtifactStatus` | `src.models.enums` | Set to `DRAFT` on all generated scripts |
| `ArtifactType` | `src.models.enums` | Must be `ArtifactType.PLAYWRIGHT_SCRIPT` |
| `BrowserName` | `src.models.enums` | Target browser for script configuration |
| `TestCategory` | `src.models.enums` | Used to group scripts by test category |

---

# 7. Detailed Numbered Execution Procedure

1. **Validate inputs.** Confirm the approved collection path exists, deserializes, and all required fields are present. Stop on failure.

2. **Assign a run identifier.** Use the caller-supplied `run_id` or generate a new UUID. Record it in `ArtifactMetadata`.

3. **Load approved test cases.** Read the `TestCaseCollection` from `specs/approved/`. Filter to cases with `ApprovalStatus.APPROVED` only. Record excluded cases as `WarningDetail`.

4. **Group by category.** Group the approved test cases by `TestCategory`. This determines the script file grouping strategy.

5. **Resolve output paths.** Confirm `output_directory` resolves to `tests/generated/`. Never resolve to any other directory.

6. **Generate script header.** For each group, produce a TypeScript file header:
   - `import { test, expect } from '@playwright/test';`
   - A comment block recording the run ID, generation timestamp, and source test case IDs
   - Any required fixture imports

7. **Generate test blocks.** For each `TestCase` in the group:
   a. Open a `test('<title> [<test_case_id>]', async ({ page }) => {` block
   b. Add `await page.goto(baseURL);` or the relevant page URL derived from preconditions
   c. For each `TestStep`, translate `action` into a Playwright action and `expected_result` into an `expect()` assertion
   d. Apply locator selection in preference order: `getByRole` → `getByLabel` → `getByPlaceholder` → `getByText` → `getByTestId` → stable CSS → XPath
   e. Never use `page.waitForTimeout()` for synchronization; use `expect(locator).toBeVisible()`, `page.waitForURL()`, `page.waitForLoadState()`, or response events
   f. If `capture_screenshots_on_failure` is true, include `expect` soft assertions or use `test.afterEach` with `testInfo.status` check
   g. Close the test block

8. **Add fixture reuse.** Extract shared setup (navigation, authentication scaffolding without credentials) into `test.beforeEach` or a shared fixture if multiple test cases share the same preconditions. Never embed credentials.

9. **Handle non-automatable test cases.** For `AutomationSuitability.NOT_SUITABLE` cases, generate a skipped test block with a comment describing the manual verification steps. Record a `WarningDetail`.

10. **Handle exploration-required test cases.** For `AutomationSuitability.REQUIRES_EXPLORATION`, generate a skeleton test block with `test.skip()` and a comment directing the reviewer to run Playwright MCP exploration first. Record a `WarningDetail`.

11. **Write script files.** Save each generated `.spec.ts` file to `tests/generated/<run_id>-<category>.spec.ts`. File names must match `^[A-Za-z0-9][A-Za-z0-9._-]*\.spec\.ts$`.

12. **Build `GeneratedPlaywrightScript` descriptors.** For each file, record: `artifact_id`, `run_id`, `source_test_case_ids`, `script_path`, `category`, `artifact_status` (`DRAFT`), `approval_status` (`PENDING`).

13. **Validate written files.** Confirm each file is non-empty, exists at the recorded path, and the path is within `tests/generated/`.

14. **Assemble `OperationResult`.** Include: list of `GeneratedPlaywrightScript` descriptors, run ID, warnings, errors, and `success=True` if at least one script was written.

15. **Stop and request human approval.** Surface the script paths and source test case mapping to the caller. Do not execute any script. The workflow transitions to `WorkflowStage.AWAITING_SCRIPT_APPROVAL`.

---

# 8. Decision Rules

- If no approved test cases exist, return `OperationResult(success=False)` and stop.
- If a test step cannot be mapped to a deterministic Playwright action, generate a `// TODO: Manual step — <expected_result>` comment and record a `WarningDetail`.
- If a test case has `AutomationSuitability.NOT_SUITABLE`, generate a skipped block; do not omit it silently.
- If the output path resolves outside `tests/generated/`, reject the request and stop.
- Never import production credentials or environment-specific secrets into any script.
- Never generate a script that calls `page.waitForTimeout()` as the only synchronization mechanism.
- If a generated file would overwrite an existing approved script, stop and record an error; never overwrite approved artifacts.

---

# 9. Structured Output Requirements

The skill must return an `OperationResult` containing:

- `success`: `True` if at least one script was written
- `artifacts`: list of `ArtifactReference` for each `GeneratedPlaywrightScript`
- `run_id`: UUID
- `message`: summary of scripts generated and test cases covered
- `warnings`: list of `WarningDetail` (non-automatable cases, exploration-required cases, skipped steps)
- `errors`: list of `ErrorDetail` (validation failures, write failures, path violations)
- `metadata`: dict mapping `test_case_id` to generated script path

---

# 10. Artifact Location and Traceability Rules

- Generated scripts are saved exclusively to: `tests/generated/`
- File naming: `tests/generated/<run_id>-<category>.spec.ts`
- Approved scripts live in: `tests/smoke/`, `tests/integration/`, `tests/ui/` — this skill never writes there
- Every `GeneratedPlaywrightScript` and `ArtifactMetadata` must include: `artifact_id`, `run_id`, `source_test_case_ids`, `skill_name` (`generate-playwright-scripts`), `artifact_type` (`ArtifactType.PLAYWRIGHT_SCRIPT`), `artifact_status` (`ArtifactStatus.DRAFT`), `approval_status` (`ApprovalStatus.PENDING`)
- Parent artifact IDs from the source `TestCaseCollection` must be recorded

---

# 11. Evidence Requirements

This skill generates scripts, not execution evidence. No test results, screenshots, or traces are produced at this stage. Evidence capture configuration (`capture_screenshots_on_failure`, `capture_traces_on_failure`) is embedded in the generated scripts so that evidence is collected when the scripts are later executed.

---

# 12. Human Approval Requirements

**Checkpoint B applies.** After this skill completes successfully, the workflow must:

1. Transition to `WorkflowStage.AWAITING_SCRIPT_APPROVAL`
2. Present the generated script paths, source test case mapping, and warnings to a human reviewer
3. Block all execution until `ApprovalStatus.APPROVED` is recorded on each script
4. If rejected, return to step 6 of the execution procedure with reviewer feedback
5. If approved, a separate promotion step must move the approved scripts to the correct target directory before execution

---

# 13. Safety Guardrails

- Never execute any script produced by this skill, even partially.
- Never write to `tests/smoke/`, `tests/integration/`, `tests/ui/`, or any directory outside `tests/generated/`.
- Never embed credentials, passwords, tokens, or connection strings in any generated script.
- Never generate a script that modifies the application under test.
- Never approve scripts automatically.
- Never overwrite an existing approved script with a draft.
- Never use `page.waitForTimeout()` as the only synchronization strategy.
- Never connect to Azure DevOps MCP or App Factory from within this skill.
- Never generate scripts against a production base URL unless explicitly enabled in environment configuration.

---

# 14. Failure Handling and Failure Classification

| Failure | Classification | Action |
|---|---|---|
| Approved collection not found | `FailureSource.TOOL` | Record in `ErrorDetail`, return `OperationResult(success=False)`, stop |
| No approved test cases in collection | `FailureSource.APPROVAL` | Record in `ErrorDetail`, return `OperationResult(success=False)`, stop |
| Output path outside `tests/generated/` | `FailureSource.CONFIGURATION` | Record in `ErrorDetail`, stop immediately |
| Script write failure | `FailureSource.TOOL` | Record in `ErrorDetail`, mark artifact `ArtifactStatus.INCOMPLETE` |
| Test step cannot be mapped | `FailureSource.SKILL` | Record as `WarningDetail`, generate TODO comment, continue |
| Generated file would overwrite approved artifact | `FailureSource.WORKFLOW` | Record in `ErrorDetail`, stop |

---

# 15. Warning and Uncertainty Handling

Record a `WarningDetail` for:

- Test cases excluded because `ApprovalStatus` is not `APPROVED`
- Test steps that could not be fully translated into deterministic Playwright actions
- Test cases marked `AutomationSuitability.NOT_SUITABLE` (skipped blocks generated)
- Test cases marked `AutomationSuitability.REQUIRES_EXPLORATION` (skeleton blocks generated)
- Locators that could not be determined from test step text alone (reviewer guidance comment added)

---

# 16. Acceptance Criteria

The skill is considered successful when:

1. At least one `.spec.ts` file has been written to `tests/generated/`.
2. Every generated `test()` block references its source `test_case_id` in the title or a comment.
3. Every generated script uses `@playwright/test` imports only.
4. No script contains hard-coded credentials.
5. No script uses `page.waitForTimeout()` as its only synchronization.
6. Every generated script has `ArtifactStatus.DRAFT` and `ApprovalStatus.PENDING`.
7. `OperationResult` has been returned with `success=True`.
8. The workflow is blocked at `WorkflowStage.AWAITING_SCRIPT_APPROVAL`.

---

# 17. Completion Criteria

This skill is complete when:

- All generated `.spec.ts` files exist under `tests/generated/`
- `OperationResult` has been returned to the workflow
- The workflow has transitioned to `WorkflowStage.AWAITING_SCRIPT_APPROVAL`
- No script has been executed or promoted

---

# 18. Workflow Handoff

On success: hand off to human reviewer via `WorkflowStage.AWAITING_SCRIPT_APPROVAL`. Execution may begin only after a human records `ApprovalStatus.APPROVED` and a separate promotion step copies the script to the appropriate approved directory.

On failure: workflow returns to `WorkflowStage.TEST_CASES_APPROVED`. The caller receives a structured failure and must address the cause before retrying.

---

# 19. Valid Example

**Input:**
- Approved test case collection: `specs/approved/run-abc123-test-cases.json`
- Contains 4 approved test cases: `TC-LOGIN-001` (smoke), `TC-LOGIN-002` (functional_ui), `TC-LOGIN-003` (functional_ui), `TC-LOGIN-005` (accessibility)
- `base_url`: `http://localhost:3000`
- `output_directory`: `tests/generated/`

**Generated output:**
- `tests/generated/run-abc123-smoke.spec.ts` — contains `test('Login page loads without errors [TC-LOGIN-001]', ...)`
- `tests/generated/run-abc123-functional_ui.spec.ts` — contains `test('Successful login redirects to dashboard [TC-LOGIN-002]', ...)` and `test('Invalid password shows error [TC-LOGIN-003]', ...)`
- `tests/generated/run-abc123-accessibility.spec.ts` — contains `test('Login form passes keyboard navigation [TC-LOGIN-005]', ...)`

All scripts use `getByRole` and `getByLabel` locators. No `waitForTimeout`. Screenshots and traces configured on failure. All scripts have `ArtifactStatus.DRAFT`, `ApprovalStatus.PENDING`.

Workflow halts at: `WorkflowStage.AWAITING_SCRIPT_APPROVAL`

---

# 20. Blocked or Failure Example

**Input:**
- Approved test case collection: `specs/approved/run-xyz789-test-cases.json`
- Collection contains 3 test cases all with `ApprovalStatus.PENDING` (not yet approved)

**Outcome:**

- Precondition check: zero test cases have `ApprovalStatus.APPROVED`
- `ErrorDetail` recorded: `"No approved test cases found in the provided collection. All 3 cases have ApprovalStatus.PENDING. Script generation requires ApprovalStatus.APPROVED."`
- `OperationResult(success=False)` returned
- Workflow remains at `WorkflowStage.AWAITING_TEST_CASE_APPROVAL`
- Recommended action: Have a human reviewer approve the test cases in `specs/approved/run-xyz789-test-cases.json` before re-invoking this skill
