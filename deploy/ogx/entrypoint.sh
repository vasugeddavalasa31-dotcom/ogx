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

# Optional: source the LLM model list from the gateway (which reads the TiDB
# admin_model registry). This makes OGX serve exactly the models enabled in the
# gateway instead of the hard-coded list in config.template.yaml. Falls back to
# the static list when the gateway is unreachable.
gateway_models_url = os.environ.get("GATEWAY_MODELS_URL", "").strip()
if gateway_models_url:
    try:
        import json as _json
        import urllib.request as _request

        with _request.urlopen(gateway_models_url, timeout=10) as _resp:
            _data = _json.load(_resp)
        _models = [
            m for m in _data.get("data", []) if m.get("id")
        ]
        if _models:
            cfg["registered_resources"]["models"] = [
                {
                    "metadata": {},
                    "model_id": m["id"],
                    "provider_id": "all",
                    "provider_model_id": "auto",
                    "model_type": "llm",
                }
                for m in _models
            ]
            print(
                f"Loaded {len(cfg['registered_resources']['models'])} model(s) from gateway: "
                f"{[m['id'] for m in _models]}",
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

# Optional Postgres: switch both backends when POSTGRES_HOST is provided.
if os.environ.get("POSTGRES_HOST"):
    pg = {
        "host": os.environ["POSTGRES_HOST"],
        "port": int(os.environ.get("POSTGRES_PORT", "5432")),
        "db": os.environ.get("POSTGRES_DB", "ogx"),
        "user": os.environ.get("POSTGRES_USER", "ogx"),
        "password": os.environ.get("POSTGRES_PASSWORD", ""),
        "pool_size": int(os.environ.get("POSTGRES_POOL_SIZE", "10")),
        "max_overflow": int(os.environ.get("POSTGRES_MAX_OVERFLOW", "20")),
        "pool_recycle": int(os.environ.get("POSTGRES_POOL_RECYCLE", "3600")),
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

with open("/tmp/ogx-config.yaml", "w") as f:
    yaml.safe_dump(cfg, f, sort_keys=False)
EOF

mkdir -p /data
# Railway injects $PORT and routes traffic to it — listen there (default 8321
# locally) so the platform healthcheck can reach the server.
PORT="${PORT:-8321}"
exec /app/.venv/bin/ogx run /tmp/ogx-config.yaml --port "$PORT" --insecure
