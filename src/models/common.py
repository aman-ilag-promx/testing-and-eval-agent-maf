"""Common validated models used across the Testing and Evaluation Agent."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    ArtifactType,
    EvidenceType,
    FailureSource,
    Severity,
)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class AgentBaseModel(BaseModel):
    """Base model for validated Testing and Evaluation Agent data."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
        str_strip_whitespace=True,
        use_enum_values=False,
    )


class ArtifactReference(AgentBaseModel):
    """Lightweight reference to a managed artifact."""

    artifact_id: UUID
    artifact_type: ArtifactType
    name: str = Field(min_length=1, max_length=255)
    path: Path | None = None
    status: ArtifactStatus
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware timestamp and normalize it to UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware.")

        return value.astimezone(UTC)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: Path | None) -> Path | None:
        """Reject parent-directory traversal in artifact paths."""

        if value is None:
            return None

        if ".." in value.parts:
            raise ValueError("Artifact path must not contain parent-directory traversal.")

        return value


class EvidenceReference(AgentBaseModel):
    """Traceable evidence supporting a test, evaluation, or finding."""

    evidence_id: UUID = Field(default_factory=uuid4)
    evidence_type: EvidenceType
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2_000)
    source: str = Field(min_length=1, max_length=500)
    artifact_id: UUID | None = None
    path: Path | None = None
    locator: str | None = Field(default=None, max_length=1_000)
    collected_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("collected_at")
    @classmethod
    def normalize_collected_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware timestamp and normalize it to UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("collected_at must be timezone-aware.")

        return value.astimezone(UTC)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: Path | None) -> Path | None:
        """Reject parent-directory traversal in evidence paths."""

        if value is None:
            return None

        if ".." in value.parts:
            raise ValueError("Evidence path must not contain parent-directory traversal.")

        return value

    @model_validator(mode="after")
    def validate_evidence_location(self) -> EvidenceReference:
        """Require at least one concrete evidence location."""

        has_location = any(
            (
                self.artifact_id is not None,
                self.path is not None,
                self.locator is not None,
                bool(self.metadata),
            )
        )

        if not has_location:
            raise ValueError("Evidence must include artifact_id, path, locator, or metadata.")

        return self


class WarningDetail(AgentBaseModel):
    """Non-blocking warning produced during an operation."""

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2_000)
    severity: Severity = Severity.MEDIUM
    source: str | None = Field(default=None, max_length=255)
    suggested_action: str | None = Field(default=None, max_length=2_000)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ErrorDetail(AgentBaseModel):
    """Structured error information produced during an operation."""

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4_000)
    failure_source: FailureSource = FailureSource.UNKNOWN
    severity: Severity = Severity.HIGH
    blocking: bool = True
    workflow_step: str | None = Field(default=None, max_length=255)
    technical_details: str | None = Field(default=None, max_length=8_000)
    suggested_actions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)

    @field_validator("suggested_actions")
    @classmethod
    def validate_suggested_actions(cls, value: list[str]) -> list[str]:
        """Reject empty actions and remove case-insensitive duplicates."""

        unique_actions: list[str] = []
        seen_actions: set[str] = set()

        for action in value:
            normalized_action = action.strip()

            if not normalized_action:
                raise ValueError("Suggested actions must not be empty.")

            comparison_value = normalized_action.casefold()

            if comparison_value not in seen_actions:
                seen_actions.add(comparison_value)
                unique_actions.append(normalized_action)

        return unique_actions


