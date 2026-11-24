# Aegis AI — Milestone 2A

Read-only, deterministic incident diagnostics from the live Aegis manager `/weights` endpoint. **Gemini, RAG, LangGraph and deployment are not implemented in this milestone.**

Start Aegis Docker Compose first, then:

```bash
cd ~/projects/aegis-ai
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
uvicorn app.main:app --reload --port 8010
```

In a second terminal:

```bash
curl -i http://localhost:8010/healthz
curl -sS 'http://localhost:8010/investigate?threshold_ms=100'
```

Set `AEGIS_MANAGER_URL` to override `http://localhost:8001`. The threshold is illustrative, not an established SLO. This endpoint does not make changes to the infrastructure.
