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
# the static list when the gateway is unreachable. Defaults to the production
# gateway so enable/disable in the admin dashboard propagates to OGX even when
# the env var is not set on the Railway service.
gateway_models_url = os.environ.get("GATEWAY_MODELS_URL", "").strip()
if not gateway_models_url:
    gateway_models_url = "https://railway-gateway-production.up.railway.app/v1/models"
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
                return _request.urlopen(url, timeout=10)
            except Exception:
                # Trusted internal gateway; base image may lack its CA chain.
                ctx = _ssl._create_unverified_context()
                return _request.urlopen(url, timeout=10, context=ctx)

        with _open(gateway_models_url) as _resp:
            _data = _json.load(_resp)
        _models = [
            m for m in _data.get("data", []) if m.get("id")
        ]
        if _models:
            # Models listed in OPENCODE_GO_MODEL_IDS (comma-separated) are
            # served by the OpenCode Go provider (https://opencode.ai/zen/go/v1)
            # and must be pinned to it. Everything else defaults to provider_id
            # "all" (first inference provider = DeepSeek). Without this, a
            # dashboard-added OpenCode Go model would be sent to DeepSeek and
            # fail.
            opencode_go_model_ids = {
                mid.strip()
                for mid in os.environ.get("OPENCODE_GO_MODEL_IDS", "").split(",")
                if mid.strip()
            }
            # OpenCode Go models (https://opencode.ai/zen/go/v1) must be pinned
            # to the opencode-go provider so they don't route to the direct DeepSeek API.
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
                "gpt-5.6-luna",
                "grok-4.5",
                "muse-spark-1.2",
                "muse-spark-1.2-contributor",
            })
            cfg["registered_resources"]["models"] = [
                {
                    # `_unprefixed_alias` registers the model under its bare id
                    # (matching what the app sends) instead of a provider-prefixed
                    # id like opencode-go/kimi-k3.
                    "metadata": {"_unprefixed_alias": True},
                    "model_id": m["id"],
                    # Pin the provider model id instead of "auto": "auto"
                    # resolves every alias to the provider's *first* listed
                    # model, so e.g. deepseek-v4-pro would silently run
                    # deepseek-v4-flash. Here the gateway/TiDB model ids are
                    # the provider ids, so they map 1:1.
                    "provider_model_id": m["id"],
                    "provider_id": "opencode-go" if m["id"] in opencode_go_model_ids or m.get("provider_id") == "opencode-go" or m["id"].startswith("muse") else "all",
                    "model_type": "llm",
                }
                for m in _models
            ]
            print(
                f"Loaded {len(cfg['registered_resources']['models'])} model(s) from gateway: "
                f"{[m['id'] for m in _models]}",
                flush=True,
            )
            if opencode_go_model_ids:
                print(
                    f"OpenCode Go models routed to opencode-go provider: {sorted(opencode_go_model_ids)}",
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
