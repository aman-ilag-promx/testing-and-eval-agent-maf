---
name: plan-vs-implementation
description: Use this skill when comparing intended test plans against produced artifacts and outcomes.
metadata:
  version: 1.0.0
  category: testing
---

# 1. Skill Name and Purpose

**Skill:** `plan-vs-implementation`

This skill acts as an independent reviewer that compares the original user request and approved implementation plan against the completed implementation artifacts, test execution evidence, and evaluation findings. It classifies each identified requirement using the `RequirementStatus` enum, produces a structured gap analysis, and generates improvement recommendations. It does not modify the implementation. It stops after producing its findings and requires human review before any downstream change is proposed or applied.

---

# 2. Scope

This skill covers:

- Parsing the original user request and approved implementation plan to extract discrete requirements
- Mapping each requirement to available implementation artifacts, test execution results, and evaluation results
- Classifying each requirement as: `fully_implemented`, `partially_implemented`, `missing`, `changed`, `additional_unrequested_behavior`, or `not_verifiable`
- Identifying evidence that supports each classification
- Calculating a coverage summary
- Producing improvement recommendations for each gap
- Persisting the plan comparison result to `reports/`
- Presenting findings for human review

This skill does not:

- Modify any implementation file, configuration, or source artifact
- Approve or reject findings automatically
- Execute tests or generate test cases
- Invent requirements not present in the original request or plan
- Produce a finding without traceable evidence or explicit documentation of missing evidence

---

# 3. When to Use and When Not to Use

**Use this skill when:**

- Implementation artifacts and test execution results are available and need to be compared to the original plan
- The final stage of a testing workflow requires a structured gap analysis before reporting
- A reviewer needs to confirm that all approved requirements have been addressed
- Material implementation drift has been detected and needs to be documented

**Do not use this skill when:**

- No approved implementation plan or original user request is available
- Test execution has not yet occurred (evidence would be insufficient for most requirements)
- Only AI feature quality scoring is needed (use `evaluation-testing`)
- A structural gap analysis is not required

---

# 4. Required and Optional Inputs

## Required

| Field | Model | Description |
|---|---|---|
| `original_user_request` | `ImplementationInput.original_user_request` | Verbatim or summarized original requirement |
| `implementation_artifacts` | list of `ArtifactReference` | References to generated or modified implementation files |
| `run_id` | UUID | Run identifier for traceability |

## Optional

| Field | Model | Description |
|---|---|---|
| `approved_implementation_plan` | `ImplementationInput.implementation_plan` | Text of the approved implementation plan |
| `execution_results` | list of `PlaywrightExecutionResult` | Deterministic test execution evidence |
| `evaluation_result` | `EvaluationResult` | Approved evaluation findings |
| `approved_test_case_collection_path` | path string | Path to the approved test case collection for traceability |
| `evaluation_approved` | bool | Confirmation that `evaluation_result` has `ApprovalStatus.APPROVED` |

---

# 5. Preconditions and Input Validation

1. `original_user_request` is non-empty.
2. At least one `ArtifactReference` is provided in `implementation_artifacts`.
3. Each `ArtifactReference` has a valid `artifact_id`, `artifact_type`, and recorded `artifact_status`.
4. If `execution_results` are provided, each has a recorded `ExecutionStatus` (not `NOT_STARTED`).
5. If `evaluation_result` is provided and `evaluation_approved` is `True`, the `evaluation_result` must have `ApprovalStatus.APPROVED`. If `evaluation_approved` is `False` or not provided, record a `WarningDetail` that evaluation findings are unreviewed and reduce confidence accordingly.
6. `run_id` is a valid UUID.

Return `OperationResult(success=False)` and stop if any required field fails validation.

---

# 6. Relevant Existing Domain Models

