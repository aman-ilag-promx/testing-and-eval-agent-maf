"""Data contracts for implementation plans used by the testing workflow."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RequirementPriority(StrEnum):
    """Supported requirement priority levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Requirement(BaseModel):
    """A single requirement extracted from an implementation plan."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    requirement_id: str = Field(
        min_length=1,
        description="Stable identifier for the requirement.",
        examples=["REQ-001"],
    )

    title: str = Field(
        min_length=1,
        description="Short requirement title.",
    )

    description: str = Field(
        min_length=1,
        description="Detailed description of the expected behavior.",
    )

    priority: RequirementPriority = Field(
        default=RequirementPriority.MEDIUM,
        description="Business or testing priority.",
    )

    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description=("Observable conditions that prove the requirement is satisfied."),
    )

    tags: list[str] = Field(
        default_factory=list,
        description="Optional categories used for filtering and reporting.",
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional source-specific fields.",
    )

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_acceptance_criteria(
        cls,
        values: list[str],
    ) -> list[str]:
        """Remove blank acceptance criteria while preserving order."""

        return [value.strip() for value in values if value.strip()]

    @field_validator("tags")
    @classmethod
    def normalize_tags(
        cls,
        values: list[str],
    ) -> list[str]:
        """Normalize tags and remove duplicates while preserving order."""

        normalized: list[str] = []
        seen: set[str] = set()

        for value in values:
            tag = value.strip().lower()

            if tag and tag not in seen:
                normalized.append(tag)
                seen.add(tag)

        return normalized


class ImplementationPlan(BaseModel):
    """Normalized implementation plan consumed by test-case generation."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    plan_id: str = Field(
        min_length=1,
        description="Stable identifier for the implementation plan.",
        examples=["PLAN-DATAVERSE-001"],
    )

    title: str = Field(
        min_length=1,
        description="Human-readable plan title.",
    )

    objective: str = Field(
        min_length=1,
        description="Business or implementation objective.",
    )

    source_path: Path | None = Field(
        default=None,
        description="Optional path from which the plan was loaded.",
    )

    requirements: list[Requirement] = Field(
        min_length=1,
        description="Requirements covered by the implementation plan.",
    )

    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions made by the implementation plan.",
    )

    constraints: list[str] = Field(
        default_factory=list,
        description="Technical, safety, or business constraints.",
    )

    out_of_scope: list[str] = Field(
        default_factory=list,
        description="Items excluded from the implementation.",
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional plan-level metadata.",
    )

    @field_validator("requirements")
    @classmethod
    def validate_unique_requirement_ids(
        cls,
        requirements: list[Requirement],
    ) -> list[Requirement]:
        """Require each requirement identifier to be unique."""

        requirement_ids = [requirement.requirement_id for requirement in requirements]

        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("Requirement IDs must be unique within a plan.")

        return requirements

    @field_validator("assumptions", "constraints", "out_of_scope")
    @classmethod
    def remove_blank_list_items(
        cls,
        values: list[str],
    ) -> list[str]:
        """Remove blank entries from plan-level string lists."""

        return [value.strip() for value in values if value.strip()]
