# AGENTS.md — PRISM ETL/EDA Assistant

## What this is

FastAPI backend (Python) serving an ETL/EDA assistant. Single `index.html` frontend.
Deploy target: Vercel serverless + Neon Postgres.

## Running locally

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. No database required for basic analysis features.
`DATABASE_URL` env var enables history persistence and AI config storage.

## Entry point

`api/index.py` — thin wrapper that adds `backend/` to `sys.path` and imports the FastAPI `app` from `backend/app/main.py`. All routers live under `backend/app/routers`, all business logic under `backend/app/services`. Quality rules are in `backend/app/services/quality/` (one file per rule, `engine.py` orchestrates them).

## Vercel deployment

- Entry point is `api/index.py` which imports `app` from `backend/app/main.py`. Vercel auto-detects functions in `api/`.
- `vercel.json` rewrites all non-static routes to `/api/index`.
- `public/index.html` at root is served by Vercel CDN — do NOT confuse with `backend/frontend/index.html` (local dev only).
- If `StaticFiles` mount fails, the API (`/api/*`) still works — only HTML on `/` is affected.

**Required Vercel Environment Variables (Project Settings → Environment Variables):**

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql://user:pass@ep-xxxx.neon.tech/dbname?sslmode=require` |
| `JWT_SECRET` | 64-char hex string (generate: `python3 -c "import secrets; print(secrets.token_hex(32))"`) |
| `ALLOWED_ORIGINS` | `https://your-app.vercel.app` (add multiple comma-separated if needed) |

**Optional:**
| Variable | Value |
|---|---|
| `SUPER_ADMIN_USERNAME` | `admin` (or custom) |
| `SUPER_ADMIN_PASSWORD` | Secure password (if not set, random one generated at first startup) |

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | No (enables persistence) | Neon Postgres connection string with `?sslmode=require` |
| `JWT_SECRET` | Yes for production | Without it, multi-instance deploys break (intermittent 401s). Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ALLOWED_ORIGINS` | Yes for production | Comma-separated list of allowed origins for CORS (e.g., `https://your-app.vercel.app`). Default: localhost only. |
| `SUPER_ADMIN_USERNAME` | No | Default: `admin` |
| `SUPER_ADMIN_PASSWORD` | No | Default: random (printed once at startup) |

## First-run setup (no DB)

The app auto-creates a `super_admin` on startup if no users exist. Password is printed once to stdout — capture it from the uvicorn/Vercel logs.

## First-run setup (with Neon)

```bash
export DATABASE_URL="postgresql://user:pass@ep-xxxx.neon.tech/dbname?sslmode=require"
python3 scripts/seed_admin.py
```

Default credentials: `admin` / (password from `ADMIN_PASSWORD` env var, or empty — change immediately). Idempotent — won't overwrite an existing user.

To use custom credentials:
```bash
export ADMIN_USERNAME="your_username"
export ADMIN_PASSWORD="your_secure_password"
python3 scripts/seed_admin.py
```

## Auth model

4 roles: `super_admin` > `admin` > `analista` > `report_viewer`.
Passwords: PBKDF2-HMAC-SHA256, 200k iterations, per-user salt.
JWT tokens via `pyjwt`. Auth deps in `app/routers/auth_deps.py`.

## No test suite

There are no tests, no linter config, no type checker, no CI. The README references Playwright e2e testing done manually. If you add tooling, keep it simple — there's no existing infrastructure to extend.

## Gotchas

- `backend/requirements.txt` and root `requirements.txt` are identical copies — Vercel looks for the root one.
- Vercel Hobby plan: ~4.5 MB body limit, 10s execution timeout. Large Excel files may hit either. This app enforces a 4MB upload limit in `/api/analyze`.
- In-memory `data_cache` does not survive serverless cold starts. If charts fail after re-analysis, this is why.
- The `quality/` engine has 12+ rule files. Adding a new rule means creating a file in `backend/app/services/quality/` and registering it in `engine.py`.
- Key detection (`key_detection.py`) uses both name patterns AND structural signals (consecutive integers). Column names are user-provided and unpredictable.
- Connection pools (`asyncpg`) are closed on shutdown via FastAPI lifespan — avoids connection leak warnings in serverless.
