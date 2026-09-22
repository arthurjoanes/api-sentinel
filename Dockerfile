FROM ghcr.io/astral-sh/uv:0.12.17@sha256:10787c682e4184e4f290de1171fd4703dc63de99221f10fe1c99002ce7fa9acc AS uv
FROM python:3.12.14-alpine3.24@sha256:c4634f578a412db396771b61b064c6e546c9d6414c7fb5b1b05d5871f1885f7b
COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN apk add --no-cache --virtual .protobuf-build-deps gcc musl-dev \
    && uv sync --frozen --no-install-project --no-cache --no-binary-package protobuf \
    && apk del .protobuf-build-deps \
    && python -c "from google.protobuf.internal import api_implementation; assert api_implementation.Type() == 'upb'"
COPY . .
RUN uv sync --frozen --no-cache --no-binary-package protobuf \
    && addgroup -g 10001 sentinel \
    && adduser -D -u 10001 -G sentinel sentinel \
    && rm -rf /usr/local/lib/python3.12/site-packages/pip \
              /usr/local/lib/python3.12/site-packages/pip-*.dist-info \
              /usr/local/lib/python3.12/ensurepip \
    && rm -f /usr/local/bin/pip* \
    && python -m compileall -q -j 1 /usr/local/lib/python3.12 \
        /opt/venv/lib/python3.12/site-packages /app/src /app/alert_receiver /app/erp_simulator \
    && python -c "from google.protobuf.internal import api_implementation; assert api_implementation.Type() == 'upb'"
USER 10001
CMD ["uvicorn", "api_sentinel.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers", "--limit-concurrency", "64", "--backlog", "64", "--timeout-keep-alive", "3", "--timeout-graceful-shutdown", "5"]
