# LandPPT Docker Image
# Multi-stage build for minimal image size

# Build stage
FROM python:3.11-slim-bookworm AS builder

# Set environment variables for build
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers \
    PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS=1

# Install build dependencies
ARG APT_DEBIAN_URL=http://deb.debian.org/debian
ARG APT_SECURITY_URL=http://deb.debian.org/debian-security
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i "s|http://deb.debian.org/debian|${APT_DEBIAN_URL}|g" /etc/apt/sources.list.d/debian.sources; \
      sed -i "s|http://deb.debian.org/debian-security|${APT_SECURITY_URL}|g" /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
      sed -i "s|http://deb.debian.org/debian|${APT_DEBIAN_URL}|g" /etc/apt/sources.list; \
      sed -i "s|http://deb.debian.org/debian-security|${APT_SECURITY_URL}|g" /etc/apt/sources.list; \
    fi; \
    apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 update; \
    apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    libpq-dev \
    libatomic1 \
    ; \
    rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
RUN pip install --no-cache-dir uv

# Create a dedicated virtualenv for runtime dependencies.
# Note: `uv sync` defaults to `.venv`; we explicitly sync to this env via `--active`.
RUN uv venv /opt/venv --python python3.11

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# Set work directory and copy dependency files
WORKDIR /app
COPY pyproject.toml uv.lock* uv.toml README.md ./
COPY src/ ./src/

# Install Python dependencies using uv
# uv sync will create venv at UV_PROJECT_ENVIRONMENT and install all dependencies
RUN uv sync --active --no-dev --frozen --extra-index-url=https://pypi.apryse.com && \
    # Clean up build artifacts
    find /opt/venv -name "*.pyc" -delete && \
    find /opt/venv -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Sanity check: fail the build early if core runtime deps are missing.
RUN /opt/venv/bin/python -c "import fastapi, uvicorn, edge_tts; print('Core deps installed')"

# Install Playwright browsers in builder stage
RUN mkdir -p /opt/playwright-browsers && \
    /opt/venv/bin/python -m playwright install chromium || \
    (echo "Retrying with mirror..." && \
     PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright \
     /opt/venv/bin/python -m playwright install chromium)

# Production stage
FROM python:3.11-slim-bookworm AS production

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src:/opt/venv/lib/python3.11/site-packages \
    PATH=/opt/venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers \
    HOME=/root \
    VIRTUAL_ENV=/opt/venv \
    WORKERS=4 \
    RELOAD=false

# Allow overriding Debian mirrors (useful in restricted networks).
ARG APT_DEBIAN_URL=http://deb.debian.org/debian
ARG APT_SECURITY_URL=http://deb.debian.org/debian-security

# Install essential runtime dependencies
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i "s|http://deb.debian.org/debian|${APT_DEBIAN_URL}|g" /etc/apt/sources.list.d/debian.sources; \
      sed -i "s|http://deb.debian.org/debian-security|${APT_SECURITY_URL}|g" /etc/apt/sources.list.d/debian.sources; \
    elif [ -f /etc/apt/sources.list ]; then \
      sed -i "s|http://deb.debian.org/debian|${APT_DEBIAN_URL}|g" /etc/apt/sources.list; \
      sed -i "s|http://deb.debian.org/debian-security|${APT_SECURITY_URL}|g" /etc/apt/sources.list; \
    fi; \
    apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 update; \
    apt-get install -y --no-install-recommends \
    ffmpeg \
    poppler-utils \
    libmagic1 \
    libpq5 \
    ca-certificates \
    curl \
    wget \
    libgomp1 \
    libatomic1 \
    fonts-liberation \
    fonts-noto-cjk \
    fontconfig \
    netcat-openbsd \
    libjpeg62-turbo \
    libxrender1 \
    libfontconfig1 \
    libx11-6 \
    libxext6 \
    # Chromium/Playwright runtime dependencies
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    # GPU acceleration support (optional, for NVIDIA containers)
    libegl1 \
    libgl1 \
    libgles2 \
    ; \
    fc-cache -fv; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.cache

# Create non-root user (for compatibility, but run as root)
RUN groupadd -r landppt && \
    useradd -r -g landppt -m -d /home/landppt landppt

# Copy Python packages from builder
COPY --from=builder /opt/venv /opt/venv

# Copy Playwright browsers from builder
COPY --from=builder /opt/playwright-browsers /opt/playwright-browsers

# Sanity check: ensure the copied venv is usable in the runtime image.
RUN /opt/venv/bin/python -c "import fastapi, uvicorn; print('Runtime venv OK')"

# Set permissions for landppt user and playwright browsers
RUN chown -R landppt:landppt /home/landppt && \
    chmod -R 755 /opt/playwright-browsers

# Set work directory
WORKDIR /app

# Copy application code (minimize layers)
COPY run.py ./
COPY src/ ./src/
COPY template_examples/ ./template_examples/
COPY docker-healthcheck.sh docker-entrypoint.sh /usr/local/bin/
COPY .env.example ./.env

# Create directories and set permissions in one layer
RUN sed -i 's/\r$//' /usr/local/bin/docker-healthcheck.sh /usr/local/bin/docker-entrypoint.sh && \
    chmod +x /usr/local/bin/docker-healthcheck.sh /usr/local/bin/docker-entrypoint.sh && \
    mkdir -p temp/ai_responses_cache temp/style_genes_cache temp/summeryanyfile_cache temp/templates_cache \
             research_reports lib/Linux lib/MacOS lib/Windows uploads data && \
    chown -R landppt:landppt /app /home/landppt && \
    chmod -R 755 /app /home/landppt && \
    chmod 666 /app/.env

# Expose port
EXPOSE 8000

# Minimal health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=2 \
    CMD ["/usr/local/bin/docker-healthcheck.sh"]

# Set entrypoint and command
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/opt/venv/bin/python", "run.py"]
