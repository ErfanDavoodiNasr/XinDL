# === Build Stage ===
FROM python:3.12-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# === Production Stage ===
FROM python:3.12-slim

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime dependencies (ffmpeg) and create non-root user
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd -r botgroup && \
    useradd -r -g botgroup botuser && \
    mkdir -p /app/data /app/downloads /app/cookies && \
    chown -R botuser:botgroup /app

# Copy wheels and install
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && \
    rm -rf /wheels && \
    find /usr/local -type d -name __pycache__ -prune -exec rm -rf {} + || true

# Copy application code
COPY --chown=botuser:botgroup src/ /app/src/

# Switch to non-root user
USER botuser

# Default command
CMD ["python", "-m", "src.bot.main"]

