"""Explicit parser discovery and coverage classification."""

import json
import os
import subprocess
import time
import tomllib
from pathlib import Path

from .storage import read_json, schema_path, write_json

# Semantic information which parsers cannot express. All other arguments are
# deliberately classified as unrestricted, rather than guessed from help prose.
PROVIDERS = {
    "config": "file",
    "data_dir": "directory",
    "addons_path": "directories",
    "upgrade_path": "directories",
    "pre_upgrade_scripts": "files",
    "pg_path": "directory",
    "init": "modules",
    "update": "installed_modules",
    "reinit": "modules",
    "server_wide_modules": "modules",
    "db_name": "databases",
    "database": "database",
    "db_template": "database",
    "db_system": "database",
    "db_sslmode": "sslmode",
    "log_db": "database",
    "modules": "module",
    "language": "language",
    "languages": "language",
    "load_language": "languages",
    "country": "country",
    "template": "template",
    "test_tags": "test_tags",
    "dev_mode": "dev",
    "shell_interface": "shell",
    "log_handler": "log_handler",
    "log_db_level": "log_level",
    "pidfile": "file",
    "import_partial": "file",
    "logfile": "file",
    "log_config": "file",
    "shell_file": "file",
    "test_file": "file",
    "screenshots": "directory",
    "screencasts": "directory",
    "dump_file": "file",
    "output": "file",
    "file": "file",
    "dest": "directory",
    "path": "file",
    "fields": "columns",
    "exclude": "columns",
    "models": "models",
    "blueprint": "blueprints",
    "resuming": "sessions",
    "smtp_ssl_certificate_filename": "file",
    "smtp_ssl_private_key_filename": "file",
    "geoip_city_db": "file",
    "geoip_country_db": "file",
    "from_version": "version",
    "to_version": "version",
    "script": "upgrade_script",
    "dump_path": "file",
    "files": "file",
}
CHOICES = {
    "sslmode": ["disable", "allow", "prefer", "require", "verify-ca", "verify-full"],
    "dev": ["all", "xml", "reload", "qweb", "access", "replica"],
    "shell": ["ipython", "ptpython", "bpython", "python"],
    "log_level": ["debug", "info", "warning", "error", "critical"],
}


def classify(node, path=()):
    for item in node["options"] + node["positionals"]:
        dest = item["dest"]
        provider = "none" if item["nargs"] == 0 else PROVIDERS.get(dest, "text")
        if "--without-demo" in item["flags"]:
            item["choices"] = ["True", "False"]
        if dest == "job_runners":
            item["choices"] = ["auto"]
        if item["choices"]:
            provider = "choices"
        elif item.get("type") == "path" and provider == "text":
            provider = "file"
        if path[:2] in (("db", "init"), ("db", "load")) and dest == "database":
            provider = "text"
        if path[:2] in (("db", "duplicate"), ("db", "rename")) and dest == "source":
            provider = "database"
        if path == ("scaffold",) and dest == "name":
            provider = "text"
        if path == ("scaffold",) and dest == "template":
            provider = "template"
        if path in (("start",), ("deploy",)) and dest == "path":
            provider = "directory"
        if path[:2] in (("module", "upgrade"), ("module", "uninstall")) and dest == "modules":
            provider = "installed_module"
        if dest == "modules" and path[:2] == ("i18n", "export"):
            provider = "module"
        if provider == "databases" and item.get("type") != "comma":
            provider = "database"
        if provider == "language" and path[:1] == ("i18n",):
            provider = "iso_language"
        item["allow_all"] = dest in ("init", "update", "reinit") or path[:2] == (
            "module",
            "upgrade",
        )
        item["allow_files"] = dest == "modules" and path[:2] == ("module", "install")
        item["allow_pot"] = path[:2] == ("i18n", "export")
        if provider in CHOICES:
            item["choices"] = CHOICES[provider]
        item["provider"] = provider
        item["reason"] = (
            "Unrestricted value; no finite candidate set"
            if provider == "text"
            else "Flag without a value"
            if provider == "none"
            else "Parser choices"
            if provider == "choices"
            else "Semantic provider: " + provider
        )
    for name, child in node["children"].items():
        classify(child, (*path, name))


