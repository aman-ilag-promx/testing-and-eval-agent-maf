---
name: evaluation-testing
description: Use this skill when scoring test outcomes and quality signals against agreed criteria.
metadata:
  version: 1.0.0
  category: testing
---

# 1. Skill Name and Purpose

**Skill:** `evaluation-testing`

This skill evaluates AI-based features and agent-generated outputs against configurable, rubric-driven criteria. It loads a human-approved rubric from `evals/rubrics/`, applies each criterion to execution results or model outputs, produces an evidence-backed score for each criterion, records rationale and confidence, compares results to optional baselines, and persists the evaluation result to `evals/results/`. The skill then stops and requests human review before any downstream implementation changes are proposed.

---

# 2. Scope

This skill covers:

- Loading evaluation rubrics from `evals/rubrics/`
- Loading evaluation datasets from `evals/datasets/`
- Loading baseline expectations from `evals/baselines/`
- Applying `EvaluationCriterion` entries from an `EvaluationRubric` to provided evidence
- Scoring each criterion using `EvaluationOutcome` and an optional numeric `EvaluationScale`
- Recording evidence references, rationale, and confidence for each `CriterionEvaluation`
- Comparing scores to baselines when available
- Producing an `EvaluationResult` with all findings
- Persisting results to `evals/results/`
- Surfacing the result for human review

This skill does not:

- Execute Playwright tests or browser automation
- Generate test cases or scripts
- Automatically approve evaluation findings
- Propose or implement downstream changes without human approval
- Modify the application, rubrics, baselines, or datasets
- Couple evaluation logic to a specific provider SDK (adapter pattern required)

---

# 3. When to Use and When Not to Use

**Use this skill when:**

- Execution results from `smoke-testing`, `ui-testing`, or `integration-self-testing` are available and need to be scored against a rubric
- Agent-generated outputs (test cases, scripts, reports) need to be evaluated for quality
- AI feature behavior needs to be scored for accuracy, relevance, groundedness, or safety
- Longitudinal quality trend analysis is needed across multiple runs

**Do not use this skill when:**

- No approved rubric exists in `evals/rubrics/`
- Only deterministic pass/fail results are needed (check `ExecutionStatus` from execution skills directly)
- Plan-versus-implementation structural comparison is needed (use `plan-vs-implementation`)
- Browser execution is the primary need (use `smoke-testing` or `ui-testing`)

---

# 4. Required and Optional Inputs

## Required

| Field | Model | Description |
|---|---|---|
| `rubric_path` | `EvaluationRequest.rubric_path` | Path to approved rubric YAML under `evals/rubrics/` |
| `execution_results` | `EvaluationRequest` | One or more `PlaywrightExecutionResult` records or agent output artifacts |
| `run_id` | UUID | Run identifier for traceability |

## Optional

| Field | Model | Description |
|---|---|---|
| `dataset_path` | `EvaluationRequest` | Path to evaluation dataset under `evals/datasets/` |
| `baseline_path` | `EvaluationRequest` | Path to baseline expectations under `evals/baselines/` |
| `evaluation_scope` | string | Human-readable label for what is being evaluated |
| `criteria_filter` | list of criterion IDs | Evaluate only the specified criteria |

---

# 5. Preconditions and Input Validation

Before evaluating, validate the following:

1. `rubric_path` exists and is located under `evals/rubrics/`. Do not load rubrics from outside this directory.
2. The rubric file deserializes as a valid `EvaluationRubric` with at least one `EvaluationCriterion`.
3. `execution_results` is non-empty and each result has a recorded `ExecutionStatus`.
4. If `baseline_path` is provided, it exists under `evals/baselines/` and is valid.
5. If `dataset_path` is provided, it exists under `evals/datasets/` and is non-empty.
6. `run_id` is a valid UUID.
7. No input contains embedded secrets or credentials.

Return `OperationResult(success=False)` and stop if any precondition fails.

---

# 6. Relevant Existing Domain Models

