import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from odoo_completion import database
from odoo_completion.storage import cache_dir


def pg_binary(name):
    installed = shutil.which(name)
    if installed:
        return installed
    paths = sorted(Path("/usr/lib/postgresql").glob(f"*/bin/{name}"))
    return str(paths[-1]) if paths else None


@pytest.fixture(scope="module")
def postgres(tmp_path_factory):
    initdb, pg_ctl = pg_binary("initdb"), pg_binary("pg_ctl")
    if not initdb or not pg_ctl:
        pytest.skip("PostgreSQL server binaries not installed")
    if os.geteuid() == 0:
        pytest.skip("initdb requires an unprivileged test user")
    directory = tmp_path_factory.mktemp("postgres")
    data = directory / "data"
    subprocess.run(
        [initdb, "-D", str(data), "-A", "trust", "-U", "completion_test", "--no-locale"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            pg_ctl,
            "-D",
            str(data),
            "-l",
            str(directory / "log"),
            "-o",
            f"-h '' -k {directory} -p 55439",
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    params = {
        "host": str(directory),
        "port": 55439,
        "user": "completion_test",
        "dbname": "postgres",
    }
    import psycopg

    with psycopg.connect(**params, autocommit=True) as connection:
        connection.execute("CREATE DATABASE completion_example")
        connection.execute("CREATE TABLE ir_module_module (name text, state text)")
        connection.execute(
            "INSERT INTO ir_module_module VALUES ('sale', 'installed'), ('unused', 'uninstalled')"
        )
    try:
        yield params
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
            check=True,
            capture_output=True,
        )


def test_real_metadata_is_read_only(postgres, monkeypatch):
    assert "completion_example" in database.query({"kind": "database", "params": postgres})
    assert database.query({"kind": "installed_module", "params": postgres}) == ["sale"]
    monkeypatch.setitem(database.QUERIES, "database", "DELETE FROM ir_module_module RETURNING name")
    import psycopg

    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        database.query({"kind": "database", "params": postgres})


def test_worker_cache_and_secret_handling(postgres, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    config = {
        "db_host": postgres["host"],
        "db_port": postgres["port"],
        "db_user": postgres["user"],
        "db_password": "do-not-cache-this",
        "db_name": "postgres",
    }
    assert "completion_example" in database.candidates("database", config)
    assert database.candidates("installed_module", config) == ["sale"]
    monkeypatch.setattr(database.subprocess, "run", lambda *a, **kw: pytest.fail("cache miss"))
    assert "completion_example" in database.candidates("database", config)
    for path in cache_dir().rglob("*.json"):
        assert "do-not-cache-this" not in path.read_text()


def test_failed_connection_is_quiet_and_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    start = time.monotonic()
    assert (
        database.candidates(
            "database", {"db_host": str(tmp_path / "missing"), "db_user": "missing"}
        )
        == []
    )
    assert time.monotonic() - start < 0.6


def test_timeout_keeps_last_result(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 0.3
        raise subprocess.TimeoutExpired(args[0], 0.3)

    monkeypatch.setattr(database.subprocess, "run", timeout)
    assert database.candidates("database", {}) == []
