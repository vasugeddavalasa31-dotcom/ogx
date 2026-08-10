# OGX beta deploy

Railway deploys this repo automatically — no local Docker needed.

## Services

1. **OGX server**: Railway service with Dockerfile `deploy/ogx/Dockerfile`.
   Env: `DEEPSEEK_API_KEY` + optional `POSTGRES_HOST/PORT/DB/USER/PASSWORD`
   (skip Postgres for a quick SQLite beta; add it for persistence).
   Optional: `GATEWAY_MODELS_URL=https://railway-gateway-production.up.railway.app`
   — when set, OGX fetches its model list from the gateway (which reads the
   active TiDB `admin_model` registry) instead of the hard-coded config list.
   URL example: `https://<ogx>.up.railway.app` (port 8321).
2. **ogx-ui (optional ops dashboard)**: Railway service with root directory
   `src/ogx_ui` (uses `src/ogx_ui/Containerfile` + `src/ogx_ui/railway.toml`).
   Env: `OGX_BACKEND_URL=https://<ogx>.up.railway.app`.
   Admin at `/admin`, models at `/models`, playground at `/chat-playground`.

The entrypoint renders the real config from env at start
(`deploy/ogx/entrypoint.sh`), so the DeepSeek key never sits in the image.

Then point your OrbiterX gateway/app at the OGX URL.
