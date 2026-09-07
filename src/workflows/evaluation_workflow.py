"""Deterministic workflow for rubric-based evaluation and review gating."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.evaluators.result_evaluator import ResultEvaluator
from src.models.common import ArtifactReference, ErrorDetail, WarningDetail, utc_now
from src.models.enums import (
    ArtifactStatus,
    FailureSource,
    WorkflowOutcome,
    WorkflowStage,
)
from src.models.evaluation import EvaluationRequest
from src.models.workflow import WorkflowResult, WorkflowState, WorkflowTransition
from src.tools.artifact_store import ArtifactStore
from src.tools.skill_loader import SkillLoader, SkillLoaderError
from src.workflows.approval_workflow import ApprovalWorkflow


class EvaluationWorkflow:
    """Evaluate deterministic evidence and enforce checkpoint C review."""

    def __init__(
        self,
        evaluator: ResultEvaluator | None = None,
        artifact_store: ArtifactStore | None = None,
        skill_loader: SkillLoader | None = None,
        approval_workflow: ApprovalWorkflow | None = None,
    ) -> None:
        """Initialize deterministic dependencies."""

        self._evaluator = evaluator or ResultEvaluator()
        self._artifact_store = artifact_store or ArtifactStore()
        self._skill_loader = skill_loader or SkillLoader()
        self._approval_workflow = approval_workflow or ApprovalWorkflow()

    def run(
        self,
        request: EvaluationRequest,
    ) -> WorkflowResult:
        """Run evaluation and transition to awaiting-evaluation-approval."""

        now = utc_now()
        warnings: list[WarningDetail] = []
        errors: list[ErrorDetail] = []

        try:
            self._skill_loader.load("evaluation-testing")
        except SkillLoaderError as error:
            errors.append(
                ErrorDetail(
                    code="SKILL_LOAD_FAILED",
                    message="Unable to load evaluation-testing skill definition.",
                    failure_source=FailureSource.SKILL,
                    workflow_step="evaluation.load_skill",
                    technical_details=repr(error),
                )
            )
            return self._failed_result(errors, now, "Skill loading failed.")

        evaluation_result = self._evaluator.evaluate(request)
        relative_path = Path(f"evals/results/{request.run_id}-evaluation.json")

        persisted = self._artifact_store.create_model(
            metadata=evaluation_result.metadata,
            relative_path=relative_path,
            model=evaluation_result,
        )

        if not persisted.success or persisted.artifact is None:
            errors.extend(persisted.errors)
            if not persisted.errors:
                errors.append(
                    ErrorDetail(
                        code="EVALUATION_RESULT_PERSIST_FAILED",
                        message="Evaluation result could not be persisted.",
                        failure_source=FailureSource.TOOL,
                        workflow_step="evaluation.persist",
                    )
                )
            return self._failed_result(errors, now, "Evaluation persistence failed.")

        if evaluation_result.metadata.status is not ArtifactStatus.AWAITING_APPROVAL:
            warnings.append(
                WarningDetail(
                    code="EVALUATION_STATUS_UNEXPECTED",
                    message="Evaluation result status is not awaiting approval.",
                    source="evaluation-workflow",
                )
            )

        prepared_state = self._prepared_state(now, persisted.artifact, warnings, errors)

        return self._approval_workflow.create_pending_checkpoint(
            workflow_state=prepared_state,
            name="Checkpoint C - Evaluation Approval",
            stage=WorkflowStage.AWAITING_EVALUATION_APPROVAL,
            instructions=(
                "Review the evaluation result and recommendations before any downstream "
                "proposal or comparison step."
            ),
            required_artifacts=[persisted.artifact],
            triggered_by="evaluation-workflow",
        )

    @staticmethod
    def _prepared_state(
        now: datetime,
        produced_artifact: ArtifactReference,
        warnings: list[WarningDetail],
        errors: list[ErrorDetail],
    ) -> WorkflowState:
        transition_a = WorkflowTransition(
            transition_id=uuid4(),
            from_stage=WorkflowStage.INITIALIZED,
            to_stage=WorkflowStage.INPUT_VALIDATED,
            occurred_at=now,
            reason="Validated evaluation request.",
            triggered_by="evaluation-workflow",
        )
        transition_b = WorkflowTransition(
            transition_id=uuid4(),
            from_stage=WorkflowStage.INPUT_VALIDATED,
            to_stage=WorkflowStage.EVALUATION_COMPLETED,
            occurred_at=now,
            reason="Produced evaluation result.",
            triggered_by="evaluation-workflow",
            artifact_references=[produced_artifact],
        )

        return WorkflowState(
            workflow_id=uuid4(),
            current_stage=WorkflowStage.EVALUATION_COMPLETED,
            outcome=WorkflowOutcome.PENDING,
            checkpoints=[],
            transitions=[transition_a, transition_b],
            input_artifacts=[],
            output_artifacts=[produced_artifact],
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
