# syntax=docker/dockerfile:1
FROM python:3.11-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    uv sync --frozen --no-dev
COPY ui ./ui
COPY scripts ./scripts
ENV PATH="/app/.venv/bin:$PATH" ORDER_DB=/app/runtime/orders.db
CMD ["uvicorn", "order_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
