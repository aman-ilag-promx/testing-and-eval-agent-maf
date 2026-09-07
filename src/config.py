"""Application configuration for the Testing and Evaluation Agent."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Validated configuration loaded from environment variables and .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        validate_default=True,
    )

    # Application
    APP_NAME: str = "Testing and Evaluation Agent"
    APP_ENV: Literal["development", "test", "staging", "production"] = "development"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Microsoft Agent Framework and Microsoft Foundry
    MAF_AUTH_MODE: Literal["azure_cli", "api_key"] = "azure_cli"
    MAF_PROJECT_ENDPOINT: str | None = None
    MAF_MODEL_NAME: str | None = None
    MAF_MODEL_API_KEY: SecretStr | None = None

    # Agent behavior
    AGENT_NAME: str = "TestingEvaluationAgent"
    AGENT_TEMPERATURE: float = Field(default=0.1, ge=0.0, le=2.0)
    AGENT_MAX_WORKFLOW_STEPS: int = Field(default=20, ge=1, le=100)

    # Human approval controls
    REQUIRE_TEST_CASE_APPROVAL: bool = True
    REQUIRE_SCRIPT_APPROVAL: bool = True
    REQUIRE_EVALUATION_APPROVAL: bool = True
    ALLOW_LIVE_TEST_EXECUTION: bool = False
    ALLOW_DESTRUCTIVE_TESTS: bool = False

    # Repository paths
    SKILLS_DIR: Path = Path("skills")
    GENERATED_SPECS_DIR: Path = Path("specs/generated")
    APPROVED_SPECS_DIR: Path = Path("specs/approved")
    GENERATED_TESTS_DIR: Path = Path("tests/generated")
    REPORTS_DIR: Path = Path("reports")
    TRACES_DIR: Path = Path("traces")
    SCREENSHOTS_DIR: Path = Path("screenshots")

    EVAL_DATASETS_DIR: Path = Path("evals/datasets")
    EVAL_RUBRICS_DIR: Path = Path("evals/rubrics")
    EVAL_BASELINES_DIR: Path = Path("evals/baselines")
    EVAL_RESULTS_DIR: Path = Path("evals/results")

    # Per-target workspace isolation
    WORKSPACES_DIR: Path = Path("workspaces")
    CONVERSATION_SESSIONS_DIR: Path = Path("workspaces/.sessions")

    # Playwright Test
    TARGET_BASE_URL: str = "http://localhost:3000"
    PLAYWRIGHT_HEADLESS: bool = True
    PLAYWRIGHT_BROWSER: Literal["chromium", "firefox", "webkit"] = "chromium"
    PLAYWRIGHT_TIMEOUT_MS: int = Field(default=30_000, ge=1)
    PLAYWRIGHT_EXPECT_TIMEOUT_MS: int = Field(default=5_000, ge=1)
    PLAYWRIGHT_RETRIES: int = Field(default=0, ge=0)
    PLAYWRIGHT_WORKERS: int = Field(default=1, ge=1)

    # Playwright MCP
    PLAYWRIGHT_MCP_ENABLED: bool = False
    PLAYWRIGHT_MCP_COMMAND: str = "npx"
    PLAYWRIGHT_MCP_ARGS: str = "@playwright/mcp@latest"
    PLAYWRIGHT_MCP_URL: str | None = None

    # GitHub MCP (read-only repository evidence)
    GITHUB_MCP_ENABLED: bool = False
    GITHUB_MCP_URL: str | None = None
    GITHUB_MCP_COMMAND: str = ""
    GITHUB_MCP_ARGS: str = ""
    GITHUB_MCP_TOKEN: SecretStr | None = None
    GITHUB_MCP_ALLOW_PRIVATE_REPOSITORIES: bool = False
    GITHUB_MCP_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0.0, le=120.0)

    # Azure DevOps MCP
    ADO_MCP_ENABLED: bool = False
    ADO_MCP_URL: str | None = None

    # Reporting and artifact retention
    SAVE_SCREENSHOTS_ON_FAILURE: bool = True
    SAVE_TRACE_ON_FAILURE: bool = True
    SAVE_VIDEO_ON_FAILURE: bool = False
    REPORT_FORMAT: Literal["json", "markdown", "both"] = "json"

    @field_validator(
        "APP_NAME",
        "AGENT_NAME",
        "PLAYWRIGHT_MCP_COMMAND",
        "PLAYWRIGHT_MCP_ARGS",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value: object) -> object:
        """Reject empty values for required text settings."""

        if isinstance(value, str) and not value.strip():
            raise ValueError("Value must not be empty.")

        return value

    @field_validator(
        "MAF_PROJECT_ENDPOINT",
        "MAF_MODEL_NAME",
        "PLAYWRIGHT_MCP_URL",
        "GITHUB_MCP_URL",
        "ADO_MCP_URL",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        """Convert empty optional strings to None."""

        if isinstance(value, str):
            normalized_value = value.strip()
            return normalized_value or None

        return value

    @field_validator("GITHUB_MCP_TOKEN", mode="before")
    @classmethod
    def normalize_github_mcp_token(cls, value: object) -> object:
        """Convert a blank hosted GitHub MCP token to a missing secret."""

        if isinstance(value, str) and not value.strip():
            return None

        return value

    @field_validator(
        "MAF_PROJECT_ENDPOINT",
        "PLAYWRIGHT_MCP_URL",
        "ADO_MCP_URL",
    )
    @classmethod
    def validate_optional_url(cls, value: str | None) -> str | None:
        """Validate configured HTTP or HTTPS endpoints."""

        if value is None:
            return None

        parsed_url = urlparse(value)

        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("Endpoint must be a valid HTTP or HTTPS URL.")

        return value.rstrip("/")

    @field_validator("GITHUB_MCP_URL")
    @classmethod
    def validate_github_mcp_url(cls, value: str | None) -> str | None:
        """Allow only GitHub's hosted HTTPS MCP endpoint for token safety."""

        if value is None:
            return None

        parsed_url = urlparse(value)
        if (
            parsed_url.scheme != "https"
            or parsed_url.netloc.casefold() != "api.githubcopilot.com"
            or not parsed_url.path.startswith("/mcp")
        ):
            raise ValueError("GITHUB_MCP_URL must be an HTTPS api.githubcopilot.com MCP endpoint.")

        return value.rstrip("/")

    @field_validator("TARGET_BASE_URL")
    @classmethod
    def validate_target_base_url(cls, value: str) -> str:
        """Validate and normalize the Playwright target URL."""

        normalized_value = value.strip()
        parsed_url = urlparse(normalized_value)

        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("TARGET_BASE_URL must be a valid HTTP or HTTPS URL.")

        return normalized_value.rstrip("/")

    @field_validator(
        "SKILLS_DIR",
        "GENERATED_SPECS_DIR",
        "APPROVED_SPECS_DIR",
        "GENERATED_TESTS_DIR",
        "REPORTS_DIR",
        "TRACES_DIR",
        "SCREENSHOTS_DIR",
        "EVAL_DATASETS_DIR",
        "EVAL_RUBRICS_DIR",
        "EVAL_BASELINES_DIR",
        "EVAL_RESULTS_DIR",
        "WORKSPACES_DIR",
        "CONVERSATION_SESSIONS_DIR",
    )
    @classmethod
    def resolve_repository_path(cls, value: Path) -> Path:
        """Resolve a configured path and ensure it remains inside the repository."""

        resolved_path = value.resolve() if value.is_absolute() else (PROJECT_ROOT / value).resolve()

        try:
            resolved_path.relative_to(PROJECT_ROOT)
        except ValueError as error:
            raise ValueError(
                f"Configured path must remain inside the project root: {value}"
            ) from error

        return resolved_path

    @model_validator(mode="after")
    def validate_authentication_configuration(self) -> Settings:
        """Validate settings required by the selected authentication mode."""

        if self.MAF_AUTH_MODE == "api_key" and self.MAF_MODEL_API_KEY is None:
            raise ValueError("MAF_MODEL_API_KEY is required when MAF_AUTH_MODE is set to api_key.")

        return self

    @model_validator(mode="after")
    def validate_mcp_configuration(self) -> Settings:
        """Validate enabled MCP integrations."""

        if self.PLAYWRIGHT_MCP_ENABLED:
            has_command = bool(self.PLAYWRIGHT_MCP_COMMAND.strip())
            has_url = self.PLAYWRIGHT_MCP_URL is not None

            if not has_command and not has_url:
                raise ValueError("Playwright MCP requires a command or URL when enabled.")

        if self.GITHUB_MCP_ENABLED and not (
            self.GITHUB_MCP_URL or self.GITHUB_MCP_COMMAND.strip()
        ):
            raise ValueError(
                "GITHUB_MCP_URL or GITHUB_MCP_COMMAND is required when GITHUB_MCP_ENABLED is true."
            )

        if self.GITHUB_MCP_ENABLED and self.GITHUB_MCP_URL and self.GITHUB_MCP_TOKEN is None:
            raise ValueError(
                "GITHUB_MCP_TOKEN is required for the hosted GitHub MCP endpoint."
            )

        if (
            self.GITHUB_MCP_ALLOW_PRIVATE_REPOSITORIES
            and self.GITHUB_MCP_TOKEN is None
        ):
            raise ValueError(
                "GITHUB_MCP_TOKEN is required when private repository access is enabled."
            )

        if self.ADO_MCP_ENABLED and self.ADO_MCP_URL is None:
            raise ValueError("ADO_MCP_URL is required when ADO_MCP_ENABLED is true.")

        return self

    @model_validator(mode="after")
    def enforce_safety_configuration(self) -> Settings:
        """Prevent unsafe execution settings."""

        if self.ALLOW_DESTRUCTIVE_TESTS and not self.ALLOW_LIVE_TEST_EXECUTION:
            raise ValueError(
                "ALLOW_DESTRUCTIVE_TESTS cannot be enabled while "
                "ALLOW_LIVE_TEST_EXECUTION is disabled."
            )

        if self.APP_ENV == "production" and self.ALLOW_DESTRUCTIVE_TESTS:
            raise ValueError("Destructive testing is not permitted in production.")

        if self.APP_ENV == "production" and not self.REQUIRE_SCRIPT_APPROVAL:
            raise ValueError("Script approval cannot be disabled in production.")

        if self.APP_ENV == "production" and not self.REQUIRE_TEST_CASE_APPROVAL:
            raise ValueError("Test-case approval cannot be disabled in production.")

        return self

    @property
    def foundry_configured(self) -> bool:
        """Return whether the minimum Foundry model settings are available."""

        return bool(self.MAF_PROJECT_ENDPOINT and self.MAF_MODEL_NAME)

    @property
    def approval_gates_enabled(self) -> bool:
        """Return whether all required approval gates are enabled."""

        return (
            self.REQUIRE_TEST_CASE_APPROVAL
            and self.REQUIRE_SCRIPT_APPROVAL
            and self.REQUIRE_EVALUATION_APPROVAL
        )

    def ensure_output_directories(self) -> None:
        """Create approved runtime output directories when missing."""

        output_directories = (
            self.GENERATED_SPECS_DIR,
            self.APPROVED_SPECS_DIR,
            self.GENERATED_TESTS_DIR,
            self.REPORTS_DIR,
            self.TRACES_DIR,
            self.SCREENSHOTS_DIR,
            self.EVAL_DATASETS_DIR,
            self.EVAL_RUBRICS_DIR,
            self.EVAL_BASELINES_DIR,
            self.EVAL_RESULTS_DIR,
            self.WORKSPACES_DIR,
            self.CONVERSATION_SESSIONS_DIR,
        )

        for directory in output_directories:
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached, validated application settings."""

    return Settings()


def clear_settings_cache() -> None:
    """Clear cached settings, primarily for tests."""

    get_settings.cache_clear()
