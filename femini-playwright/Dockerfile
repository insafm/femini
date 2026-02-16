# Use Python 3.11 slim image for smaller size
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONHASHSEED=random
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies for Playwright
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
    libxss1 \
    libxtst6 \
    libxrandr2 \
    libasound2 \
    libpangocairo-1.0-0 \
    libatk1.0-0 \
    libcairo-gobject2 \
    libgtk-3-0 \
    libgdk-pixbuf2.0-0 \
    # Additional dependencies
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r femini && useradd -r -g femini femini

# Create directories
RUN mkdir -p /app/user_data /app/cookies /app/downloads /app/logs && \
    chown -R femini:femini /app

# Set work directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

# Copy application code
COPY . .

# Change ownership of the app directory
RUN chown -R femini:femini /app

# Switch to non-root user
USER femini

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import asyncio; from src.config import settings; print('Health check passed')" || exit 1

# Default command
CMD ["python", "-m", "src.main"]