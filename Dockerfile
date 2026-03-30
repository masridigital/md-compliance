FROM python:3.12-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packages into a prefix so we can copy them cleanly
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install -r requirements.txt

# Final application image
FROM python:3.12-slim AS app
WORKDIR /app

# Runtime system dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# Git config for in-app updates (safe directory + remote)
RUN git config --global --add safe.directory /app

# Ensure startup script is executable
RUN chmod +x run.sh

CMD ["/bin/bash", "run.sh"]
