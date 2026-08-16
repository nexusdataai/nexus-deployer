#!/usr/bin/env python3
"""
Ensure pgvector Postgres is available for semantic_rag on the DR target.

Deploys (or verifies) a pgvector StatefulSet, initializes control_plane_embeddings,
patches the backend with FDW_PG_* env vars, and restarts the backend if needed.

Exit 0 on success; exit 1 on failure.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import List, Optional, Tuple

PG_STS = "pgvector"
PG_SVC = "pgvector-svc"
PG_DB = "ontology_cp"
PG_USER = "nexus"
PG_PASSWORD = "nexus"
VECTOR_INIT_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS control_plane_embeddings (
    id SERIAL PRIMARY KEY,
    content_type VARCHAR(50) NOT NULL,
    source_id VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(content_type, source_id)
);
CREATE INDEX IF NOT EXISTS idx_cpe_content_type ON control_plane_embeddings(content_type);
"""


def _run(cmd: List[str], timeout: int = 120) -> Tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, out


def _backend_has_fdw(namespace: str, deployment: str) -> bool:
    rc, out = _run([
        "kubectl", "get", "deployment", deployment, "-n", namespace,
        "-o", "jsonpath={.spec.template.spec.containers[0].env[?(@.name=='FDW_PG_HOST')].value}",
    ])
    return rc == 0 and bool(out.strip())


def _discover_postgres_image(namespace: str, deployment: str) -> str:
    """Prefer public pgvector image; ECR nexus-sre-postgres may be absent on DR targets."""
    return "pgvector/pgvector:pg16"


def _postgres_manifest(namespace: str, image: str) -> str:
    return f"""apiVersion: v1
kind: Service
metadata:
  name: {PG_SVC}
  namespace: {namespace}
  labels:
    app: {PG_STS}
    nexus.ai/component: pgvector
spec:
  type: ClusterIP
  selector:
    app: {PG_STS}
  ports:
    - port: 5432
      targetPort: 5432
      name: postgres
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {PG_STS}
  namespace: {namespace}
  labels:
    app: {PG_STS}
    nexus.ai/component: pgvector
spec:
  serviceName: {PG_SVC}
  replicas: 1
  selector:
    matchLabels:
      app: {PG_STS}
  template:
    metadata:
      labels:
        app: {PG_STS}
    spec:
      containers:
        - name: postgres
          image: {image}
          ports:
            - containerPort: 5432
              name: postgres
          env:
            - name: POSTGRES_USER
              value: "{PG_USER}"
            - name: POSTGRES_PASSWORD
              value: "{PG_PASSWORD}"
            - name: POSTGRES_DB
              value: "{PG_DB}"
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          readinessProbe:
            exec:
              command: ["pg_isready", "-U", "{PG_USER}", "-d", "{PG_DB}"]
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            exec:
              command: ["pg_isready", "-U", "{PG_USER}", "-d", "{PG_DB}"]
            initialDelaySeconds: 15
            periodSeconds: 20
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 1Gi
          volumeMounts:
            - name: pgvector-data
              mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
    - metadata:
        name: pgvector-data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 5Gi
        storageClassName: gp2
"""


def _apply_manifest(manifest: str) -> Tuple[bool, str]:
    proc = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=manifest,
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode == 0, out


def _wait_postgres_ready(namespace: str, timeout: int = 300) -> Tuple[bool, str]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rc, out = _run([
            "kubectl", "get", "statefulset", PG_STS, "-n", namespace,
            "-o", "jsonpath={.status.readyReplicas}/{.spec.replicas}",
        ])
        if rc == 0 and out.strip() in ("1/1", "1"):
            rc2, _ = _run([
                "kubectl", "exec", "-n", namespace, f"statefulset/{PG_STS}", "--",
                "pg_isready", "-U", PG_USER, "-d", PG_DB,
            ])
            if rc2 == 0:
                return True, "postgres ready"
        time.sleep(5)
    return False, f"postgres not ready after {timeout}s"


def _init_schema(namespace: str) -> Tuple[bool, str]:
    rc, out = _run([
        "kubectl", "exec", "-n", namespace, f"statefulset/{PG_STS}", "--",
        "psql", "-U", PG_USER, "-d", PG_DB, "-v", "ON_ERROR_STOP=1", "-c", VECTOR_INIT_SQL,
    ], timeout=180)
    if rc != 0:
        return False, out
    _run([
        "kubectl", "exec", "-n", namespace, f"statefulset/{PG_STS}", "--",
        "bash", "-lc",
        "psql -U nexus -d ontology_cp -c \"CREATE EXTENSION IF NOT EXISTS age;\" 2>/dev/null || true; "
        "psql -U nexus -d ontology_cp -c \"LOAD 'age'; SET search_path = ag_catalog, public; "
        "SELECT create_graph('enterprise_onto');\" 2>/dev/null || true",
    ], timeout=60)
    return True, "schema initialized"


