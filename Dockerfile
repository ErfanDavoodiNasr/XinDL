# === Build Stage ===
FROM python:3.12-alpine as builder

WORKDIR /build

# Install build dependencies
RUN apk add --no-cache build-base

COPY requirements.txt .
# Build wheels for all dependencies (no-deps removed so it builds everything)
RUN pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt

# === Production Stage ===
FROM python:3.12-alpine

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime dependencies (ffmpeg) and create non-root user
RUN apk add --no-cache ffmpeg && \
    addgroup -S botgroup && \
    adduser -S botuser -G botgroup && \
    mkdir -p /app/data /app/downloads && \
    chown -R botuser:botgroup /app

# Copy wheels and install
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && \
    rm -rf /wheels && \
    # Aggressive cleanup of python caches and unused files
    find /usr/local -depth \
    \( \
        -type d -a \( -name test -o -name tests -o -name idle_test -o -name __pycache__ \) \
    \) -exec rm -rf '{}' + || true && \
    find /usr/local -type f -name '*.pyc' -delete || true

# Copy application code
COPY --chown=botuser:botgroup src/ /app/src/

# Switch to non-root user
USER botuser

# Default command
CMD ["python", "-m", "src.bot.main"]
