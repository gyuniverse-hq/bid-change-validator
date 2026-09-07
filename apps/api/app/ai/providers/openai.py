"""OpenAI Structured Output adapter for qualification extraction.

This is intentionally isolated under `app.ai.providers` so the Backend team's
routers/services/settings remain untouched. The SDK import is lazy: importing the
AI package does not require `openai` to be installed until an actual model call is
made.

The adapter matches `StructuredExtractor` from requirement_extraction.py:

    extractor(system_prompt, user_body, json_schema) -> dict

It uses Chat Completions Structured Outputs because that is the same contract used
by the current LLM/RAG PoC. A future migration to another OpenAI endpoint only
needs to change this provider, not the analysis pipeline.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

ClientFactory = Callable[[str], Any]


def _default_client_factory(api_key: str) -> Any:
    try:
        from openai import OpenAI
    except ImportError as error:  # pragma: no cover - depends on runtime extras
        raise RuntimeError(
            "OpenAI provider requires the optional `openai` package at runtime"
        ) from error
    return OpenAI(api_key=api_key)


class OpenAIStructuredExtractor:
    """Callable adapter that returns strict JSON-schema model output as a dict."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL_DEFAULT") or "gpt-5.6-luna"
        self._client_factory = client_factory or _default_client_factory
        self._client: Any | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self) -> Any:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if self._client is None:
            self._client = self._client_factory(self.api_key)
        return self._client

    def __call__(
        self,
        system_prompt: str,
        user_body: str,
        json_schema: dict[str, Any],
    ) -> dict[str, Any]:
        if "schema" not in json_schema:
            raise ValueError("json_schema must contain a `schema` field")

        response = self._get_client().chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_body},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": json_schema.get("name", "result"),
                    "strict": True,
                    "schema": json_schema["schema"],
                },
            },
        )

        choices = getattr(response, "choices", None)
        if not choices:
            raise RuntimeError("OpenAI response did not contain any choices")

        message = choices[0].message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise RuntimeError("OpenAI structured extraction was refused")

        content = getattr(message, "content", None)
        if not content:
            raise RuntimeError("OpenAI structured extraction returned empty content")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                "OpenAI structured extraction returned invalid JSON content"
            ) from error

        if not isinstance(parsed, dict):
            raise RuntimeError("OpenAI structured extraction must return a JSON object")
        return parsed
