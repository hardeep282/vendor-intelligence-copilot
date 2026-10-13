# syntax=docker/dockerfile:1
# Purpose : production image for the Copilot API.
# Stages  : builder (uv installs the locked dependencies into /app/.venv) -> runtime (no uv,
#           no compilers, non-root user). Only what the API needs is copied in.
# Build   : docker build -f docker/api.Dockerfile --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t copilot-api .
# Run     : docker run --rm -p 8000:8000 copilot-api   (APP_ENV defaults to dev; compose sets prod)

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Dependencies first: this layer is cached until pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
# Then the application code.
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
ARG GIT_SHA=dev
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GIT_SHA=${GIT_SHA}
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
COPY --chown=app:app policies ./policies
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# --proxy-headers: trust X-Forwarded-* from nginx. The port is published on 127.0.0.1 only
# (see infra/server/compose.yaml), so nothing outside the host can spoof these headers.
CMD ["uvicorn", "copilot.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