def probe(entry, name):
    request = {"root": entry["root"], "addons": entry.get("addons", []), "command": name}
    process = subprocess.run(
        [entry["python"], "-B", str(Path(__file__).with_name("probe.py"))],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        timeout=20,
        cwd=entry["root"],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if process.returncode:
        # Last exception line only: don't expose config or captured CLI output.
        error = process.stderr.strip().splitlines()
        raise RuntimeError(error[-1] if error else "discovery process failed")
    return json.loads(process.stdout)


def fingerprint(files):
    result = {}
    for filename in files:
        try:
            stat = Path(filename).stat()
            result[filename] = [stat.st_mtime_ns, stat.st_size]
        except OSError:
            result[filename] = None
    return result


def apply_overrides(schema, filename):
    if not filename:
        return
    data = tomllib.loads(Path(filename).read_text())
    for name, node in data.get("command", {}).items():
        classify(node, (name,))
        schema["commands"][name] = node
        schema["errors"].pop(name, None)
    for override in data.get("argument", []):
        parts = override["command"].split()
        node = schema["commands"][parts[0]]
        for part in parts[1:]:
            node = node["children"][part]
        matches = [
            item
            for item in node["options"] + node["positionals"]
            if item["dest"] == override["dest"]
        ]
        if not matches:
            raise ValueError(
                f"Override argument not found: {override['command']} {override['dest']}"
            )
        item = matches[0]
        if "choices" in override:
            item.update(provider="choices", choices=override["choices"])
        if "provider" in override:
            item["provider"] = override["provider"]
        if "argv" in override:
            argv = override["argv"]
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(arg, str) for arg in argv)
            ):
                raise ValueError("Override argv must be a nonempty string array")
            item.update(provider="external", argv=argv)
        item["reason"] = "Explicit override"


def refresh(entry, progress=None):
    from .index import build_index

    base = probe(entry, "__base__")
    previous = read_json(schema_path(entry), {})
    commands, errors = {}, {}
    for name in base["commands"]:
        if progress:
            progress(name)
        try:
            commands[name] = probe(entry, name)
        except (RuntimeError, subprocess.TimeoutExpired, ValueError) as exc:
            errors[name] = str(exc)
            if name in previous.get("commands", {}):
                commands[name] = previous["commands"][name]
    # These commands parse their own options then forward remaining server options.
    for name in ("start", "cloc"):
        if name in commands:
            node = commands[name]
            existing = {flag for option in node["options"] for flag in option["flags"]}
            node["options"].extend(
                o for o in base["server"]["options"] if not existing.intersection(o["flags"])
            )
    for name, node in commands.items():
        classify(node, (name,))
    tracked = list(base["commands"].values()) + [
        str(Path(entry["root"]) / "odoo/tools/config.py"),
        str(Path(entry["root"]) / "odoo/release.py"),
    ]
    schema = {
        "protocol": 1,
        "commands": commands,
        "command_sources": base["commands"],
        "errors": errors,
        "version": base["version"],
        "defaults": base["defaults"],
        "env": base["env"],
        "addons": base["addons"],
        "sources": fingerprint(tracked + [str(Path(p).parent) for p in tracked] + base["addons"]),
        "updated": time.time(),
        "root": entry["root"],
        "index_file": str(schema_path(entry).with_suffix(".index.json")),
    }
    try:
        schema["revision"] = subprocess.check_output(
            ["git", "-C", entry["root"], "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        schema["revision"] = "unknown"
    apply_overrides(schema, entry.get("overrides"))
    if not commands:
        raise RuntimeError("No parsers captured; previous metadata retained")
    write_json(schema["index_file"], build_index(base["addons"], entry["root"]))
    write_json(schema_path(entry), schema)
    return schema


def coverage(schema):
    rows = []

    def walk(node, path):
        for item in node["options"] + node["positionals"]:
            rows.append(
                {
                    "command": path,
                    "argument": ", ".join(item["flags"]) or item["dest"],
                    "provider": item["provider"],
                    "reason": item["reason"],
                }
            )
        for name, child in node["children"].items():
            walk(child, path + " " + name)

    for name, node in schema["commands"].items():
        walk(node, name)
    return rows
