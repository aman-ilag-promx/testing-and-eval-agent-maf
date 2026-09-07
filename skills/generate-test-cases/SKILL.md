---
name: generate-test-cases
description: Use this skill when producing structured test case drafts from implementation context.
metadata:
  version: 1.0.0
  category: testing
---

# 1. Skill Name and Purpose

**Skill:** `generate-test-cases`

This skill generates structured, traceable test cases from an implementation plan, original user request, or implementation artifact. It extracts verifiable requirements, maps each requirement to positive, negative, and edge-case test scenarios, produces ordered test steps with explicit expected results, and saves all output as draft artifacts under `specs/generated/`. The skill then stops and requests human approval before any downstream script generation begins.

---

# 2. Scope

This skill covers:

- Requirement extraction from `ImplementationInput` (original user request, implementation plan, constraints, assumptions)
- Test-case generation across all `TestCategory` values: `smoke`, `integration`, `self_test`, `functional_ui`, `visual_ui`, `responsive_ui`, `performance`, `usability`, `accessibility`, `ai_evaluation`, `plan_vs_implementation`
- Priority assignment using `TestPriority`: `critical`, `high`, `medium`, `low`
- Automation suitability assessment using `AutomationSuitability`
- Coverage mapping that identifies uncovered or ambiguous requirements
- Draft persistence under `specs/generated/`
- Presentation of the collection for human approval

This skill does not:

- Generate Playwright scripts
- Execute any tests
- Approve test cases
- Modify any source, configuration, or tested application file

---

# 3. When to Use and When Not to Use

**Use this skill when:**

- A new implementation plan or user requirement has been received and test cases do not yet exist
- Existing test cases must be regenerated after a plan change
- A test coverage gap has been identified and additional test cases are needed
- A smoke, UI, integration, evaluation, or plan-comparison test pass requires structured input

**Do not use this skill when:**

- Approved test cases already exist and only Playwright scripts are needed (use `generate-playwright-scripts`)
- Tests are ready to execute (use `smoke-testing`, `ui-testing`, or `integration-self-testing`)
- Evaluation against rubric criteria is required without additional test cases (use `evaluation-testing`)
- The plan-versus-implementation comparison does not need new test coverage (use `plan-vs-implementation`)

---

# 4. Required and Optional Inputs

## Required

| Field | Model | Description |
|---|---|---|
| `title` | `ImplementationInput.title` | Short label for the implementation being tested |
| `original_user_request` | `ImplementationInput.original_user_request` | The verbatim or summarized original requirement |
| `target_scope` | `ImplementationInput.target_scope` | Boundaries of what must be tested |

## Optional

| Field | Model | Description |
|---|---|---|
| `implementation_plan` | `ImplementationInput.implementation_plan` | Approved implementation plan text |
| `constraints` | `ImplementationInput.constraints` | Known restrictions to apply during generation |
| `assumptions` | `ImplementationInput.assumptions` | Stated assumptions that narrow the test scope |
| `source_references` | `ImplementationInput.source_references` | Referenced requirements, ticket IDs, or document links |
| `requested_categories` | caller-supplied list of `TestCategory` | Limit generation to specific test categories |
| `run_id` | UUID | Caller-supplied run identifier for traceability |

---

# 5. Preconditions and Input Validation

Before generating test cases, validate the following:

1. `ImplementationInput` passes Pydantic model validation (all required fields present, no empty strings, length bounds respected).
2. `target_scope` is non-empty and does not reference a production environment unless explicitly permitted.
3. `original_user_request` contains at least one identifiable requirement or behavior statement.
4. If `implementation_plan` is provided, it must not be empty after whitespace stripping.
5. All items in `constraints` and `assumptions` are unique and non-empty.
6. No input field contains embedded credentials, connection strings, or secrets.

If any validation step fails, return a structured `OperationResult` with `success=False`, record the failure in `ErrorDetail`, and stop without generating any test cases.

---

# 6. Relevant Existing Domain Models

