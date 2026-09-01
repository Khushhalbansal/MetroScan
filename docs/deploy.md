# Deploying MetroScan

Three pieces, three hosts:

| Piece | Host | Why |
|---|---|---|
| Frontend (`frontend/`, static Vite build) | **Vercel** | static, global CDN |
| Database | **Supabase** (managed Postgres) | the app already speaks `postgresql+psycopg://` |
| API + OCR pipeline (`backend/`) | **Fly.io** (Docker) | needs a long-lived Python process, ~1 GB RAM for the ONNX models, a disk for evidence files, and an always-on machine for the retention sweep |

Supabase **cannot** run the API — its edge functions are Deno-only with a ~10 s limit. It is the database (and optionally file storage) only.

---

## 1. Supabase — the database

1. Create a project at supabase.com. Region: closest to your users (e.g. `ap-south-1`).
2. Project → **Connect** → **ORMs** (or Database Settings → Connection string). Take the **session-mode pooler** URI (port `5432`), which looks like:
   ```
   postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
3. Rewrite the scheme for SQLAlchemy + psycopg 3 — change `postgresql://` to `postgresql+psycopg://`:
   ```
   postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```
   Keep this string for step 2. Migrations run against it automatically on every Fly deploy (`entrypoint.sh` → `alembic upgrade head`).

---

## 2. Fly.io — the API

Install `flyctl` and `fly auth login`. From the repo root (the `Dockerfile` and `fly.toml` are here):

```sh
# Pick a name; it becomes <name>.fly.dev
fly apps create metroscan-api          # or edit `app` in fly.toml and run `fly launch --no-deploy`

# A 1 GB volume in the same region as fly.toml's primary_region (bom) for
# evidence images + generated PDFs
fly volumes create metroscan_data --region bom --size 1

# Secrets (never put these in fly.toml)
fly secrets set \
  DATABASE_URL='postgresql+psycopg://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:5432/postgres' \
  JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  CORS_ORIGINS='https://metroscan.vercel.app'   # set the real Vercel URL after step 3

fly deploy
```

Then create the first administrator (interactive, once):

```sh
fly ssh console -C "python -m app.cli create-admin --email you@x.gov.in --name 'Your Name'"
```

Optional — load the demo dataset (13 scans, a demo admin) onto the deployed DB:

```sh
fly ssh console -C "python -m scripts.seed_demo"
```

Health check: `curl https://metroscan-api.fly.dev/api/v1/health` → `{"status":"ok",...}`.

**Notes**
- `ENVIRONMENT=production` is set in `fly.toml`, so the app *refuses to boot* if `JWT_SECRET` is still the dev default — that is deliberate.
- `min_machines_running = 1` keeps one machine up so Feature 6's retention sweep runs. Drop it to 0 if you don't need the sweep and want the machine to sleep.
- The evidence volume is single-machine. If you scale past one machine, move file storage to Supabase Storage (`app/services/storage.py`) — not needed for a demo.

---

## 3. Vercel — the frontend

1. Import the repo. **Root Directory → `frontend`.** Framework auto-detects as Vite; `frontend/vercel.json` supplies the build command, output dir, and the SPA rewrite.
2. Environment variable:
   ```
   VITE_API_BASE_URL = https://metroscan-api.fly.dev
   ```
   (build-time — a redeploy is needed if you change it.)
3. Deploy. Note the resulting URL (e.g. `https://metroscan.vercel.app`).
4. Back on Fly, set `CORS_ORIGINS` to that exact URL and redeploy:
   ```sh
   fly secrets set CORS_ORIGINS='https://metroscan.vercel.app'
   ```
   Preview deploys get their own URLs; add them comma-separated if you need CORS for previews.

---

## Local development is unchanged

SQLite, no services:

```sh
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
cd frontend && npm run dev          # proxies /api → 127.0.0.1:8000
```

`VITE_API_BASE_URL` unset ⇒ same-origin ⇒ the dev proxy handles it.
