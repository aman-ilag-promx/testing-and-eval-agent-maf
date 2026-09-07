"""Safe loading and validation of repository evaluation rubrics."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import ValidationError

from src.config import PROJECT_ROOT, Settings, get_settings
from src.models.evaluation import EvaluationRubric

RUBRIC_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$|^[a-z0-9]+$")
RUBRIC_FILE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".yaml",
        ".yml",
    }
)


class RubricLoaderError(ValueError):
    """Base error raised for invalid rubric loader operations."""


class RubricNameError(RubricLoaderError):
    """Raised when a rubric name is invalid."""


class RubricPathError(RubricLoaderError):
    """Raised when a rubric path violates repository safety boundaries."""


class RubricNotFoundError(RubricLoaderError):
    """Raised when a requested rubric file does not exist."""


class RubricContentError(RubricLoaderError):
    """Raised when rubric content cannot be decoded or parsed."""


class RubricValidationError(RubricLoaderError):
    """Raised when rubric content does not match EvaluationRubric."""


class DuplicateRubricError(RubricLoaderError):
    """Raised when multiple files use the same rubric name."""


class RubricLoader:
    """Load validated evaluation rubrics from the configured directory."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the loader without reading rubric files."""
        self._settings = settings or get_settings()
        self._project_root = PROJECT_ROOT.resolve()
        self._rubrics_root = self._resolve_rubrics_root()

    @property
    def rubrics_root(self) -> Path:
        """Return the resolved evaluation rubric directory."""
        return self._rubrics_root

    def list_rubric_names(self) -> list[str]:
        """Return available rubric names in deterministic sorted order."""
        rubric_paths = self._discover_rubric_paths()
        return sorted(rubric_paths)

    def load(self, rubric_name: str) -> EvaluationRubric:
        """Load and validate one rubric by name."""
        validated_name = self._validate_rubric_name(rubric_name)
        rubric_paths = self._discover_rubric_paths()

        rubric_path = rubric_paths.get(validated_name)

        if rubric_path is None:
            raise RubricNotFoundError(f"Evaluation rubric does not exist: {validated_name}.")

        return self._load_path(rubric_path)

    def load_file(self, relative_path: Path) -> EvaluationRubric:
        """Load a rubric using a safe rubric-directory-relative path."""
        rubric_path = self._resolve_relative_rubric_path(relative_path)

        if not rubric_path.is_file():
            raise RubricNotFoundError(
                f"Evaluation rubric does not exist: {relative_path.as_posix()}."
            )

        return self._load_path(rubric_path)

    def load_all(self) -> list[EvaluationRubric]:
        """Load all available rubrics in deterministic name order."""
        rubric_paths = self._discover_rubric_paths()

        return [self._load_path(rubric_paths[rubric_name]) for rubric_name in sorted(rubric_paths)]

    def _load_path(self, rubric_path: Path) -> EvaluationRubric:
        self._validate_existing_rubric_path(rubric_path)

        try:
            content = rubric_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise RubricContentError(
                f"Evaluation rubric is not valid UTF-8: {self._display_path(rubric_path)}."
            ) from error
        except OSError as error:
            raise RubricLoaderError(
                f"Unable to read evaluation rubric: {self._display_path(rubric_path)}."
            ) from error

        if not content.strip():
            raise RubricContentError(
                f"Evaluation rubric is empty: {self._display_path(rubric_path)}."
            )

        try:
            parsed_content = yaml.safe_load(content)
        except yaml.YAMLError as error:
            raise RubricContentError(
                f"Evaluation rubric contains invalid YAML: {self._display_path(rubric_path)}."
            ) from error

        if not isinstance(parsed_content, dict):
            raise RubricContentError("Evaluation rubric YAML must contain a top-level mapping.")

        normalized_content = self._normalize_mapping(parsed_content)

        try:
            return EvaluationRubric.model_validate(normalized_content)
        except ValidationError as error:
            raise RubricValidationError(
                f"Evaluation rubric does not match EvaluationRubric: "
                f"{self._display_path(rubric_path)}. {error}"
            ) from error

    def _discover_rubric_paths(self) -> dict[str, Path]:
        if not self._rubrics_root.exists():
            return {}

        if self._rubrics_root.is_symlink():
            raise RubricPathError("The configured rubric directory must not be a symbolic link.")

        if not self._rubrics_root.is_dir():
            raise RubricPathError("The configured rubric path is not a directory.")

        discovered_paths: dict[str, Path] = {}

        candidates = sorted(
            self._rubrics_root.iterdir(),
            key=lambda path: path.name.casefold(),
        )

        for candidate in candidates:
            if candidate.name == ".gitkeep":
                continue

            if candidate.is_dir():
                continue

            if candidate.suffix.casefold() not in RUBRIC_FILE_SUFFIXES:
                continue

            self._validate_existing_rubric_path(candidate)

            rubric_name = self._validate_rubric_name(candidate.stem)
            normalized_name = rubric_name.casefold()

            if normalized_name in discovered_paths:
                existing_path = discovered_paths[normalized_name]

                raise DuplicateRubricError(
                    f"Duplicate evaluation rubric name "
                    f"'{rubric_name}' was found in "
                    f"{existing_path.name} and {candidate.name}."
                )

            discovered_paths[normalized_name] = candidate

        return discovered_paths

    def _resolve_rubrics_root(self) -> Path:
        configured_path = self._settings.EVAL_RUBRICS_DIR

        if configured_path.is_absolute():
            resolved_path = configured_path.resolve()
        else:
            resolved_path = (self._project_root / configured_path).resolve()

        self._require_within(
            resolved_path,
            self._project_root,
            "Configured rubric directory must remain inside the project.",
        )

        return resolved_path

    def _resolve_relative_rubric_path(
        self,
        relative_path: Path,
    ) -> Path:
        if relative_path.is_absolute():
            raise RubricPathError("Rubric paths must be relative to the rubric directory.")

        if ".." in relative_path.parts:
            raise RubricPathError("Rubric paths must not contain traversal segments.")

        if len(relative_path.parts) != 1:
            raise RubricPathError("Rubric files must be directly inside the rubric directory.")

        if not relative_path.name or relative_path.name in {".", ".."}:
            raise RubricPathError("Rubric path must identify a valid file.")

        if relative_path.suffix.casefold() not in RUBRIC_FILE_SUFFIXES:
            raise RubricPathError("Rubric files must use the .yaml or .yml extension.")

        self._validate_rubric_name(relative_path.stem)

        unresolved_path = self._rubrics_root / relative_path

        if self._contains_symbolic_link(unresolved_path):
            raise RubricPathError("Rubric paths must not contain symbolic links.")

        resolved_path = unresolved_path.resolve()

        self._require_within(
            resolved_path,
            self._rubrics_root,
            "Rubric path must remain inside the rubric directory.",
        )

        return resolved_path

    def _validate_existing_rubric_path(
        self,
        rubric_path: Path,
    ) -> None:
        if self._contains_symbolic_link(rubric_path):
            raise RubricPathError(
                f"Rubric paths must not contain symbolic links: {self._display_path(rubric_path)}."
            )

        resolved_path = rubric_path.resolve()

        self._require_within(
            resolved_path,
            self._rubrics_root,
            "Rubric path must remain inside the rubric directory.",
        )

        if resolved_path.parent != self._rubrics_root:
            raise RubricPathError("Rubric files must be directly inside the rubric directory.")

        if resolved_path.suffix.casefold() not in RUBRIC_FILE_SUFFIXES:
            raise RubricPathError("Rubric files must use the .yaml or .yml extension.")

        self._validate_rubric_name(resolved_path.stem)

        if not resolved_path.is_file():
            raise RubricNotFoundError(
                f"Evaluation rubric does not exist: {self._display_path(resolved_path)}."
            )

    @staticmethod
    def _validate_rubric_name(rubric_name: str) -> str:
        if not isinstance(rubric_name, str):
            raise RubricNameError("Rubric name must be a string.")

        if rubric_name != rubric_name.strip():
            raise RubricNameError("Rubric name must not contain surrounding whitespace.")

        if not RUBRIC_NAME_PATTERN.fullmatch(rubric_name):
            raise RubricNameError("Rubric name must use lowercase kebab-case.")

        return rubric_name

    @classmethod
    def _normalize_mapping(
        cls,
        value: dict[Any, Any],
    ) -> dict[str, Any]:
        normalized_mapping: dict[str, Any] = {}

        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise RubricContentError("Evaluation rubric mapping keys must be strings.")

            normalized_key = raw_key.strip()

            if not normalized_key:
                raise RubricContentError("Evaluation rubric mapping keys must not be empty.")

            if normalized_key in normalized_mapping:
                raise RubricContentError(f"Duplicate normalized rubric key: {normalized_key}.")

            normalized_mapping[normalized_key] = cls._normalize_yaml_value(raw_value)

        return normalized_mapping

    @classmethod
    def _normalize_yaml_value(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return cls._normalize_mapping(value)

        if isinstance(value, list):
            return [cls._normalize_yaml_value(item) for item in value]

        return value

    def _display_path(self, path: Path) -> str:
        resolved_path = path.resolve()

        if self._is_within(resolved_path, self._project_root):
            return resolved_path.relative_to(self._project_root).as_posix()

        return path.name

    @staticmethod
    def _contains_symbolic_link(path: Path) -> bool:
        current_path = path

        while True:
            if current_path.exists() and current_path.is_symlink():
                return True

            if current_path.parent == current_path:
                return False

            current_path = current_path.parent

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False

        return True

    @classmethod
    def _require_within(
        cls,
        path: Path,
        root: Path,
        message: str,
    ) -> None:
        if not cls._is_within(path, root):
            raise RubricPathError(message)