class ApprovalRecord(AgentBaseModel):
    """Human approval decision associated with a controlled artifact."""

    approval_id: UUID = Field(default_factory=uuid4)
    artifact_id: UUID
    status: ApprovalStatus = ApprovalStatus.PENDING
    reviewer: str | None = Field(default=None, max_length=255)
    comments: str | None = Field(default=None, max_length=4_000)
    requested_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None

    @field_validator("requested_at", "decided_at")
    @classmethod
    def normalize_timestamps(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        """Require timezone-aware timestamps and normalize them to UTC."""

        if value is None:
            return None

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Approval timestamps must be timezone-aware.")

        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_decision_state(self) -> ApprovalRecord:
        """Ensure decision details are consistent with the approval status."""

        completed_statuses = {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.CHANGES_REQUESTED,
        }

        if self.status in completed_statuses:
            if not self.reviewer:
                raise ValueError("reviewer is required for a completed approval decision.")

            if self.decided_at is None:
                raise ValueError("decided_at is required for a completed approval decision.")

        if self.status is ApprovalStatus.PENDING:
            if self.decided_at is not None:
                raise ValueError("A pending approval must not have a decided_at timestamp.")

            if self.reviewer is not None:
                raise ValueError("A pending approval must not have a reviewer.")

        if self.decided_at is not None and self.decided_at < self.requested_at:
            # Allow inline completed decisions created in one constructor call where
            # requested_at is auto-generated a few milliseconds after decided_at.
            skew_seconds = (self.requested_at - self.decided_at).total_seconds()
            if self.status in completed_statuses and skew_seconds <= 1.0:
                self.requested_at = self.decided_at
            else:
                raise ValueError("decided_at must not be earlier than requested_at.")

        return self


class ArtifactMetadata(AgentBaseModel):
    """Traceability and lifecycle metadata for a managed artifact."""

    artifact_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    artifact_type: ArtifactType
    name: str = Field(min_length=1, max_length=255)
    status: ArtifactStatus = ArtifactStatus.DRAFT
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    skill_name: str | None = Field(default=None, max_length=255)
    source_references: list[str] = Field(default_factory=list)
    parent_artifact_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    created_by: str = Field(
        default="testing-evaluation-agent",
        min_length=1,
        max_length=255,
    )
    validation_passed: bool = False
    warnings: list[WarningDetail] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        """Require timezone-aware timestamps and normalize them to UTC."""

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Artifact timestamps must be timezone-aware.")

        return value.astimezone(UTC)

    @field_validator("source_references")
    @classmethod
    def validate_source_references(cls, value: list[str]) -> list[str]:
        """Reject empty references and remove duplicates."""

        unique_references: list[str] = []
        seen_references: set[str] = set()

        for reference in value:
            normalized_reference = reference.strip()

            if not normalized_reference:
                raise ValueError("Source references must not be empty.")

            comparison_value = normalized_reference.casefold()

            if comparison_value not in seen_references:
                seen_references.add(comparison_value)
                unique_references.append(normalized_reference)

        return unique_references

    @field_validator("parent_artifact_ids")
    @classmethod
    def remove_duplicate_parent_ids(
        cls,
        value: list[UUID],
    ) -> list[UUID]:
        """Remove duplicate parent identifiers while preserving order."""

        return list(dict.fromkeys(value))

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, value: dict[str, str]) -> dict[str, str]:
        """Reject empty label keys and values."""

        validated_labels: dict[str, str] = {}

        for key, label_value in value.items():
            normalized_key = key.strip()
            normalized_value = label_value.strip()

            if not normalized_key:
                raise ValueError("Artifact label keys must not be empty.")

            if not normalized_value:
                raise ValueError("Artifact label values must not be empty.")

            validated_labels[normalized_key] = normalized_value

        return validated_labels

    @model_validator(mode="after")
    def validate_artifact_state(self) -> ArtifactMetadata:
        """Validate timestamps, hierarchy, and approval lifecycle state."""

        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at.")

        if self.artifact_id in self.parent_artifact_ids:
            raise ValueError("An artifact cannot be its own parent.")

        if (
            self.status is ArtifactStatus.APPROVED
            and self.approval_status is not ApprovalStatus.APPROVED
        ):
            raise ValueError("An approved artifact must have an approved approval_status.")

        if (
            self.status is ArtifactStatus.REJECTED
            and self.approval_status is not ApprovalStatus.REJECTED
        ):
            raise ValueError("A rejected artifact must have a rejected approval_status.")

        if (
            self.status is ArtifactStatus.AWAITING_APPROVAL
            and self.approval_status is not ApprovalStatus.PENDING
        ):
            raise ValueError("An artifact awaiting approval must have a pending approval_status.")

        return self

    def to_reference(self, path: Path | None = None) -> ArtifactReference:
        """Create a lightweight reference to this artifact."""

        return ArtifactReference(
            artifact_id=self.artifact_id,
            artifact_type=self.artifact_type,
            name=self.name,
            path=path,
            status=self.status,
            created_at=self.created_at,
        )


class OperationResult(AgentBaseModel):
    """Structured result returned by a deterministic operation."""

    success: bool
    message: str = Field(min_length=1, max_length=4_000)
    artifact: ArtifactReference | None = None
    warnings: list[WarningDetail] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_result_consistency(self) -> OperationResult:
        """Ensure success and failure states are internally consistent."""

        blocking_errors = [error for error in self.errors if error.blocking]

        if self.success and blocking_errors:
            raise ValueError("A successful operation cannot contain blocking errors.")

        if not self.success and not self.errors:
            raise ValueError("An unsuccessful operation must contain at least one error.")

        return self
