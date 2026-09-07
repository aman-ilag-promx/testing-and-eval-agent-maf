"""Structured models for final testing and evaluation reports."""

from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from src.models.common import (
    AgentBaseModel,
    ArtifactMetadata,
    ArtifactReference,
    ErrorDetail,
    EvidenceReference,
    WarningDetail,
)
from src.models.enums import ArtifactType, ReportFormat, Severity
from src.models.evaluation import EvaluationResult
from src.models.plan_comparison import (
    PlanComparisonResult,
    SuggestedImprovement,
)
from src.models.playwright import PlaywrightExecutionResult
from src.models.test_cases import ImplementationInput, TestCaseCollection


def _normalize_required_text(value: object, field_name: str) -> object:
    """Normalize required text and reject empty values."""
    if isinstance(value, str):
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"{field_name} must not be empty or whitespace.")
        return normalized_value

    return value


def _normalize_unique_strings(
    value: object,
    field_name: str,
) -> object:
    """Normalize a list of strings and reject empty or duplicate entries."""
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


class ReportSection(AgentBaseModel):
    """A structured section included in a generated report."""

    section_id: str = Field(
        min_length=1,
        max_length=100,
        description="Stable identifier for the report section.",
    )
    title: str = Field(
        min_length=1,
        max_length=300,
        description="Human-readable title of the report section.",
    )
    content: str = Field(
        min_length=1,
        description="Complete textual content of the report section.",
    )
    order: int = Field(
        ge=0,
        description="Zero-based display order of the section.",
    )
    evidence_references: list[EvidenceReference] = Field(
        default_factory=list,
        description="Evidence references supporting claims in this section.",
    )
    artifact_references: list[ArtifactReference] = Field(
        default_factory=list,
        description="Artifacts referenced by this section.",
    )

    @field_validator("section_id", "title", "content", mode="before")
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate required section text."""
        return _normalize_required_text(value, "Report section text")


class ReportRecommendation(AgentBaseModel):
    """A traceable, non-destructive recommendation included in a report."""

    recommendation_id: UUID = Field(
        description="Unique identifier for the recommendation.",
    )
    title: str = Field(
        min_length=1,
        max_length=300,
        description="Short human-readable recommendation title.",
    )
    description: str = Field(
        min_length=1,
        description="Complete recommendation description.",
    )
    rationale: str = Field(
        min_length=1,
        description="Evidence-based reason for the recommendation.",
    )
    severity: Severity = Field(
        description="Severity or importance of the recommendation.",
    )
    source_requirement_ids: list[str] = Field(
        default_factory=list,
        description="Requirement identifiers related to the recommendation.",
    )
    evidence_references: list[EvidenceReference] = Field(
        default_factory=list,
        description="Evidence supporting the recommendation.",
    )
    suggested_improvement: SuggestedImprovement | None = Field(
        default=None,
        description="Structured improvement associated with the recommendation.",
    )
    requires_human_approval: bool = Field(
        default=True,
        description="Whether human approval is required before acting.",
    )

    @field_validator("title", "description", "rationale", mode="before")
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate required recommendation text."""
        return _normalize_required_text(value, "Recommendation text")

    @field_validator("source_requirement_ids", mode="before")
    @classmethod
    def validate_source_requirement_ids(cls, value: object) -> object:
        """Normalize and validate source requirement identifiers."""
        return _normalize_unique_strings(
            value,
            "source_requirement_ids",
        )

    @model_validator(mode="after")
    def validate_approval_boundary(self) -> Self:
        """Ensure recommendations cannot bypass human review."""
        if not self.requires_human_approval:
            raise ValueError("Report recommendations must require human approval.")

        return self


