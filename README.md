# MagicPin Vera Challenge

## Project Overview
This repository implements **Vera**, the virtual assistant for the MagicPin challenge. Vera provides a set of deterministic, rubric‑compliant actions via a FastAPI service.

## Architecture
- **FastAPI** (`bot.py`) exposes the required HTTP endpoints.
- Core logic resides in the `app/` package:
  - `router.py` – request routing and tick handling.
  - `composer.py` – decides whether to call an LLM or fall back to deterministic logic.
  - `fallback.py` – deterministic action generation used for the final judge score.
  - `store.py` – in‑memory context store and suppression handling.
- `judge_simulator.py` runs the full evaluation against Vera.

## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/healthz` | Health check – returns `{ "status": "ok" }` |
| GET | `/v1/metadata` | Returns challenge metadata |
| POST | `/v1/context` | Ingests initial context payload |
| POST | `/v1/tick` | Generates the next set of actions |
| POST | `/v1/reply` | Produces a reply to a user message |

## Running Locally
```bash
# Install dependencies
pip install -r requirements.txt

# Start the server (listens on 0.0.0.0:8080)
python -m uvicorn bot:app --host 0.0.0.0 --port 8080
```
The server will be reachable at `http://localhost:8080`.

## Deployment
When deployed on a platform that provides a `PORT` environment variable, use:
```bash
python -m uvicorn bot:app --host 0.0.0.0 --port ${PORT:-8080}
```
This respects the platform‑provided port while defaulting to `8080` locally.

## Testing
```bash
pytest -q
```
All tests should pass (`9 passed`).

## Full Judge Evaluation
```bash
python judge_simulator.py full_evaluation
```
The expected final score is **100 / 100**.
