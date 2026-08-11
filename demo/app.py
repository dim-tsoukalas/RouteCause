"""Optional live-run server for the Network Investigator demo.

The static demo (demo/index.html) works with zero backend — it embeds a
snapshot of real pipeline output and deploys to any static host (GitHub
Pages, Vercel, Netlify). This FastAPI app is the *live* path: it runs the
actual engine on demand for any catalog incident, so a reviewer can point it
at a fresh incident and watch the real deterministic + agentic + ACH pipeline
produce the answer (or abstain) live.

Run locally:
    pip install fastapi uvicorn
    python -m uvicorn demo.app:app --reload --port 8000
    # open http://localhost:8000

Deploy free:
    - Hugging Face Spaces (Docker or "FastAPI" SDK): push this repo, set the
      app to `demo.app:app`.
    - Render.com web service: build `pip install -r requirements.txt fastapi
      uvicorn`, start `uvicorn demo.app:app --host 0.0.0.0 --port $PORT`.

Set INVESTIGATOR_MODEL (+ provider key) to add natural-language narration;
without it the pipeline still runs fully — retrieval, contradiction search,
and ACH ranking are all LLM-free.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))  # so `export_demo` resolves however app is launched

from export_demo import DEFAULT_INCIDENTS, export_incident

INCIDENTS_DIR = REPO / "data" / "incidents"

app = FastAPI(title="Network Investigator demo")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (HERE / "index.html").read_text()


@app.get("/api/incidents")
def list_incidents() -> JSONResponse:
    names = sorted(p.stem.replace("_", "-") for p in INCIDENTS_DIR.glob("*.json")
                   if p.stem != "catalog")
    return JSONResponse({"incidents": names, "featured": DEFAULT_INCIDENTS})


@app.get("/api/investigate")
def investigate(incident: str) -> JSONResponse:
    """Run the REAL pipeline live for one catalog incident and return the same
    structured JSON the static snapshot uses."""
    candidate = INCIDENTS_DIR / f"{incident.replace('-', '_')}.json"
    if not candidate.is_file():
        raise HTTPException(404, f"unknown incident {incident!r}")
    try:
        return JSONResponse(export_incident(incident))
    except Exception as e:  # surface real errors to the caller, don't hide them
        raise HTTPException(500, f"{type(e).__name__}: {e}") from e
