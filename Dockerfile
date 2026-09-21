FROM ghcr.io/astral-sh/uv:0.12.17 AS uv
FROM python:3.12.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-cache
COPY . .
RUN uv sync --frozen --no-cache && useradd --uid 10001 --create-home sentinel
USER 10001
CMD ["uvicorn", "api_sentinel.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "64", "--backlog", "64", "--timeout-keep-alive", "3", "--timeout-graceful-shutdown", "5"]
