"""Models for instruction-based testing and evaluation skills."""

from __future__ import annotations

from typing import Self

from pydantic import Field, field_validator, model_validator

from src.models.common import AgentBaseModel, ArtifactReference


def _normalize_required_text(value: object, field_name: str) -> object:
    """Normalize required text and reject empty values."""
    if isinstance(value, str):
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"{field_name} must not be empty or whitespace.")
        return normalized_value

    return value


def _normalize_optional_text(value: object) -> object:
    """Normalize optional text and convert blank values to None."""
    if isinstance(value, str):
        normalized_value = value.strip()
        return normalized_value or None

    return value


def _normalize_unique_strings(
    value: object,
    field_name: str,
) -> object:
    """Normalize string lists and reject empty or duplicate entries."""
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


class SkillInputDefinition(AgentBaseModel):
    """Definition of one input accepted by an instruction-based skill."""

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Stable input name used by the skill.",
    )
    description: str = Field(
        min_length=1,
        description="Human-readable description of the input.",
    )
    data_type: str = Field(
        min_length=1,
        max_length=200,
        description="Expected logical type of the input.",
    )
    required: bool = Field(
        default=True,
        description="Whether the input must be supplied.",
    )
    allows_multiple: bool = Field(
        default=False,
        description="Whether the input may contain multiple values.",
    )
    default_value: str | None = Field(
        default=None,
        description="Optional non-secret default value.",
    )

    @field_validator(
        "name",
        "description",
        "data_type",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate required input-definition text."""
        return _normalize_required_text(value, "Skill input definition")

    @field_validator("default_value", mode="before")
    @classmethod
    def validate_default_value(cls, value: object) -> object:
        """Normalize an optional default value."""
        return _normalize_optional_text(value)

    @model_validator(mode="after")
    def validate_default_boundary(self) -> Self:
        """Prevent an optional default from contradicting required input state."""
        if self.required and self.default_value is not None:
            raise ValueError("A required skill input must not define a default value.")

        return self


class SkillOutputDefinition(AgentBaseModel):
    """Definition of one output produced by an instruction-based skill."""

    name: str = Field(
        min_length=1,
        max_length=100,
        description="Stable output name produced by the skill.",
    )
    description: str = Field(
        min_length=1,
        description="Human-readable description of the output.",
    )
    data_type: str = Field(
        min_length=1,
        max_length=200,
        description="Expected logical type of the output.",
    )
    required: bool = Field(
        default=True,
        description="Whether successful execution must produce the output.",
    )
    persisted: bool = Field(
        default=False,
        description="Whether the output must be persisted as an artifact.",
    )
    generated_artifact: bool = Field(
        default=False,
        description="Whether the output is a generated draft artifact.",
    )
    requires_human_approval: bool = Field(
        default=False,
        description="Whether the output requires human approval.",
    )

    @field_validator(
        "name",
        "description",
        "data_type",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate required output-definition text."""
        return _normalize_required_text(value, "Skill output definition")

    @model_validator(mode="after")
    def validate_output_safety(self) -> Self:
        """Require approval for outputs designated as generated artifacts."""
        if self.generated_artifact and not self.persisted:
            raise ValueError("A generated artifact output must be persisted.")

        if self.generated_artifact and not self.requires_human_approval:
            raise ValueError("A generated artifact output must require human approval.")

        return self


class SkillGuardrail(AgentBaseModel):
    """A mandatory safety or quality constraint applied to a skill."""

    guardrail_id: str = Field(
        min_length=1,
        max_length=100,
        description="Stable guardrail identifier.",
    )
    description: str = Field(
        min_length=1,
        description="Constraint enforced by the guardrail.",
    )
    blocking: bool = Field(
        default=True,
        description="Whether violation blocks further processing.",
    )
    validation_message: str = Field(
        min_length=1,
        description="Message returned when the guardrail is violated.",
    )

    @field_validator(
        "guardrail_id",
        "description",
        "validation_message",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate required guardrail text."""
        return _normalize_required_text(value, "Skill guardrail")


class SkillAcceptanceCriterion(AgentBaseModel):
    """A deterministic acceptance criterion for a skill result."""

    criterion_id: str = Field(
        min_length=1,
        max_length=100,
        description="Stable acceptance-criterion identifier.",
    )
    description: str = Field(
        min_length=1,
        description="Condition required for successful skill completion.",
    )
    validation_method: str = Field(
        min_length=1,
        description="Deterministic method used to validate the criterion.",
    )
    required: bool = Field(
        default=True,
        description="Whether the criterion is mandatory.",
    )

    @field_validator(
        "criterion_id",
        "description",
        "validation_method",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate required acceptance-criterion text."""
        return _normalize_required_text(value, "Skill acceptance criterion")


class SkillDefinition(AgentBaseModel):
    """Complete parsed definition of an instruction-based skill."""

    name: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Stable lowercase kebab-case skill name.",
    )
    version: str = Field(
        min_length=1,
        max_length=50,
        description="Version identifier declared by the skill.",
    )
    purpose: str = Field(
        min_length=1,
        description="Purpose and responsibility of the skill.",
    )
    instructions: str = Field(
        min_length=1,
        description="Complete instructions loaded from the skill asset.",
    )
    inputs: list[SkillInputDefinition] = Field(
        min_length=1,
        description="Inputs accepted by the skill.",
    )
    outputs: list[SkillOutputDefinition] = Field(
        min_length=1,
        description="Outputs produced by the skill.",
    )
    guardrails: list[SkillGuardrail] = Field(
        min_length=1,
        description="Mandatory safety and quality constraints.",
    )
    acceptance_criteria: list[SkillAcceptanceCriterion] = Field(
        min_length=1,
        description="Criteria required for successful skill completion.",
    )
    approval_required: bool = Field(
        description="Whether the skill output requires human approval.",
    )
    external_actions_allowed: bool = Field(
        default=False,
        description="Whether the skill may perform external-system actions.",
    )
    destructive_actions_allowed: bool = Field(
        default=False,
        description="Whether the skill may perform destructive actions.",
    )
    deterministic_execution_allowed: bool = Field(
        default=False,
        description="Whether the skill may invoke deterministic execution.",
    )
    source_artifact: ArtifactReference | None = Field(
        default=None,
        description="Reference to the loaded SKILL.md artifact.",
    )

    @field_validator(
        "name",
        "version",
        "purpose",
        "instructions",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate required skill text."""
        return _normalize_required_text(value, "Skill definition")

    @field_validator("inputs")
    @classmethod
    def validate_unique_inputs(
        cls,
        value: list[SkillInputDefinition],
    ) -> list[SkillInputDefinition]:
        """Require unique skill input names."""
        input_names = [item.name.casefold() for item in value]
        if len(input_names) != len(set(input_names)):
            raise ValueError("Skill input names must be unique.")

        return value

    @field_validator("outputs")
    @classmethod
    def validate_unique_outputs(
        cls,
        value: list[SkillOutputDefinition],
    ) -> list[SkillOutputDefinition]:
        """Require unique skill output names."""
        output_names = [item.name.casefold() for item in value]
        if len(output_names) != len(set(output_names)):
            raise ValueError("Skill output names must be unique.")

        return value

    @field_validator("guardrails")
    @classmethod
    def validate_unique_guardrails(
        cls,
        value: list[SkillGuardrail],
    ) -> list[SkillGuardrail]:
        """Require unique skill guardrail identifiers."""
        guardrail_ids = [item.guardrail_id.casefold() for item in value]
        if len(guardrail_ids) != len(set(guardrail_ids)):
            raise ValueError("Skill guardrail identifiers must be unique.")

        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_unique_acceptance_criteria(
        cls,
        value: list[SkillAcceptanceCriterion],
    ) -> list[SkillAcceptanceCriterion]:
        """Require unique acceptance-criterion identifiers."""
        criterion_ids = [item.criterion_id.casefold() for item in value]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("Skill acceptance-criterion identifiers must be unique.")

        return value

    @model_validator(mode="after")
    def validate_safety_boundaries(self) -> Self:
        """Validate approval and action boundaries declared by the skill."""
        generated_outputs = [output for output in self.outputs if output.generated_artifact]

        if generated_outputs and not self.approval_required:
            raise ValueError("A skill that generates artifacts must require human approval.")

        if self.destructive_actions_allowed:
            raise ValueError(
                "Skills must not allow destructive actions in the initial implementation."
            )

        if self.external_actions_allowed:
            raise ValueError(
                "Skills must not allow external-system actions in the initial implementation."
            )

        if self.deterministic_execution_allowed and generated_outputs:
            raise ValueError("A skill that generates draft artifacts must not execute them.")

        return self


class SkillInvocationRequest(AgentBaseModel):
    """Validated request to invoke an instruction-based skill."""

    skill_name: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Name of the requested skill.",
    )
    input_artifacts: list[ArtifactReference] = Field(
        default_factory=list,
        description="Artifacts supplied to the skill invocation.",
    )
    requested_outputs: list[str] = Field(
        min_length=1,
        description="Named outputs requested from the skill.",
    )
    initiated_by: str = Field(
        min_length=1,
        max_length=200,
        description="User or trusted component requesting the invocation.",
    )
    correlation_id: str | None = Field(
        default=None,
        max_length=200,
        description="Optional operation correlation identifier.",
    )

    @field_validator(
        "skill_name",
        "initiated_by",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate required invocation text."""
        return _normalize_required_text(value, "Skill invocation")

    @field_validator("correlation_id", mode="before")
    @classmethod
    def validate_correlation_id(cls, value: object) -> object:
        """Normalize an optional correlation identifier."""
        return _normalize_optional_text(value)

    @field_validator("requested_outputs", mode="before")
    @classmethod
    def validate_requested_outputs(cls, value: object) -> object:
        """Normalize and validate requested output names."""
        return _normalize_unique_strings(value, "requested_outputs")


class SkillInvocationResult(AgentBaseModel):
    """Structured result returned by an instruction-based skill."""

    skill_name: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Name of the invoked skill.",
    )
    successful: bool = Field(
        description="Whether instruction processing completed successfully.",
    )
    message: str = Field(
        min_length=1,
        description="Human-readable invocation result.",
    )
    output_artifacts: list[ArtifactReference] = Field(
        default_factory=list,
        description="Artifacts produced by the skill.",
    )
    approval_required: bool = Field(
        description="Whether outputs require human approval.",
    )
    approved: bool = Field(
        default=False,
        description="Whether required human approval has been recorded.",
    )
    validation_failures: list[str] = Field(
        default_factory=list,
        description="Validation failures produced during invocation.",
    )

    @field_validator(
        "skill_name",
        "message",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Normalize and validate required result text."""
        return _normalize_required_text(value, "Skill invocation result")

    @field_validator("validation_failures", mode="before")
    @classmethod
    def validate_failure_messages(cls, value: object) -> object:
        """Normalize validation failure messages."""
        return _normalize_unique_strings(value, "validation_failures")

    @model_validator(mode="after")
    def validate_result_integrity(self) -> Self:
        """Validate success, approval, and failure consistency."""
        if self.approved and not self.approval_required:
            raise ValueError("approved cannot be true when approval_required is false.")

        if self.successful and self.validation_failures:
            raise ValueError("A successful skill invocation cannot contain validation failures.")

        if not self.successful and not self.validation_failures:
            raise ValueError("An unsuccessful skill invocation requires a validation failure.")

        if self.output_artifacts and self.approval_required and self.approved:
            raise ValueError("Skill invocation must not record artifact approval directly.")

        return self