| Model | Module | Purpose |
|---|---|---|
| `EvaluationScale` | `src.models.evaluation` | Numeric scoring scale with min, max, and passing threshold |
| `EvaluationCriterion` | `src.models.evaluation` | One configurable rubric criterion |
| `EvaluationRubric` | `src.models.evaluation` | Complete set of criteria with scale and metadata |
| `EvaluationRequest` | `src.models.evaluation` | Full evaluation request |
| `CriterionEvaluation` | `src.models.evaluation` | Scored outcome for one criterion with evidence and rationale |
| `EvaluationResult` | `src.models.evaluation` | Complete evaluation result for a run |
| `PlaywrightExecutionResult` | `src.models.playwright` | Deterministic execution result used as evidence |
| `EvidenceReference` | `src.models.common` | Evidence supporting a criterion score |
| `ArtifactMetadata` | `src.models.common` | Traceability metadata |
| `WarningDetail` | `src.models.common` | Non-blocking warning |
| `ErrorDetail` | `src.models.common` | Structured failure |
| `OperationResult` | `src.models.common` | Unified structured result |
| `EvaluationOutcome` | `src.models.enums` | `passed`, `partially_passed`, `failed`, `not_applicable`, `not_evaluated`, `insufficient_evidence` |
| `ArtifactType` | `src.models.enums` | Must be `ArtifactType.EVALUATION_RESULT` |
| `ArtifactStatus` | `src.models.enums` | Set after evaluation completes |
| `ApprovalStatus` | `src.models.enums` | `PENDING` until human reviews |

---

# 7. Detailed Numbered Execution Procedure

1. **Validate inputs.** Check all preconditions. Return failure and stop if any fail.

2. **Assign a run identifier.** Use the caller-supplied `run_id`. Record in `ArtifactMetadata`.

3. **Load rubric.** Deserialize the rubric file as `EvaluationRubric`. Confirm it has at least one criterion. If `criteria_filter` is provided, apply it.

4. **Load baseline (if provided).** Deserialize baseline expectations. Record a warning if the baseline format does not match the rubric criteria.

5. **Load dataset (if provided).** Deserialize the evaluation dataset. Confirm it is non-empty.

6. **Prepare evidence index.** Build an index of available evidence from the provided execution results, screenshots, traces, assertions, and any model output artifacts. Assign `EvidenceReference` objects for each piece of evidence.

7. **Evaluate each criterion.** For each `EvaluationCriterion` in the rubric:
   a. Locate relevant evidence in the evidence index
   b. Apply the criterion description and scoring guidance to the evidence
   c. Assign an `EvaluationOutcome`: `passed`, `partially_passed`, `failed`, `not_applicable`, `insufficient_evidence`
   d. If a numeric scale is defined, assign a score within `EvaluationScale.minimum_score` to `EvaluationScale.maximum_score`
   e. Record the evidence references that support the score
   f. Write rationale (minimum one sentence explaining why this score was assigned)
   g. Record confidence level: `high`, `medium`, `low`
   h. If outcome is `insufficient_evidence`, record exactly what additional evidence would be needed
   i. If a recommended improvement is warranted, record it
   j. Never assign a score without rationale and at least one evidence reference

8. **Compare to baseline (if available).** For each criterion, compare the assigned score to the baseline expectation. Record regression or improvement findings.

9. **Compute overall evaluation status.** If all criteria with a weight or requirement setting pass, overall outcome is `EvaluationOutcome.PASSED`. If any required criterion fails, overall outcome is `EvaluationOutcome.FAILED`. Mixed results produce `EvaluationOutcome.PARTIALLY_PASSED`.

10. **Build `EvaluationResult`.** Populate: `evaluation_id`, `run_id`, `rubric_reference`, `baseline_reference`, criterion evaluations, overall outcome, warnings, errors, `ArtifactMetadata` with `ArtifactStatus.AWAITING_APPROVAL`.

11. **Persist result.** Save `EvaluationResult` to `evals/results/<run_id>-evaluation.json`.

