"""Ollama client with schema validation, retry logic, and graceful fallback.

Enforces:
- Deterministic extraction: temperature 0.0, fixed seed 42.
- Schema enforcement via Ollama format parameter.
- 1-retry self-repair on invalid JSON or Pydantic validation failures.
- Fast failure / graceful offline handling when Ollama daemon is down.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Type, TypeVar
import requests
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_TIMEOUT = 45.0

T = TypeVar("T", bound=BaseModel)

_DIGEST_CACHE: Dict[str, str] = {}


class OllamaUnavailableError(Exception):
    """Raised when Ollama daemon is unreachable."""
    pass


class OllamaGenerationError(Exception):
    """Raised when Ollama output cannot be validated after retries."""
    pass


def is_ollama_available(base_url: str = OLLAMA_BASE_URL, timeout: float = 2.0) -> bool:
    """Quickly check if the Ollama server is responding."""
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def get_model_digest(model_name: str = DEFAULT_MODEL, base_url: str = OLLAMA_BASE_URL) -> str:
    """Fetch model digest from Ollama tags for caching/versioning."""
    if model_name in _DIGEST_CACHE:
        return _DIGEST_CACHE[model_name]

    try:
        r = requests.get(f"{base_url}/api/tags", timeout=5.0)
        if r.status_code == 200:
            for m in r.json().get("models", []):
                if m.get("name") == model_name or m.get("model") == model_name:
                    digest = m.get("digest") or "unknown"
                    _DIGEST_CACHE[model_name] = digest
                    return digest
    except Exception as exc:
        logger.debug("Could not fetch digest for %s: %s", model_name, exc)

    return "unknown"


def call_structured_ollama(
    messages: List[Dict[str, str]],
    response_model: Type[T],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
    seed: int = 42,
    timeout: float = DEFAULT_TIMEOUT,
    base_url: str = OLLAMA_BASE_URL,
    max_retries: int = 1,
) -> T:
    """Call Ollama with JSON schema enforcement and validate with Pydantic.

    Retries once on JSON/schema mismatch by feeding error context back to model.
    """
    if not is_ollama_available(base_url=base_url):
        raise OllamaUnavailableError(f"Ollama server not reachable at {base_url}")

    schema = response_model.model_json_schema()
    current_messages = list(messages)

    for attempt in range(max_retries + 1):
        payload = {
            "model": model,
            "messages": current_messages,
            "format": schema,
            "stream": False,
            "options": {
                "temperature": temperature,
                "seed": seed,
            },
        }

        try:
            resp = requests.post(
                f"{base_url}/api/chat",
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            content = resp.json().get("message", {}).get("content", "")
        except requests.exceptions.RequestException as exc:
            if attempt == max_retries:
                raise OllamaUnavailableError(f"Ollama chat call failed: {exc}") from exc
            logger.warning("Ollama call failed (attempt %d): %s. Retrying...", attempt + 1, exc)
            continue

        # Try parsing JSON
        try:
            parsed_json = json.loads(content)
        except json.JSONDecodeError as jde:
            if attempt < max_retries:
                logger.warning("Invalid JSON returned by Ollama on attempt %d: %s. Retrying with error feedback...", attempt + 1, jde)
                current_messages.append({"role": "assistant", "content": content})
                current_messages.append({
                    "role": "user",
                    "content": f"Your response was invalid JSON: {jde}. Return ONLY valid JSON strictly matching the schema."
                })
                continue
            raise OllamaGenerationError(f"Ollama returned unparseable JSON after retries: {content[:200]}") from jde

        # Try validating with Pydantic
        try:
            validated = response_model.model_validate(parsed_json)
            return validated
        except ValidationError as ve:
            if attempt < max_retries:
                logger.warning("Pydantic validation failed on attempt %d: %s. Retrying with error feedback...", attempt + 1, ve)
                current_messages.append({"role": "assistant", "content": content})
                current_messages.append({
                    "role": "user",
                    "content": f"Your JSON did not validate against the required schema: {ve}. Please fix and return compliant JSON."
                })
                continue
            raise OllamaGenerationError(f"Ollama response failed Pydantic validation: {ve}") from ve

    raise OllamaGenerationError("Exhausted retries without valid output.")
