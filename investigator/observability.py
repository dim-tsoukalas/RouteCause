"""Optional, dependency-light tracing for the LLM/agent path.

Off by default — `span(...)` is a no-op unless `INVESTIGATOR_TRACING` is set,
so nothing here touches the deterministic detection path or changes any output.

Enable it with one env var:

    INVESTIGATOR_TRACING=console   # human-readable span lines on stderr
    INVESTIGATOR_TRACING=otlp      # export to any OpenTelemetry collector
                                   # (Langfuse, Arize Phoenix, Jaeger, Grafana
                                   # Tempo, …) via OTEL_EXPORTER_OTLP_ENDPOINT

`console` works with zero extra dependencies. `otlp` (and OpenTelemetry-backed
`console`) needs the `obs` extra: `pip install -e ".[obs]"`. If OpenTelemetry
isn't installed, any setting falls back to the dependency-free stderr tracer,
so enabling tracing can never crash the app.

What gets traced: one span per investigation / ask (`engine.investigate`,
`engine.ask`) and one child span per real LLM completion (`llm.complete`, with
model, prompt size, latency, completion size). That's the layer worth watching
in production — retrieval breadth and model latency/verbosity per request.
"""
from __future__ import annotations

import json
import os
import sys
import time
from contextlib import contextmanager

SERVICE_NAME = "routecause"
TRACER_NAME = "routecause"

_state: dict = {"resolved": False, "enabled": False, "mode": None, "configured": False}


def _resolve() -> None:
    if _state["resolved"]:
        return
    setting = os.environ.get("INVESTIGATOR_TRACING", "").strip().lower()
    _state["resolved"] = True
    if setting in ("", "0", "off", "false", "none"):
        _state["enabled"] = False
        return
    _state["enabled"] = True
    # Prefer real OpenTelemetry when available; otherwise a stderr fallback so
    # turning tracing on never fails for a missing dependency.
    try:
        import opentelemetry.trace  # noqa: F401

        _state["mode"] = "otel"
    except Exception:
        _state["mode"] = "stderr"


def tracing_enabled() -> bool:
    _resolve()
    return _state["enabled"]


def configure_tracing() -> None:
    """Wire up an exporter. Call once at process start (the API server does this
    in its lifespan). Safe to call when tracing is disabled or OTel is absent."""
    _resolve()
    if not _state["enabled"] or _state["mode"] != "otel" or _state["configured"]:
        return
    _state["configured"] = True

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    setting = os.environ.get("INVESTIGATOR_TRACING", "").strip().lower()
    if setting == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter()  # honours OTEL_EXPORTER_OTLP_ENDPOINT / headers
    else:
        exporter = ConsoleSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


@contextmanager
def span(name: str, **attributes):
    """Start a span named `name`. Yields a handle usable with `set_attribute`.
    A no-op (yields None) when tracing is disabled."""
    _resolve()
    if not _state["enabled"]:
        yield None
        return

    if _state["mode"] == "otel":
        configure_tracing()
        from opentelemetry import trace

        tracer = trace.get_tracer(TRACER_NAME)
        with tracer.start_as_current_span(name) as otel_span:
            for key, value in attributes.items():
                otel_span.set_attribute(key, value)
            yield otel_span
        return

    # Dependency-free fallback: time the block and print one structured line.
    start = time.perf_counter()
    record = {"span": name, **attributes}
    try:
        yield record
    finally:
        record["duration_ms"] = round((time.perf_counter() - start) * 1000, 1)
        print(json.dumps(record), file=sys.stderr, flush=True)


def set_attribute(handle, key: str, value) -> None:
    """Attach an attribute to a span handle from either backend."""
    if handle is None:
        return
    setter = getattr(handle, "set_attribute", None)
    if callable(setter):
        setter(key, value)
    elif isinstance(handle, dict):
        handle[key] = value
