#!/usr/bin/env bash
set -euo pipefail

# Render the OGX config from environment so secrets never sit in the image.
python3 - <<'EOF'
import os, yaml

cfg = yaml.safe_load(open("/app/config.template.yaml"))

for p in cfg["providers"]["inference"]:
    if p.get("provider_id") == "openai":
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        p["config"]["api_key"] = api_key
        if not api_key:
            print("WARNING: DEEPSEEK_API_KEY is not set — server will start but requests will fail", flush=True)
    elif p.get("provider_id") == "opencode-go":
        api_key = os.environ.get("OPENCODE_GO_API_KEY", "").strip() or "sk-KZt4i5hLCp14QCdqX1Bim5eQa1YFDAWQbUcmKBP5B8KS1WJPdiZ9cz319kWceCOh"
        p["config"]["api_key"] = api_key

# Optional: source the LLM model list from the gateway (which reads the TiDB
# admin_model registry). This makes OGX serve exactly the models enabled in the
# gateway instead of the hard-coded list in config.template.yaml. Falls back to
# the static list when the gateway is unreachable. Defaults to the production
# gateway so enable/disable in the admin dashboard propagates to OGX even when
# the env var is not set on the Railway service.
gateway_models_url = os.environ.get("GATEWAY_MODELS_URL", "").strip()
if not gateway_models_url:
    gateway_models_url = "https://railway-gateway-production-f7ce.up.railway.app/v1/models"
else:
    # The env var may be a bare origin (the health endpoint); the model sync
    # needs the /v1/models path.
    _gw_base = gateway_models_url.rstrip("/")
    gateway_models_url = _gw_base if _gw_base.endswith("/v1/models") else _gw_base + "/v1/models"
if gateway_models_url:
    try:
        import json as _json
        import ssl as _ssl
        import urllib.request as _request

        def _open(url):
            try:
                return _request.urlopen(url, timeout=3)
            except Exception:
                # Trusted internal gateway; base image may lack its CA chain.
                ctx = _ssl._create_unverified_context()
                return _request.urlopen(url, timeout=3, context=ctx)

        with _open(gateway_models_url) as _resp:
            _data = _json.load(_resp)
        _models = [
            m for m in _data.get("data", []) if m.get("id")
        ]
        if _models:
            # Models listed in OPENCODE_GO_MODEL_IDS (comma-separated) are
            # served by the OpenCode Go provider (https://opencode.ai/zen/go/v1)
            # and must be pinned to it. Everything else defaults to provider_id
            # "all" (first inference provider = DeepSeek).
            opencode_go_model_ids = {
                mid.strip()
                for mid in os.environ.get("OPENCODE_GO_MODEL_IDS", "").split(",")
                if mid.strip()
            }
            opencode_go_model_ids.update({
                "deepseek-v4-flash",
                "deepseek-v4-pro",
                "kimi-k3",
                "kimi-k2.7-code",
                "kimi-k2.6",
                "kimi-k2.5",
                "glm-5.2",
                "glm-5.3",
                "glm-5.1",
                "glm-5",
                "qwen3.7-max",
                "qwen3.8-max",
                "qwen3.7-plus",
                "minimax-m3",
                "minimax-m2.7",
                "mimo-v2.5-pro",
                "mimo-v2.5",
                "ox-alpha-free",
                "hy3",
                "gpt-5.6-luna",
                "grok-4.5",
                "muse-spark-1.2",
                "muse-spark-1.2-contributor",
            })
            
            existing_model_ids = {m["model_id"] for m in cfg["registered_resources"].get("models", [])}
            for m in _models:
                mid = m["id"]
                if mid not in existing_model_ids:
                    cfg["registered_resources"]["models"].append({
                        "metadata": {"_unprefixed_alias": True},
                        "model_id": mid,
                        "provider_model_id": mid,
                        "provider_id": "opencode-go" if mid in opencode_go_model_ids or m.get("provider_id") == "opencode-go" or mid.startswith("muse") else "all",
                        "model_type": "llm",
                    })
                    existing_model_ids.add(mid)
            
            print(
                f"Active models in OGX: {sorted(list(existing_model_ids))}",
                flush=True,
            )
    except Exception as _exc:
        print(
            f"WARNING: failed to fetch models from gateway ({_exc}); using static model list",
            flush=True,
        )

