"""Evaluation models for the Testing and Evaluation Agent."""

from __future__ import annotations

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
    EvaluationOutcome,
    Severity,
)
from src.models.playwright import PlaywrightExecutionResult


def normalize_unique_text(
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


class EvaluationScale(AgentBaseModel):
    """Numeric scale used by an evaluation rubric."""

    minimum_score: float = 0.0
    maximum_score: float = 5.0
    passing_score: float = 3.0

    @model_validator(mode="after")
    def validate_scale(self) -> Self:
        """Ensure the scale and passing threshold are valid."""

        if self.maximum_score <= self.minimum_score:
            raise ValueError("maximum_score must be greater than minimum_score.")

        if not (self.minimum_score <= self.passing_score <= self.maximum_score):
            raise ValueError("passing_score must be between minimum_score and maximum_score.")

        return self


class EvaluationCriterion(AgentBaseModel):
    """One configurable criterion in an evaluation rubric."""

    criterion_id: str = Field(
        min_length=1,
        max_length=100,
    )
    name: str = Field(
        min_length=1,
        max_length=255,
    )
    description: str = Field(
        min_length=1,
        max_length=4_000,
    )
    weight: float = Field(
        default=1.0,
        gt=0.0,
        le=100.0,
    )
    scale: EvaluationScale = Field(default_factory=EvaluationScale)
    required_evidence_types: list[str] = Field(default_factory=list)
    evaluation_instructions: str = Field(
        min_length=1,
        max_length=8_000,
    )

    @field_validator("criterion_id")
    @classmethod
    def normalize_criterion_id(
        cls,
        value: str,
    ) -> str:
        """Normalize the criterion identifier."""

        normalized_value = value.strip().upper()
        comparable_value = normalized_value.replace("-", "").replace("_", "")

        if not comparable_value.isalnum():
            raise ValueError(
                "criterion_id may contain only letters, numbers, hyphens, and underscores."
            )

        return normalized_value

    @field_validator("required_evidence_types")
    @classmethod
    def validate_required_evidence_types(
        cls,
        value: list[str],
    ) -> list[str]:
        """Normalize required evidence type names."""

        return normalize_unique_text(
            value,
            "required_evidence_types",
        )


class EvaluationRubric(AgentBaseModel):
    """Configurable rubric used to evaluate an implementation."""

    rubric_id: str = Field(
        min_length=1,
        max_length=100,
    )
    name: str = Field(
        min_length=1,
        max_length=255,
    )
    version: str = Field(
        min_length=1,
        max_length=50,
    )
    description: str = Field(
        min_length=1,
        max_length=4_000,
    )
    criteria: list[EvaluationCriterion] = Field(min_length=1)
    approved: bool = False
    approval_reference_id: UUID | None = None

    @field_validator("rubric_id")
    @classmethod
    def normalize_rubric_id(
        cls,
        value: str,
    ) -> str:
        """Normalize the rubric identifier."""

        normalized_value = value.strip().upper()
        comparable_value = normalized_value.replace("-", "").replace("_", "")

        if not comparable_value.isalnum():
            raise ValueError(
                "rubric_id may contain only letters, numbers, hyphens, and underscores."
            )

        return normalized_value

    @model_validator(mode="after")
    def validate_criteria(self) -> Self:
        """Require unique criteria and consistent approval data."""

        criterion_ids = [criterion.criterion_id for criterion in self.criteria]

        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("Rubric criterion identifiers must be unique.")

        if self.approved and self.approval_reference_id is None:
            raise ValueError("An approved rubric must include approval_reference_id.")

        if not self.approved and self.approval_reference_id is not None:
            raise ValueError("An unapproved rubric must not include approval_reference_id.")

        return self

    @property
    def total_weight(self) -> float:
        """Return the sum of all criterion weights."""

        return sum(criterion.weight for criterion in self.criteria)


class EvaluationRequest(AgentBaseModel):
    """Request to evaluate deterministic execution evidence."""

    run_id: UUID
    source_artifact_ids: list[UUID] = Field(min_length=1)
    rubric: EvaluationRubric
    execution_results: list[PlaywrightExecutionResult] = Field(default_factory=list)
    additional_evidence: list[EvidenceReference] = Field(default_factory=list)
    evaluator_instructions: str | None = Field(
        default=None,
        max_length=8_000,
    )

    @field_validator("source_artifact_ids")
    @classmethod
    def remove_duplicate_source_ids(
        cls,
        value: list[UUID],
    ) -> list[UUID]:
        """Remove duplicate source artifact identifiers."""

        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        """Require an approved rubric and available evidence."""

        if not self.rubric.approved:
            raise ValueError("Evaluation requires an approved rubric.")

        if not self.execution_results and not self.additional_evidence:
            raise ValueError("Evaluation requires execution results or additional evidence.")

        return self


class CriterionEvaluation(AgentBaseModel):
    """Evidence-based result for one rubric criterion."""

    criterion_id: str = Field(
        min_length=1,
        max_length=100,
    )
    outcome: EvaluationOutcome
    score: float | None = None
    rationale: str = Field(
        min_length=1,
        max_length=8_000,
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )
    evidence: list[EvidenceReference] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    severity: Severity = Severity.INFORMATIONAL

    @field_validator("criterion_id")
    @classmethod
    def normalize_criterion_id(
        cls,
        value: str,
    ) -> str:
        """Normalize the evaluated criterion identifier."""

        return value.strip().upper()

    @field_validator("recommendations")
    @classmethod
    def validate_recommendations(
        cls,
        value: list[str],
    ) -> list[str]:
        """Normalize recommendations and remove duplicates."""

        return normalize_unique_text(
            value,
            "recommendations",
        )

    @model_validator(mode="after")
    def validate_evidence_and_score(self) -> Self:
        """Require evidence for scored evaluation outcomes."""

        unscored_outcomes = {
            EvaluationOutcome.NOT_APPLICABLE,
            EvaluationOutcome.NOT_EVALUATED,
            EvaluationOutcome.INSUFFICIENT_EVIDENCE,
        }

        if self.outcome in unscored_outcomes and self.score is not None:
            raise ValueError("Non-evaluated outcomes must not include a numeric score.")

        if self.outcome not in unscored_outcomes:
            if self.score is None:
                raise ValueError("Evaluated outcomes must include a numeric score.")

            if not self.evidence:
                raise ValueError("Evaluated outcomes must include evidence.")

        return self


class EvaluationResult(AgentBaseModel):
    """Complete evaluation result awaiting human approval."""

    metadata: ArtifactMetadata
    rubric_id: str = Field(
        min_length=1,
        max_length=100,
    )
    rubric_version: str = Field(
        min_length=1,
        max_length=50,
    )
    criterion_results: list[CriterionEvaluation] = Field(min_length=1)
    weighted_score: float | None = None
    overall_outcome: EvaluationOutcome
    summary: str = Field(
        min_length=1,
        max_length=8_000,
    )
    warnings: list[WarningDetail] = Field(default_factory=list)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING

    @model_validator(mode="after")
    def validate_metadata(self) -> Self:
        """Require evaluation-result artifact metadata."""

        if self.metadata.artifact_type is not ArtifactType.EVALUATION_RESULT:
            raise ValueError("Evaluation metadata artifact_type must be evaluation_result.")

        allowed_statuses = {
            ArtifactStatus.DRAFT,
            ArtifactStatus.AWAITING_APPROVAL,
            ArtifactStatus.APPROVED,
            ArtifactStatus.REJECTED,
            ArtifactStatus.SUPERSEDED,
            ArtifactStatus.INCOMPLETE,
        }

        if self.metadata.status not in allowed_statuses:
            raise ValueError("Evaluation result has an invalid artifact status.")

        return self

    @model_validator(mode="after")
    def validate_criterion_results(self) -> Self:
        """Require unique results and consistent scoring."""

        criterion_ids = [result.criterion_id for result in self.criterion_results]

        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("Evaluation criterion results must be unique.")

        scored_results = [result for result in self.criterion_results if result.score is not None]

        if scored_results and self.weighted_score is None:
            raise ValueError("weighted_score is required when criterion scores are present.")

        if not scored_results and self.weighted_score is not None:
            raise ValueError("weighted_score must be omitted when no criterion is scored.")

        return self
