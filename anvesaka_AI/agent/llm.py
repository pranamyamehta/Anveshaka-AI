"""Ollama client wrapper: model choice, temperature 0, JSON output, retries.

Owner: Member 2

Guarantees:
- temperature=0  (deterministic / reproducible)
- format="json"  (structured output from Ollama)
- one automatic retry on JSON-decode or schema-validation failure
- raises OllamaError (not raw httpx/json errors) so callers have one
  exception type to catch
- Never calls a cloud endpoint; host is always read from config.settings
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Type

import httpx
from pydantic import BaseModel, ValidationError

from anvesaka_AI.config import settings

logger = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Raised when Ollama returns an error or produces invalid output after retries."""


def _post(payload: dict[str, Any], timeout: float = 120.0) -> dict:
    """Low-level POST to /api/chat with a single httpx call."""
    url = f"{settings.ollama_host.rstrip('/')}/api/chat"
    try:
        resp = httpx.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise OllamaError(f"Ollama HTTP error: {exc}") from exc


def _extract_content(response: dict) -> str:
    """Pull the assistant message content from the /api/chat response."""
    try:
        return response["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise OllamaError(f"Unexpected Ollama response shape: {response}") from exc


def chat(
    messages: list[dict[str, str]],
    *,
    tools: Optional[list[dict]] = None,
    timeout: float = 120.0,
) -> str:
    """Send a chat request to Ollama and return the raw content string.

    Args:
        messages: List of {"role": ..., "content": ...} dicts.
        tools: Optional Ollama tool-calling schemas.
        timeout: HTTP timeout in seconds.

    Returns:
        Raw content string from the assistant message.

    Raises:
        OllamaError: on network error or unexpected response shape.
    """
    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0},
        "format": "json",
    }
    if tools:
        payload["tools"] = tools

    response = _post(payload, timeout=timeout)
    return _extract_content(response)


def chat_structured(
    messages: list[dict[str, str]],
    schema: Type[BaseModel],
    *,
    tools: Optional[list[dict]] = None,
    timeout: float = 120.0,
    retries: int = 1,
) -> BaseModel:
    """Send a chat request and parse the response into *schema*.

    Retries once on JSON-decode or Pydantic validation failure.  If both
    attempts fail, raises OllamaError with a description of what went wrong.

    Args:
        messages: Conversation history.
        schema: Pydantic model class to validate against.
        tools: Optional tool schemas.
        timeout: HTTP timeout in seconds.
        retries: Number of additional attempts after the first (default 1).

    Returns:
        Validated instance of *schema*.

    Raises:
        OllamaError: when all attempts fail.
    """
    last_error: Exception = RuntimeError("no attempts made")
    for attempt in range(retries + 1):
        try:
            raw = chat(messages, tools=tools, timeout=timeout)
            data = json.loads(raw)
            return schema.model_validate(data)
        except json.JSONDecodeError as exc:
            last_error = exc
            logger.warning("Ollama JSON decode error (attempt %d): %s", attempt + 1, exc)
        except ValidationError as exc:
            last_error = exc
            logger.warning("Ollama schema validation error (attempt %d): %s", attempt + 1, exc)
        except OllamaError:
            raise  # network errors are not retried
    raise OllamaError(
        f"Ollama failed to produce valid {schema.__name__} after {retries + 1} attempt(s): {last_error}"
    )


def is_available() -> bool:
    """Return True if the Ollama server responds to a health check (no model required)."""
    try:
        url = f"{settings.ollama_host.rstrip('/')}/api/tags"
        httpx.get(url, timeout=5.0).raise_for_status()
        return True
    except Exception:
        return False
