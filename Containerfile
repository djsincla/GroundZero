# GroundZero as one OCI image: REST API + web UI + install-media server + SQLite state.
# Builds and runs with Podman (no Docker Desktop licence needed), Colima, Rancher Desktop or Docker.
#   podman build -t groundzero -f Containerfile .      (or: scripts/gz-container build)

FROM ghcr.io/astral-sh/uv:0.8 AS uv

FROM python:3.12-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --system --uid 10001 --home-dir /data groundzero \
 && mkdir -p /data /isos && chown groundzero /data
COPY --from=build /app/.venv /app/.venv
# State (SQLite, API token, encryption key, TLS cert, built media) lives in the /data volume.
# Stock ISOs are mounted read-only at /isos. The API listens on all interfaces *inside* the
# container; publish it to 127.0.0.1 only. The media server uses an unprivileged port; publish it as 443.
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    GROUNDZERO_HOME=/data \
    GROUNDZERO_ISO_REPOSITORY=/isos \
    GROUNDZERO_BIND_HOST=0.0.0.0 \
    GROUNDZERO_MEDIA_PORT=8443
USER groundzero
VOLUME ["/data"]
EXPOSE 7182 8443
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7182/healthz', timeout=3)"
ENTRYPOINT ["groundzero"]
CMD ["serve"]
