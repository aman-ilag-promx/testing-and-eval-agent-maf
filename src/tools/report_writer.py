"""Deterministic serialization and persistence of validated final reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from src.config import Settings, get_settings
from src.models.common import OperationResult
from src.models.enums import ReportFormat
from src.models.reports import FinalReport
from src.tools.artifact_store import ArtifactStore

_REPORT_FILE_EXTENSIONS: Final[dict[str, str]] = {
    "json": ".json",
    "markdown": ".md",
}


class ReportWriterError(ValueError):
    """Base error raised for invalid report-writer operations."""


class ReportFormatError(ReportWriterError):
    """Raised when a requested report format is unsupported."""


class ReportPathError(ReportWriterError):
    """Raised when a report path violates destination constraints."""


class ReportSerializationError(ReportWriterError):
    """Raised when a validated report cannot be serialized."""


class ReportWriter:
    """Serialize and persist validated reports in supported formats."""

    def __init__(
        self,
        settings: Settings | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        """Initialize the writer with deterministic dependencies."""
        self._settings = settings or get_settings()
        self._artifact_store = artifact_store or ArtifactStore(self._settings)
        self._reports_root = self._settings.REPORTS_DIR.resolve()

    def write(
        self,
        report: FinalReport,
        relative_path: Path,
        report_format: ReportFormat,
    ) -> OperationResult:
        """Serialize and atomically persist one validated final report."""
        normalized_format = self._normalize_format(report_format)
        destination = self._validate_destination(
            relative_path,
            normalized_format,
        )
        content = self._serialize(report, normalized_format)

        return self._artifact_store.create_text(
            metadata=report.metadata,
            relative_path=destination,
            content=content,
        )

    def serialize(
        self,
        report: FinalReport,
        report_format: ReportFormat,
    ) -> str:
        """Serialize a validated final report without persisting it."""
        normalized_format = self._normalize_format(report_format)
        return self._serialize(report, normalized_format)

    def _validate_destination(
        self,
        relative_path: Path,
        normalized_format: str,
    ) -> Path:
        if relative_path.is_absolute():
            raise ReportPathError("Report paths must be repository-relative.")

        if ".." in relative_path.parts:
            raise ReportPathError("Report paths must not contain traversal segments.")

        if not relative_path.name:
            raise ReportPathError("Report path must identify a file.")

        if relative_path.name in {".", ".."}:
            raise ReportPathError("Report path must identify a valid file.")

        expected_extension = _REPORT_FILE_EXTENSIONS[normalized_format]

        if relative_path.suffix.casefold() != expected_extension:
            raise ReportPathError(
                f"{normalized_format} reports must use the {expected_extension} file extension."
            )

        reports_directory = self._reports_root.name

        if not relative_path.parts:
            raise ReportPathError("Report path must be located under the reports directory.")

        if relative_path.parts[0] != reports_directory:
            raise ReportPathError(
                "Report path must be located under the configured reports directory."
            )

        resolved_destination = (self._reports_root.parent / relative_path).resolve()

        if not self._is_within(
            resolved_destination,
            self._reports_root,
        ):
            raise ReportPathError(
                "Report path must remain inside the configured reports directory."
            )

        return relative_path

    def _serialize(
        self,
        report: FinalReport,
        normalized_format: str,
    ) -> str:
        if normalized_format == "json":
            return self._serialize_json(report)

        if normalized_format == "markdown":
            return self._serialize_markdown(report)

        raise ReportFormatError(f"Unsupported report format: {normalized_format}.")

    @staticmethod
    def _serialize_json(report: FinalReport) -> str:
        try:
            serialized_report = report.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=False,
            )
            return (
                json.dumps(
                    serialized_report,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
        except (TypeError, ValueError) as error:
            raise ReportSerializationError(
                "Unable to serialize the final report as JSON."
            ) from error

    @classmethod
    def _serialize_markdown(cls, report: FinalReport) -> str:
        lines: list[str] = [
            f"# {cls._escape_heading(report.title)}",
            "",
            "## Summary",
            "",
            "### Objective",
            "",
            report.summary.objective.strip(),
            "",
            "### Scope",
            "",
            report.summary.scope.strip(),
            "",
            "### Overall Result",
            "",
            report.summary.overall_result.strip(),
            "",
        ]

        cls._append_string_section(
            lines,
            "Tested Areas",
            report.summary.tested_areas,
        )
        cls._append_string_section(
            lines,
            "Untested Areas",
            report.summary.untested_areas,
        )
        cls._append_string_section(
            lines,
            "Key Findings",
            report.summary.key_findings,
        )
        cls._append_string_section(
            lines,
            "Limitations",
            report.summary.limitations,
        )

        for section in sorted(
            report.sections,
            key=lambda item: item.order,
        ):
            lines.extend(
                [
                    f"## {cls._escape_heading(section.title)}",
                    "",
                    section.content.strip(),
                    "",
                ]
            )

            if section.evidence_references:
                lines.extend(
                    [
                        "### Evidence References",
                        "",
                    ]
                )
                for evidence in section.evidence_references:
                    lines.append(f"- {cls._format_evidence_reference(evidence)}")
                lines.append("")

            if section.artifact_references:
                lines.extend(
                    [
                        "### Artifact References",
                        "",
                    ]
                )
                for artifact in section.artifact_references:
                    lines.append(f"- {cls._format_artifact_reference(artifact)}")
                lines.append("")

        if report.recommendations:
            lines.extend(
                [
                    "## Recommendations",
                    "",
                ]
            )

            for recommendation in report.recommendations:
                lines.extend(
                    [
                        f"### {cls._escape_heading(recommendation.title)}",
                        "",
                        recommendation.description.strip(),
                        "",
                        "Rationale:",
                        "",
                        recommendation.rationale.strip(),
                        "",
                        f"Severity: {recommendation.severity.value}",
                        "",
                        "Human approval required: Yes",
                        "",
                    ]
                )

                if recommendation.source_requirement_ids:
                    lines.extend(
                        [
                            "Source requirements:",
                            "",
                        ]
                    )
                    for requirement_id in recommendation.source_requirement_ids:
                        lines.append(f"- {requirement_id}")
                    lines.append("")

        if report.warnings:
            lines.extend(
                [
                    "## Warnings",
                    "",
                ]
            )
            for warning in report.warnings:
                lines.append(f"- {warning.code}: {warning.message}")
            lines.append("")

        if report.errors:
            lines.extend(
                [
                    "## Errors",
                    "",
                ]
            )
            for error in report.errors:
                lines.append(f"- {error.code}: {error.message}")
            lines.append("")

        lines.extend(
            [
                "## Review Status",
                "",
                "Human review required: Yes",
                "",
            ]
        )

        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _append_string_section(
        lines: list[str],
        title: str,
        values: list[str],
    ) -> None:
        if not values:
            return

        lines.extend(
            [
                f"### {title}",
                "",
            ]
        )

        for value in values:
            lines.append(f"- {value.strip()}")

        lines.append("")

    @staticmethod
    def _format_evidence_reference(evidence: object) -> str:
        title = getattr(evidence, "title", None)
        path = getattr(evidence, "path", None)
        evidence_type = getattr(evidence, "evidence_type", None)

        components: list[str] = []

        if isinstance(title, str) and title.strip():
            components.append(title.strip())

        evidence_type_value = getattr(
            evidence_type,
            "value",
            evidence_type,
        )
        if evidence_type_value is not None:
            components.append(str(evidence_type_value))

        if isinstance(path, Path):
            components.append(path.as_posix())

        return " | ".join(components) or "Evidence reference"

    @staticmethod
    def _format_artifact_reference(artifact: object) -> str:
        name = getattr(artifact, "name", None)
        path = getattr(artifact, "path", None)
        artifact_id = getattr(artifact, "artifact_id", None)

        components: list[str] = []

        if isinstance(name, str) and name.strip():
            components.append(name.strip())

        if artifact_id is not None:
            components.append(str(artifact_id))

        if isinstance(path, Path):
            components.append(path.as_posix())

        return " | ".join(components) or "Artifact reference"

    @staticmethod
    def _escape_heading(value: str) -> str:
        return value.replace("\r", " ").replace("\n", " ").strip()

    @staticmethod
    def _normalize_format(report_format: ReportFormat) -> str:
        normalized_format = report_format.value.strip().casefold().replace("-", "_")

        aliases = {
            "json": "json",
            "markdown": "markdown",
            "md": "markdown",
        }

        resolved_format = aliases.get(normalized_format)

        if resolved_format is None:
            raise ReportFormatError(f"Unsupported report format: {report_format.value}.")

        return resolved_format

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False

        return True
