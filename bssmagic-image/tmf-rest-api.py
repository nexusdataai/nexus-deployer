#!/usr/bin/env python3
"""
TMF REST API gateway on port 8000.

Handles locally:
  - POST /query          — SOQL-to-SQL translation via FDW foreign tables
  - POST to writable views — INSERT with RETURNING + fallback ID query
                             (critical for Lead ID -> ContentVersion chain)

Proxies to product TMF Server (port 8001):
  - GET requests          — OpenAPI-driven filtering, pagination, field selection
  - All other paths       — metadata, docs, health, etc.

Zero external dependencies — stdlib only.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from http.server import HTTPServer
from urllib.parse import urlparse, parse_qs

TMF_SERVER_PORT = int(os.environ.get("TMF_SERVER_INTERNAL_PORT", "8001"))

VIEWS = {
    "/tmf-api/salesManagement/v4/salesLead": {
        "view": 'mapping."salesLead"',
        "writable": True,
    },
    "/tmf-api/productCatalogManagement/v5/productOffering": {
        "view": 'mapping."productOffering"',
        "writable": False,
    },
    "/tmf-api/productCatalogManagement/v5/productOfferingPrice": {
        "view": 'mapping."productOfferingPrice"',
        "writable": False,
    },
    "/tmf-api/documentManagement/v1/contentVersion": {
        "view": 'mapping."contentVersion"',
        "writable": True,
    },
    "/tmf-api/documentManagement/v1/contentDocumentLink": {
        "view": 'mapping."contentDocumentLink"',
        "writable": True,
    },
    "/tmf-api/documentManagement/v1/attachment": {
        "view": 'mapping."attachment"',
        "writable": True,
    },
}


def run_sql(sql):
    """Execute SQL via psql and return stdout, stderr."""
    result = subprocess.run(
        ["psql", "-U", "postgres", "-d", "bssmagic", "-t", "-A", "-c", sql],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout.strip(), result.stderr.strip()


def escape_sql_string(value):
    """Escape a value for safe SQL inclusion."""
    if value is None:
        return "NULL"
    s = str(value).replace("'", "''")
    return f"'{s}'"


_fdw_schema_cache = None
_view_columns_cache = {}
_COLUMN_CACHE_TTL = 300
_ft_columns_cache = {}


def get_ft_columns(schema, table):
    """
    Return a case-insensitive mapping of column names for a foreign table.
    Key = lowercase column name, value = actual column name.
    """
    import time
    now = time.time()
    cache_key = f"{schema}.{table}"

    cached = _ft_columns_cache.get(cache_key)
    if cached:
        mapping, ts = cached
        if now - ts < _COLUMN_CACHE_TTL:
            return mapping

    sql = (
        f"SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema='{schema}' AND table_name='{table}';"
    )
    stdout, _ = run_sql(sql)
    mapping = {}
    if stdout:
        for line in stdout.split('\n'):
            col = line.strip()
            if col:
                mapping[col.lower()] = col
    _ft_columns_cache[cache_key] = (mapping, now)
    return mapping


def get_view_columns(view_ref):
    """
    Return the set of column names for a view (e.g. mapping."SalesLead").
    Results are cached with a TTL so that columns added by
    apply-tmf-mappings.sh (which runs after DB restore) are picked up.
    """
    import time
    now = time.time()

    cached = _view_columns_cache.get(view_ref)
    if cached:
        cols, ts = cached
        if now - ts < _COLUMN_CACHE_TTL:
            return cols

    parts = view_ref.replace('"', '').split('.')
    if len(parts) == 2:
        schema, table = parts
    else:
        return set()
    sql = (
        f"SELECT column_name FROM information_schema.columns "
        f"WHERE table_schema='{schema}' AND table_name='{table}';"
    )
    stdout, _ = run_sql(sql)
    cols = set()
    if stdout:
        cols = {line.strip() for line in stdout.split('\n') if line.strip()}
    _view_columns_cache[view_ref] = (cols, now)
    return cols


def get_fdw_schema():
    """Get the FDW foreign server name used as the schema for foreign tables."""
    global _fdw_schema_cache
    if _fdw_schema_cache:
        return _fdw_schema_cache
    out, err = run_sql("SELECT srvname FROM pg_foreign_server LIMIT 1;")
    if out:
        _fdw_schema_cache = out.strip()
    return _fdw_schema_cache


SQL_KEYWORDS = {
    'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'LIKE', 'IN', 'IS',
    'NULL', 'LIMIT', 'OFFSET', 'ORDER', 'BY', 'ASC', 'DESC', 'BETWEEN',
    'AS', 'HAVING', 'GROUP', 'COUNT', 'SUM', 'AVG', 'MIN', 'MAX',
    'TRUE', 'FALSE', 'DISTINCT',
}


def soql_to_fdw_sql(soql, schema):
    """
    Translate a SOQL-ish query to SQL against the FDW foreign tables.

    Tokenises the input and:
      - SQL keywords  -> pass through (upper-cased)
      - FROM <object> -> schema-qualified: "schema"."object"
      - identifiers   -> double-quoted, case-corrected against FDW columns
      - relationship fields (X__r.Y) -> replaced with NULL (FDW can't JOIN)
      - string literals, numbers, operators -> unchanged
    """
    soql_clean = re.sub(r'\b\w+__r\.\w+', 'NULL', soql)

    from_match = re.search(r'\bFROM\s+(\w+)', soql_clean, re.IGNORECASE)
    table_name = from_match.group(1) if from_match else None

    col_map = {}
    if table_name:
        col_map = get_ft_columns(schema, table_name)

    def fix_case(identifier):
        if col_map:
            actual = col_map.get(identifier.lower())
            if actual:
                return actual
        return identifier

    result = []
    i = 0
    expect_table = False

    while i < len(soql_clean):
        ch = soql_clean[i]

        if ch == "'":
            j = i + 1
            while j < len(soql_clean):
                if soql_clean[j] == "'" and j + 1 < len(soql_clean) and soql_clean[j + 1] == "'":
                    j += 2
                    continue
                if soql_clean[j] == "'":
                    break
                j += 1
            result.append(soql_clean[i:j + 1])
            i = j + 1
            continue

        m = re.match(r'([A-Za-z_]\w*)', soql_clean[i:])
        if m:
            word = m.group(1)
            upper = word.upper()

            if upper in SQL_KEYWORDS:
                result.append(upper)
                expect_table = (upper == 'FROM')
            elif expect_table:
                result.append(f'"{schema}"."{word}"')
                expect_table = False
            else:
                result.append(f'"{fix_case(word)}"')

            i += len(word)
            continue

        nm = re.match(r'\d+(?:\.\d+)?', soql_clean[i:])
        if nm:
            result.append(nm.group())
            i += len(nm.group())
            continue

        result.append(ch)
        i += 1

    return ''.join(result), None


# ---------------------------------------------------------------------------
# Reverse proxy helper
# ---------------------------------------------------------------------------

def _proxy_request(method, path, headers, body=None):
    """Forward a request to the product TMF Server on the internal port."""
    url = f"http://localhost:{TMF_SERVER_PORT}{path}"
    req = urllib.request.Request(url, data=body, method=method)
    for key, val in headers.items():
        if key.lower() in ('host', 'transfer-encoding', 'content-length'):
            continue
        req.add_header(key, val)
    if body is not None:
        req.add_header('Content-Length', str(len(body)))
    return urllib.request.urlopen(req, timeout=60)


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class TMFHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, data):
        body = json.dumps(data, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _proxy_to_tmf_server(self):
        """Reverse proxy: forward request to product TMF Server on internal port."""
        body = None
        if self.command in ('POST', 'PUT', 'PATCH'):
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length else None
        try:
            resp = _proxy_request(self.command, self.path, self.headers, body)
            self.send_response(resp.status)
            for key, val in resp.headers.items():
                if key.lower() in ('transfer-encoding',):
                    continue
                self.send_header(key, val)
            self.end_headers()
            self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            body_bytes = e.read()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        except (urllib.error.URLError, ConnectionRefusedError):
            self._send_json(502, {
                "error": "TMF Server not ready on internal port",
                "hint": "The product TMF Server may still be starting up. Retry in a few seconds.",
            })

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path in ("", "/"):
            endpoints = [{"path": "/query", "methods": ["POST"]}]
            for p, cfg in VIEWS.items():
                methods = ["GET", "POST"] if cfg["writable"] else ["GET"]
                endpoints.append({"path": p, "methods": methods})
            self._send_json(200, {"endpoints": endpoints})
            return

        # Proxy all GETs to the product TMF Server for OpenAPI-driven filtering
        self._proxy_to_tmf_server()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode()

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON body"})
            return

        if not payload:
            self._send_json(400, {"error": "Empty payload"})
            return

        if path == "/query":
            self._handle_query(payload)
            return

        # Handle writes locally (RETURNING + fallback ID query)
        if path in VIEWS and VIEWS[path]["writable"]:
            self._handle_write(path, payload)
            return

        # Everything else proxied to TMF Server
        # Re-encode body since we already consumed it
        body_bytes = json.dumps(payload).encode()
        try:
            req = urllib.request.Request(
                f"http://localhost:{TMF_SERVER_PORT}{self.path}",
                data=body_bytes,
                method='POST',
            )
            req.add_header('Content-Type', 'application/json')
            req.add_header('Content-Length', str(len(body_bytes)))
            resp = urllib.request.urlopen(req, timeout=60)
            self.send_response(resp.status)
            for key, val in resp.headers.items():
                if key.lower() in ('transfer-encoding',):
                    continue
                self.send_header(key, val)
            self.end_headers()
            self.wfile.write(resp.read())
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            resp_body = e.read()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
        except (urllib.error.URLError, ConnectionRefusedError):
            self._send_json(502, {
                "error": "TMF Server not ready on internal port",
            })

    def do_PUT(self):
        self._proxy_to_tmf_server()

    def do_PATCH(self):
        self._proxy_to_tmf_server()

    def do_DELETE(self):
        self._proxy_to_tmf_server()

    def _handle_write(self, path, payload):
        """Handle POST writes locally via INSTEAD OF triggers with ID fallback."""
        config = VIEWS[path]
        view = config["view"]

        filtered = dict(payload)
        dropped = []
        max_retries = 3
        returning_id = None

        for attempt in range(max_retries):
            columns = ", ".join(f'"{k}"' for k in filtered.keys())
            values = ", ".join(escape_sql_string(v) for v in filtered.values())

            sql = f"INSERT INTO {view} ({columns}) VALUES ({values}) RETURNING id;"
            stdout, stderr = run_sql(sql)

            if stderr and "ERROR" in stderr:
                col_match = re.search(
                    r'column "([^"]+)" of relation "[^"]+" does not exist',
                    stderr
                )
                if col_match and attempt < max_retries - 1:
                    bad_col = col_match.group(1)
                    if bad_col in filtered:
                        dropped.append(bad_col)
                        del filtered[bad_col]
                        continue

                sql_plain = f"INSERT INTO {view} ({columns}) VALUES ({values});"
                stdout2, stderr2 = run_sql(sql_plain)
                if stderr2 and "ERROR" in stderr2:
                    col_match2 = re.search(
                        r'column "([^"]+)" of relation "[^"]+" does not exist',
                        stderr2
                    )
                    if col_match2 and attempt < max_retries - 1:
                        bad_col = col_match2.group(1)
                        if bad_col in filtered:
                            dropped.append(bad_col)
                            del filtered[bad_col]
                            continue
                    self._send_json(400, {"error": stderr2})
                    return
                stdout = ""
                break

            raw = stdout.strip() if stdout else ""
            if "\n" in raw:
                raw = raw.split("\n")[0].strip()
            sys.stderr.write(
                f"[TMF-REST] RETURNING id parsed: {repr(raw)}\n"
            )
            if raw and not raw.startswith("INSERT") and len(raw) >= 15:
                returning_id = raw
            break

        resp = {
            "status": "created",
            "resource": path,
            "fieldsProvided": list(filtered.keys()),
        }
        if dropped:
            resp["fieldsDropped"] = dropped

        record_id = returning_id
        if not record_id:
            record_id = self._post_insert_id_query(view, filtered)
        if record_id:
            resp["id"] = record_id
        else:
            sys.stderr.write(
                f"[TMF-REST] WARNING: INSERT into {view} succeeded "
                f"but could not retrieve record ID\n"
            )

        self._send_json(201, resp)

    def _post_insert_id_query(self, view, payload):
        """
        After a successful INSERT into a writable view, query Salesforce
        via FDW to retrieve the ID of the most recently created record.
        Fallback for when RETURNING doesn't work reliably with Multicorn.
        """
        schema = get_fdw_schema()
        if not schema:
            return None

        view_lower = view.lower().replace('"', '')

        if "saleslead" in view_lower:
            last = payload.get("familyName", "")
            company = payload.get("name", "")
            email = payload.get("email", "")
            if not last or not company:
                return None
            soql = (
                f"SELECT Id FROM Lead "
                f"WHERE LastName = {escape_sql_string(last)} "
                f"AND Company = {escape_sql_string(company)} "
            )
            if email:
                soql += f"AND Email = {escape_sql_string(email)} "
            soql += "ORDER BY CreatedDate DESC LIMIT 1"

        elif "contentversion" in view_lower:
            title = payload.get("title", "")
            path_on_client = payload.get("pathOnClient", "")
            if not title:
                return None
            soql = (
                f"SELECT Id, ContentDocumentId FROM ContentVersion "
                f"WHERE Title = {escape_sql_string(title)} "
            )
            if path_on_client:
                soql += f"AND PathOnClient = {escape_sql_string(path_on_client)} "
            soql += "ORDER BY CreatedDate DESC LIMIT 1"

        else:
            return None

        sys.stderr.write(f"[TMF-REST] Post-insert ID query SOQL: {soql}\n")
        sql_query, _ = soql_to_fdw_sql(soql, schema)
        wrapped = f"SELECT json_agg(row_to_json(t)) FROM ({sql_query}) t;"
        stdout, stderr = run_sql(wrapped)

        if stderr and "ERROR" in stderr:
            sys.stderr.write(
                f"[TMF-REST] Post-insert ID query FAILED: {stderr[:500]}\n"
            )
            return None

        if not stdout or stdout in ("", "null", "None"):
            sys.stderr.write(
                f"[TMF-REST] Post-insert ID query returned empty/null\n"
            )
            return None

        try:
            records = json.loads(stdout)
            if records and len(records) > 0:
                found_id = records[0].get("Id")
                sys.stderr.write(
                    f"[TMF-REST] Post-insert ID query found: {found_id}\n"
                )
                return found_id
        except (json.JSONDecodeError, IndexError, TypeError) as e:
            sys.stderr.write(
                f"[TMF-REST] Post-insert ID query parse error: {e}, "
                f"stdout={stdout[:200]}\n"
            )

        return None

    def _handle_query(self, payload):
        """
        Handle POST /query - route SOQL through FDW foreign tables.

        Body: {"query": "SELECT Id, Name FROM RecordType WHERE SObjectType = 'Lead' LIMIT 10"}
        Response: {"records": [...], "totalSize": N}
        """
        soql = payload.get("query", "")
        if not soql:
            self._send_json(400, {"error": "Missing 'query' field"})
            return

        schema = get_fdw_schema()
        if not schema:
            self._send_json(503, {
                "error": "FDW foreign server not ready (schema discovery failed)"
            })
            return

        sql_query, err = soql_to_fdw_sql(soql, schema)
        if err:
            self._send_json(400, {"error": err, "soql": soql})
            return

        wrapped = f"SELECT json_agg(row_to_json(t)) FROM ({sql_query}) t;"
        stdout, stderr = run_sql(wrapped)

        if stderr and "ERROR" in stderr:
            self._send_json(500, {
                "error": stderr,
                "sql": sql_query,
                "soql": soql,
            })
            return

        if not stdout or stdout in ("", "null", "None"):
            records = []
        else:
            try:
                records = json.loads(stdout)
                if records is None:
                    records = []
            except json.JSONDecodeError:
                records = []

        self._send_json(200, {
            "records": records,
            "totalSize": len(records),
        })

    def log_message(self, format, *args):
        sys.stderr.write(
            f"[TMF-REST] {self.address_string()} - {format % args}\n"
        )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("0.0.0.0", port), TMFHandler)
    print(f"=== TMF REST API gateway on 0.0.0.0:{port} ===")
    print(f"  Proxying reads to product TMF Server on localhost:{TMF_SERVER_PORT}")
    print(f"  Handling writes and /query locally")
    print(f"  [POST] http://localhost:{port}/query")
    for path, config in VIEWS.items():
        methods = "GET, POST" if config["writable"] else "GET"
        print(f"  [{methods}] http://localhost:{port}{path}")
    print("=" * 60)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
