"""Models for registered test targets and their environment profiles."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from src.models.common import AgentBaseModel, utc_now
from src.models.enums import TargetType

_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_SAFE_REF_PATTERN = re.compile(r"^[A-Za-z0-9._/:\-]{1,500}$")

# Auth reference names only — never secrets
AuthReferenceName = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_\-\.]{1,100}$")]

_SECRET_LIKE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_\-]?key|bearer|credential|private[_\-]?key|conn[ection]*[_\-]?str)",
)


class EnvironmentProfile(AgentBaseModel):
    """Classification and constraint profile for a target environment."""

    name: str = Field(min_length=1, max_length=100)
    classification: str = Field(min_length=1, max_length=50)
    base_url: str | None = Field(default=None, max_length=2_000)
    allow_live_execution: bool = False
    allow_destructive: bool = False
    notes: str | None = Field(default=None, max_length=2_000)

    @field_validator("classification")
    @classmethod
    def validate_classification(cls, value: str) -> str:
        """Reject production classification so it cannot be set silently."""
        if value.strip().lower() == "production":
            raise ValueError(
                "Production environment requires explicit ALLOW_LIVE_TEST_EXECUTION override. "
                "Set classification to a non-production value or configure the safety flag."
            )
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://.")
        return stripped


class TargetVersion(AgentBaseModel):
    """Commit or version identity for a registered target."""

    commit_sha: str | None = Field(default=None, max_length=64)
    branch: str | None = Field(default=None, max_length=255)
    tag: str | None = Field(default=None, max_length=255)
    version_label: str | None = Field(default=None, max_length=100)
    recorded_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def require_at_least_one_identity(self) -> TargetVersion:
        """Require at least one non-None identity field."""
        if not any([self.commit_sha, self.branch, self.tag, self.version_label]):
            raise ValueError("At least one of commit_sha, branch, tag, or version_label must be set.")
        return self


class PluginTargetLink(AgentBaseModel):
    """Declares the relationship between a plugin/extension and its generated Code App."""

    plugin_target_id: UUID
    code_app_target_id: UUID
    relationship_notes: str | None = Field(default=None, max_length=1_000)
    linked_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def reject_self_link(self) -> PluginTargetLink:
        if self.plugin_target_id == self.code_app_target_id:
            raise ValueError("plugin_target_id and code_app_target_id must be different targets.")
        return self


class TestTarget(AgentBaseModel):
    """Stable, named test target with type, source, environment, and run history."""

    target_id: UUID = Field(default_factory=uuid4)
    slug: str = Field(min_length=3, max_length=63)
    name: str = Field(min_length=1, max_length=255)
    target_type: TargetType
    description: str | None = Field(default=None, max_length=2_000)

    # Source reference — local approved path or repository URL (not cloned automatically)
    repo_ref: str | None = Field(default=None, max_length=500)
    app_url: str | None = Field(default=None, max_length=2_000)

    environment: EnvironmentProfile | None = None
    version: TargetVersion | None = None

    # Auth reference names only — never actual secrets
    auth_references: list[AuthReferenceName] = Field(default_factory=list)

    forbidden_operations: list[str] = Field(default_factory=list)
    related_targets: list[PluginTargetLink] = Field(default_factory=list)
    run_ids: list[UUID] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        stripped = value.strip().lower()
        if not _SLUG_PATTERN.match(stripped):
            raise ValueError(
                "slug must be 3–63 lowercase alphanumeric characters or hyphens, "
                "starting and ending with a letter or digit."
            )
        return stripped

    @field_validator("repo_ref")
    @classmethod
    def validate_repo_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if not _SAFE_REF_PATTERN.match(stripped) and not stripped.startswith(("http://", "https://", "\\")):
            raise ValueError("repo_ref contains disallowed characters.")
        return stripped

    @field_validator("app_url")
    @classmethod
    def validate_app_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped.startswith(("http://", "https://")):
            raise ValueError("app_url must start with http:// or https://.")
        return stripped

    @field_validator("auth_references")
    @classmethod
    def reject_secret_like_auth_names(cls, value: list[str]) -> list[str]:
        """Reject values that look like actual secrets rather than reference names."""
        for ref in value:
            if _SECRET_LIKE.search(ref) and len(ref) > 30:
                raise ValueError(
                    f"auth_references must contain reference names only, not secret values. "
                    f"Rejected value appears to be a secret: {ref[:20]}..."
                )
        return value

    @field_validator("forbidden_operations")
    @classmethod
    def normalize_forbidden(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for op in value:
            stripped = op.strip()
            if not stripped:
                raise ValueError("forbidden_operations must not contain empty entries.")
            key = stripped.casefold()
            if key not in seen:
                seen.add(key)
                result.append(stripped)
        return result
