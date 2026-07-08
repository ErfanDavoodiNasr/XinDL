# syntax=docker/dockerfile:1
# === Build Stage ===
FROM python:3.12-slim-bookworm AS builder

WORKDIR /build

# Install build dependencies (host network required on servers with broken docker bridge)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip wheel --wheel-dir /build/wheels -r requirements.txt

# === Production Stage ===
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:${PATH}"

WORKDIR /app

# Runtime deps: ffmpeg, nodejs (yt-dlp EJS), deno, non-root user
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg nodejs libcurl4 unzip ca-certificates curl && \
    curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -r botgroup && \
    useradd -r -g botgroup botuser && \
    mkdir -p /app/data /app/downloads /app/cookies && \
    chown -R botuser:botgroup /app

COPY --from=builder /build/wheels /wheels
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir /wheels/* && \
    rm -rf /wheels && \
    find /usr/local -type d -name __pycache__ -prune -exec rm -rf {} + || true

COPY --chown=botuser:botgroup src/ /app/src/

CMD ["python", "-m", "src.bot.main"]
