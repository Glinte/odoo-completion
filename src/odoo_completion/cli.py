"""Manage and diagnose checkout-aware Odoo shell completion."""

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .storage import config_dir, executable, load_schema, registrations, schema_path, write_json


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--version", action="version", version=__version__)
    commands = result.add_subparsers(dest="action", required=True)
    register = commands.add_parser("register", help="Register a checkout and discover its CLI")
    register.add_argument("--command", required=True)
    register.add_argument("--odoo-root", type=Path, required=True)
    register.add_argument("--python", type=Path, required=True)
    register.add_argument(
        "--addons-path", default="", help="Comma-separated extra addons directories"
    )
    register.add_argument("--overrides", type=Path)
    refresh = commands.add_parser("refresh", help="Refresh parsers and source indexes explicitly")
    refresh.add_argument("--all", action="store_true")
    refresh.add_argument("--command", default="odoo-bin")
    for action in ("init", "install", "uninstall"):
        commands.add_parser(action).add_argument("shell", choices=("bash", "zsh", "fish"))
    doctor = commands.add_parser("doctor", help="Report coverage, errors, and stale registrations")
    doctor.add_argument("--json", action="store_true")
    coverage = commands.add_parser(
        "coverage", help="List every argument and its completion behavior"
    )
    coverage.add_argument("--command", default="odoo-bin")
    coverage.add_argument("--json", action="store_true")
    complete = commands.add_parser("_complete", help=argparse.SUPPRESS)
    complete.add_argument("--shell", choices=("bash", "zsh", "fish", "json"), required=True)
    complete.add_argument("--line", required=True)
    complete.add_argument("--point", type=int, required=True)
    complete.add_argument("--word")
    complete.add_argument("--cwd", default=os.getcwd())
    return result


def refresh_entry(entry: dict) -> dict:
    from .discovery import refresh

    print(f"Discovering {entry['root']} ...", file=sys.stderr)
    schema = refresh(entry)
    count = len(schema["commands"])
    print(f"Odoo {schema['version']}: {count} commands, {len(schema['errors'])} discovery errors.")
    for name, error in schema["errors"].items():
        print(f"  {name}: {error}", file=sys.stderr)
    return schema


def register(args) -> int:
    root = args.odoo_root.expanduser().resolve()
    # Do NOT resolve the interpreter symlink: doing so bypasses the virtualenv.
    python = args.python.expanduser().absolute()
    if not (root / "odoo-bin").is_file() or not python.is_file():
        raise ValueError("Expected an Odoo source root and an existing Python interpreter")
    entry = {"root": str(root), "python": str(python), "addons": []}
    if args.addons_path:
        entry["addons"] = [
            str(Path(p).expanduser().resolve()) for p in args.addons_path.split(",") if p
        ]
    if args.overrides:
        entry["overrides"] = str(args.overrides.expanduser().resolve())
    command = executable(args.command)
    schema = refresh_entry(entry)
    entries = registrations()
    entries[command] = entry
    write_json(config_dir() / "registrations.json", entries)
    return bool(schema["errors"])


def diagnostics() -> list[dict]:
    from .discovery import coverage, fingerprint
    from .storage import read_json

    reports = []
    for command, entry in registrations().items():
        schema = read_json(schema_path(entry), {})
        sources = schema.get("sources", {})
        reports.append(
            {
                "command": command,
                "root": entry["root"],
                "version": schema.get("version"),
                "revision": schema.get("revision"),
                "commands": len(schema.get("commands", {})),
                "arguments": len(coverage(schema)) if schema.get("commands") else 0,
                "stale": not sources or fingerprint(sources) != sources,
                "errors": schema.get("errors", {}),
                "missing_interpreter": not Path(entry["python"]).is_file(),
            }
        )
    return reports


def emit_completions(args) -> None:
    from .engine import complete_line

    try:
        results = complete_line(args.line, args.point, args.cwd, args.shell, args.word)
    except (OSError, ValueError, KeyError, TypeError):
        results = []  # Completion failures must not break the interactive shell.
    if args.shell == "json":
        print(json.dumps({"protocol": 1, "candidates": results}))
        return
    for item in results:
        value, description = item["value"], item["description"] or " "
        if args.shell == "fish":
            print(f"{value}\t{description}")
        else:
            print(f"{item['kind']}\t{value}\t{description}")


def execute(args) -> int:
    if args.action == "_complete":
        emit_completions(args)
        return 0
    if args.action == "register":
        return register(args)
    if args.action in ("init", "install", "uninstall"):
        from . import integration

        if args.action == "init":
            print(integration.render(args.shell), end="")
        else:
            print(getattr(integration, args.action)(args.shell))
        return 0
    if args.action == "refresh":
        entries = registrations()
        selected = entries.values() if args.all else [entries[executable(args.command)]]
        unique = {str(schema_path(entry)): entry for entry in selected}
        return any([bool(refresh_entry(entry)["errors"]) for entry in unique.values()])
    if args.action == "coverage":
        from .discovery import coverage
        from .storage import select

        rows = coverage(load_schema(select(args.command, os.getcwd())))
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for row in rows:
                print(f"{row['command']}\t{row['argument']}\t{row['provider']}\t{row['reason']}")
        return 0
    reports = diagnostics()
    if args.json:
        print(json.dumps(reports, indent=2))
    elif not reports:
        print(
            "No registered checkouts. Using bundled Odoo 20 core metadata; run register for dynamic discovery."
        )
    else:
        for report in reports:
            status = "stale; run refresh" if report["stale"] else "current"
            print(
                f"{report['command']}: Odoo {report['version']}, {report['commands']} commands, "
                f"{report['arguments']} arguments ({status})"
            )
            if report["missing_interpreter"]:
                print("  Registered Python interpreter is missing; register the checkout again.")
            for name, error in report["errors"].items():
                print(f"  {name}: {error}")
    return int(any(r["errors"] or r["missing_interpreter"] for r in reports))


def main() -> None:
    args = parser().parse_args()
    try:
        status = execute(args)
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"odoo-completion: {error}", file=sys.stderr)
        status = 1
    raise SystemExit(status)
