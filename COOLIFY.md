# Deploying pawscode on Coolify

pawscode is a single-file Flask app (single-user, file-based state). This deploys it
behind a public URL via Coolify using the **Dockerfile** provider. No database needed.

## Prerequisites
- A Coolify server (self-hosted or coolify.io).
- Your `OPENROUTER_API_KEY` (required — the app reads it at import time and crashes without it).
- Optional: `OPENAI_API_KEY` (Whisper voice transcription), `FIRECRAWL_API_KEY` + `FIRECRAWL_ENABLED`.

## Steps
1. In Coolify, create a new **Application** → **Dockerfile** (or **Git Repository** pointing at this repo).
2. Set the **ports**: container `5050` → public (Coolify assigns a domain or you bring your own).
3. Add **environment variables** (Coolify → Env Variables):
   - `OPENROUTER_API_KEY` = `sk-or-...`  ← REQUIRED
   - `OPENAI_API_KEY` = `sk-...`  (optional)
   - `FIRECRAWL_API_KEY` = `fc-...`  (optional)
   - `FIRECRAWL_ENABLED` = `true`  (optional)
   - `PORT` = `5050`  (already default in the Dockerfile)
4. Deploy. Coolify builds the image from the `Dockerfile`, runs `gunicorn` on `5050`.
5. Health check: use `GET /` (the app index) — no dedicated `/health` route exists yet.

## Notes / limitations
- **State is ephemeral by default.** `progress.json`, `history.json`, `chats.json` live in the
  container's filesystem and are lost on redeploy/restart for anonymous users. Per-user persistence
  is available via Supabase: set `SUPABASE_URL` + `SUPABASE_KEY` and run `refactor/supabase-schema.sql`
  in Supabase once — then each authenticated user's `progress`/`chats`/`judges`/`replay_comments`
  persist across redeploys (isolated by RLS). Anonymous sessions remain ephemeral.
- **`OPENROUTER_API_KEY` is mandatory.** Without it the container exits immediately at import.
- The image uses `python:3.12-slim` + `gunicorn` (2 workers, 120s timeout).
- `.dockerignore` excludes local-only files (`graphify-out/`, `.opencode/`, `.env`, `*.pdf`, state files).
- The `security gate` (`security_scan.py` + `bandit`) runs server-side and blocks malicious
  candidate code before execution. It degrades gracefully if `bandit` is missing.
