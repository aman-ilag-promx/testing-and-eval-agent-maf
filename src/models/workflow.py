"""Models for approval-aware testing and evaluation workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from src.models.common import (
    AgentBaseModel,
    ApprovalRecord,
    ArtifactReference,
    ErrorDetail,
    WarningDetail,
)
from src.models.enums import (
    ApprovalStatus,
    WorkflowOutcome,
    WorkflowStage,
)
from src.models.test_cases import ImplementationInput


def _normalize_required_text(value: object, field_name: str) -> object:
    """Normalize required text and reject empty values."""
    if isinstance(value, str):
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"{field_name} must not be empty or whitespace.")
        return normalized_value

    return value


def _normalize_optional_text(value: object) -> object:
    """Normalize optional text and convert blank text to None."""
    if isinstance(value, str):
        normalized_value = value.strip()
        return normalized_value or None

    return value


def _normalize_unique_strings(
    value: object,
    field_name: str,
) -> object:
    """Normalize a string list and reject empty or duplicate entries."""
    if value is None:
        return []

    if not isinstance(value, list):
        return value

    normalized_items: list[object] = []
    seen_items: set[str] = set()

    for item in value:
        if not isinstance(item, str):
            normalized_items.append(item)
            continue

        normalized_item = item.strip()
        if not normalized_item:
            raise ValueError(f"{field_name} must not contain empty or whitespace-only entries.")

        comparison_value = normalized_item.casefold()
        if comparison_value in seen_items:
            raise ValueError(f"{field_name} entries must be unique.")

        seen_items.add(comparison_value)
        normalized_items.append(normalized_item)

    return normalized_items


def _enum_value(value: object) -> str:
    """Return a normalized string representation of an enum-like value."""
    raw_value = getattr(value, "value", value)
    return str(raw_value).strip().lower().replace("-", "_").replace(" ", "_")


def _is_pending_approval(value: ApprovalStatus) -> bool:
    """Return whether an approval state is pending human review."""
    return _enum_value(value) in {
        "pending",
        "pending_approval",
        "awaiting_approval",
        "awaiting_review",
    }


def _is_approved(value: ApprovalStatus) -> bool:
    """Return whether an approval state represents explicit approval."""
    return _enum_value(value) == "approved"


def _is_terminal_outcome(value: WorkflowOutcome) -> bool:
    """Return whether a workflow outcome is terminal."""
    return _enum_value(value) in {
        "completed",
        "failed",
        "cancelled",
        "canceled",
        "blocked",
        "rejected",
    }


class WorkflowCheckpoint(AgentBaseModel):
    """A mandatory human approval checkpoint in a workflow."""

    checkpoint_id: UUID = Field(
        description="Unique identifier for the approval checkpoint.",
    )
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Human-readable checkpoint name.",
    )
    stage: WorkflowStage = Field(
        description="Workflow stage protected by the checkpoint.",
    )
    approval_state: ApprovalStatus = Field(
        description="Current human approval state.",
    )
    approval_record: ApprovalRecord | None = Field(
        default=None,
        description="Human approval record when a decision has been recorded.",
    )
    required_artifacts: list[ArtifactReference] = Field(
        default_factory=list,
        description="Artifacts that must be reviewed at this checkpoint.",
    )
    instructions: str = Field(
        min_length=1,
        description="Instructions presented to the human reviewer.",
    )
    blocking: bool = Field(
        default=True,
        description="Whether unresolved approval blocks workflow progress.",
    )

    @field_validator("name", "instructions", mode="before")
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate checkpoint text."""
        return _normalize_required_text(value, "Checkpoint text")

    @model_validator(mode="after")
    def validate_approval_record(self) -> Self:
        """Ensure approval state and approval record remain consistent."""
        if _is_pending_approval(self.approval_state):
            if self.approval_record is not None:
                raise ValueError("A pending checkpoint must not contain an approval record.")
            return self

        if self.approval_record is None:
            raise ValueError("A decided checkpoint requires an approval record.")

        return self


