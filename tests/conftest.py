import argparse

import pytest

from odoo_completion.discovery import classify
from odoo_completion.probe import describe


@pytest.fixture
def schema(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server = argparse.ArgumentParser()
    server.add_argument("-d", "--database", dest="db_name")
    server.add_argument("-u", "--update", dest="update")
    server.add_argument("--addons-path", dest="addons_path")
    server.add_argument("--test-tags", dest="test_tags")
    server.add_argument("--log-level", choices=["debug", "info", "warn"])
    server.add_argument("--dev", dest="dev_mode")
    server.add_argument("--config", "-c")
    server.add_argument("--db_host")
    server.add_argument("--logfile")
    server.add_argument("--without-demo", nargs="?")
    server.add_argument("-v", action="count")
    module = argparse.ArgumentParser()
    install = module.add_subparsers().add_parser("install")
    install.add_argument("modules", nargs="+")
    install.add_argument("-d", dest="db_name")
    database = argparse.ArgumentParser()
    subs = database.add_subparsers()
    load = subs.add_parser("load")
    load.add_argument("database", nargs="?")
    load.add_argument("dump_file")
    init = subs.add_parser("init")
    init.add_argument("database")
    commands = {"server": describe(server), "module": describe(module), "db": describe(database)}
    for name, node in commands.items():
        classify(node, (name,))
    addons = tmp_path / "addons"
    for name in ("sale", "account", "account_payment"):
        module_dir = addons / name
        module_dir.mkdir(parents=True)
        (module_dir / "__manifest__.py").write_text("{}")
    return {
        "protocol": 1,
        "commands": commands,
        "root": str(tmp_path),
        "version": "20.0",
        "defaults": {"addons_path": [str(addons)]},
        "env": {"addons_path": "ODOO_ADDONS_PATH", "db_host": "PGHOST"},
        "index": {
            "tests": [
                {
                    "module": "sale",
                    "file": "sale/tests/test_sale.py",
                    "class": "TestSale",
                    "methods": ["test_total"],
                    "tags": ["standard", "post_install"],
                }
            ]
        },
    }