| Model | Module | Purpose |
|---|---|---|
| `ImplementationInput` | `src.models.test_cases` | Source of original request and plan text |
| `PlaywrightExecutionResult` | `src.models.playwright` | Deterministic execution evidence |
| `EvaluationResult` | `src.models.evaluation` | Approved evaluation findings |
| `ArtifactReference` | `src.models.common` | Reference to an implementation artifact |
| `EvidenceReference` | `src.models.common` | Evidence supporting a finding |
| `ArtifactMetadata` | `src.models.common` | Traceability metadata |
| `WarningDetail` | `src.models.common` | Non-blocking warning |
| `ErrorDetail` | `src.models.common` | Structured failure |
| `OperationResult` | `src.models.common` | Unified structured result |
| `RequirementStatus` | `src.models.enums` | Classification values for each requirement |
| `Severity` | `src.models.enums` | Severity of a gap finding |
| `ArtifactType` | `src.models.enums` | Must be `ArtifactType.PLAN_COMPARISON` for the result |
| `ArtifactStatus` | `src.models.enums` | Set to `AWAITING_APPROVAL` after comparison |
| `ApprovalStatus` | `src.models.enums` | `PENDING` until human reviews |
| `EvidenceType` | `src.models.enums` | Types of supporting evidence |

---

# 7. Detailed Numbered Execution Procedure

1. **Validate inputs.** Check all preconditions. Return failure and stop if any fail.

2. **Assign a run identifier.** Use caller-supplied `run_id`. Record in `ArtifactMetadata`.

3. **Extract requirements.** Parse `original_user_request` and `approved_implementation_plan` to produce a deduplicated list of discrete, verifiable requirement statements. Assign each a `requirement_id` (e.g., `REQ-001`). Record ambiguous requirements as `WarningDetail`.

4. **Index available evidence.** Build an evidence index from:
   - `implementation_artifacts` (existence and status)
   - `execution_results` (per-test `ExecutionStatus`, assertions, failure details)
   - `evaluation_result` (per-criterion outcomes, if approved)
   - Assign `EvidenceReference` objects for each piece of evidence.

5. **Classify each requirement.** For each `requirement_id`, apply the following decision logic:

   | Condition | Status |
   |---|---|
   | Implementation artifact exists, all relevant tests pass, evaluation criterion passes (where applicable) | `FULLY_IMPLEMENTED` |
   | Implementation artifact exists, some relevant tests pass, some fail or are missing | `PARTIALLY_IMPLEMENTED` |
   | No implementation artifact or test coverage exists | `MISSING` |
   | Implementation artifact exists but behavior differs from the original requirement | `CHANGED` |
   | Implementation artifact adds functionality not present in the original request | `ADDITIONAL_UNREQUESTED_BEHAVIOR` |
   | Insufficient evidence to make any classification | `NOT_VERIFIABLE` |

6. **Record evidence for each finding.** For each classification, list the `EvidenceReference` objects that support the decision. For `NOT_VERIFIABLE`, document exactly what evidence is missing.

7. **Assess gap impact.** For `MISSING`, `PARTIALLY_IMPLEMENTED`, and `CHANGED` requirements:
   - Assign `Severity`: `critical`, `high`, `medium`, `low`
   - Write an impact description
   - Write a specific improvement recommendation

8. **Identify additional unrequested behavior.** List all `ADDITIONAL_UNREQUESTED_BEHAVIOR` findings with a description of the behavior and whether it represents scope creep, an enhancement, or a risk.

9. **Compute coverage summary.** Calculate:
   - Total requirements extracted
   - Count per `RequirementStatus`
   - Percentage fully implemented
   - List of unverifiable requirements

10. **Check for material drift.** If the count of `MISSING` + `PARTIALLY_IMPLEMENTED` + `CHANGED` requirements exceeds zero in a critical-severity category, flag the result as requiring mandatory human review before downstream change proposals.

11. **Build plan comparison result.** Populate all fields: `comparison_id`, `run_id`, `requirements`, `findings`, `coverage_summary`, `improvement_recommendations`, `warnings`, `errors`, `ArtifactMetadata`.

