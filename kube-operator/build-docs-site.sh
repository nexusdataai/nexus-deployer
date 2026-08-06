#!/usr/bin/env bash
#
# Build MkDocs output into nexus-ui/docs-site for nginx /docs/ serving.
#
# Usage:
#   ./build-docs-site.sh <frontend-dir> [docs-dir]
#
set -euo pipefail

FRONTEND_DIR="${1:-}"
DOCS_DIR="${2:-}"

if [ -z "${FRONTEND_DIR}" ]; then
    echo "Usage: $0 <frontend-dir> [docs-dir]"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCS_DIR="${DOCS_DIR:-$(cd "${SCRIPT_DIR}/../../nexus-docs" 2>/dev/null && pwd || echo "")}"
DOCS_VENV="${DOCS_VENV:-/tmp/docs-venv}"

echo "Building documentation into ${FRONTEND_DIR}/docs-site ..."

if [ -n "${DOCS_DIR}" ] && [ -d "${DOCS_DIR}" ] && [ -f "${DOCS_DIR}/mkdocs.yml" ]; then
    cd "${DOCS_DIR}"
    if [ ! -x "${DOCS_VENV}/bin/python" ] || ! "${DOCS_VENV}/bin/python" -c "import mkdocs" 2>/dev/null; then
        rm -rf "${DOCS_VENV}"
        python3 -m venv "${DOCS_VENV}"
        "${DOCS_VENV}/bin/pip" install -q -r requirements.txt
    fi
    "${DOCS_VENV}/bin/python" -m mkdocs build -q
    rm -rf "${FRONTEND_DIR}/docs-site"
    cp -r site "${FRONTEND_DIR}/docs-site"
    echo "Docs built: $(find "${FRONTEND_DIR}/docs-site" -name 'index.html' | wc -l) pages"
    if [ ! -f "${FRONTEND_DIR}/docs-site/index.html" ]; then
        echo "ERROR: docs-site/index.html missing after MkDocs build"
        exit 1
    fi
else
    echo "Docs repo not found at ${DOCS_DIR:-<unset>}, creating placeholder docs-site"
    mkdir -p "${FRONTEND_DIR}/docs-site"
    cat > "${FRONTEND_DIR}/docs-site/index.html" <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Documentation unavailable</title></head>
<body><h1>Documentation not available</h1><p>The docs site was not built into this image.</p></body>
</html>
EOF
fi
