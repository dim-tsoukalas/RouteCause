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


class InstrumentedBackend:
    """Wraps any backend to emit one tracing span per completion (model, prompt
    size, latency, completion size). Transparent: same `complete`/`name`
    contract, so callers and `isinstance` checks on the *protocol* are
    unaffected. Only applied when tracing is enabled (see
    investigator/observability.py); otherwise `default_backend` returns the raw
    backend and this class is never in the path."""

    def __init__(self, inner: LLMBackend):
        self._inner = inner

    def complete(self, prompt: str) -> str:
        from investigator.observability import set_attribute, span

        with span("llm.complete", **{"llm.model": self._inner.name(), "llm.prompt_chars": len(prompt)}) as s:
            output = self._inner.complete(prompt)
            set_attribute(s, "llm.completion_chars", len(output))
            return output

    def name(self) -> str:
        return self._inner.name()


def default_backend() -> LLMBackend:
    """Pick a backend from the environment.

    Uses LiteLLM if INVESTIGATOR_MODEL is set *and* litellm is importable;
    otherwise falls back to the offline NoOp backend. When tracing is enabled
    the chosen backend is wrapped in InstrumentedBackend.
    """
    backend: LLMBackend = NoOpBackend()
    if os.environ.get("INVESTIGATOR_MODEL"):
        try:
            import litellm  # noqa: F401
            backend = LiteLLMBackend()
        except ImportError:
            pass

    from investigator.observability import tracing_enabled

    return InstrumentedBackend(backend) if tracing_enabled() else backend