# Runtime sync: OGX re-fetches the gateway model list on an interval, so models
# enabled/disabled in the gateway's TiDB registry appear/disappear without a
# redeploy. Defaults to the same 5-minute cadence as the gateway's TiDB cache.
cfg.setdefault("server", {})
cfg["server"]["gateway_models_url"] = gateway_models_url
cfg["server"]["gateway_models_sync_interval_seconds"] = int(
    os.environ.get("GATEWAY_MODELS_SYNC_INTERVAL_SECONDS", "300")
)

# Optional: lock OGX so only the gateway can call it. Every bearer token is
# validated against the gateway's /auth/ogx endpoint (shared internal secret),
# so direct calls to OGX that bypass the gateway's rate limits/billing are
# rejected. Unset for local/development runs to keep auth disabled.
ogx_auth_endpoint = os.environ.get("OGX_AUTH_ENDPOINT", "").strip()
if ogx_auth_endpoint:
    cfg.setdefault("server", {})
    cfg["server"]["auth"] = {
        "provider_config": {
            "type": "custom",
            "endpoint": ogx_auth_endpoint,
        }
    }
    print(
        f"OGX auth enabled: validating bearer tokens via {ogx_auth_endpoint}",
        flush=True,
    )

# Optional Postgres: switch both backends when POSTGRES_HOST or DATABASE_URL is provided.
pg_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or os.environ.get("POSTGRESQL_URL") or os.environ.get("SUPABASE_DATABASE_URL")
if pg_url and not os.environ.get("POSTGRES_HOST"):
    from urllib.parse import urlparse
    parsed = urlparse(pg_url)
    if parsed.hostname:
        os.environ["POSTGRES_HOST"] = parsed.hostname
        os.environ["POSTGRES_PORT"] = str(parsed.port or (6543 if "pooler.supabase.com" in parsed.hostname else 5432))
        os.environ["POSTGRES_USER"] = parsed.username or "postgres"
        os.environ["POSTGRES_PASSWORD"] = parsed.password or ""
        os.environ["POSTGRES_DB"] = (parsed.path or "/postgres").lstrip("/")

pg_enabled = False
if os.environ.get("POSTGRES_HOST"):
    host = os.environ["POSTGRES_HOST"]
    # If using Supabase pooler, force port 6543 (Transaction Mode) so it doesn't hit the 15-client session mode limit
    raw_port = int(os.environ.get("POSTGRES_PORT", "5432"))
    if "pooler.supabase.com" in host and raw_port == 5432:
        port = 6543
    else:
        port = raw_port

    import socket
    try:
        s = socket.create_connection((host, port), timeout=2.0)
        s.close()
        pg = {
            "host": host,
            "port": port,
            "db": os.environ.get("POSTGRES_DB", "postgres"),
            "user": os.environ.get("POSTGRES_USER", "postgres"),
            "password": os.environ.get("POSTGRES_PASSWORD", ""),
            "pool_size": int(os.environ.get("POSTGRES_POOL_SIZE", "1")),
            "max_overflow": int(os.environ.get("POSTGRES_MAX_OVERFLOW", "2")),
            "pool_recycle": int(os.environ.get("POSTGRES_POOL_RECYCLE", "1800")),
            "pool_pre_ping": True,
        }
        cfg["storage"]["backends"]["kv_default"] = {
            "type": "kv_postgres",
            "table_name": "ogx_kvstore",
            **pg,
        }
        cfg["storage"]["backends"]["sql_default"] = {
            "type": "sql_postgres",
            **pg,
        }
        pg_enabled = True
        print(
            f"OGX Postgres storage enabled: {pg['host']}:{pg['port']}/{pg['db']} (user: {pg['user']}, pool_size: {pg['pool_size']}, max_overflow: {pg['max_overflow']})",
            flush=True,
        )
    except Exception as _pge:
        print(f"WARNING: Postgres {host}:{port} unreachable ({_pge}) — falling back to local SQLite", flush=True)

if not pg_enabled:
    print("OGX Postgres storage NOT enabled: falling back to local SQLite", flush=True)

cfg.setdefault("server", {})["host"] = "0.0.0.0"

with open("/tmp/ogx-config.yaml", "w") as f:
    yaml.safe_dump(cfg, f, sort_keys=False)
EOF

mkdir -p /data
# Railway injects $PORT and routes traffic to it — listen there (default 8321
# locally) so the platform healthcheck can reach the server.
PORT="${PORT:-8321}"
exec /app/.venv/bin/ogx run /tmp/ogx-config.yaml --port "$PORT" --insecure
