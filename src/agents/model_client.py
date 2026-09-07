"""Model-client adapters for deterministic and Foundry-backed prompting."""

from __future__ import annotations

import json
from typing import Any, Protocol
from urllib import error as url_error
from urllib import request as url_request
from urllib.parse import urlparse

from azure.identity import AzureCliCredential
from pydantic import Field, field_validator

from src.config import Settings, get_settings
from src.models.common import AgentBaseModel


class ModelInvocationError(RuntimeError):
    """Raised when a model request cannot be completed."""


class ModelRequest(AgentBaseModel):
    """Validated request payload for model invocation."""

    user_prompt: str = Field(min_length=1, max_length=50_000)
    system_prompt: str | None = Field(default=None, max_length=20_000)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=1200, ge=1, le=16_384)

    @field_validator("user_prompt", "system_prompt", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class ModelResponse(AgentBaseModel):
    """Structured response from a model invocation."""

    content: str = Field(min_length=1)
    model_name: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=100)
    raw: dict[str, Any] = Field(default_factory=dict)


class ModelClient(Protocol):
    """Protocol implemented by all runtime model clients."""

    def invoke(self, request: ModelRequest) -> ModelResponse:
        """Invoke a model and return structured response text."""

    def invoke_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> ModelResponse:
        """Invoke with a full conversation message list."""


class DeterministicModelClient:
    """Offline deterministic fallback model client."""

    def __init__(self, model_name: str = "deterministic-local") -> None:
        """Initialize deterministic client metadata."""

        self._model_name = model_name

    def invoke(self, request: ModelRequest) -> ModelResponse:
        """Return deterministic text that echoes prompt metadata."""

        prefix = (
            "Deterministic fallback response. "
            "Configure Foundry endpoint and credentials to use live model inference."
        )
        content = (
            f"{prefix}\n\n"
            f"System prompt present: {'yes' if request.system_prompt else 'no'}\n"
            f"Prompt length: {len(request.user_prompt)}"
        )

        return ModelResponse(
            content=content,
            model_name=self._model_name,
            provider="deterministic",
            raw={
                "temperature": request.temperature,
                "max_output_tokens": request.max_output_tokens,
            },
        )

    def invoke_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> ModelResponse:
        """Fallback: concatenate last few messages and call invoke."""
        tail = messages[-6:]
        combined = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in tail)
        return self.invoke(ModelRequest(
            user_prompt=combined or "conversation",
            system_prompt=system_prompt,
        ))


class FoundryModelClient:
    """Minimal OpenAI-compatible Foundry REST model client."""

    _API_VERSION = "2024-12-01-preview"
    _TOKEN_SCOPE = "https://ai.azure.com/.default"

    def __init__(
        self,
        settings: Settings | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize Foundry settings and request timeout."""

        self._settings = settings or get_settings()
        self._timeout_seconds = timeout_seconds

        if not self._settings.foundry_configured:
            raise ModelInvocationError(
                "Foundry is not configured. Set MAF_PROJECT_ENDPOINT and MAF_MODEL_NAME."
            )

    def invoke(self, request: ModelRequest) -> ModelResponse:
        """Invoke configured Foundry deployment through REST."""

        endpoint = self._settings.MAF_PROJECT_ENDPOINT
        model_name = self._settings.MAF_MODEL_NAME
        if endpoint is None or model_name is None:
            raise ModelInvocationError(
                "Foundry endpoint or model name is missing from configuration."
            )

        parsed_ep = urlparse(endpoint)
        base_url = f"{parsed_ep.scheme}://{parsed_ep.netloc}"
        url = (
            f"{base_url}/openai/deployments/{model_name}/chat/completions"
            f"?api-version={self._API_VERSION}"
        )
        payload = {
            "messages": self._build_messages(request),
            "max_completion_tokens": request.max_output_tokens,
        }
        body = json.dumps(payload).encode("utf-8")

        request_headers = self._build_headers()
        http_request = url_request.Request(
            url=url,
            data=body,
            headers=request_headers,
            method="POST",
        )

        try:
            with url_request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except url_error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise ModelInvocationError(f"Foundry HTTP error {error.code}: {error_body}") from error
        except url_error.URLError as error:
            raise ModelInvocationError(
                f"Unable to reach Foundry endpoint: {error.reason}"
            ) from error

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as error:
            raise ModelInvocationError("Foundry response was not valid JSON.") from error

        content = self._extract_content(parsed)

        return ModelResponse(
            content=content,
            model_name=model_name,
            provider="foundry",
            raw=parsed,
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }

        if self._settings.MAF_AUTH_MODE == "api_key":
            api_key_secret = self._settings.MAF_MODEL_API_KEY
            if api_key_secret is None:
                raise ModelInvocationError(
                    "MAF_MODEL_API_KEY is required when MAF_AUTH_MODE is api_key."
                )
            headers["api-key"] = api_key_secret.get_secret_value()
            return headers

        credential = AzureCliCredential()
        token = credential.get_token(self._TOKEN_SCOPE)
        headers["Authorization"] = f"Bearer {token.token}"
        return headers

    def invoke_chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> ModelResponse:
        """Invoke Foundry with a full conversation message history."""
        endpoint = self._settings.MAF_PROJECT_ENDPOINT
        model_name = self._settings.MAF_MODEL_NAME
        if endpoint is None or model_name is None:
            raise ModelInvocationError("Foundry endpoint or model name is missing.")

        parsed_ep = urlparse(endpoint)
        base_url = f"{parsed_ep.scheme}://{parsed_ep.netloc}"
        url = (
            f"{base_url}/openai/deployments/{model_name}/chat/completions"
            f"?api-version={self._API_VERSION}"
        )

        all_messages: list[dict[str, str]] = []
        if system_prompt:
            all_messages.append({"role": "system", "content": system_prompt})
        all_messages.extend(messages)

        payload = {
            "messages": all_messages,
            "max_completion_tokens": 8000,
        }
        body = json.dumps(payload).encode("utf-8")
        request_headers = self._build_headers()
        http_request = url_request.Request(url=url, data=body, headers=request_headers, method="POST")

        try:
            with url_request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except url_error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")
            raise ModelInvocationError(f"Foundry HTTP error {error.code}: {error_body}") from error
        except url_error.URLError as error:
            raise ModelInvocationError(f"Unable to reach Foundry endpoint: {error.reason}") from error

        try:
            parsed_resp = json.loads(raw_body)
        except json.JSONDecodeError as error:
            raise ModelInvocationError("Foundry response was not valid JSON.") from error

        content = self._extract_content(parsed_resp)
        return ModelResponse(
            content=content,
            model_name=model_name,
            provider="foundry",
            raw=parsed_resp,
        )

    @staticmethod
    def _build_messages(request: ModelRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.user_prompt})
        return messages

    @staticmethod
    def _extract_content(payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelInvocationError("Foundry response did not contain choices.")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ModelInvocationError("Foundry response choice did not contain a message.")

        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

        raise ModelInvocationError("Foundry response message content is empty.")


def create_model_client(
    settings: Settings | None = None,
    *,
    force_deterministic: bool = False,
) -> ModelClient:
    """Create a runtime model client with deterministic fallback."""

    resolved_settings = settings or get_settings()

    if force_deterministic:
        return DeterministicModelClient()

    if not resolved_settings.foundry_configured:
        return DeterministicModelClient()

    if resolved_settings.MAF_AUTH_MODE == "api_key" and resolved_settings.MAF_MODEL_API_KEY is None:
        return DeterministicModelClient()

    try:
        return FoundryModelClient(settings=resolved_settings)
    except ModelInvocationError:
        return DeterministicModelClient()