12. **Persist result.** Save to `reports/<run_id>-plan-comparison.json`. Never write outside `reports/`.

13. **Validate persisted artifact.** Confirm file exists and deserializes correctly.

14. **Assemble `OperationResult`.** Include: artifact reference, coverage summary, finding counts by status and severity, warnings, errors, `success=True`.

15. **Stop and surface for human review.** The workflow transitions to `WorkflowStage.PLAN_COMPARISON_COMPLETED`. Do not propose or apply any changes.

---

# 8. Decision Rules

- Never classify a requirement as `FULLY_IMPLEMENTED` without at least one artifact reference and one passing test result or deterministic evidence.
- Never classify as `NOT_VERIFIABLE` if evidence is available but unfavorable; use the appropriate failing status.
- Never invent requirements not present in the input.
- Never propose implementation changes directly; recommendations are for human review only.
- If `evaluation_result` is provided but not approved, record it as `EvidenceType.MODEL_OUTPUT` with reduced confidence and add a `WarningDetail`.
- If the plan and the original request conflict, classify the conflicting requirement based on both sources and record the conflict as a `WarningDetail`.

---

# 9. Structured Output Requirements

The skill must return an `OperationResult` containing:

- `success`: `True` if the comparison completed and was persisted
- `artifact`: `ArtifactReference` to the plan comparison result
- `run_id`: UUID
- `coverage_summary`: dict with total count, per-status counts, coverage percentage
- `finding_counts_by_severity`: dict of severity to count (for `MISSING`, `PARTIALLY_IMPLEMENTED`, `CHANGED`)
- `additional_behavior_count`: integer
- `requires_human_review`: bool (True if any critical-severity gap exists)
- `warnings`: list of `WarningDetail`
- `errors`: list of `ErrorDetail`
- `message`: human-readable summary

---

# 10. Artifact Location and Traceability Rules

- Plan comparison result: `reports/<run_id>-plan-comparison.json`
- This skill reads from (but never writes to): `specs/approved/`, `evals/results/`, `reports/` (for evidence references)
- Every result must include `ArtifactMetadata`: `skill_name` (`plan-vs-implementation`), `artifact_type` (`ArtifactType.PLAN_COMPARISON`), `artifact_status` (`ArtifactStatus.AWAITING_APPROVAL`), `approval_status` (`ApprovalStatus.PENDING`), `run_id`, `created_at`
- Parent artifact IDs from implementation artifacts and execution results must be recorded

---

# 11. Evidence Requirements

For each requirement classification:

- `FULLY_IMPLEMENTED`: at least one artifact reference + at least one `ExecutionStatus.PASSED` result
- `PARTIALLY_IMPLEMENTED`: at least one artifact reference + mixed test results or missing coverage
- `MISSING`: explicit statement that no artifact or test was found
- `CHANGED`: artifact reference + description of the behavioral difference
- `ADDITIONAL_UNREQUESTED_BEHAVIOR`: artifact reference + description of the additional behavior
- `NOT_VERIFIABLE`: explicit documentation of what evidence is needed

---

# 12. Human Approval Requirements

This skill produces findings for human review. No downstream change proposal is made without explicit human approval. The workflow must:

1. Transition to `WorkflowStage.PLAN_COMPARISON_COMPLETED`
2. Surface the result path, coverage summary, and critical-severity gaps to a human reviewer
3. Block any implementation modification or external-system action until the human acknowledges the findings

---

# 13. Safety Guardrails

- Never modify any implementation file, source file, configuration, or tested application.
- Never approve findings automatically.
- Never propose changes to a production environment.
- Never invent requirements not present in the input.
- Never classify a requirement without traceable evidence or explicit documentation of missing evidence.
- Never write results outside `reports/`.
- Never activate Azure DevOps MCP or App Factory.
- Never suppress gap findings because they are embarrassing or numerous.

---

# 14. Failure Handling and Failure Classification

