# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONHASHSEED=random
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONPATH=/app

# Install system dependencies required by femini-playwright
RUN apt-get update && apt-get install -y \
    # Playwright dependencies
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxtst6 \
    libpangocairo-1.0-0 \
    libatk1.0-0 \
    libcairo-gobject2 \
    # Additional dependencies
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r femini && useradd -r -g femini femini

# Create directories and set permissions
RUN mkdir -p /app/data /app/downloads /app/logs /app/cookies /app/user_data && \
    chmod -R 777 /app/data /app/downloads /app/logs /app/cookies /app/user_data && \
    chown -R femini:femini /app

# Set work directory
WORKDIR /app

# Copy requirements files first (for better caching)
COPY femini-playwright/requirements.txt /tmp/femini-playwright-reqs.txt
COPY femini-api/requirements.txt /tmp/api-reqs.txt

# Install Python dependencies (cached if requirements don't change)
RUN pip install --no-cache-dir -r /tmp/femini-playwright-reqs.txt && \
    pip install --no-cache-dir -r /tmp/api-reqs.txt && \
    rm /tmp/femini-playwright-reqs.txt /tmp/api-reqs.txt

# Copy and install femini-playwright package
COPY femini-playwright/ /tmp/femini-playwright/
RUN pip install --no-cache-dir /tmp/femini-playwright && \
    rm -rf /tmp/femini-playwright

# Set Playwright browsers path to shared location
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

# Install Playwright browsers as root (with system dependencies)
RUN playwright install chromium --with-deps

# Copy API application code (last, as it changes most frequently)
COPY femini-api/src/ ./src/

# Change ownership before switching user
RUN chown -R femini:femini /app && \
    chmod -R 755 /opt/ms-playwright

# Switch to non-root user
USER femini

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${API_PORT:-12000}/api/v1/health || exit 1

# Expose API port
EXPOSE 12000

# Default command
CMD ["python", "-m", "src.api_server"]
