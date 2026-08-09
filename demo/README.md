# Demo — hosted, interactive

A self-contained web demo of the investigator. It shows the real pipeline
output for four incidents — two where the system **asserts** a cited leading
hypothesis, and two where it **abstains** because it can't ground a claim —
so a reviewer sees the measured-abstention behavior, not just a happy path.

Nothing here is mocked. `index.html` embeds a snapshot produced by
`export_demo.py`, which calls the exact same engine, contradiction-search,
and ACH-ranking code paths as the CLI. The verdicts in the demo match
`investigate <incident> --seek-contradictions` line for line.

## Two ways to run it

**Static (zero backend).** Just open `index.html`, or host the `demo/`
folder anywhere static:

- **GitHub Pages (included):** the repo ships a workflow at
  `.github/workflows/deploy-pages.yml` that publishes this `demo/` folder.
  One-time setup: repo **Settings → Pages → Source: GitHub Actions**. Then
  push to your default branch (the workflow targets `main` — edit the
  `branches:` line if yours differs) or run it manually from the **Actions**
  tab. It goes live at `https://dim-tsoukalas.github.io/RouteCause/`.
- Vercel / Netlify: set the project root (or publish dir) to `demo/`.
- Local: `python -m http.server` from `demo/`, then open the page.

**Live (runs the real engine on request).** The optional FastAPI app reruns
the full pipeline on demand for any of the 25 catalog incidents — the demo's
"↻ Run live" button hits it and swaps in freshly computed results:

```bash
pip install -e .            # the investigator package
pip install fastapi uvicorn
python -m uvicorn demo.app:app --host 0.0.0.0 --port 8000
# open http://localhost:8000
```

Free hosting for the live version:

- **Hugging Face Spaces** — new Space, Docker or FastAPI SDK, launch
  `demo.app:app`.
- **Render.com** — web service; build `pip install -e . fastapi uvicorn`,
  start `uvicorn demo.app:app --host 0.0.0.0 --port $PORT`.

Set `INVESTIGATOR_MODEL` (+ a provider API key) to add natural-language
narration over the same cited sources; without it the pipeline still runs
fully — retrieval, adversarial contradiction search, and ACH ranking are all
LLM-free.

## Regenerating the snapshot

```bash
python demo/export_demo.py > demo/demo_data.json   # real pipeline output
python demo/build_demo.py                           # rebuilds index.html
```

`build_demo.py` injects `demo_data.json` into a single self-contained HTML
file (no external assets, no build step, no network).

## Before you publish

Edit the `REPO_URL` near the top of `build_demo.py` (currently a placeholder)
to your GitHub URL and rerun `build_demo.py`, so the "View source" button
points at your repo.
