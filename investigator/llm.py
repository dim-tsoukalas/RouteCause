"""LLM backend abstraction.

Mirrors K8sGPT's `IAI` interface (Configure / GetCompletion / GetName / Close).
Detection and citation retrieval never require an LLM; the LLM is *enrichment*.
Two backends ship:

* `NoOpBackend`  — deterministic, offline. Used for tests and for running the
  whole pipeline with no API key. It does not fabricate: it simply stitches the
  already-grounded findings and numbered sources into prose.
* `LiteLLMBackend` — real completions via LiteLLM (OpenAI/Anthropic/Ollama/…),
  activated only when a key/model is configured. Import is guarded so the
  scaffold runs even if `litellm` isn't installed.
"""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMBackend(Protocol):
    def complete(self, prompt: str) -> str: ...
    def name(self) -> str: ...


class NoOpBackend:
    """Offline backend. Echoes a deterministic, citation-preserving summary.

    It is intentionally *not* generative: the pipeline stays fully grounded and
    testable without a network call. When the user adds a real key they swap in
    LiteLLMBackend and get natural-language narration over the same sources.
    """

    def complete(self, prompt: str) -> str:
        return (
            "[no-LLM mode] The structured findings and numbered sources below "
            "are shown verbatim. Configure an LLM backend (e.g. "
            "INVESTIGATOR_MODEL=gpt-4o-mini with an API key) for natural-language "
            "narration that cites these same sources.\n\n" + prompt
        )

    def name(self) -> str:
        return "noop"


class LiteLLMBackend:
    """Real completions via LiteLLM. Model string comes from INVESTIGATOR_MODEL
    (e.g. 'gpt-4o-mini', 'claude-3-5-sonnet-latest', 'ollama/llama3.1')."""

    def __init__(self, model: str | None = None, temperature: float = 0.0):
        self.model = model or os.environ.get("INVESTIGATOR_MODEL", "gpt-4o-mini")
        self.temperature = temperature

    def complete(self, prompt: str) -> str:
        try:
            import litellm  # guarded: only needed for real completions
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "litellm is not installed. `pip install litellm` or use the "
                "default no-LLM mode."
            ) from exc
        resp = litellm.completion(
            model=self.model,
            temperature=self.temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp["choices"][0]["message"]["content"]

    def name(self) -> str:
        return self.model


def default_backend() -> LLMBackend:
    """Pick a backend from the environment.

    Uses LiteLLM if INVESTIGATOR_MODEL is set *and* litellm is importable;
    otherwise falls back to the offline NoOp backend.
    """
    if os.environ.get("INVESTIGATOR_MODEL"):
        try:
            import litellm  # noqa: F401
            return LiteLLMBackend()
        except ImportError:
            pass
    return NoOpBackend()
