"""Models for reusable approved assets and reuse compatibility decisions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from src.models.common import AgentBaseModel, utc_now
from src.models.enums import ArtifactStatus, BrowserName, ReusableAssetKind, TargetType


class ReuseCompatibilityCheck(AgentBaseModel):
    """Result of validating whether an approved asset is safe to reuse in a new run."""

    asset_id: UUID
    candidate_target_id: UUID
    candidate_run_id: UUID

    # Seven required compatibility dimensions
    target_identity_match: bool
    target_type_match: bool
    environment_match: bool
    version_match: bool
    scope_match: bool
    browser_match: bool
    approval_status_confirmed: bool

    notes: str | None = Field(default=None, max_length=2_000)
    checked_at: datetime = Field(default_factory=utc_now)

    @property
    def is_compatible(self) -> bool:
        """Return True only when all seven dimensions pass."""
        return all([
            self.target_identity_match,
            self.target_type_match,
            self.environment_match,
            self.version_match,
            self.scope_match,
            self.browser_match,
            self.approval_status_confirmed,
        ])

    def incompatible_dimensions(self) -> list[str]:
        """Return the names of dimensions that failed."""
        failed: list[str] = []
        if not self.target_identity_match:
            failed.append("target_identity_match")
        if not self.target_type_match:
            failed.append("target_type_match")
        if not self.environment_match:
            failed.append("environment_match")
        if not self.version_match:
            failed.append("version_match")
        if not self.scope_match:
            failed.append("scope_match")
        if not self.browser_match:
            failed.append("browser_match")
        if not self.approval_status_confirmed:
            failed.append("approval_status_confirmed")
        return failed


class ReuseDecision(AgentBaseModel):
    """Explicit human-confirmed decision to reuse or reject a reusable asset."""

    decision_id: UUID = Field(default_factory=uuid4)
    asset_id: UUID
    source_target_id: UUID
    source_run_id: UUID
    destination_run_id: UUID

    approved: bool
    # Cross-target reuse requires an explicit validated relationship record
    is_cross_target: bool = False
    cross_target_relationship_validated: bool = False

    rejection_reason: str | None = Field(default=None, max_length=2_000)
    compatibility_check: ReuseCompatibilityCheck | None = None
    decided_by: str = Field(min_length=1, max_length=255)
    decided_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_cross_target_reuse(self) -> ReuseDecision:
        if self.is_cross_target and self.approved and not self.cross_target_relationship_validated:
            raise ValueError(
                "Cross-target reuse requires cross_target_relationship_validated=True."
            )
        if not self.approved and self.rejection_reason is None:
            raise ValueError("rejection_reason is required when approved=False.")
        return self


class ReusableAsset(AgentBaseModel):
    """An approved artifact eligible for reuse in compatible future runs."""

    asset_id: UUID = Field(default_factory=uuid4)
    kind: ReusableAssetKind
    name: str = Field(min_length=1, max_length=255)

    # Origin traceability — immutable after creation
    source_target_id: UUID
    source_run_id: UUID
    source_artifact_id: UUID

    source_target_type: TargetType
    source_environment_classification: str = Field(min_length=1, max_length=50)
    source_browser: BrowserName | None = None
    source_version_label: str | None = Field(default=None, max_length=255)
    scope_summary: str = Field(min_length=1, max_length=2_000)

    approval_status: ArtifactStatus
    approved_by: str = Field(min_length=1, max_length=255)
    approved_at: datetime

    # Relative path within the target's reusable/ directory — read-only after creation
    relative_path: str = Field(min_length=1, max_length=500)

    registered_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_approved_status(self) -> ReusableAsset:
        """Only approved artifacts may be registered as reusable."""
        if self.approval_status not in (ArtifactStatus.APPROVED, ArtifactStatus.REUSED):
            raise ValueError(
                f"ReusableAsset requires APPROVED or REUSED status; got {self.approval_status}."
            )
        return self

    @model_validator(mode="after")
    def reject_path_traversal(self) -> ReusableAsset:
        if ".." in self.relative_path:
            raise ValueError("relative_path must not contain parent-directory traversal.")
        return self
