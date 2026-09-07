"""Models for comparing approved plans with observed implementations."""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from src.models.common import AgentBaseModel, ArtifactMetadata, EvidenceReference
from src.models.enums import ArtifactType, RequirementStatus, Severity
from src.models.evaluation import EvaluationResult
from src.models.playwright import PlaywrightExecutionResult
from src.models.test_cases import ImplementationInput


def _normalized_enum_value(value: object) -> str:
    """Return a normalized string representation of an enum-like value."""
    raw_value = getattr(value, "value", value)
    return str(raw_value).strip().lower().replace("-", "_").replace(" ", "_")


def _is_not_verifiable(status: RequirementStatus) -> bool:
    """Return whether a requirement status represents a non-verifiable finding."""
    return _normalized_enum_value(status) == "not_verifiable"


def _is_additional_behavior(status: RequirementStatus) -> bool:
    """Return whether a status represents additional unrequested behavior."""
    normalized_status = _normalized_enum_value(status)
    return normalized_status in {
        "additional",
        "additional_behavior",
        "additional_unrequested_behavior",
    }


class SourceRequirement(AgentBaseModel):
    """A requirement extracted from an original request or approved plan."""

    requirement_id: str = Field(
        min_length=1,
        max_length=100,
        description="Stable identifier used to trace the requirement.",
    )
    title: str = Field(
        min_length=1,
        max_length=300,
        description="Short human-readable requirement title.",
    )
    description: str = Field(
        min_length=1,
        description="Complete requirement statement.",
    )
    source_references: list[str] = Field(
        default_factory=list,
        description="References to the source locations that define the requirement.",
    )
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="Observable conditions that indicate successful implementation.",
    )
    is_mandatory: bool = Field(
        default=True,
        description="Whether the requirement is mandatory.",
    )

    @field_validator(
        "requirement_id",
        "title",
        "description",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Reject required text values containing only whitespace."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Value must not be empty or whitespace.")
        return value

    @field_validator(
        "source_references",
        "acceptance_criteria",
        mode="before",
    )
    @classmethod
    def validate_string_lists(cls, value: object) -> object:
        """Normalize string lists and reject empty or duplicate entries."""
        if value is None:
            return []

        if not isinstance(value, list):
            return value

        normalized_items: list[object] = []
        seen_values: set[str] = set()

        for item in value:
            if not isinstance(item, str):
                normalized_items.append(item)
                continue

            normalized_item = item.strip()
            if not normalized_item:
                raise ValueError("List entries must not be empty or whitespace.")

            comparison_value = normalized_item.casefold()
            if comparison_value in seen_values:
                raise ValueError("List entries must be unique.")

            seen_values.add(comparison_value)
            normalized_items.append(normalized_item)

        return normalized_items


class RequirementEvidence(AgentBaseModel):
    """Evidence mapped to a specific source requirement."""

    requirement_id: str = Field(
        min_length=1,
        max_length=100,
        description="Identifier of the requirement supported by this evidence.",
    )
    evidence: EvidenceReference = Field(
        description="Reference to deterministic or evaluation evidence.",
    )
    supports_claim: bool = Field(
        description="Whether the evidence supports the implementation claim.",
    )
    is_conclusive: bool = Field(
        default=False,
        description="Whether the evidence conclusively establishes the claim.",
    )
    explanation: str = Field(
        min_length=1,
        description="Explanation of how the evidence relates to the requirement.",
    )

    @field_validator("requirement_id", "explanation", mode="before")
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Reject required text values containing only whitespace."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Value must not be empty or whitespace.")
        return value

    @model_validator(mode="after")
    def validate_conclusive_evidence(self) -> Self:
        """Ensure conclusive evidence is not marked as contradicting the claim."""
        if self.is_conclusive and not self.supports_claim:
            raise ValueError(
                "Conclusive evidence must support the associated implementation claim."
            )
        return self


