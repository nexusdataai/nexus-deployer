# Nexus Operator Dockerfile
# Runs as non-root user (UID 1000) for security
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt awscli

ARG KUBECTL_VERSION=v1.29.6
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && ARCH=$(dpkg --print-architecture) \
    && case "$ARCH" in amd64) KARCH=amd64 ;; arm64) KARCH=arm64 ;; *) echo "unsupported arch: $ARCH"; exit 1 ;; esac \
    && curl -fsSL -o /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${KARCH}/kubectl" \
    && chmod 755 /usr/local/bin/kubectl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r -g 1000 nexus && \
    useradd -r -u 1000 -g 1000 -m -d /home/nexus -s /bin/bash nexus && \
    mkdir -p /home/nexus /tmp && \
    chown -R nexus:nexus /home/nexus /tmp

COPY --chown=nexus:nexus src/nexus_operator/ ./nexus_operator/
COPY --chown=nexus:nexus manifests/ ./manifests/
COPY --chown=nexus:nexus inspect-capability.sh /app/inspect-capability.sh
COPY --chown=nexus:nexus cleanup-capability.sh /app/cleanup-capability.sh
RUN chmod 755 /app/inspect-capability.sh /app/cleanup-capability.sh

RUN chown -R nexus:nexus /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HOME=/home/nexus
ENV USER=nexus
ENV AWS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

USER 1000:1000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/healthz')" || exit 1

ENTRYPOINT ["python", "-m", "nexus_operator.main"]
