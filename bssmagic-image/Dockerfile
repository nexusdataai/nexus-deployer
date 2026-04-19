# =============================================================================
# BSS Magic Runtime — Kubernetes / EKS Deployment Image
# =============================================================================
# Phase 2: StarHub Proxy Mode with FDW -> Axway -> Salesforce
#
# Architecture:
#   Port 8000 — Python TMF REST API gateway (front-facing, single external port)
#               Handles /query and writes locally, proxies reads to TMF Server
#   Port 8001 — Product TMF Server (Spring Boot, internal only)
#   Port 5432 — PostgreSQL
#   Port 3000 — Controller health/metrics
#
# The TMF Server is moved to port 8001 via SERVER_PORT env var so that the
# Python gateway can serve as the single external API port on 8000.
#
# Custom OpenAPI specs (TMF699 SalesLead, Document Management) are injected
# into the TMF Server JAR at build time via jar uf.
#
# Build context: this directory (starhub-deployer/bssmagic-image/)
# =============================================================================

FROM 654654554404.dkr.ecr.us-east-1.amazonaws.com/nexus/bssmagic-runtime:latest

# ---- Move product TMF Server to internal port 8001 ----
ENV SERVER_PORT=8001
ENV TMF_SERVER_INTERNAL_PORT=8001
# ---- Tell TMF Server to look for views in the 'mapping' schema ----
ENV TMF_SCHEMA=mapping

# ---- AI Control Plane: Install pgvector + Apache AGE at BUILD TIME ----
# pgvector: vector similarity search for embeddings
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends postgresql-17-pgvector && \
    rm -rf /var/lib/apt/lists/*

# Apache AGE: graph traversal for ontology relationships (build from source for PG17)
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends git bison flex libreadline-dev make gcc postgresql-server-dev-17 && \
    cd /tmp && \
    git clone --branch release/PG17/1.7.0 --depth 1 https://github.com/apache/age.git && \
    cd /tmp/age && \
    make -j"$(nproc)" && make install && \
    cd /tmp && rm -rf age && \
    apt-get purge -y git bison flex libreadline-dev make gcc postgresql-server-dev-17 && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* \
    || echo "WARN: Apache AGE build failed — graph queries will use metadata fallback"

# ---- FDW: Overwrite with StarHub proxy-compatible versions ----
COPY salesforce_fdw_k8s.py /usr/local/lib/python3.11/dist-packages/fdw_salesforce/salesforce_fdw.py
COPY salesforce_fdw_services.py /usr/local/lib/python3.11/dist-packages/fdw_salesforce/salesforce_fdw_services.py

# ---- Controller patches (same as ECS Dockerfile) ----
COPY patch-fdw-server-name.js /tmp/patch-fdw-server-name.js
RUN node /tmp/patch-fdw-server-name.js && rm /tmp/patch-fdw-server-name.js

# ---- Inject custom OpenAPI specs into TMF Server JAR ----
# TMF699 SalesLead + Document Management (ContentVersion, ContentDocumentLink, Attachment)
# These are picked up by OpenApiSpecRegistry at startup via classpath:specs/**
COPY custom-specs/ /tmp/custom-specs/
RUN mkdir -p /tmp/BOOT-INF/classes/specs && \
    cp /tmp/custom-specs/*.yaml /tmp/BOOT-INF/classes/specs/ && \
    cd /tmp && jar uf /tmf-server-0.0.1-SNAPSHOT.jar \
      BOOT-INF/classes/specs/TMF699-Sales_Management.oas.yaml \
      BOOT-INF/classes/specs/DocumentManagement-ContentVersion.oas.yaml \
      BOOT-INF/classes/specs/DocumentManagement-ContentDocumentLink.oas.yaml \
      BOOT-INF/classes/specs/DocumentManagement-Attachment.oas.yaml && \
    rm -rf /tmp/BOOT-INF /tmp/custom-specs

# ---- Init helper (creates _bssmagic_table_list after boot) ----
COPY init-bssmagic-table-list.sh /usr/local/bin/init-bssmagic-table-list.sh
RUN chmod +x /usr/local/bin/init-bssmagic-table-list.sh

# ---- Baked-in database dump (baseline: 1661 foreign tables + TMF views) ----
COPY bssmagic-dump.sql.gz /opt/bssmagic-dump.sql.gz

# ---- Restore script (checks S3 mount first, then baked-in, then skips) ----
COPY restore-if-needed.sh /usr/local/bin/restore-if-needed.sh
RUN chmod +x /usr/local/bin/restore-if-needed.sh

# ---- TMF mapping SQL files (applied on startup after restore) ----
# Views are created in the 'mapping' schema (product convention).
COPY tmf-mappings/ /opt/tmf-mappings/
COPY apply-tmf-mappings.sh /usr/local/bin/apply-tmf-mappings.sh
RUN chmod +x /usr/local/bin/apply-tmf-mappings.sh

# ---- AI Control Plane extensions (pgvector + Apache AGE, runs after restore) ----
COPY init-extensions.sh /usr/local/bin/init-extensions.sh
RUN chmod +x /usr/local/bin/init-extensions.sh

# ---- TMF REST API gateway (port 8000, proxies reads to TMF Server on 8001) ----
COPY tmf-rest-api.py /usr/local/bin/tmf-rest-api.py
COPY start-tmf-rest-api.sh /usr/local/bin/start-tmf-rest-api.sh
RUN chmod +x /usr/local/bin/start-tmf-rest-api.sh

# ---- Strip Windows CRLF from all shell scripts & SQL (safeguard for Windows checkouts) ----
RUN sed -i 's/\r$//' /usr/local/bin/*.sh /opt/tmf-mappings/*.sql 2>/dev/null || true

# ---- Entrypoint: restore DB -> extensions -> apply TMF mappings -> init table list -> start API gateway -> original ----
RUN printf '#!/bin/bash\n\
/usr/local/bin/restore-if-needed.sh &\n\
/usr/local/bin/init-extensions.sh &\n\
/usr/local/bin/apply-tmf-mappings.sh &\n\
/usr/local/bin/init-bssmagic-table-list.sh &\n\
/usr/local/bin/start-tmf-rest-api.sh &\n\
exec bssmagic-entrypoint.sh "$@"\n' \
    > /usr/local/bin/k8s-entrypoint.sh && \
    chmod +x /usr/local/bin/k8s-entrypoint.sh

EXPOSE 5432 8000 3000

ENTRYPOINT ["/usr/local/bin/k8s-entrypoint.sh"]