12. **Validate persisted artifact.** Confirm file exists and deserializes correctly.

13. **Assemble `OperationResult`.** Include: artifact reference, overall outcome, per-criterion summaries, baseline comparison, warnings, errors, `success=True`.

14. **Stop and request human review.** Surface result path and summary to the caller. Transition workflow to `WorkflowStage.AWAITING_EVALUATION_APPROVAL`. Do not propose or implement downstream changes.

---

# 8. Decision Rules

- Never assign a score without rationale and at least one evidence reference.
- If evidence is insufficient to evaluate a criterion, assign `EvaluationOutcome.INSUFFICIENT_EVIDENCE` and document what is missing.
- If a criterion is not applicable to the current scope, assign `EvaluationOutcome.NOT_APPLICABLE` with a brief explanation.
- Model-generated output is not deterministic execution evidence; label it as `EvidenceType.MODEL_OUTPUT` and reduce confidence accordingly.
- If the rubric changes between runs, record a `WarningDetail` about potential incompatibility with prior baselines.
- Never approve evaluation findings automatically.
- Never propose code changes based on evaluation findings without human review.

---

# 9. Structured Output Requirements

The skill must return an `OperationResult` containing:

- `success`: `True` if the evaluation completed and was persisted
- `artifact`: `ArtifactReference` pointing to the `EvaluationResult`
- `run_id`: UUID
- `overall_outcome`: `EvaluationOutcome`
- `criterion_summaries`: list of `{criterion_id, name, outcome, score, confidence}` for quick review
- `baseline_comparison`: dict mapping criterion IDs to regression/improvement status (if baseline was provided)
- `warnings`: list of `WarningDetail`
- `errors`: list of `ErrorDetail`
- `message`: human-readable summary

---

# 10. Artifact Location and Traceability Rules

- Evaluation results: `evals/results/<run_id>-evaluation.json`
- Rubrics (read-only): `evals/rubrics/`
- Datasets (read-only): `evals/datasets/`
- Baselines (read-only): `evals/baselines/`
- Every result must include `ArtifactMetadata`: `skill_name` (`evaluation-testing`), `artifact_type` (`ArtifactType.EVALUATION_RESULT`), `artifact_status` (`ArtifactStatus.AWAITING_APPROVAL`), `approval_status` (`ApprovalStatus.PENDING`), `run_id`, `created_at`
- Parent artifact IDs from execution results must be recorded

---

# 11. Evidence Requirements

For each `CriterionEvaluation`:

- At least one `EvidenceReference` must be recorded
- Evidence must be traceable to a file, assertion, execution result, or documented observation
- Model-generated text alone is not sufficient evidence for a deterministic criterion
- Scores assigned on `insufficient_evidence` must document what additional evidence would resolve the uncertainty

---

# 12. Human Approval Requirements

**Checkpoint C applies.** After this skill completes:

1. Workflow transitions to `WorkflowStage.AWAITING_EVALUATION_APPROVAL`
2. The evaluation result path, overall outcome, criterion summaries, and recommendations are presented to a human reviewer
3. All downstream actions (implementation change proposals, `plan-vs-implementation` triggering, report generation with recommendations) are blocked until `ApprovalStatus.APPROVED` is recorded
4. If the reviewer requests changes, return to step 7 with the reviewer's feedback and re-evaluate the flagged criteria

---

# 13. Safety Guardrails

- Never automatically approve evaluation findings.
- Never propose or implement code or configuration changes based on evaluation output without human review.
- Never load rubric, baseline, or dataset files from outside their designated directories.
- Never modify rubric, baseline, or dataset files.
- Never couple evaluation logic directly to a specific external evaluation SDK; use adapter pattern.
- Never assign a score without evidence and rationale.
- Never hide `insufficient_evidence` outcomes.
- Never claim overall pass if any required criterion has `EvaluationOutcome.FAILED`.

---

# 14. Failure Handling and Failure Classification

