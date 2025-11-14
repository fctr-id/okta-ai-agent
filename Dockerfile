# Stage 1: Build the frontend
FROM --platform=$BUILDPLATFORM node:24-slim AS frontend-builder

WORKDIR /app/frontend

# Copy frontend source code
COPY src/frontend/ ./

# Create the target directory for the build output
RUN mkdir -p ../api/static

# Install dependencies and build the frontend
RUN npm ci && \
    npm run build

# Stage 2: Python application with built frontend  
FROM python:3.13-slim

WORKDIR /app

# Install OpenSSL for certificate generation and curl for healthchecks
RUN apt-get update && apt-get install -y \
    openssl \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install UV for faster package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy Python requirements and install dependencies with UV (10-100x faster)
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy main entry point
COPY main.py /app/

# Copy Python source code (excluding legacy folder)
COPY src/api /app/src/api
COPY src/backend /app/src/backend
COPY src/config /app/src/config
COPY src/core /app/src/core
COPY src/data /app/src/data
COPY src/utils /app/src/utils

# Copy built frontend assets from the frontend builder stage
# Frontend builds to ../api/static relative to the frontend directory
COPY --from=frontend-builder /app/api/static/ /app/src/api/static/

# Create necessary directories
RUN mkdir -p /app/certs /app/sqlite_db /app/logs

# Create startup script for SSL and server
RUN echo '#!/bin/bash \n\
# Generate SSL certificates if they don\'t exist \n\
if [ ! -f /app/certs/cert.pem ] || [ ! -f /app/certs/key.pem ]; then \n\
  echo "Generating SSL certificates..." \n\
  mkdir -p /app/certs \n\
  openssl req -x509 -newkey rsa:2048 -keyout /app/certs/key.pem -out /app/certs/cert.pem -sha256 -days 3650 -nodes \
  -subj "/C=US/ST=State/L=City/O=Okta AI Agent/OU=Development/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:127.0.0.1,DNS:host.docker.internal" \n\
  echo "SSL certificates generated successfully" \n\
fi \n\
\n\
# Start the server with SSL \n\
exec python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8001 --ssl-keyfile /app/certs/key.pem --ssl-certfile /app/certs/cert.pem \n\
' > /app/start.sh && chmod +x /app/start.sh

# Environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose HTTPS port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD curl -k https://localhost:8001/health || exit 1

# Start the server with SSL
CMD ["/app/start.sh"]