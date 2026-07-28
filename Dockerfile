# ─────────────────────────────────────────────────────────────────────────────
# SafeHer Backend — Multi-stage Dockerfile
# Stage 1: build dependencies (including librosa C extensions)
# Stage 2: lean production image
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# System deps for librosa (CFFI, libsndfile) and cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make \
    libsndfile1-dev \
    libffi-dev \
    libssl-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install Python deps into a dedicated prefix for easy copy
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: production image ─────────────────────────────────────────────────
FROM python:3.12-slim

LABEL maintainer="SafeHer Team <dev@safeher.app>"
LABEL description="SafeHer Women Safety Platform — FastAPI Backend"

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# ── App setup ─────────────────────────────────────────────────────────────────
WORKDIR /app

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash safeher && \
    mkdir -p /app/uploads /app/app/ml/models && \
    chown -R safeher:safeher /app

# Copy source code
COPY --chown=safeher:safeher . .

# Switch to non-root
USER safeher

# Environment defaults (override via docker-compose or k8s secrets)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    WORKERS=4 \
    ENVIRONMENT=production

EXPOSE 8000

# ── Health check ──────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ── Start ─────────────────────────────────────────────────────────────────────
CMD ["gunicorn", "app.main:app", "-c", "gunicorn.conf.py"]