class SuggestedImprovement(AgentBaseModel):
    """A non-destructive improvement suggested by a comparison finding."""

    description: str = Field(
        min_length=1,
        description="Recommended improvement.",
    )
    rationale: str = Field(
        min_length=1,
        description="Reason the improvement is recommended.",
    )
    priority: Severity = Field(
        description="Relative importance of the suggested improvement.",
    )
    affected_requirement_ids: list[str] = Field(
        default_factory=list,
        description="Requirement identifiers affected by the improvement.",
    )

    @field_validator("description", "rationale", mode="before")
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Reject required text values containing only whitespace."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Value must not be empty or whitespace.")
        return value

    @field_validator("affected_requirement_ids", mode="before")
    @classmethod
    def validate_requirement_ids(cls, value: object) -> object:
        """Normalize and validate affected requirement identifiers."""
        if value is None:
            return []

        if not isinstance(value, list):
            return value

        normalized_ids: list[object] = []
        seen_ids: set[str] = set()

        for item in value:
            if not isinstance(item, str):
                normalized_ids.append(item)
                continue

            normalized_item = item.strip()
            if not normalized_item:
                raise ValueError("Affected requirement identifiers must not be empty.")

            comparison_value = normalized_item.casefold()
            if comparison_value in seen_ids:
                raise ValueError("Affected requirement identifiers must be unique.")

            seen_ids.add(comparison_value)
            normalized_ids.append(normalized_item)

        return normalized_ids