class WorkflowTransition(AgentBaseModel):
    """An immutable record of a workflow stage transition."""

    transition_id: UUID = Field(
        description="Unique identifier for the transition.",
    )
    from_stage: WorkflowStage = Field(
        description="Workflow stage before the transition.",
    )
    to_stage: WorkflowStage = Field(
        description="Workflow stage after the transition.",
    )
    occurred_at: datetime = Field(
        description="Timezone-aware timestamp of the transition.",
    )
    reason: str = Field(
        min_length=1,
        description="Reason the workflow transitioned between stages.",
    )
    triggered_by: str = Field(
        min_length=1,
        max_length=200,
        description="Actor or deterministic component that triggered the transition.",
    )
    checkpoint_id: UUID | None = Field(
        default=None,
        description="Approval checkpoint authorizing the transition.",
    )
    artifact_references: list[ArtifactReference] = Field(
        default_factory=list,
        description="Artifacts associated with the transition.",
    )

    @field_validator("reason", "triggered_by", mode="before")
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate transition text."""
        return _normalize_required_text(value, "Workflow transition text")

    @field_validator("occurred_at")
    @classmethod
    def validate_timezone_aware_timestamp(
        cls,
        value: datetime,
    ) -> datetime:
        """Require a timezone-aware transition timestamp."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware.")

        return value

    @model_validator(mode="after")
    def validate_stage_change(self) -> Self:
        """Require a transition to move between different stages."""
        if self.from_stage == self.to_stage:
            raise ValueError("A workflow transition must move to a different stage.")

        return self


