# docker/Dockerfile
FROM python:3.11-slim-bookworm

# ── System deps ───────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin poietes \
    && mkdir -p /app /workspace \
    && chown poietes:poietes /app /workspace

# ── Install security tools ────────────────────────────────────────────────────
RUN pip install --no-cache-dir bandit safety pip-audit

# ── App ───────────────────────────────────────────────────────────────────────
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers to a shared path so the non-root user can use them
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright || true

COPY --chown=poietes:poietes . .

# ── Runtime ───────────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

USER poietes

# Config is mounted read-only at runtime from ../config
ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
