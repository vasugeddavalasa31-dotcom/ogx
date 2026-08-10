FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends git curl && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY deploy/ogx/config.template.yaml ./config.template.yaml
COPY deploy/ogx/entrypoint.sh ./entrypoint.sh

RUN uv sync --frozen --no-dev && chmod +x /app/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8321
CMD ["/app/entrypoint.sh"]
