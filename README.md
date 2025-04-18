# Chuk A2A Agent Runtime

> **Status:** Early prototype – implements core data‑layer and FSM for the [Agent‑to‑Agent (A2A) Protocol](https://github.com/…) draft spec.

This repo is a Python reference implementation of an **A2A‑compliant remote‑agent runtime**.  It exposes JSON‑RPC 2.0 endpoints (via FastAPI – coming next), streams updates over SSE, and persists tasks / artifacts with pluggable back‑ends.

---

## ✨ Key features (today)

* **Canonical Pydantic models** auto‑generated from the source JSON Schema.
* **In‑memory Task Manager** enforcing the official state‑machine.
* **Async‑first** – ready for `asyncio`, Celery, or other worker pools.
* **One‑command model regeneration** (`scripts/generate_models.sh`).

Roadmap items are tracked in [#issues](https://github.com/…/issues).

---

## 📂 Repo layout

```
chuk-a2a/
├── a2a/                    # Python package (runtime code)
│   ├── __init__.py
│   ├── task_manager.py     # FSM + helpers (imports generated models)
│   └── models.py           # ← generated 🇺🇸
│
├── spec/
│   └── a2a_spec.json       # Canonical JSON Schema (source of truth)
│
├── scripts/
│   └── generate_models.sh  # Regenerate models.py from schema
│
└── README.md
```

---

## 🚀 Quick start

```bash
# 1. Clone & create a virtualenv
python -m venv .venv && source .venv/bin/activate

# 2. Install deps
pip install -r requirements.txt  # (pydantic, datamodel-code-generator, fastapi, uvicorn, …)

# 3. Generate Pydantic models (first time or after schema changes)
./scripts/generate_models.sh

# 4. Smoke‑test the Task Manager
python a2a/task_manager.py
```

You should see JSON for a freshly created → completed task printed to the console.

---

## 🔄 Regenerating **models.py**

Whenever `spec/a2a_spec.json` changes, run:

```bash
./scripts/generate_models.sh                # default paths
#   or
./scripts/generate_models.sh custom/schema.json a2a/models.py
```

The script ensures the target directory exists and always invokes the code‑generator via `python -m` to dodge `$PATH` quirks.

---

## 🛠️ Development workflow

1. **Update schema** → regenerate models.
2. Write or update runtime logic under `a2a/` (imports `models.py`).
3. Add or update tests in `tests/` (pytest recommended).
4. Run `pre‑commit run --all-files` (black, isort, flake8, mypy) before pushing.

---

## 🗺️ Next milestones

| M‑# | Milestone | ETA |
|-----|-----------|-----|
| 1 | FastAPI JSON‑RPC router & OpenAPI docs | ✅ WIP |
| 2 | SSE streaming endpoint | 2025‑05‑01 |
| 3 | Redis cache + Postgres persistence | 2025‑05‑08 |
| 4 | OAuth2 / JWT auth middleware | 2025‑05‑15 |

---

## 🤝 Contributing

Issues and PRs are welcome!  Please file an issue first if you’re planning a non‑trivial change so we can discuss design.

---

## 📄 License

MIT © 2025 Chuk Corp

