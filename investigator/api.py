"""HTTP API for the investigator.

A thin FastAPI layer over the exact same engine the CLI uses
(`InvestigationEngine`) — no reimplementation of the analysis, so the API and
`investigate`/`ask` can never drift. The corpus (945 RFC chunks) is loaded and
the BM25 index is built once at startup and reused across requests.

Run it:
    pip install -e ".[api]"      # or ".[all]"
    investigator-serve           # -> http://127.0.0.1:8000  (docs at /docs)
    # or explicitly:
    uvicorn investigator.api:app --host 0.0.0.0 --port 8000

Offline by default (deterministic detection + cited retrieval). Set
INVESTIGATOR_MODEL (+ a provider key) before starting the server to enable
natural-language narration on /investigate and /ask.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from investigator.ach import rank_hypotheses
from investigator.engine import InvestigationEngine
from investigator.evaluation.entailment import default_contradiction_checker
from investigator.retrieval.contradiction import hypotheses_from_results, seek_contradictions
from investigator.toolsets import DEFAULT_TOOLSETS_PATH, load_citation_eval_config
from investigator.types import Incident

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RFC_DIR = str(_ROOT / "data" / "rfcs")
INCIDENTS_DIR = _ROOT / "data" / "incidents"
CATALOG_PATH = INCIDENTS_DIR / "catalog.json"


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #
class InvestigateRequest(BaseModel):
    incident: str = Field(..., description="A catalog name, e.g. 'pakistan-youtube-2008'.")
    question: str = "Why did connectivity to this prefix change?"
    seek_contradictions: bool = Field(
        False, description="Also run adversarial counter-evidence retrieval + ACH ranking."
    )


class AskRequest(BaseModel):
    question: str


class FindingOut(BaseModel):
    text: str
    rfc_hint: str | None = None


class ResultOut(BaseModel):
    kind: str
    name: str
    severity: str
    findings: list[FindingOut]
    evidence: list[str]
    evidence_total: int


class SourceOut(BaseModel):
    n: int
    source_id: str
    text: str


class ExplanationOut(BaseModel):
    abstained: bool
    answer: str | None = None
    sources: list[SourceOut] = []


class InvestigateResponse(BaseModel):
    incident_id: str
    question: str
    has_findings: bool
    results: list[ResultOut]
    explanation: ExplanationOut | None = None
    next_steps: list[str]
    competing_hypotheses_markdown: str | None = None
    ach_ranking_markdown: str | None = None
    markdown: str


class AskResponse(BaseModel):
    question: str
    abstained: bool
    answer: str
    sources: list[SourceOut]


# --------------------------------------------------------------------------- #
# App + shared engine
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Set up tracing (no-op unless INVESTIGATOR_TRACING is set).
    from investigator.observability import configure_tracing

    configure_tracing()
    # Build the engine (loads + indexes the corpus) once, reuse for every request.
    app.state.engine = InvestigationEngine(
        rfc_dir=DEFAULT_RFC_DIR, toolsets_path=str(DEFAULT_TOOLSETS_PATH)
    )
    yield


app = FastAPI(
    title="RouteCause",
    description="Citation-grounded BGP-incident investigator.",
    version="0.1.0",
    lifespan=lifespan,
)


def _resolve_incident(name: str) -> Path:
    """Catalog names only — no arbitrary filesystem paths from the network."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="incident must be a catalog name, not a path")
    candidate = INCIDENTS_DIR / f"{name.replace('-', '_')}.json"
    if not candidate.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"no ready-to-run incident named {name!r}; see GET /incidents",
        )
    return candidate


def _source_out(s) -> SourceOut:
    return SourceOut(n=s.n, source_id=s.source_id, text=s.text)


def _result_out(r) -> ResultOut:
    return ResultOut(
        kind=r.kind,
        name=r.name,
        severity=r.severity,
        findings=[FindingOut(text=f.text, rfc_hint=f.rfc_hint) for f in r.findings],
        evidence=list(r.evidence[:8]),
        evidence_total=len(r.evidence),
    )


@app.get("/health")
def health() -> dict:
    model = os.environ.get("INVESTIGATOR_MODEL")
    return {"status": "ok", "llm_enabled": bool(model), "model": model}


@app.get("/incidents")
def incidents() -> dict:
    """Catalog entries, flagged by whether they ship ready-to-run (bundled JSON)
    or need ingesting first."""
    import json

    entries = json.loads(CATALOG_PATH.read_text())
    out = []
    for e in entries:
        name = e["name"]
        ready = (INCIDENTS_DIR / f"{name.replace('-', '_')}.json").is_file()
        out.append({"name": name, "description": e.get("description", ""), "ready": ready})
    return {"incidents": out}


@app.post("/investigate", response_model=InvestigateResponse)
def investigate(req: InvestigateRequest) -> InvestigateResponse:
    engine: InvestigationEngine = app.state.engine
    incident = Incident.from_json(_resolve_incident(req.incident))
    report = engine.investigate(incident, req.question)

    explanation = None
    if report.explanation is not None:
        explanation = ExplanationOut(
            abstained=report.explanation.abstained,
            answer=None if report.explanation.abstained else report.explanation.answer,
            sources=[_source_out(s) for s in report.explanation.sources],
        )

    competing_md = None
    ranking_md = None
    if req.seek_contradictions:
        checker_name = load_citation_eval_config(str(DEFAULT_TOOLSETS_PATH)).get("contradiction_checker")
        checker = default_contradiction_checker(checker_name)
        hyps = hypotheses_from_results(report.results)
        checks = [seek_contradictions(h, engine.citations, checker) for h in hyps]
        if checks:
            competing_md = "\n\n".join(c.render() for c in checks)
            ranking_md = rank_hypotheses(checks).render()

    return InvestigateResponse(
        incident_id=report.incident_id,
        question=report.question,
        has_findings=report.has_findings,
        results=[_result_out(r) for r in report.results if not r.is_empty()],
        explanation=explanation,
        next_steps=report.next_steps,
        competing_hypotheses_markdown=competing_md,
        ach_ranking_markdown=ranking_md,
        markdown=report.render(),
    )


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    engine: InvestigationEngine = app.state.engine
    answer = engine.ask(req.question)
    return AskResponse(
        question=req.question,
        abstained=answer.abstained,
        answer=answer.answer,
        sources=[_source_out(s) for s in answer.sources],
    )


def main() -> None:
    """Console-script entry point (`investigator-serve`)."""
    import uvicorn

    uvicorn.run(
        "investigator.api:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