| Failure | Classification | Action |
|---|---|---|
| Empty `original_user_request` | `FailureSource.TOOL` | Record error, stop |
| No `ArtifactReference` provided | `FailureSource.TOOL` | Record error, stop |
| Unapproved evaluation result used as evidence | `FailureSource.APPROVAL` | Record warning, reduce confidence, continue |
| Requirement extraction yields zero requirements | `FailureSource.SKILL` | Record error, stop |
| Persistence failure | `FailureSource.TOOL` | Record error, flag artifact `INCOMPLETE` |
| Plan contradicts original request | `FailureSource.SKILL` | Record warning, classify based on both sources |

---

# 15. Warning and Uncertainty Handling

Record a `WarningDetail` for:

- Requirements that could not be unambiguously extracted
- Evaluation results used but not yet approved by a human
- Requirements classified as `NOT_VERIFIABLE` due to missing evidence
- Plan-to-request conflicts
- Additional unrequested behaviors that may represent scope creep
- Very low coverage percentage (flagged for mandatory reviewer attention)

---

# 16. Acceptance Criteria

The skill is considered successful when:

1. Every extracted requirement has a `RequirementStatus` classification.
2. Every classification has at least one evidence reference or an explicit documentation of missing evidence.
3. All `MISSING`, `PARTIALLY_IMPLEMENTED`, and `CHANGED` findings have a severity and improvement recommendation.
4. The result is persisted to `reports/`.
5. `OperationResult` returned with `success=True`.
6. No implementation file was modified.

---

# 17. Completion Criteria

This skill is complete when:

- The plan comparison result file exists at `reports/<run_id>-plan-comparison.json`
- `OperationResult` returned to workflow
- Workflow transitioned to `WorkflowStage.PLAN_COMPARISON_COMPLETED`
- No implementation change has been initiated

---

# 18. Workflow Handoff

On success: workflow transitions to `WorkflowStage.PLAN_COMPARISON_COMPLETED`. Report generation may proceed. Implementation changes require explicit human approval.

On failure: caller receives structured failure. Dependent steps are blocked.

---

# 19. Valid Example

**Input:**
- `original_user_request`: "Users must log in with email and password. Invalid credentials must show an error. The login form must be keyboard accessible."
- `approved_implementation_plan`: references login component implementation
- `implementation_artifacts`: 2 artifact references (login component, error message component)
- `execution_results`: 5 passing tests (TC-LOGIN-001 through TC-LOGIN-005)
- `evaluation_result`: accessibility criterion `partially_passed` (approved)

**Outcome:**
- 3 requirements extracted: `REQ-001` (login), `REQ-002` (error message), `REQ-003` (accessibility)
- `REQ-001`: `FULLY_IMPLEMENTED` — artifact + TC-LOGIN-001, TC-LOGIN-002 passed
- `REQ-002`: `FULLY_IMPLEMENTED` — artifact + TC-LOGIN-003, TC-LOGIN-006 passed
- `REQ-003`: `PARTIALLY_IMPLEMENTED` — artifact exists, TC-LOGIN-005 passed but evaluation shows 2 WCAG violations. Severity: `high`. Recommendation: "Fix 2 WCAG 2.1 AA violations identified in accessibility snapshot."
- Coverage: 2/3 fully implemented (67%), 1/3 partially implemented
- Persisted: `reports/<run_id>-plan-comparison.json`
- Workflow: `PLAN_COMPARISON_COMPLETED`

---

# 20. Blocked or Failure Example

**Input:**
- `original_user_request`: "" (empty string)

**Outcome:**
- Input validation: `original_user_request` is empty
- `ErrorDetail`: `"original_user_request is required and must not be empty. Plan comparison cannot proceed without a source requirement."`
- `OperationResult(success=False)` returned
- Workflow remains at `WorkflowStage.EVALUATION_APPROVED`
- Recommended action: Provide the original user request text and re-invoke this skill
