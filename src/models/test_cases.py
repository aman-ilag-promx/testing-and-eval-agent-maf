"""Test-case models for the Testing and Evaluation Agent."""

from __future__ import annotations

import re
from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from src.models.common import (
    AgentBaseModel,
    ArtifactMetadata,
    EvidenceReference,
    WarningDetail,
)
from src.models.enums import (
    ApprovalStatus,
    ArtifactStatus,
    ArtifactType,
    AutomationSuitability,
    TestCategory,
    TestPriority,
)

TEST_CASE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{2,49}$")
REQUIREMENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")


def _normalize_unique_text_values(
    values: list[str],
    field_name: str,
) -> list[str]:
    """Normalize text values and remove case-insensitive duplicates."""

    normalized_values: list[str] = []
    seen_values: set[str] = set()

    for value in values:
        normalized_value = value.strip()

        if not normalized_value:
            raise ValueError(f"{field_name} must not contain empty values.")

        comparison_value = normalized_value.casefold()

        if comparison_value not in seen_values:
            seen_values.add(comparison_value)
            normalized_values.append(normalized_value)

    return normalized_values


class ImplementationInput(AgentBaseModel):
    """Original implementation request or plan used to generate test cases."""

    title: str = Field(min_length=1, max_length=255)
    original_user_request: str = Field(min_length=1, max_length=50_000)
    implementation_plan: str | None = Field(default=None, max_length=100_000)
    target_scope: str = Field(min_length=1, max_length=4_000)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    source_references: list[str] = Field(default_factory=list)
    # Optional traceability links to a registered target and run
    target_id: UUID | None = None
    run_id: UUID | None = None

    @field_validator("constraints")
    @classmethod
    def validate_constraints(cls, value: list[str]) -> list[str]:
        """Normalize constraints and remove duplicates."""

        return _normalize_unique_text_values(value, "constraints")

    @field_validator("assumptions")
    @classmethod
    def validate_assumptions(cls, value: list[str]) -> list[str]:
        """Normalize assumptions and remove duplicates."""

        return _normalize_unique_text_values(value, "assumptions")

    @field_validator("source_references")
    @classmethod
    def validate_source_references(cls, value: list[str]) -> list[str]:
        """Normalize source references and remove duplicates."""

        return _normalize_unique_text_values(value, "source_references")


class TestStep(AgentBaseModel):
    """One deterministic or manually executable test step."""

    step_number: int = Field(ge=1)
    action: str = Field(min_length=1, max_length=4_000)
    expected_result: str = Field(min_length=1, max_length=4_000)
    test_data_reference: str | None = Field(default=None, max_length=500)
    evidence_required: list[str] = Field(default_factory=list)

    @field_validator("evidence_required")
    @classmethod
    def validate_evidence_required(cls, value: list[str]) -> list[str]:
        """Normalize required evidence descriptions."""

        return _normalize_unique_text_values(value, "evidence_required")


class TestCase(AgentBaseModel):
    """Structured and traceable test case."""

    test_case_id: str
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=4_000)
    category: TestCategory
    priority: TestPriority

    source_requirement_ids: list[str] = Field(min_length=1)
    source_requirement_text: str = Field(min_length=1, max_length=8_000)

    preconditions: list[str] = Field(default_factory=list)
    test_data: list[str] = Field(default_factory=list)
    steps: list[TestStep] = Field(min_length=1)
    postconditions: list[str] = Field(default_factory=list)

    automation_suitability: AutomationSuitability
    automation_notes: str | None = Field(default=None, max_length=4_000)

    required_evidence: list[str] = Field(default_factory=list)
    safety_considerations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    destructive: bool = False
    requires_live_environment: bool = False
    requires_authentication: bool = False
    approval_status: ApprovalStatus = ApprovalStatus.PENDING

    @field_validator("test_case_id")
    @classmethod
    def validate_test_case_id(cls, value: str) -> str:
        """Validate and normalize the test-case identifier."""

        normalized_value = value.strip().upper()

        if not TEST_CASE_ID_PATTERN.fullmatch(normalized_value):
            raise ValueError(
                "test_case_id must contain 3 to 50 uppercase letters, "
                "numbers, underscores, or hyphens and must begin with a letter."
            )

        return normalized_value

    @field_validator("source_requirement_ids")
    @classmethod
    def validate_requirement_ids(cls, value: list[str]) -> list[str]:
        """Validate requirement identifiers and remove duplicates."""

        normalized_values = _normalize_unique_text_values(
            value,
            "source_requirement_ids",
        )

        for requirement_id in normalized_values:
            if not REQUIREMENT_ID_PATTERN.fullmatch(requirement_id):
                raise ValueError(
                    "Each source requirement identifier must begin with an "
                    "alphanumeric character and may contain letters, numbers, "
                    "periods, underscores, colons, forward slashes, or hyphens."
                )

        return normalized_values

    @field_validator(
        "preconditions",
        "test_data",
        "postconditions",
        "required_evidence",
        "safety_considerations",
        "tags",
    )
    @classmethod
    def normalize_text_lists(cls, value: list[str], info: object) -> list[str]:
        """Normalize reusable text-list fields."""

        field_name = getattr(info, "field_name", "list")
        return _normalize_unique_text_values(value, field_name)

    @model_validator(mode="after")
    def validate_test_steps(self) -> Self:
        """Require unique, continuous test-step numbering."""

        step_numbers = [step.step_number for step in self.steps]
        expected_numbers = list(range(1, len(self.steps) + 1))

        if step_numbers != expected_numbers:
            raise ValueError(
                "Test steps must be ordered and numbered continuously starting from 1."
            )

        return self

    @model_validator(mode="after")
    def validate_automation_details(self) -> Self:
        """Require notes when automation is not fully suitable."""

        automation_requires_notes = {
            AutomationSuitability.PARTIALLY_SUITABLE,
            AutomationSuitability.NOT_SUITABLE,
            AutomationSuitability.REQUIRES_EXPLORATION,
        }

        if self.automation_suitability in automation_requires_notes and not self.automation_notes:
            raise ValueError("automation_notes is required when automation is not fully suitable.")

        return self

    @model_validator(mode="after")
    def validate_safety_details(self) -> Self:
        """Require explicit safety information for destructive tests."""

        if self.destructive and not self.safety_considerations:
            raise ValueError("A destructive test must include safety considerations.")

        return self


