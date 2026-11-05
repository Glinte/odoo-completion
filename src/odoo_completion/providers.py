"""Value providers independent of shell syntax and Odoo imports."""

import json
import os
import subprocess
import time
from pathlib import Path

from . import database
from .index import module_paths
from .model import Candidate, candidate
from .storage import cache_dir, identity, read_json, write_json

LIST_PROVIDERS = {
    "modules",
    "installed_modules",
    "databases",
    "directories",
    "files",
    "languages",
    "dev",
    "log_handler",
    "models",
    "columns",
}
SINGULAR = {
    "modules": "module",
    "installed_modules": "installed_module",
    "databases": "database",
    "directories": "directory",
    "files": "file",
    "languages": "language",
}


def source_index(schema: dict) -> dict:
    if "index" in schema:
        return schema["index"]
    return read_json(schema.get("index_file", ""), {})


def available_modules(config: dict) -> list[str]:
    paths = config.get("addons_path", [])
    key = identity(["modules", paths])
    filename = cache_dir() / "values" / (key + ".json")
    cached = read_json(filename, {})
    if time.time() - cached.get("updated", 0) < 5:
        return cached.get("values", [])
    values = sorted(module_paths(paths))
    try:
        write_json(filename, {"updated": time.time(), "values": values})
    except OSError:
        pass
    return values


def paths(prefix: str, cwd: str, directories_only: bool = False) -> list[Candidate]:
    expanded = os.path.expandvars(os.path.expanduser(prefix))
    path = Path(cwd) / expanded
    parent = path if expanded.endswith("/") else path.parent
    name_prefix = "" if expanded.endswith("/") else path.name
    if not expanded:
        parent, name_prefix = Path(cwd), ""
    display_parent = prefix[: len(prefix) - len(prefix.rsplit("/", 1)[-1])] if "/" in prefix else ""
    try:
        children = sorted(parent.iterdir())
    except OSError:
        return []
    results = []
    for child in children:
        if not child.name.startswith(name_prefix):
            continue
        if child.name.startswith(".") and not name_prefix.startswith("."):
            continue
        is_directory = child.is_dir()
        if directories_only and not is_directory:
            continue
        value = display_parent + child.name + ("/" if is_directory else "")
        results.append(
            candidate(
                value,
                "Directory" if is_directory else "File",
                "directory" if is_directory else "file",
            )
        )
    return results


def test_selectors(prefix: str, schema: dict, config: dict) -> list[Candidate]:
    # A comma inside a parameter expression is not a selector separator.
    depth, last_comma = 0, -1
    for i, char in enumerate(prefix):
        if char == "[":
            depth += 1
        elif char == "]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            last_comma = i
    if depth:
        return []
    previous, selector = prefix[: last_comma + 1], prefix[last_comma + 1 :]
    sign = selector[:1] if selector.startswith(("-", "+")) else ""
    selector = selector[len(sign) :]
    tests = source_index(schema).get("tests", [])
    values = set()
    if ":" in selector:
        scope, class_method = selector.split(":", 1)
        module_or_file = scope.partition("/")[2]
        matching = [
            t for t in tests if not module_or_file or module_or_file in (t["module"], t["file"])
        ]
        if "." in class_method:
            klass, _ = class_method.split(".", 1)
            values.update(
                f"{scope}:{klass}.{method}"
                for t in matching
                if not klass or t["class"] == klass
                for method in t["methods"]
            )
        else:
            values.update(f"{scope}:{t['class']}" for t in matching)
    elif "/" in selector:
        tag, module_or_file = selector.split("/", 1)
        values.update(f"{tag}/{module}" for module in available_modules(config))
        values.update(f"{tag}/{t['file']}" for t in tests)
    elif "." in selector:
        values.update("." + method for t in tests for method in t["methods"])
    else:
        values.update(("standard", "at_install", "post_install", "*", "/"))
        values.update(tag for test in tests for tag in test["tags"])
    return [
        candidate(previous + sign + value, "Test selector")
        for value in sorted(values)
        if value.startswith(selector)
    ]


def log_handlers(prefix: str, config: dict) -> list[str]:
    levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if ":" in prefix:
        logger = prefix.partition(":")[0]
        return [f"{logger}:{level}" for level in levels]
    loggers = ["", "odoo", "odoo.http", "odoo.sql_db", "werkzeug"]
    loggers.extend(f"odoo.addons.{module}" for module in available_modules(config))
    return [f"{logger}:" for logger in loggers]


def simple_values(
    provider: str, argument: dict, schema: dict, config: dict, prefix: str
) -> list[str]:
    if provider in ("choices", "dev", "shell", "log_level", "sslmode"):
        return argument["choices"]
    if provider == "module":
        return available_modules(config)
    if provider == "installed_module":
        return database.candidates(provider, config) or available_modules(config)
    if provider in database.QUERIES:
        values = database.candidates(provider, config)
        if provider == "models" and not values:
            return source_index(schema).get("models", [])
        return values
    if provider in ("language", "iso_language", "country"):
        return source_index(schema).get(provider, [])
    if provider == "log_handler":
        return log_handlers(prefix, config)
    if provider == "upgrade_script":
        directory = Path(schema.get("root", ".")) / "odoo/upgrade_code"
        return sorted(p.name for p in directory.glob("*.py"))
    if provider == "version":
        directory = Path(schema.get("root", ".")) / "odoo/upgrade_code"
        return sorted({p.name.split("-", 1)[0] for p in directory.glob("*.py")})
    return []


def complete_value(
    argument: dict, prefix: str, schema: dict, config: dict, cwd: str
) -> list[Candidate]:
    provider = argument.get("provider", "text")
    if provider == "external":
        return external_values(argument["argv"], prefix, cwd)
    if provider == "test_tags":
        return test_selectors(prefix, schema, config)
    head, part = "", prefix
    if provider in LIST_PROVIDERS:
        head, separator, part = prefix.rpartition(",")
        head = head + separator
    singular = SINGULAR.get(provider, provider)
    if singular in ("file", "directory"):
        result = paths(part, cwd, singular == "directory")
    elif provider == "template":
        directory = Path(schema.get("root", ".")) / "odoo/cli/templates"
        templates = [
            candidate(p.name, "Scaffold template")
            for p in directory.glob("*")
            if p.is_dir() and p.name != "base"
        ]
        result = templates + paths(part, cwd, directories_only=True)
    else:
        values = simple_values(singular, argument, schema, config, part)
        result = [candidate(value, argument.get("help", "")) for value in values]
        if argument.get("allow_files"):
            result += paths(part, cwd)
        if argument.get("allow_all"):
            result.append(candidate("all", "All modules"))
        if argument.get("allow_pot"):
            result.append(candidate("pot", "Translation template"))
    already_used = set(head.rstrip(",").split(",")) if head else set()
    return [
        {**item, "value": head + item["value"]}
        for item in result
        if item["value"].startswith(part) and item["value"] not in already_used
    ]


def external_values(argv: list[str], prefix: str, cwd: str) -> list[Candidate]:
    """Explicitly configured providers use JSON and argv, never a shell."""
    try:
        result = subprocess.run(
            argv,
            input=json.dumps({"protocol": 1, "prefix": prefix, "cwd": cwd}),
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=0.3,
            check=True,
        )
        values = json.loads(result.stdout)
        if not isinstance(values, list):
            return []
        return [
            candidate(value)
            for value in values
            if isinstance(value, str) and value.startswith(prefix)
        ]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