class PlanComparisonFinding(AgentBaseModel):
    """A traceable finding for one requirement or additional behavior."""

    finding_id: UUID = Field(
        description="Unique identifier for the comparison finding.",
    )
    requirement_id: str = Field(
        min_length=1,
        max_length=100,
        description="Requirement associated with the finding.",
    )
    status: RequirementStatus = Field(
        description="Observed implementation status for the requirement.",
    )
    summary: str = Field(
        min_length=1,
        description="Concise explanation of the finding.",
    )
    evidence: list[RequirementEvidence] = Field(
        default_factory=list,
        description="Evidence used to support the finding.",
    )
    gap_impact: str | None = Field(
        default=None,
        description="Impact caused by the identified gap.",
    )
    severity: Severity = Field(
        description="Severity of the finding or identified gap.",
    )
    suggested_improvements: list[SuggestedImprovement] = Field(
        default_factory=list,
        description="Suggested non-destructive improvements.",
    )

    @field_validator("requirement_id", "summary", mode="before")
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Reject required text values containing only whitespace."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Value must not be empty or whitespace.")
        return value

    @field_validator("gap_impact", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        """Normalize optional text and convert blank text to None."""
        if isinstance(value, str):
            normalized_value = value.strip()
            return normalized_value or None
        return value

    @model_validator(mode="after")
    def validate_evidence_consistency(self) -> Self:
        """Enforce evidence rules for verifiable and non-verifiable findings."""
        for evidence_item in self.evidence:
            if evidence_item.requirement_id != self.requirement_id:
                raise ValueError("Every evidence item must reference the finding requirement_id.")

        if _is_not_verifiable(self.status):
            if any(item.is_conclusive for item in self.evidence):
                raise ValueError("A not-verifiable finding cannot contain conclusive evidence.")
            return self

        if not self.evidence:
            raise ValueError("A verifiable implementation finding requires mapped evidence.")

        return self


class PlanComparisonRequest(AgentBaseModel):
    """Input required to compare a plan with an observed implementation."""

    original_input: ImplementationInput = Field(
        description="Original request or implementation input.",
    )
    approved_plan: ImplementationInput | None = Field(
        default=None,
        description="Approved implementation plan when one is available.",
    )
    requirements: list[SourceRequirement] = Field(
        min_length=1,
        description="Requirements extracted from the original input or approved plan.",
    )
    implementation_artifacts: list[ArtifactMetadata] = Field(
        default_factory=list,
        description="Implementation artifacts included in the comparison.",
    )
    execution_results: list[PlaywrightExecutionResult] = Field(
        default_factory=list,
        description="Deterministic Playwright execution results.",
    )
    evaluation_results: list[EvaluationResult] = Field(
        default_factory=list,
        description="Approved or review-ready evaluation results.",
    )

    @model_validator(mode="after")
    def validate_requirement_identifiers(self) -> Self:
        """Ensure all source requirement identifiers are unique."""
        normalized_ids = [
            requirement.requirement_id.casefold() for requirement in self.requirements
        ]

        if len(normalized_ids) != len(set(normalized_ids)):
            raise ValueError("Source requirement identifiers must be unique.")

        return self


class PlanComparisonResult(AgentBaseModel):
    """Complete result of comparing a plan with an implementation."""

    artifact_metadata: ArtifactMetadata = Field(
        description="Metadata for the persisted plan-comparison artifact.",
    )
    requirements: list[SourceRequirement] = Field(
        min_length=1,
        description="Requirements included in the comparison.",
    )
    findings: list[PlanComparisonFinding] = Field(
        min_length=1,
        description="Traceable findings produced by the comparison.",
    )
    suggested_improvements: list[SuggestedImprovement] = Field(
        default_factory=list,
        description="Consolidated non-destructive improvement suggestions.",
    )
    summary: str = Field(
        min_length=1,
        description="Overall comparison summary.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Known evidence or comparison limitations.",
    )
    requires_human_review: bool = Field(
        default=True,
        description="Whether the comparison requires human review.",
    )

    @field_validator("summary", mode="before")
    @classmethod
    def validate_summary(cls, value: object) -> object:
        """Reject an empty comparison summary."""
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("Summary must not be empty or whitespace.")
        return value

    @field_validator("limitations", mode="before")
    @classmethod
    def validate_limitations(cls, value: object) -> object:
        """Normalize limitations and reject empty or duplicate entries."""
        if value is None:
            return []

        if not isinstance(value, list):
            return value

        normalized_items: list[object] = []
        seen_values: set[str] = set()

        for item in value:
            if not isinstance(item, str):
                normalized_items.append(item)
                continue

            normalized_item = item.strip()
            if not normalized_item:
                raise ValueError("Limitations must not contain empty entries.")

            comparison_value = normalized_item.casefold()
            if comparison_value in seen_values:
                raise ValueError("Limitations must be unique.")

            seen_values.add(comparison_value)
            normalized_items.append(normalized_item)

        return normalized_items

    @model_validator(mode="after")
    def validate_result_integrity(self) -> Self:
        """Validate artifact type, traceability, evidence, and review boundaries."""
        if self.artifact_metadata.artifact_type != ArtifactType.PLAN_COMPARISON:
            raise ValueError(
                "artifact_metadata.artifact_type must be ArtifactType.PLAN_COMPARISON."
            )

        requirement_ids = {requirement.requirement_id for requirement in self.requirements}

        finding_ids = [finding.finding_id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("Finding identifiers must be unique.")

        findings_by_requirement: dict[str, int] = {}

        for finding in self.findings:
            if finding.requirement_id not in requirement_ids and not _is_additional_behavior(
                finding.status
            ):
                raise ValueError(
                    "Every finding must reference a known requirement unless it "
                    "classifies additional unrequested behavior."
                )

            findings_by_requirement[finding.requirement_id] = (
                findings_by_requirement.get(finding.requirement_id, 0) + 1
            )

        missing_requirement_ids = requirement_ids.difference(findings_by_requirement)
        if missing_requirement_ids:
            missing_ids = ", ".join(sorted(missing_requirement_ids))
            raise ValueError(
                "Every source requirement must have a comparison finding. "
                f"Missing findings for: {missing_ids}."
            )

        if not self.requires_human_review:
            raise ValueError("Plan-comparison results must require human review.")

        return self