| Model | Module | Purpose |
|---|---|---|
| `ImplementationInput` | `src.models.test_cases` | Validated input source for generation |
| `TestStep` | `src.models.test_cases` | One ordered step with action and expected result |
| `TestCase` | `src.models.test_cases` | Structured and traceable test case |
| `TestCaseGenerationRequest` | `src.models.test_cases` | Full generation request |
| `TestCaseCollection` | `src.models.test_cases` | Collection of generated test cases with metadata |
| `ArtifactMetadata` | `src.models.common` | Traceability and lifecycle metadata |
| `WarningDetail` | `src.models.common` | Non-blocking warning |
| `ErrorDetail` | `src.models.common` | Structured failure detail |
| `OperationResult` | `src.models.common` | Unified structured result |
| `TestCategory` | `src.models.enums` | Test classification values |
| `TestPriority` | `src.models.enums` | Priority values |
| `AutomationSuitability` | `src.models.enums` | Automation readiness values |
| `ApprovalStatus` | `src.models.enums` | Approval lifecycle values |
| `ArtifactStatus` | `src.models.enums` | Artifact lifecycle values |
| `ArtifactType` | `src.models.enums` | Must be `ArtifactType.TEST_CASE_COLLECTION` for the saved collection |

---

# 7. Detailed Numbered Execution Procedure

1. **Validate input.** Instantiate and validate `ImplementationInput` via Pydantic. Record any validation failure in `ErrorDetail` and stop.

2. **Assign a run identifier.** Use the caller-supplied `run_id` or generate a new UUID. Record it in `ArtifactMetadata`.

3. **Extract requirements.** Parse `original_user_request` and `implementation_plan` to produce a deduplicated list of discrete, testable requirement statements. Assign each a `requirement_id` following the pattern `REQ-NNN`. Record any ambiguous, incomplete, or untestable statement as a `WarningDetail`.

4. **Map categories.** For each requirement, determine which `TestCategory` values apply: `smoke` for availability, `functional_ui` for user-facing behavior, `integration` for component interactions, `accessibility` for assistive-technology compliance, and so on. If `requested_categories` was provided, generate only for those categories.

5. **Generate positive scenarios.** For each requirement and each applicable category, create at least one test case verifying the requirement succeeds under normal conditions.

6. **Generate negative scenarios.** For each requirement, create at least one test case verifying the system responds correctly to invalid, missing, or boundary-condition input.

7. **Generate edge cases.** For requirements involving boundaries, concurrency, large data, empty state, or optional features, create additional edge-case test cases.

8. **Assign priority.** Set `TestPriority` for each test case:
   - `critical`: core user path or safety boundary
   - `high`: important feature or data integrity
   - `medium`: secondary behavior or non-critical path
   - `low`: cosmetic, optional, or low-impact behavior

9. **Write ordered steps.** For each test case, produce a list of `TestStep` objects with sequential `step_number`, explicit `action`, and explicit `expected_result`. Minimum one step per test case.

10. **Assess automation suitability.** Assign `AutomationSuitability` to each test case:
    - `suitable`: fully automatable with Playwright Test
    - `partially_suitable`: automatable with manual verification for some steps
    - `not_suitable`: inherently manual (e.g., physical device, visual judgment without tooling)
    - `requires_exploration`: Playwright MCP exploration required before scripting

11. **Record evidence requirements.** List the evidence types (screenshot, trace, assertion, accessibility snapshot, etc.) required to confirm each test case passed.

12. **Record safety considerations.** Note any destructive actions, environment dependencies, or data state requirements for each test case.

13. **Build coverage map.** List every extracted requirement ID alongside the test case IDs that cover it. Identify requirements with no coverage and add them as warnings.

14. **Assign test case IDs.** Use uppercase alphanumeric identifiers matching `^[A-Z][A-Z0-9_-]{2,49}$` (e.g., `TC-SMOKE-001`, `TC-AUTH-NEG-002`).

15. **Set approval status.** Set `ApprovalStatus.PENDING` and `ArtifactStatus.DRAFT` on every test case and on the collection.

16. **Persist the draft collection.** Save the `TestCaseCollection` to `specs/generated/<run_id>-test-cases.json`. Never write to `specs/approved/`.

17. **Validate the persisted artifact.** Confirm the file was written, is non-empty, and deserializes correctly. Record a warning if validation fails.

18. **Assemble `OperationResult`.** Include: artifact reference, run ID, coverage map, list of uncovered requirements, warnings, errors, and `success=True` if at least one test case was generated and persisted.

19. **Stop and request human approval.** Surface the draft collection path and coverage summary to the caller. Do not proceed to script generation. The workflow transitions to `WorkflowStage.AWAITING_TEST_CASE_APPROVAL`.

