# Totogi Operator Dockerfile
# Runs as non-root user (UID 1000) for security
FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies (all packages have pre-built wheels)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt awscli

# aws CLI v1 + kubectl for /app/inspect-capability.sh and /app/cleanup-capability.sh (in-cluster IRSA)
ARG KUBECTL_VERSION=v1.29.6
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in amd64) KARCH=amd64 ;; arm64) KARCH=arm64 ;; *) echo "unsupported arch: $ARCH"; exit 1 ;; esac \
    && curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${KARCH}/kubectl" \
    && chmod 755 /usr/local/bin/kubectl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with proper UID/GID
# UID 1000 matches Kubernetes security context
RUN groupadd -r -g 1000 totogi && \
    useradd -r -u 1000 -g 1000 -m -d /home/totogi -s /bin/bash totogi && \
    mkdir -p /home/totogi /tmp && \
    chown -R totogi:totogi /home/totogi /tmp

# Copy application code
COPY --chown=totogi:totogi src/totogi_operator/ ./totogi_operator/
COPY --chown=totogi:totogi manifests/ ./manifests/
COPY --chown=totogi:totogi inspect-capability.sh /app/inspect-capability.sh
COPY --chown=totogi:totogi cleanup-capability.sh /app/cleanup-capability.sh
RUN chmod 755 /app/inspect-capability.sh /app/cleanup-capability.sh

# Set proper ownership for app directory
RUN chown -R totogi:totogi /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HOME=/home/totogi
ENV USER=totogi
# Explicit CA bundle for botocore/boto3 (override in cluster if you mount a custom bundle)
ENV AWS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Switch to non-root user
USER 1000:1000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')" || exit 1

# Run the operator
ENTRYPOINT ["python", "-m", "totogi_operator.main"]
