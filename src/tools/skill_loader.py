"""Safe loading and validation of repository skill instruction assets."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from src.config import PROJECT_ROOT, Settings, get_settings
from src.models.skills import SkillDefinition

_SKILL_FILE_NAME = "SKILL.md"
_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillLoaderError(ValueError):
    """Base error raised for invalid skill-loader operations."""


class SkillNameError(SkillLoaderError):
    """Raised when a skill name is invalid."""


class SkillPathError(SkillLoaderError):
    """Raised when a skill path escapes or violates the skills directory."""


class SkillNotFoundError(SkillLoaderError):
    """Raised when a requested skill instruction asset does not exist."""


class SkillContentError(SkillLoaderError):
    """Raised when a skill instruction asset contains invalid content."""


class DuplicateSkillError(SkillLoaderError):
    """Raised when duplicate skill names are discovered."""


class SkillDefinitionMismatchError(SkillLoaderError):
    """Raised when a structured definition does not match its skill asset."""


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    """Immutable skill instruction asset loaded from the repository."""

    name: str
    path: Path
    content: str
    content_sha256: str

    def __post_init__(self) -> None:
        """Validate the immutable loaded-skill representation."""
        if not _SKILL_NAME_PATTERN.fullmatch(self.name):
            raise SkillNameError("Loaded skill name must use lowercase kebab-case.")

        if self.path.is_absolute():
            raise SkillPathError("Loaded skill path must be repository-relative.")

        if not self.content.strip():
            raise SkillContentError("Loaded skill content must not be empty.")

        expected_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()

        if self.content_sha256 != expected_hash:
            raise SkillContentError("Loaded skill content hash does not match its content.")


class SkillLoader:
    """Load skill instruction assets from the configured skills directory."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the loader with validated application settings."""
        self._settings = settings or get_settings()
        self._project_root = PROJECT_ROOT.resolve()
        self._skills_root = self._resolve_skills_root()

    @property
    def skills_root(self) -> Path:
        """Return the resolved configured skills directory."""
        return self._skills_root

    def list_skill_names(self) -> list[str]:
        """Return valid skill names in deterministic sorted order."""
        if not self._skills_root.exists():
            return []

        if not self._skills_root.is_dir():
            raise SkillPathError("The configured skills path is not a directory.")

        discovered_names: list[str] = []
        normalized_names: set[str] = set()

        for candidate in self._skills_root.iterdir():
            if not candidate.is_dir():
                continue

            if candidate.is_symlink():
                raise SkillPathError(
                    f"Skill directories must not be symbolic links: {candidate.name}."
                )

            skill_name = candidate.name
            self._validate_skill_name(skill_name)

            instruction_path = candidate / _SKILL_FILE_NAME
            if not instruction_path.is_file():
                continue

            normalized_name = skill_name.casefold()
            if normalized_name in normalized_names:
                raise DuplicateSkillError(f"Duplicate skill name discovered: {skill_name}.")

            normalized_names.add(normalized_name)
            discovered_names.append(skill_name)

        return sorted(discovered_names)

    def load(self, skill_name: str) -> LoadedSkill:
        """Load one validated skill instruction asset."""
        normalized_name = self._validate_skill_name(skill_name)
        instruction_path = self._resolve_instruction_path(normalized_name)

        if not instruction_path.exists():
            raise SkillNotFoundError(
                f"Skill instruction file does not exist: {normalized_name}/{_SKILL_FILE_NAME}."
            )

        if instruction_path.is_symlink():
            raise SkillPathError("Skill instruction files must not be symbolic links.")

        if not instruction_path.is_file():
            raise SkillNotFoundError(
                f"Skill instruction path is not a file: {normalized_name}/{_SKILL_FILE_NAME}."
            )

        try:
            raw_content = instruction_path.read_bytes()
        except OSError as error:
            raise SkillLoaderError(
                f"Unable to read skill instruction file: {normalized_name}/{_SKILL_FILE_NAME}."
            ) from error

        try:
            content = raw_content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SkillContentError(
                f"Skill instruction file is not valid UTF-8: {normalized_name}/{_SKILL_FILE_NAME}."
            ) from error

        if not content.strip():
            raise SkillContentError(
                f"Skill instruction file is empty: {normalized_name}/{_SKILL_FILE_NAME}."
            )

        repository_relative_path = instruction_path.relative_to(self._project_root)

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        return LoadedSkill(
            name=normalized_name,
            path=repository_relative_path,
            content=content,
            content_sha256=content_hash,
        )

    def load_all(self) -> list[LoadedSkill]:
        """Load all discovered skills in deterministic order."""
        return [self.load(skill_name) for skill_name in self.list_skill_names()]

    def validate_definition(
        self,
        definition: SkillDefinition,
    ) -> LoadedSkill:
        """Validate a structured definition against its instruction asset."""
        loaded_skill = self.load(definition.name)

        if definition.name != loaded_skill.name:
            raise SkillDefinitionMismatchError(
                "Skill definition name does not match the skill directory."
            )

        if definition.instructions.strip() != loaded_skill.content.strip():
            raise SkillDefinitionMismatchError(
                "Skill definition instructions do not match SKILL.md."
            )

        return loaded_skill

    def _resolve_skills_root(self) -> Path:
        configured_path = self._settings.SKILLS_DIR

        if configured_path.is_absolute():
            resolved_path = configured_path.resolve()
        else:
            resolved_path = (self._project_root / configured_path).resolve()

        self._require_within(resolved_path, self._project_root)
        return resolved_path

    def _resolve_instruction_path(self, skill_name: str) -> Path:
        skill_directory = (self._skills_root / skill_name).resolve()

        self._require_within(skill_directory, self._skills_root)

        if skill_directory.exists() and skill_directory.is_symlink():
            raise SkillPathError("Skill directories must not be symbolic links.")

        instruction_path = (skill_directory / _SKILL_FILE_NAME).resolve()

        self._require_within(instruction_path, skill_directory)
        self._require_within(instruction_path, self._skills_root)

        return instruction_path

    @staticmethod
    def _validate_skill_name(skill_name: str) -> str:
        if not isinstance(skill_name, str):
            raise SkillNameError("Skill name must be a string.")

        normalized_name = skill_name.strip()

        if normalized_name != skill_name:
            raise SkillNameError("Skill name must not contain surrounding whitespace.")

        if not _SKILL_NAME_PATTERN.fullmatch(normalized_name):
            raise SkillNameError("Skill name must use lowercase kebab-case.")

        return normalized_name

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False

        return True

    @classmethod
    def _require_within(cls, path: Path, root: Path) -> None:
        if not cls._is_within(path, root):
            raise SkillPathError(f"Path must remain inside the configured directory: {path}.")