def _set_backend_env_merge(namespace: str, deployment: str) -> Tuple[bool, str]:
    """Merge FDW env vars without replacing existing env."""
    env_pairs = [
        ("FDW_PG_HOST", PG_SVC),
        ("FDW_PG_PORT", "5432"),
        ("FDW_PG_DATABASE", PG_DB),
        ("FDW_PG_USER", PG_USER),
        ("FDW_PG_PASSWORD", PG_PASSWORD),
        ("FDW_PG_SCHEMA", "public"),
    ]
    for name, value in env_pairs:
        rc, out = _run([
            "kubectl", "set", "env", f"deployment/{deployment}", "-n", namespace,
            f"{name}={value}",
        ])
        if rc != 0:
            return False, out
    return True, "backend env updated"


def _restart_backend(namespace: str, deployment: str, timeout: int = 180) -> Tuple[bool, str]:
    rc, out = _run(["kubectl", "rollout", "restart", f"deployment/{deployment}", "-n", namespace])
    if rc != 0:
        return False, out
    rc, out = _run([
        "kubectl", "rollout", "status", f"deployment/{deployment}", "-n", namespace,
        f"--timeout={timeout}s",
    ], timeout=timeout + 30)
    if rc != 0:
        return False, out
    rc, _ = _run([
        "kubectl", "exec", "-n", namespace, f"deploy/{deployment}", "--",
        "curl", "-sf", "--max-time", "15", "http://127.0.0.1:8000/health",
    ])
    if rc != 0:
        return False, "backend health check failed after restart"
    return True, "backend restarted and healthy"


def _verify_embeddings_table(namespace: str) -> Tuple[bool, str]:
    rc, out = _run([
        "kubectl", "exec", "-n", namespace, f"statefulset/{PG_STS}", "--",
        "psql", "-U", PG_USER, "-d", PG_DB, "-t", "-A", "-c",
        "SELECT count(*) FROM information_schema.tables WHERE table_name='control_plane_embeddings';",
    ])
    if rc != 0:
        return False, out
    if out.strip() != "1":
        return False, "control_plane_embeddings table missing"
    return True, "control_plane_embeddings exists"


def run(args: argparse.Namespace) -> int:
    namespace = args.namespace
    deployment = args.deployment

    print(f"  namespace:   {namespace}")
    print(f"  deployment:  {deployment}")
    print(f"  postgres:    {PG_SVC}:5432/{PG_DB}")
    print()

    if _backend_has_fdw(namespace, deployment):
        print("  OK    backend-fdw           FDW_PG_HOST already set")
        ok, msg = _wait_postgres_ready(namespace, timeout=60)
        if ok:
            print(f"  OK    postgres-ready        {msg}")
            ok2, msg2 = _verify_embeddings_table(namespace)
            if ok2:
                print(f"  OK    embeddings-table      {msg2}")
                return 0
            print(f"  INFO  re-init schema          {msg2}")
        else:
            print(f"  WARN  postgres                {msg} — will deploy")

    image = args.image or _discover_postgres_image(namespace, deployment)
    print(f"  image:       {image}")

    ok, msg = _apply_manifest(_postgres_manifest(namespace, image))
    if not ok:
        print(f"  FAIL  apply-manifest          {msg}")
        return 1
    print(f"  OK    apply-manifest          {msg}")

    ok, msg = _wait_postgres_ready(namespace, timeout=args.timeout)
    if not ok:
        print(f"  FAIL  postgres-ready          {msg}")
        return 1
    print(f"  OK    postgres-ready          {msg}")

    ok, msg = _init_schema(namespace)
    if not ok:
        print(f"  FAIL  init-schema             {msg}")
        return 1
    print(f"  OK    init-schema             {msg}")

    if not _backend_has_fdw(namespace, deployment):
        ok, msg = _set_backend_env_merge(namespace, deployment)
        if not ok:
            print(f"  FAIL  backend-env             {msg}")
            return 1
        print(f"  OK    backend-env             {msg}")

        ok, msg = _restart_backend(namespace, deployment)
        if not ok:
            print(f"  FAIL  backend-restart         {msg}")
            return 1
        print(f"  OK    backend-restart         {msg}")
    else:
        ok, msg = _restart_backend(namespace, deployment)
        if ok:
            print(f"  OK    backend-restart         {msg}")
        else:
            print(f"  WARN  backend-restart         {msg}")

    ok, msg = _verify_embeddings_table(namespace)
    if not ok:
        print(f"  FAIL  embeddings-table        {msg}")
        return 1
    print(f"  OK    embeddings-table        {msg}")

    print()
    print("  pgvector: OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensure pgvector Postgres for DR semantic_rag")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--deployment", required=True)
    parser.add_argument("--image", help="Postgres image (default: derive from backend ECR)")
    parser.add_argument("--timeout", type=int, default=300, help="Wait timeout seconds")
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