---

# 8. Decision Rules

- If zero testable requirements can be extracted, return a structured failure and stop.
- If an extracted requirement is ambiguous, record a `WarningDetail` and generate a placeholder test case marked with a warning; do not invent application behavior.
- If `constraints` conflict with a generated test case, remove the test case and record a warning explaining the conflict.
- If a requirement cannot be safely tested (e.g., it implies a destructive action), set `safety_considerations` and `AutomationSuitability.NOT_SUITABLE`; do not suppress the test case.
- If `implementation_plan` contradicts `original_user_request`, record both as `WarningDetail` entries and generate test cases for both; do not silently resolve the conflict.
- Never assign `ApprovalStatus.APPROVED` during generation regardless of model confidence.

---

# 9. Structured Output Requirements

The skill must return an `OperationResult` containing:

- `success`: `True` if at least one test case was persisted, `False` otherwise
- `artifact`: `ArtifactReference` pointing to the saved `TestCaseCollection`
- `run_id`: UUID of this run
- `message`: Human-readable summary of generation outcome
- `warnings`: list of `WarningDetail` (ambiguities, uncovered requirements, conflict resolutions)
- `errors`: list of `ErrorDetail` (validation failures, persistence failures)
- `metadata`: coverage map as a dict mapping requirement IDs to lists of test case IDs

---

# 10. Artifact Location and Traceability Rules

- Draft test cases are saved exclusively to: `specs/generated/`
- File naming: `specs/generated/<run_id>-test-cases.json`
- Approved test cases live at: `specs/approved/` — this skill never writes there
- Every `ArtifactMetadata` field must be populated: `artifact_id`, `run_id`, `created_at`, `source_input_reference`, `skill_name` (`generate-test-cases`), `artifact_type` (`ArtifactType.TEST_CASE_COLLECTION`), `artifact_status` (`ArtifactStatus.DRAFT`), `approval_status` (`ApprovalStatus.PENDING`)
- Parent artifact IDs from the originating `ImplementationInput` must be recorded if provided

---

# 11. Evidence Requirements

This skill produces draft structured data artifacts, not execution evidence. No screenshots, traces, or test results are required. Evidence references are recorded within each `TestCase` as `evidence_required` to inform future execution.

---

# 12. Human Approval Requirements

**Checkpoint A applies.** After this skill completes successfully, the workflow must:

1. Transition to `WorkflowStage.AWAITING_TEST_CASE_APPROVAL`
2. Present the draft collection path, coverage summary, uncovered requirements, and warnings to a human reviewer
3. Block all downstream operations (`generate-playwright-scripts`, execution, evaluation) until `ApprovalStatus.APPROVED` is recorded for the collection
4. If the reviewer rejects (`ApprovalStatus.REJECTED`) or requests changes (`ApprovalStatus.CHANGES_REQUESTED`), return to step 3 of the execution procedure with the reviewer's feedback

---

# 13. Safety Guardrails

- Never set `ApprovalStatus.APPROVED` automatically on any generated artifact.
- Never write any file to `specs/approved/`, `tests/generated/`, `tests/smoke/`, `tests/integration/`, or `tests/ui/`.
- Never generate test cases that embed credentials, tokens, or secrets.
- Never invent application behavior not supported by the input.
- Never test against a production environment.
- Never trigger Playwright MCP or Playwright Test from within this skill.
- Never modify any file outside `specs/generated/`.
- Never overwrite an already-approved test case collection with a draft.
- Never continue to script generation if this skill returned `success=False`.

---

# 14. Failure Handling and Failure Classification

| Failure | Classification | Action |
|---|---|---|
| Pydantic validation error on input | `FailureSource.TOOL` | Record in `ErrorDetail`, return `OperationResult(success=False)`, stop |
| Zero testable requirements extracted | `FailureSource.MODEL_OUTPUT` | Record in `ErrorDetail`, return `OperationResult(success=False)`, stop |
| File persistence failure | `FailureSource.TOOL` | Record in `ErrorDetail`, mark artifact `ArtifactStatus.INCOMPLETE`, return `OperationResult(success=False)` |
| Deserialization validation failure after write | `FailureSource.TOOL` | Record in `WarningDetail`, continue but flag artifact as potentially incomplete |
| Plan contradicts request | `FailureSource.SKILL` | Record as `WarningDetail`, generate for both, surface to reviewer |

