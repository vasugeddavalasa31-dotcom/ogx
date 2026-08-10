#!/usr/bin/env bash
set -euo pipefail

# Render the OGX config from environment so secrets never sit in the image.
python3 - <<'EOF'
import os, yaml

cfg = yaml.safe_load(open("/app/config.template.yaml"))

for p in cfg["providers"]["inference"]:
    if p.get("provider_id") == "openai":
        p["config"]["api_key"] = os.environ["DEEPSEEK_API_KEY"]

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
exec /app/.venv/bin/ogx run /tmp/ogx-config.yaml --port 8321 --insecure
