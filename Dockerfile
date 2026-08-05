# Multi-stage: build dependencies first, then runtime image.
FROM python:3.12-slim AS base

# Browser runtime dependencies (Chromium + Firefox need these)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 libxcomposite1 \
    libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 libxshmfence1 \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency resolution
COPY pyproject.toml README.md LICENSE ./
RUN pip install --no-cache-dir uv && \
    uv pip install --system --no-cache .

# Download browser binaries (Camoufox Firefox + Patchright Chromium)
RUN python -m camoufox fetch || echo "camoufox fetch skipped (will retry at runtime)"
RUN patchright install chromium || echo "patchright install skipped (will retry at runtime)"

COPY app/ ./app/

EXPOSE 8321

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8321/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8321"]