class TestCaseGenerationRequest(AgentBaseModel):
    """Validated request for the generate-test-cases skill."""

    run_id: UUID
    implementation_input: ImplementationInput
    requested_categories: list[TestCategory] = Field(min_length=1)
    default_priority: TestPriority = TestPriority.MEDIUM
    include_positive_tests: bool = True
    include_negative_tests: bool = True
    include_edge_cases: bool = True
    maximum_test_cases: int = Field(default=50, ge=1, le=500)
    additional_instructions: str | None = Field(
        default=None,
        max_length=8_000,
    )

    @field_validator("requested_categories")
    @classmethod
    def remove_duplicate_categories(
        cls,
        value: list[TestCategory],
    ) -> list[TestCategory]:
        """Remove duplicate categories while preserving their order."""

        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def require_generation_scope(self) -> Self:
        """Require at least one enabled test-generation scenario."""

        if not any(
            (
                self.include_positive_tests,
                self.include_negative_tests,
                self.include_edge_cases,
            )
        ):
            raise ValueError(
                "At least one of positive, negative, or edge-case generation must be enabled."
            )

        return self


class TestCaseCollection(AgentBaseModel):
    """Generated collection of test cases awaiting human approval."""

    metadata: ArtifactMetadata
    source_input: ImplementationInput
    test_cases: list[TestCase] = Field(min_length=1)
    coverage_summary: dict[str, list[str]] = Field(default_factory=dict)
    uncovered_requirements: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[WarningDetail] = Field(default_factory=list)
    generation_evidence: list[EvidenceReference] = Field(default_factory=list)

    @field_validator("uncovered_requirements")
    @classmethod
    def validate_uncovered_requirements(
        cls,
        value: list[str],
    ) -> list[str]:
        """Normalize uncovered requirement descriptions."""

        return _normalize_unique_text_values(value, "uncovered_requirements")

    @field_validator("assumptions")
    @classmethod
    def validate_assumptions(cls, value: list[str]) -> list[str]:
        """Normalize collection assumptions."""

        return _normalize_unique_text_values(value, "assumptions")

    @field_validator("coverage_summary")
    @classmethod
    def validate_coverage_summary(
        cls,
        value: dict[str, list[str]],
    ) -> dict[str, list[str]]:
        """Validate requirement-to-test-case coverage mappings."""

        normalized_summary: dict[str, list[str]] = {}

        for requirement_id, test_case_ids in value.items():
            normalized_requirement_id = requirement_id.strip()

            if not normalized_requirement_id:
                raise ValueError("Coverage-summary requirement IDs must not be empty.")

            if not REQUIREMENT_ID_PATTERN.fullmatch(normalized_requirement_id):
                raise ValueError("Coverage-summary requirement IDs contain unsupported characters.")

            normalized_test_case_ids = _normalize_unique_text_values(
                test_case_ids,
                f"coverage_summary[{normalized_requirement_id}]",
            )

            normalized_summary[normalized_requirement_id] = [
                test_case_id.upper() for test_case_id in normalized_test_case_ids
            ]

        return normalized_summary

    @model_validator(mode="after")
    def validate_collection_metadata(self) -> Self:
        """Ensure metadata represents a generated test-case collection."""

        if self.metadata.artifact_type is not ArtifactType.TEST_CASE_COLLECTION:
            raise ValueError("Collection metadata artifact_type must be test_case_collection.")

        allowed_statuses = {
            ArtifactStatus.DRAFT,
            ArtifactStatus.AWAITING_APPROVAL,
            ArtifactStatus.APPROVED,
            ArtifactStatus.REJECTED,
            ArtifactStatus.SUPERSEDED,
            ArtifactStatus.INCOMPLETE,
        }

        if self.metadata.status not in allowed_statuses:
            raise ValueError("Test-case collection metadata has an invalid status.")

        return self

    @model_validator(mode="after")
    def validate_unique_test_case_ids(self) -> Self:
        """Require unique test-case identifiers."""

        test_case_ids = [test_case.test_case_id for test_case in self.test_cases]

        if len(test_case_ids) != len(set(test_case_ids)):
            raise ValueError("Test-case identifiers must be unique within a collection.")

        return self

    @model_validator(mode="after")
    def validate_coverage_references(self) -> Self:
        """Ensure coverage mappings reference test cases in this collection."""

        available_test_case_ids = {test_case.test_case_id for test_case in self.test_cases}

        referenced_test_case_ids = {
            test_case_id
            for test_case_ids in self.coverage_summary.values()
            for test_case_id in test_case_ids
        }

        unknown_test_case_ids = referenced_test_case_ids - available_test_case_ids

        if unknown_test_case_ids:
            unknown_values = ", ".join(sorted(unknown_test_case_ids))
            raise ValueError(f"Coverage summary references unknown test cases: {unknown_values}.")

        return self
