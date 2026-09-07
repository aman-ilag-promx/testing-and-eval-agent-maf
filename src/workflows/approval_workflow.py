"""Deterministic approval checkpoint orchestration for workflow stages."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from src.models.common import ApprovalRecord, ArtifactReference, ErrorDetail, utc_now
from src.models.enums import ApprovalStatus, FailureSource, WorkflowOutcome, WorkflowStage
from src.models.workflow import (
    WorkflowCheckpoint,
    WorkflowResult,
    WorkflowState,
    WorkflowTransition,
)
from src.tools.approval_store import ApprovalStore, ApprovalStoreError


class ApprovalWorkflowError(ValueError):
    """Base error raised for approval-workflow operations."""


class ApprovalWorkflow:
    """Manage approval checkpoints and explicit human decisions."""

    def __init__(self, approval_store: ApprovalStore | None = None) -> None:
        """Initialize deterministic dependencies."""

        self._approval_store = approval_store or ApprovalStore()

    def create_pending_checkpoint(
        self,
        *,
        workflow_state: WorkflowState,
        name: str,
        stage: WorkflowStage,
        instructions: str,
        required_artifacts: list[ArtifactReference],
        triggered_by: str,
    ) -> WorkflowResult:
        """Add a blocking pending checkpoint and transition to the waiting stage."""

        now = utc_now()
        checkpoint = WorkflowCheckpoint(
            checkpoint_id=uuid4(),
            name=name,
            stage=stage,
            approval_state=ApprovalStatus.PENDING,
            approval_record=None,
            required_artifacts=required_artifacts,
            instructions=instructions,
            blocking=True,
        )

        transition = WorkflowTransition(
            transition_id=uuid4(),
            from_stage=workflow_state.current_stage,
            to_stage=stage,
            occurred_at=now,
            reason=f"Entered {stage.value} for human approval.",
            triggered_by=triggered_by,
            artifact_references=required_artifacts,
        )

        updated_state = WorkflowState(
            workflow_id=workflow_state.workflow_id,
            current_stage=stage,
            outcome=WorkflowOutcome.BLOCKED,
            checkpoints=[*workflow_state.checkpoints, checkpoint],
            transitions=[*workflow_state.transitions, transition],
            input_artifacts=workflow_state.input_artifacts,
            output_artifacts=workflow_state.output_artifacts,
            warnings=workflow_state.warnings,
            errors=workflow_state.errors,
            created_at=workflow_state.created_at,
            updated_at=now,
        )

        return WorkflowResult(
            workflow_state=updated_state,
            outcome=WorkflowOutcome.BLOCKED,
            message=(f"Approval checkpoint '{name}' is pending at stage {stage.value}."),
            produced_artifacts=workflow_state.output_artifacts,
            pending_checkpoint=checkpoint,
            warnings=workflow_state.warnings,
            errors=workflow_state.errors,
        )

    def record_decision(
        self,
        *,
        workflow_state: WorkflowState,
        checkpoint_id: UUID,
        artifact_reference: ArtifactReference,
        status: ApprovalStatus,
        reviewer: str,
        comments: str | None,
        next_stage_on_approval: WorkflowStage,
        revision_stage_on_rejection: WorkflowStage,
        triggered_by: str,
        decided_at: datetime | None = None,
    ) -> WorkflowResult:
        """Record one explicit human approval decision and advance workflow stage."""

        if status not in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.CHANGES_REQUESTED,
        }:
            raise ApprovalWorkflowError(
                "Decision status must be approved, rejected, or changes_requested."
            )

        now = decided_at or utc_now()
        checkpoint = self._find_checkpoint(workflow_state, checkpoint_id)

        record = ApprovalRecord(
            artifact_id=artifact_reference.artifact_id,
            status=status,
            reviewer=reviewer,
            comments=comments,
            requested_at=checkpoint.approval_record.requested_at
            if checkpoint.approval_record is not None
            else now,
            decided_at=now,
        )

        errors = list(workflow_state.errors)
        try:
            if self._approval_store.exists(artifact_reference):
                self._approval_store.replace(artifact_reference, record)
            else:
                self._approval_store.save(artifact_reference, record)
        except ApprovalStoreError as error:
            errors.append(
                ErrorDetail(
                    code="APPROVAL_RECORD_PERSIST_FAILED",
                    message="Unable to persist approval decision.",
                    failure_source=FailureSource.TOOL,
                    workflow_step="approval.record_decision",
                    technical_details=repr(error),
                )
            )

            failed_state = WorkflowState(
                workflow_id=workflow_state.workflow_id,
                current_stage=workflow_state.current_stage,
                outcome=WorkflowOutcome.FAILURE,
                checkpoints=workflow_state.checkpoints,
                transitions=workflow_state.transitions,
                input_artifacts=workflow_state.input_artifacts,
                output_artifacts=workflow_state.output_artifacts,
                warnings=workflow_state.warnings,
                errors=errors,
                created_at=workflow_state.created_at,
                updated_at=now,
            )

            return WorkflowResult(
                workflow_state=failed_state,
                outcome=WorkflowOutcome.FAILURE,
                message="Approval decision could not be persisted.",
                produced_artifacts=workflow_state.output_artifacts,
                warnings=workflow_state.warnings,
                errors=errors,
            )

        decided_checkpoint = WorkflowCheckpoint(
            checkpoint_id=checkpoint.checkpoint_id,
            name=checkpoint.name,
            stage=checkpoint.stage,
            approval_state=status,
            approval_record=record,
            required_artifacts=checkpoint.required_artifacts,
            instructions=checkpoint.instructions,
            blocking=checkpoint.blocking,
        )

        updated_checkpoints = [
            decided_checkpoint if item.checkpoint_id == checkpoint_id else item
            for item in workflow_state.checkpoints
        ]

        approved = status is ApprovalStatus.APPROVED
        to_stage = next_stage_on_approval if approved else revision_stage_on_rejection
        outcome = WorkflowOutcome.SUCCESS if approved else WorkflowOutcome.BLOCKED

        transition = WorkflowTransition(
            transition_id=uuid4(),
            from_stage=workflow_state.current_stage,
            to_stage=to_stage,
            occurred_at=now,
            reason=f"Checkpoint {checkpoint.name} resolved as {status.value}.",
            triggered_by=triggered_by,
            checkpoint_id=checkpoint_id if approved else None,
            artifact_references=[artifact_reference],
        )

        updated_state = WorkflowState(
            workflow_id=workflow_state.workflow_id,
            current_stage=to_stage,
            outcome=outcome,
            checkpoints=updated_checkpoints,
            transitions=[*workflow_state.transitions, transition],
            input_artifacts=workflow_state.input_artifacts,
            output_artifacts=workflow_state.output_artifacts,
            warnings=workflow_state.warnings,
            errors=errors,
            created_at=workflow_state.created_at,
            updated_at=now,
        )

        return WorkflowResult(
            workflow_state=updated_state,
            outcome=outcome,
            message=f"Checkpoint {checkpoint.name} marked as {status.value}.",
            produced_artifacts=workflow_state.output_artifacts,
            warnings=workflow_state.warnings,
            errors=errors,
        )

    @staticmethod
    def _find_checkpoint(
        workflow_state: WorkflowState,
        checkpoint_id: UUID,
    ) -> WorkflowCheckpoint:
        for checkpoint in workflow_state.checkpoints:
            if checkpoint.checkpoint_id == checkpoint_id:
                if checkpoint.approval_state is not ApprovalStatus.PENDING:
                    raise ApprovalWorkflowError("Checkpoint is already decided.")
                return checkpoint

        raise ApprovalWorkflowError("Checkpoint does not exist in workflow state.")