class ReportSummary(AgentBaseModel):
    """High-level summary of the testing and evaluation lifecycle."""

    objective: str = Field(
        min_length=1,
        description="Objective of the testing and evaluation activity.",
    )
    scope: str = Field(
        min_length=1,
        description="Scope covered by the report.",
    )
    overall_result: str = Field(
        min_length=1,
        description="Evidence-based overall result.",
    )
    tested_areas: list[str] = Field(
        default_factory=list,
        description="Areas covered by deterministic testing.",
    )
    untested_areas: list[str] = Field(
        default_factory=list,
        description="Areas not covered or not verifiable.",
    )
    key_findings: list[str] = Field(
        default_factory=list,
        description="Most important findings included in the report.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Known limits affecting report interpretation.",
    )

    @field_validator(
        "objective",
        "scope",
        "overall_result",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate required summary text."""
        return _normalize_required_text(value, "Report summary text")

    @field_validator(
        "tested_areas",
        "untested_areas",
        "key_findings",
        "limitations",
        mode="before",
    )
    @classmethod
    def validate_string_lists(cls, value: object) -> object:
        """Normalize report summary lists."""
        return _normalize_unique_strings(value, "Report summary list")


class FinalReportRequest(AgentBaseModel):
    """Inputs required to assemble a final testing and evaluation report."""

    original_input: ImplementationInput = Field(
        description="Original request or implementation input.",
    )
    approved_plan: ImplementationInput | None = Field(
        default=None,
        description="Approved implementation plan when available.",
    )
    approved_test_cases: TestCaseCollection | None = Field(
        default=None,
        description="Approved test cases included in report traceability.",
    )
    execution_results: list[PlaywrightExecutionResult] = Field(
        default_factory=list,
        description="Deterministic Playwright execution results.",
    )
    evaluation_results: list[EvaluationResult] = Field(
        default_factory=list,
        description="Evaluation results included in the report.",
    )
    plan_comparison_result: PlanComparisonResult | None = Field(
        default=None,
        description="Plan-versus-implementation comparison result.",
    )
    supporting_artifacts: list[ArtifactReference] = Field(
        default_factory=list,
        description="Additional artifacts included in report generation.",
    )
    requested_formats: list[ReportFormat] = Field(
        min_length=1,
        description="Output formats requested for the report.",
    )
    report_title: str = Field(
        min_length=1,
        max_length=300,
        description="Requested report title.",
    )

    @field_validator("report_title", mode="before")
    @classmethod
    def validate_report_title(cls, value: object) -> object:
        """Normalize and validate the report title."""
        return _normalize_required_text(value, "report_title")

    @field_validator("requested_formats")
    @classmethod
    def validate_requested_formats(
        cls,
        value: list[ReportFormat],
    ) -> list[ReportFormat]:
        """Require unique report output formats."""
        if len(value) != len(set(value)):
            raise ValueError("requested_formats entries must be unique.")

        return value

    @model_validator(mode="after")
    def validate_report_inputs(self) -> Self:
        """Require at least one evidence-bearing report input."""
        has_report_evidence = any(
            (
                self.approved_test_cases is not None,
                bool(self.execution_results),
                bool(self.evaluation_results),
                self.plan_comparison_result is not None,
            )
        )
        if not has_report_evidence:
            raise ValueError(
                "At least one of approved_test_cases, execution_results, "
                "evaluation_results, or plan_comparison_result must be "
                "provided."
            )

        return self


class FinalReport(AgentBaseModel):
    """Final report artifact assembled from testing and evaluation outputs."""

    metadata: ArtifactMetadata = Field(
        description="Artifact metadata for the persisted report.",
    )
    title: str = Field(
        min_length=1,
        max_length=300,
        description="Final report title.",
    )
    summary: ReportSummary = Field(
        description="High-level report summary.",
    )
    sections: list[ReportSection] = Field(
        min_length=1,
        description="Structured report sections.",
    )
    recommendations: list[ReportRecommendation] = Field(
        default_factory=list,
        description="Traceable recommendations included in the final report.",
    )
    source_request: FinalReportRequest = Field(
        description="Validated inputs used to assemble the report.",
    )
    output_formats: list[ReportFormat] = Field(
        min_length=1,
        description="Formats generated for this report artifact.",
    )
    generated_artifacts: list[ArtifactReference] = Field(
        default_factory=list,
        description="Artifacts generated as report outputs.",
    )
    warnings: list[WarningDetail] = Field(
        default_factory=list,
        description="Non-blocking warnings encountered during report generation.",
    )
    errors: list[ErrorDetail] = Field(
        default_factory=list,
        description="Structured errors captured during report generation.",
    )

    @field_validator("title", mode="before")
    @classmethod
    def validate_report_title(cls, value: object) -> object:
        """Normalize and validate the final report title."""
        return _normalize_required_text(value, "title")

    @field_validator("output_formats")
    @classmethod
    def validate_output_formats(
        cls,
        value: list[ReportFormat],
    ) -> list[ReportFormat]:
        """Require unique output formats."""
        if len(value) != len(set(value)):
            raise ValueError("output_formats entries must be unique.")

        return value

    @model_validator(mode="after")
    def validate_metadata_and_outputs(self) -> Self:
        """Ensure report metadata and generated output formats are consistent."""
        if self.metadata.artifact_type is not ArtifactType.REPORT:
            raise ValueError("Report metadata artifact_type must be report.")

        requested_format_values = {
            report_format.value for report_format in self.source_request.requested_formats
        }
        output_format_values = {report_format.value for report_format in self.output_formats}

        if not output_format_values.issubset(requested_format_values):
            raise ValueError("output_formats must be a subset of source_request.requested_formats.")

        return self