| Failure | Classification | Action |
|---|---|---|
| Rubric file not found or invalid | `FailureSource.CONFIGURATION` | Record error, stop |
| Zero execution results provided | `FailureSource.TOOL` | Record error, stop |
| Criterion evaluation produces no evidence | `FailureSource.SKILL` | Assign `insufficient_evidence`, record warning |
| Baseline file format mismatch | `FailureSource.CONFIGURATION` | Record warning, skip baseline comparison |
| Persistence failure | `FailureSource.TOOL` | Record error, flag artifact `INCOMPLETE` |
| Model output used as sole evidence | `FailureSource.MODEL_OUTPUT` | Reduce confidence, record warning |

---

# 15. Warning and Uncertainty Handling

Record a `WarningDetail` for:

- Criteria evaluated with low confidence
- Evidence only from model output (not deterministic)
- Rubric version changed from previous run
- Baseline not available for comparison
- Criteria filtered out by `criteria_filter` that may be relevant
- Scores near the `passing_score` boundary (borderline results)

---

# 16. Acceptance Criteria

The skill is considered successful when:

1. Every criterion in the rubric has a recorded `CriterionEvaluation` with outcome, evidence, and rationale.
2. No criterion is scored without at least one `EvidenceReference`.
3. The `EvaluationResult` is persisted to `evals/results/` and deserializes correctly.
4. `ArtifactStatus.AWAITING_APPROVAL` and `ApprovalStatus.PENDING` are set.
5. `OperationResult` returned with `success=True`.
6. Workflow blocked at `WorkflowStage.AWAITING_EVALUATION_APPROVAL`.

---

# 17. Completion Criteria

This skill is complete when:

- `EvaluationResult` file exists at `evals/results/<run_id>-evaluation.json`
- `OperationResult` returned to workflow
- Workflow transitioned to `WorkflowStage.AWAITING_EVALUATION_APPROVAL`
- No downstream change has been initiated

---

# 18. Workflow Handoff

On success: hand off to human reviewer via `WorkflowStage.AWAITING_EVALUATION_APPROVAL`. `plan-vs-implementation` and report generation may proceed only after `ApprovalStatus.APPROVED` is recorded.

On failure: caller receives structured failure. Downstream evaluation-dependent steps are blocked.

---

# 19. Valid Example

**Input:**
- `rubric_path`: `evals/rubrics/default-evaluation-rubric.yaml`
- `execution_results`: 6 passing smoke test results, 1 accessibility result with 2 violations
- `run_id`: `run-eval-001`

**Outcome:**
- Rubric has 4 criteria: `CRIT-001` (availability), `CRIT-002` (functional correctness), `CRIT-003` (accessibility), `CRIT-004` (response time)
- `CRIT-001`: `passed`, score 5.0, evidence: 6 `ExecutionStatus.PASSED` results
- `CRIT-002`: `passed`, score 4.5, evidence: assertion results from test steps
- `CRIT-003`: `partially_passed`, score 2.5, evidence: 2 WCAG violations in accessibility snapshot, confidence: high
- `CRIT-004`: `not_evaluated`, evidence: no timing data captured, `insufficient_evidence` warning recorded
- Overall outcome: `EvaluationOutcome.PARTIALLY_PASSED`
- Persisted: `evals/results/run-eval-001-evaluation.json`
- Workflow halts at `WorkflowStage.AWAITING_EVALUATION_APPROVAL`

---

# 20. Blocked or Failure Example

**Input:**
- `rubric_path`: `evals/rubrics/nonexistent-rubric.yaml`
- `execution_results`: 3 results
- `run_id`: `run-eval-002`

**Outcome:**
- Precondition check: `evals/rubrics/nonexistent-rubric.yaml` does not exist
- `ErrorDetail`: `"Rubric file 'evals/rubrics/nonexistent-rubric.yaml' was not found. Evaluation cannot proceed without an approved rubric."`
- `OperationResult(success=False)` returned
- Workflow remains at `WorkflowStage.EXECUTION_COMPLETED`
- Recommended action: Place an approved rubric YAML file under `evals/rubrics/` and re-invoke this skill
