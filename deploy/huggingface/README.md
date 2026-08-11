---
title: RouteCause
emoji: 🛰️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# RouteCause — live API

Citation-grounded BGP-incident investigator. Deterministic anomaly detection +
cited RFC retrieval, exposed as a small FastAPI service.

- **Interactive docs:** open **`/docs`** (Swagger UI) from the Space URL.
- `GET /health` · `GET /incidents` · `POST /investigate` · `POST /ask`

Source: https://github.com/dim-tsoukalas/RouteCause

---

## How to deploy this Space (one time)

1. Create a new Space at https://huggingface.co/new-space — pick **Docker** as
   the SDK (blank template), any name.
2. Add **two files** to the Space repo root — copy them from this folder
   (`deploy/huggingface/` in the GitHub repo):
   - `Dockerfile`
   - `README.md` (this file — the YAML frontmatter above is what makes it a
     Docker Space on port 7860)
3. Commit. The Space builds automatically (a few minutes). When it's green,
   open the Space URL and append **`/docs`**.

You can either upload the two files in the Space's web UI, or push with git:

```bash
git clone https://huggingface.co/spaces/<your-username>/<space-name>
cd <space-name>
# copy deploy/huggingface/Dockerfile and deploy/huggingface/README.md here
git add Dockerfile README.md && git commit -m "RouteCause Space" && git push
```

The demo runs **offline** — no API key needed. To turn on natural-language
narration, add two **Space secrets** (Settings → Variables and secrets) and
restart:

- `INVESTIGATOR_MODEL` = e.g. `openai/gpt-4o-mini`
- `OPENAI_API_KEY` = your key

> The Dockerfile clones `main` at build time, so re-building the Space picks up
> the latest commit. If your default branch isn't `main`, edit the `git clone`
> line in the Dockerfile.