class WorkflowState(AgentBaseModel):
    """Current persisted state of an approval-aware workflow."""

    workflow_id: UUID = Field(
        description="Unique identifier for the workflow instance.",
    )
    current_stage: WorkflowStage = Field(
        description="Current workflow stage.",
    )
    outcome: WorkflowOutcome = Field(
        description="Current workflow outcome.",
    )
    checkpoints: list[WorkflowCheckpoint] = Field(
        default_factory=list,
        description="Approval checkpoints registered for the workflow.",
    )
    transitions: list[WorkflowTransition] = Field(
        default_factory=list,
        description="Ordered history of workflow transitions.",
    )
    input_artifacts: list[ArtifactReference] = Field(
        default_factory=list,
        description="Artifacts supplied to the workflow.",
    )
    output_artifacts: list[ArtifactReference] = Field(
        default_factory=list,
        description="Artifacts produced by completed workflow stages.",
    )
    warnings: list[WarningDetail] = Field(
        default_factory=list,
        description="Non-blocking warnings preserved by the workflow.",
    )
    errors: list[ErrorDetail] = Field(
        default_factory=list,
        description="Errors preserved by the workflow.",
    )
    # Optional links to the conversational platform context
    target_id: UUID | None = Field(default=None, description="Registered TestTarget this workflow belongs to.")
    run_id: UUID | None = Field(default=None, description="TestRun this workflow belongs to.")
    conversation_session_id: UUID | None = Field(default=None, description="ConversationSession that initiated this workflow.")

    created_at: datetime = Field(
        description="Timezone-aware workflow creation timestamp.",
    )
    updated_at: datetime = Field(
        description="Timezone-aware timestamp of the latest state update.",
    )

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timezone_aware_timestamp(
        cls,
        value: datetime,
    ) -> datetime:
        """Require timezone-aware workflow timestamps."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Workflow timestamps must be timezone-aware.")

        return value

    @field_validator("checkpoints")
    @classmethod
    def validate_unique_checkpoints(
        cls,
        value: list[WorkflowCheckpoint],
    ) -> list[WorkflowCheckpoint]:
        """Require unique checkpoint identifiers."""
        checkpoint_ids = [checkpoint.checkpoint_id for checkpoint in value]

        if len(checkpoint_ids) != len(set(checkpoint_ids)):
            raise ValueError("Checkpoint identifiers must be unique.")

        return value

    @field_validator("transitions")
    @classmethod
    def validate_unique_transitions(
        cls,
        value: list[WorkflowTransition],
    ) -> list[WorkflowTransition]:
        """Require unique transition identifiers."""
        transition_ids = [transition.transition_id for transition in value]

        if len(transition_ids) != len(set(transition_ids)):
            raise ValueError("Transition identifiers must be unique.")

        return value

    @model_validator(mode="after")
    def validate_state_integrity(self) -> Self:
        """Validate timestamps, transitions, and approval boundaries."""
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")

        if self.transitions:
            ordered_transitions = sorted(
                self.transitions,
                key=lambda transition: transition.occurred_at,
            )

            if ordered_transitions != self.transitions:
                raise ValueError("Workflow transitions must be ordered by occurred_at.")

            if self.transitions[-1].to_stage != self.current_stage:
                raise ValueError("The final transition must end at current_stage.")

            previous_stage = self.transitions[0].from_stage
            for transition in self.transitions:
                if transition.from_stage != previous_stage:
                    raise ValueError("Workflow transitions must form a continuous stage history.")
                previous_stage = transition.to_stage

        approved_checkpoint_ids = {
            checkpoint.checkpoint_id
            for checkpoint in self.checkpoints
            if _is_approved(checkpoint.approval_state)
        }

        known_checkpoint_ids = {checkpoint.checkpoint_id for checkpoint in self.checkpoints}

        for transition in self.transitions:
            if transition.checkpoint_id is None:
                continue

            if transition.checkpoint_id not in known_checkpoint_ids:
                raise ValueError("A transition references an unknown checkpoint.")

            if transition.checkpoint_id not in approved_checkpoint_ids:
                raise ValueError("A checkpoint-authorized transition requires explicit approval.")

        blocking_pending_checkpoints = [
            checkpoint
            for checkpoint in self.checkpoints
            if checkpoint.blocking and _is_pending_approval(checkpoint.approval_state)
        ]

        if (
            blocking_pending_checkpoints
            and _is_terminal_outcome(self.outcome)
            and _enum_value(self.outcome) == "completed"
        ):
            raise ValueError(
                "A workflow cannot complete while a blocking approval checkpoint is pending."
            )

        return self


class WorkflowStartRequest(AgentBaseModel):
    """Input required to initialize the testing and evaluation workflow."""

    implementation_input: ImplementationInput = Field(
        description="Original request, plan, or implementation artifact input.",
    )
    requested_capabilities: list[str] = Field(
        min_length=1,
        description="Testing or evaluation capabilities requested by the user.",
    )
    initial_artifacts: list[ArtifactReference] = Field(
        default_factory=list,
        description="Artifacts supplied when the workflow starts.",
    )
    initiated_by: str = Field(
        min_length=1,
        max_length=200,
        description="User or trusted component initiating the workflow.",
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=200,
        description="Optional identifier used to correlate related operations.",
    )

    @field_validator("initiated_by", mode="before")
    @classmethod
    def validate_initiated_by(cls, value: object) -> object:
        """Normalize and validate the workflow initiator."""
        return _normalize_required_text(value, "initiated_by")

    @field_validator("correlation_id", mode="before")
    @classmethod
    def validate_correlation_id(cls, value: object) -> object:
        """Normalize an optional correlation identifier."""
        return _normalize_optional_text(value)

    @field_validator("requested_capabilities", mode="before")
    @classmethod
    def validate_requested_capabilities(cls, value: object) -> object:
        """Normalize and validate requested workflow capabilities."""
        return _normalize_unique_strings(
            value,
            "requested_capabilities",
        )


class WorkflowResult(AgentBaseModel):
    """Complete result returned by an approval-aware workflow operation."""

    workflow_state: WorkflowState = Field(
        description="Persisted state after the workflow operation.",
    )
    outcome: WorkflowOutcome = Field(
        description="Outcome reported by the workflow operation.",
    )
    message: str = Field(
        min_length=1,
        description="Human-readable explanation of the workflow result.",
    )
    produced_artifacts: list[ArtifactReference] = Field(
        default_factory=list,
        description="Artifacts produced by the operation.",
    )
    pending_checkpoint: WorkflowCheckpoint | None = Field(
        default=None,
        description="Blocking checkpoint awaiting human review.",
    )
    warnings: list[WarningDetail] = Field(
        default_factory=list,
        description="Warnings produced by the workflow operation.",
    )
    errors: list[ErrorDetail] = Field(
        default_factory=list,
        description="Errors produced by the workflow operation.",
    )

    @field_validator("message", mode="before")
    @classmethod
    def validate_message(cls, value: object) -> object:
        """Normalize and validate the result message."""
        return _normalize_required_text(value, "message")

    @model_validator(mode="after")
    def validate_result_consistency(self) -> Self:
        """Ensure the reported result matches the persisted workflow state."""
        if self.outcome != self.workflow_state.outcome:
            raise ValueError("WorkflowResult outcome must match WorkflowState outcome.")

        if self.pending_checkpoint is not None:
            if not self.pending_checkpoint.blocking:
                raise ValueError("A pending result checkpoint must be blocking.")

            if not _is_pending_approval(self.pending_checkpoint.approval_state):
                raise ValueError("pending_checkpoint must have a pending approval state.")

            checkpoint_ids = {
                checkpoint.checkpoint_id for checkpoint in self.workflow_state.checkpoints
            }
            if self.pending_checkpoint.checkpoint_id not in checkpoint_ids:
                raise ValueError("pending_checkpoint must exist in workflow_state.checkpoints.")

        if _enum_value(self.outcome) == "completed":
            if self.pending_checkpoint is not None:
                raise ValueError("A completed workflow cannot have a pending checkpoint.")

            pending_blocking_checkpoints = [
                checkpoint
                for checkpoint in self.workflow_state.checkpoints
                if checkpoint.blocking and _is_pending_approval(checkpoint.approval_state)
            ]
            if pending_blocking_checkpoints:
                raise ValueError(
                    "A completed workflow cannot contain unresolved blocking checkpoints."
                )

        return self
