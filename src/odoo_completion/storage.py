"""Small atomic stores; completion must tolerate missing and corrupt state."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path


def config_dir():
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "odoo-completion"


def cache_dir():
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "odoo-completion"


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=True, separators=(",", ":"))
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def identity(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:24]


def registrations():
    value = read_json(config_dir() / "registrations.json", {})
    return value if isinstance(value, dict) else {}


def executable(command, cwd=None):
    if "/" in command:
        return str((Path(cwd or Path.cwd()) / command).absolute())
    return shutil.which(command) or command


def select(command, cwd):
    entries = registrations()
    path = executable(command, cwd)
    if path in entries:
        return entries[path]
    resolved = str(Path(path).resolve())
    for entry in entries.values():
        if resolved == str(Path(entry["root"], "odoo-bin").resolve()):
            return entry
    return None


def schema_path(entry):
    return cache_dir() / (
        identity([entry["root"], entry["python"], entry.get("addons", []), entry.get("overrides")])
        + ".json"
    )


def load_schema(entry):
    value = read_json(schema_path(entry)) if entry else None
    if not isinstance(value, dict) or value.get("protocol") != 1 or not value.get("commands"):
        value = read_json(Path(__file__).parent / "data" / "odoo20.json", {})
    return value