Never hide failures. Every failure must be surfaced in `OperationResult.errors` or `OperationResult.warnings`.

---

# 15. Warning and Uncertainty Handling

Record a `WarningDetail` for:

- Ambiguous or untestable requirement statements
- Requirements with no test case coverage
- Constraint conflicts that removed a test case
- Assumptions that materially narrow coverage
- Any model output that was not used verbatim (e.g., hallucinated step)
- Input fields that were empty but not required

Warnings do not block generation but must be presented to the human reviewer.

---

# 16. Acceptance Criteria

The skill is considered successful when:

1. At least one `TestCase` has been generated for each extracted, testable requirement.
2. Every `TestCase` contains at least one `TestStep` with a non-empty `action` and `expected_result`.
3. Every `TestCase` has a unique `test_case_id` matching the identifier pattern.
4. Every `TestCase` has `ApprovalStatus.PENDING` and `ArtifactStatus.DRAFT`.
5. The collection has been persisted to `specs/generated/` and deserializes without error.
6. A coverage map has been produced identifying all requirement IDs and their covering test cases.
7. Uncovered requirements have been surfaced as warnings.
8. `OperationResult` has been returned with `success=True`.
9. The workflow is blocked at `WorkflowStage.AWAITING_TEST_CASE_APPROVAL`.

---

# 17. Completion Criteria

This skill is complete when:

- The draft collection file exists at `specs/generated/<run_id>-test-cases.json`
- The `OperationResult` has been returned to the workflow
- The workflow has transitioned to `WorkflowStage.AWAITING_TEST_CASE_APPROVAL`
- No further processing has been initiated by this skill

---

# 18. Workflow Handoff

On success: hand off to human reviewer via `WorkflowStage.AWAITING_TEST_CASE_APPROVAL`. The `generate-playwright-scripts` skill may begin only after a human records `ApprovalStatus.APPROVED` on the collection.

On failure: the workflow remains at or returns to `WorkflowStage.INPUT_VALIDATED`. The caller receives a structured failure result and must address the cause before retrying.

---

# 19. Valid Example

**Input:**
```
title: "User Login Feature"
original_user_request: "Users must be able to log in with their email and password. Invalid credentials must show an error message. The login form must be accessible."
target_scope: "Login page of the web application"
```

**Generated output (summary):**
- `TC-LOGIN-001` (smoke, critical): Login page loads without errors
- `TC-LOGIN-002` (functional_ui, critical): Successful login with valid credentials redirects to dashboard
- `TC-LOGIN-003` (functional_ui, high): Invalid password displays error message
- `TC-LOGIN-004` (functional_ui, high): Empty email field prevents submission
- `TC-LOGIN-005` (accessibility, high): Login form passes WCAG 2.1 AA keyboard navigation check
- `TC-LOGIN-006` (functional_ui, medium): Login with non-existent email displays error message

Coverage map: `REQ-001` covered by TC-LOGIN-001, TC-LOGIN-002; `REQ-002` covered by TC-LOGIN-003, TC-LOGIN-006; `REQ-003` covered by TC-LOGIN-004; `REQ-004` covered by TC-LOGIN-005.

Persisted to: `specs/generated/<run_id>-test-cases.json`

Status: `ArtifactStatus.DRAFT`, `ApprovalStatus.PENDING`

Workflow halts at: `WorkflowStage.AWAITING_TEST_CASE_APPROVAL`

---

# 20. Blocked or Failure Example

**Input:**
```
title: "Analytics Dashboard"
original_user_request: "The dashboard should look nice."
target_scope: "Analytics dashboard"
```

**Outcome:**

- Requirement extraction produces one ambiguous statement: "should look nice" — no measurable acceptance criterion
- `WarningDetail` recorded: `"Requirement 'should look nice' is subjective and not testable without a defined visual rubric. No test case generated."`
- Zero testable requirements extracted
- `ErrorDetail` recorded: `"No testable requirements could be extracted from the provided input."`
- `OperationResult(success=False)` returned
- Workflow remains at `WorkflowStage.INPUT_VALIDATED`
- Recommended action: Provide specific, measurable requirements (e.g., "All KPI cards must display the correct value from the data source." or "The chart colors must conform to the approved brand palette defined in design-spec.md.")
