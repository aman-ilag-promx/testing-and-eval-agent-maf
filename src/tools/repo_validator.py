"""Untrusted repository structure validation and safe command discovery.

Security rules enforced here:
- No shell=True
- No shell string commands
- All subprocess args are lists
- Repository content is treated as untrusted input
- Commands are never executed automatically; discovery only
- Execution requires explicit approval via the approval workflow
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models.common import ErrorDetail, OperationResult, WarningDetail
from src.models.enums import FailureSource

# Allowed manifest and config filenames checked during validation
_SKILL_FILENAME = "SKILL.md"
_MCP_CONFIG_FILENAMES = frozenset({"mcp.json", ".mcp.json", "mcp-config.json"})
_PACKAGE_FILENAMES = frozenset({"package.json", "pyproject.toml", "setup.cfg", "setup.py"})
_EXTENSION_MANIFEST_FILENAMES = frozenset({"extension.vsixmanifest", "package.json"})

# Commands that are permitted to be surfaced for human approval (discovery only, never auto-run)
_DISCOVERABLE_SCRIPT_KEYS = frozenset({
    "build",
    "lint",
    "test",
    "typecheck",
    "type-check",
    "check",
    "compile",
    "format",
    "validate",
})

_MAX_FILE_READ_BYTES = 512 * 1024  # 512 KB


class RepoValidationError(ValueError):
    """Raised when repository validation cannot proceed."""


class RepoValidator:
    """Validate a local repository structure without executing any commands."""

    def validate(self, repo_path: Path) -> OperationResult:
        """Run all structure checks and return a structured result."""
        errors: list[ErrorDetail] = []
        warnings: list[WarningDetail] = []
        metadata: dict[str, Any] = {}

        resolved = self._resolve_safe_path(repo_path, errors)
        if resolved is None:
            return OperationResult(success=False, message="Repository path validation failed.", errors=errors)

        # Basic existence check
        if not resolved.is_dir():
            errors.append(self._error("REPO_NOT_A_DIRECTORY", f"Path is not a directory: {resolved}"))
            return OperationResult(success=False, message="Repository path does not exist.", errors=errors)

        metadata["resolved_path"] = resolved.as_posix()
        metadata["structure"] = self._check_structure(resolved, warnings)
        metadata["skill_files"] = self._check_skill_files(resolved, warnings)
        metadata["mcp_config"] = self._check_mcp_config(resolved, warnings)
        metadata["packages"] = self._check_packages(resolved, warnings)
        metadata["discoverable_commands"] = self._discover_commands(resolved, warnings)
        metadata["extension_manifest"] = self._check_extension_manifest(resolved, warnings)

        return OperationResult(
            success=True,
            message="Repository structure validated. No commands were executed.",
            errors=errors,
            warnings=warnings,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Individual checks — read-only filesystem operations only
    # ------------------------------------------------------------------

    def _check_structure(self, root: Path, warnings: list[WarningDetail]) -> dict[str, Any]:
        """Enumerate top-level entries without reading file contents."""
        entries: list[str] = []
        try:
            for entry in sorted(root.iterdir()):
                entries.append(entry.name + ("/" if entry.is_dir() else ""))
        except PermissionError:
            warnings.append(self._warning("REPO_PERMISSION_ERROR", "Could not list repository root."))
        return {"entries": entries, "entry_count": len(entries)}

    def _check_skill_files(self, root: Path, warnings: list[WarningDetail]) -> list[str]:
        """Find all SKILL.md files within the repository tree."""
        found: list[str] = []
        try:
            for skill_file in root.rglob(_SKILL_FILENAME):
                if self._is_safe_descendant(skill_file, root):
                    found.append(skill_file.relative_to(root).as_posix())
        except PermissionError:
            warnings.append(self._warning("SKILL_SCAN_PERMISSION_ERROR", "Could not scan for skill files."))
        return found

    def _check_mcp_config(self, root: Path, warnings: list[WarningDetail]) -> dict[str, Any]:
        """Locate MCP configuration files without executing them."""
        found: dict[str, bool] = {}
        for name in _MCP_CONFIG_FILENAMES:
            candidate = root / name
            found[name] = candidate.is_file() and self._is_safe_descendant(candidate, root)
        return found

    def _check_packages(self, root: Path, warnings: list[WarningDetail]) -> dict[str, bool]:
        """Detect the presence of known package manifest files."""
        result: dict[str, bool] = {}
        for name in _PACKAGE_FILENAMES:
            candidate = root / name
            result[name] = candidate.is_file() and self._is_safe_descendant(candidate, root)
        return result

    def _check_extension_manifest(self, root: Path, warnings: list[WarningDetail]) -> dict[str, Any]:
        """Check for VS Code extension manifest indicators."""
        has_vsix = (root / "extension.vsixmanifest").is_file()
        has_package_json = (root / "package.json").is_file()
        is_vscode_extension = False

        if has_package_json:
            pkg = self._safe_read_json(root / "package.json", warnings)
            if pkg is not None and isinstance(pkg, dict):
                engines = pkg.get("engines", {})
                if isinstance(engines, dict) and "vscode" in engines:
                    is_vscode_extension = True

        return {
            "has_vsixmanifest": has_vsix,
            "has_package_json": has_package_json,
            "is_vscode_extension": is_vscode_extension,
        }

    def _discover_commands(self, root: Path, warnings: list[WarningDetail]) -> dict[str, Any]:
        """Discover npm/yarn scripts and pyproject tasks without running them.

        Returns discoverable command names only. No command is executed here.
        Human approval is required before any command can run.
        """
        discovered: dict[str, str] = {}

        # npm/yarn scripts from package.json
        package_json = root / "package.json"
        if package_json.is_file() and self._is_safe_descendant(package_json, root):
            pkg = self._safe_read_json(package_json, warnings)
            if pkg is not None and isinstance(pkg, dict):
                scripts = pkg.get("scripts", {})
                if isinstance(scripts, dict):
                    for key, cmd in scripts.items():
                        if isinstance(key, str) and key.lower() in _DISCOVERABLE_SCRIPT_KEYS:
                            if isinstance(cmd, str):
                                discovered[f"npm:{key}"] = cmd[:200]

        # pyproject.toml [tool.taskipy] or [tool.poe.tasks]
        pyproject = root / "pyproject.toml"
        if pyproject.is_file() and self._is_safe_descendant(pyproject, root):
            warnings.append(self._warning(
                "PYPROJECT_DISCOVERED",
                "pyproject.toml detected. Task commands must be approved before execution.",
            ))

        return {
            "commands": discovered,
            "approval_required": True,
            "note": "These commands are for human review only. None have been executed.",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_safe_path(path: Path, errors: list[ErrorDetail]) -> Path | None:
        """Resolve the path and reject symlinks, relative escapes, and non-existent paths."""
        try:
            resolved = path.resolve(strict=False)
        except (OSError, ValueError) as exc:
            errors.append(RepoValidator._error("PATH_RESOLUTION_FAILED", str(exc)))
            return None

        if ".." in path.parts:
            errors.append(RepoValidator._error("PATH_TRAVERSAL_REJECTED", "Path contains parent-directory traversal."))
            return None

        return resolved

    @staticmethod
    def _is_safe_descendant(path: Path, root: Path) -> bool:
        """Return True only if path is strictly inside root (no traversal)."""
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    @staticmethod
    def _safe_read_json(path: Path, warnings: list[WarningDetail]) -> Any | None:
        """Read and parse a JSON file with size and content guardrails."""
        try:
            size = path.stat().st_size
            if size > _MAX_FILE_READ_BYTES:
                warnings.append(RepoValidator._warning(
                    "FILE_TOO_LARGE_TO_PARSE",
                    f"{path.name} exceeds size limit ({size} bytes); skipped.",
                ))
                return None
            raw = path.read_text(encoding="utf-8", errors="replace")
            return json.loads(raw)
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _error(code: str, message: str) -> ErrorDetail:
        return ErrorDetail(
            code=code,
            message=message,
            failure_source=FailureSource.TOOL,
            workflow_step="repo_validator",
        )

    @staticmethod
    def _warning(code: str, message: str) -> WarningDetail:
        return WarningDetail(code=code, message=message)
