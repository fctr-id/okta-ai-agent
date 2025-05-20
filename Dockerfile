# Stage 1: Build the frontend
FROM node:24-slim AS frontend-builder

WORKDIR /app/frontend

# Copy frontend source code
COPY src/frontend/ ./

# Install dependencies and build the frontend
RUN npm ci && \
    npm run build

# Stage 2: Python application with built frontend
FROM python:3.12-slim

WORKDIR /app

# Install OpenSSL for certificate generation and curl for healthchecks
RUN apt-get update && apt-get install -y \
    openssl \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy Python requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Python source code
COPY src /app/src

# Copy built frontend assets from the frontend builder stage
COPY --from=frontend-builder /app/backend/app/static/ /app/src/backend/app/static/

# Create necessary directories
RUN mkdir -p /app/src/backend/certs /app/sqlite_db /app/logs

# Create startup script for SSL and server
RUN echo '#!/bin/bash \n\
# Generate SSL certificates if they don\'t exist \n\
if [ ! -f /app/src/backend/certs/cert.pem ] || [ ! -f /app/src/backend/certs/key.pem ]; then \n\
  echo "Generating SSL certificates..." \n\
  mkdir -p /app/src/backend/certs \n\
  openssl req -x509 -newkey rsa:2048 -keyout /app/src/backend/certs/key.pem -out /app/src/backend/certs/cert.pem -sha256 -days 3650 -nodes \
  -subj "/C=US/ST=State/L=City/O=Okta AI Agent/OU=Development/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,DNS:127.0.0.1,DNS:host.docker.internal" \n\
  echo "SSL certificates generated successfully" \n\
fi \n\
\n\
# Start the server with SSL \n\
exec python -m uvicorn src.backend.app.main:app --host 0.0.0.0 --port 8001 --ssl-keyfile /app/src/backend/certs/key.pem --ssl-certfile /app/src/backend/certs/cert.pem \n\
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