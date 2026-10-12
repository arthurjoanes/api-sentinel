# Build only after the immutable API image for this attempt exists.
ARG SENTINEL_API_IMAGE
FROM ${SENTINEL_API_IMAGE}
USER root
RUN uv sync --frozen --group contracts --no-install-project --inexact --no-cache \
    --no-build \
    && python -c "import schemathesis; from importlib.metadata import version; assert version('schemathesis') == '4.30.1'"
USER 10001
CMD ["python", "scripts/verify_contracts.py", "--help"]
