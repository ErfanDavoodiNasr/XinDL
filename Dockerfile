# === Build Stage ===
FROM python:3.11-alpine as builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache build-base

COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# === Production Stage ===
FROM python:3.11-alpine

# Create directories
RUN mkdir -p /app/data /app/downloads

# Install runtime dependencies (ffmpeg)
RUN apk add --no-cache ffmpeg

WORKDIR /app

# Copy wheels from builder and install
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy application code
COPY src/ /app/src/

# Remove any pycache and unnecessary files to reduce image size
RUN find . -type d -name "__pycache__" -exec rm -r {} + || true

# Default command (Bot)
CMD ["python", "-m", "src.bot.main"]
