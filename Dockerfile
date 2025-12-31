# Multi-stage Dockerfile for USMCA Discord Bot
# Optimized for production deployment

# ============================================================================
# Stage 1: Builder - Install dependencies and download ML models
# ============================================================================
FROM python:3.11-slim as builder

# Set working directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY pyproject.toml ./

# Install dependencies to /install
RUN pip install --no-cache-dir --prefix=/install .

# Download ML models during build (cache them in image)
RUN python -c "from detoxify import Detoxify; Detoxify('original')" || true

# ============================================================================
# Stage 2: Runtime - Minimal production image
# ============================================================================
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user for security
RUN useradd -m -u 1000 botuser && \
    mkdir -p /app /models && \
    chown -R botuser:botuser /app /models

# Set working directory
WORKDIR /app

# Copy installed dependencies from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY --chown=botuser:botuser src/ ./src/
COPY --chown=botuser:botuser sql/ ./sql/

# Copy ML models from builder (if they were downloaded)
COPY --from=builder /root/.cache/torch /home/botuser/.cache/torch

# Fix ownership of cache directory
RUN chown -R botuser:botuser /home/botuser/.cache

# Switch to non-root user
USER botuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import asyncio; from usmca_bot.bot import USMCABot; print('healthy')" || exit 1

# Run the bot
CMD ["python", "-m", "usmca_bot.cli"]