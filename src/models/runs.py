"""Models for test runs, run manifests, and capability requests."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from src.models.common import AgentBaseModel, ArtifactReference, ErrorDetail, WarningDetail, utc_now
from src.models.enums import ArtifactStatus, BrowserName, TestCategory, WorkflowOutcome


class CapabilityRequest(AgentBaseModel):
    """A single testing capability requested within a run."""

    category: TestCategory
    description: str | None = Field(default=None, max_length=2_000)
    priority: str | None = Field(default=None, max_length=50)


class ReuseRecord(AgentBaseModel):
    """Immutable record of a reused approved asset within a run."""

    original_target_id: UUID
    original_run_id: UUID
    original_artifact_id: UUID
    asset_kind: str = Field(min_length=1, max_length=100)
    compatibility_summary: str = Field(min_length=1, max_length=2_000)
    reused_at: datetime = Field(default_factory=utc_now)


class RunManifest(AgentBaseModel):
    """Per-run manifest recording intent, reuse decisions, and outcomes."""

    run_id: UUID = Field(default_factory=uuid4)
    target_id: UUID
    target_slug: str = Field(min_length=3, max_length=63)
    target_version_label: str | None = Field(default=None, max_length=255)

    requested_capabilities: list[CapabilityRequest] = Field(default_factory=list)
    reused_assets: list[ReuseRecord] = Field(default_factory=list)
    rejected_reuse_reasons: list[str] = Field(default_factory=list)

    generated_artifacts: list[ArtifactReference] = Field(default_factory=list)
    approved_artifacts: list[ArtifactReference] = Field(default_factory=list)

    warnings: list[WarningDetail] = Field(default_factory=list)
    errors: list[ErrorDetail] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    outcome: WorkflowOutcome = WorkflowOutcome.PENDING
    status_summary: str | None = Field(default=None, max_length=2_000)

    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @field_validator("requested_capabilities")
    @classmethod
    def require_at_least_one_capability(cls, value: list[CapabilityRequest]) -> list[CapabilityRequest]:
        if not value:
            raise ValueError("At least one capability must be requested per run.")
        return value


class TestRun(AgentBaseModel):
    """Full state record for one test run against a registered target."""

    run_id: UUID = Field(default_factory=uuid4)
    target_id: UUID
    conversation_session_id: UUID | None = None

    manifest: RunManifest
    browser: BrowserName = BrowserName.CHROMIUM
    base_url: str | None = Field(default=None, max_length=2_000)

    # Approval references by checkpoint label
    approvals: dict[str, ArtifactStatus] = Field(default_factory=dict)

    evidence_paths: list[str] = Field(default_factory=list)
    final_status: WorkflowOutcome = WorkflowOutcome.PENDING

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def run_id_matches_manifest(self) -> TestRun:
        if self.run_id != self.manifest.run_id:
            raise ValueError("TestRun.run_id must match TestRun.manifest.run_id.")
        return self

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://.")
        return stripped
