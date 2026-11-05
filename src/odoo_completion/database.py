"""Read-only metadata queries, isolated behind a parent-enforced deadline."""

import json
import os
import subprocess
import sys
import time

from .storage import cache_dir, identity, read_json, write_json

QUERIES = {
    "database": "SELECT datname FROM pg_database WHERE datallowconn ORDER BY datname",
    "installed_module": "SELECT name FROM ir_module_module WHERE state IN ('installed', 'to upgrade', 'to remove') ORDER BY name",
    "models": "SELECT model FROM ir_model ORDER BY model",
    "columns": "SELECT table_name || '.' || column_name FROM information_schema.columns WHERE table_schema = 'public' ORDER BY 1",
    "blueprints": "SELECT module || '.' || name FROM ir_model_data WHERE model = 'populate.blueprint' ORDER BY 1",
    "sessions": "SELECT id::text FROM populate_session ORDER BY id DESC LIMIT 100",
}


def candidates(kind, config):
    selected = str(config.get("db_name", config.get("database", "")) or "").split(",")[0]
    if kind != "database" and not selected:
        return []
    params = {
        target: config[source]
        for source, target in (
            ("db_host", "host"),
            ("db_port", "port"),
            ("db_user", "user"),
            ("db_password", "password"),
            ("db_sslmode", "sslmode"),
        )
        if config.get(source) is not None
    }
    params["dbname"] = (config.get("db_system") or "postgres") if kind == "database" else selected
    # Only a hash of nonsecret connection identity is persisted.
    public = {k: v for k, v in params.items() if k != "password"}
    key = identity(
        [kind, public, os.environ.get("PGSERVICE", ""), os.environ.get("PGPASSFILE", "")]
    )
    path = cache_dir() / "values" / (key + ".json")
    cached = read_json(path, {})
    if time.time() - cached.get("updated", 0) < 30:
        return cached.get("values", [])
    try:
        process = subprocess.run(
            [sys.executable, "-m", "odoo_completion.database"],
            input=json.dumps({"kind": kind, "params": params}),
            capture_output=True,
            text=True,
            timeout=0.3,
        )
        if process.returncode:
            raise ValueError("unavailable database")
        values = json.loads(process.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        values = cached.get("values", [])
    try:
        write_json(path, {"updated": time.time(), "values": values})
    except OSError:
        pass
    return values


def query(request):
    import psycopg

    with psycopg.connect(
        **request["params"],
        connect_timeout=1,
        client_encoding="UTF8",
        options="-c default_transaction_read_only=on -c statement_timeout=200",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(QUERIES[request["kind"]])
            return [row[0] for row in cursor.fetchall()]


if __name__ == "__main__":
    try:
        print(json.dumps(query(json.load(sys.stdin))))
    except Exception:
        sys.exit(1)
