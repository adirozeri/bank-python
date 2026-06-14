# bank-python (Phase 1)

Backend-only banking API (FastAPI) with a `transactions` table and a LangGraph
LLM endpoint to ask questions about it. Uses SQLite — no DB setup needed.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env        # add your ANTHROPIC_API_KEY
python seed.py              # optional: 50 sample transactions
uvicorn main:app --reload
```

Open http://localhost:8000/docs or import the collection in `postman/`.

## Endpoints
- `GET  /health`
- `POST /transactions` — create
- `GET  /transactions` — list (filters: account_id, type, status)
- `GET  /transactions/{id}`
- `POST /ask` — natural-language question over the transactions table

## Files
| File          | Purpose                                  |
|---------------|------------------------------------------|
| `main.py`     | FastAPI app + endpoints                  |
| `database.py` | SQLAlchemy engine/session               |
| `models.py`   | `Transaction` model                      |
| `llm.py`      | LangGraph agent (question → SQL → answer) |
| `seed.py`     | Sample data                              |
