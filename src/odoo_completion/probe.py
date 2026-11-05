"""Executed ONLY on explicit refresh, under the registered Odoo interpreter.

Trusted CLI imports are required. The audit guard prevents common accidental
side effects; it is deliberately not advertised as a sandbox for hostile code.
"""

import argparse
import contextlib
import ctypes.util
import functools
import io
import json
import optparse
import os
import sys
import tempfile
from pathlib import Path


class Captured(BaseException):
    def __init__(self, parser):
        self.parser = parser


def capture(parser, *args, **kwargs):
    raise Captured(parser)


def guard(event, args):
    if event == "open":
        mode, flags = args[1:3]
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        ):
            raise RuntimeError("discovery blocked a file write")
    if event in {
        "socket.connect",
        "socket.bind",
        "subprocess.Popen",
        "os.system",
        "os.fork",
        "os.remove",
        "os.rename",
        "os.rmdir",
        "os.mkdir",
        "os.truncate",
        "os.chmod",
        "os.link",
        "os.symlink",
        "os.exec",
        "os.posix_spawn",
    }:
        raise RuntimeError("discovery blocked " + event)


def describe(parser):
    result = {"options": [], "positionals": [], "children": {}, "help": parser.description or ""}
    if isinstance(parser, argparse.ArgumentParser):
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                helps = {x.dest: x.help for x in action._choices_actions}
                for name, subparser in action.choices.items():
                    node = describe(subparser)
                    node["help"] = helps.get(name) or node["help"]
                    result["children"][name] = node
                continue
            item = {
                "flags": action.option_strings,
                "dest": action.dest,
                "nargs": 1 if action.nargs is None else action.nargs,
                "choices": [str(x) for x in action.choices] if action.choices is not None else [],
                "help": "" if action.help == argparse.SUPPRESS else action.help or "",
                "hidden": action.help == argparse.SUPPRESS,
                "repeat": isinstance(action, (argparse._AppendAction, argparse._CountAction)),
                "type": getattr(action.type, "__name__", ""),
            }
            item["exclusive_with"] = sorted(
                {
                    other.dest
                    for group in parser._mutually_exclusive_groups
                    if action in group._group_actions
                    for other in group._group_actions
                    if other is not action
                }
            )
            result["options" if action.option_strings else "positionals"].append(item)
    else:
        for option in parser.option_list + [o for g in parser.option_groups for o in g.option_list]:
            flags = option._short_opts + option._long_opts
            if not flags or not getattr(option, "cli_loadable", True):
                continue
            result["options"].append(
                {
                    "flags": flags,
                    "dest": option.dest or "",
                    "nargs": option.nargs if option.takes_value() else 0,
                    "choices": list(option.choices or []),
                    "help": "" if option.help == optparse.SUPPRESS_HELP else option.help or "",
                    "hidden": option.help == optparse.SUPPRESS_HELP,
                    "repeat": option.action in ("append", "append_const", "count"),
                    "type": option.type or "",
                    "env": getattr(option, "env_name", ""),
                }
            )
    return result


def run(request):
    root = Path(request["root"])
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    # Ignore personal server configuration during parser extraction.
    for key in list(os.environ):
        if key.startswith("ODOO_") or key == "OPENERP_SERVER":
            del os.environ[key]
    os.environ["ODOO_RC"] = os.devnull
    sys.argv = [str(root / "odoo-bin"), "--help"]
    tempfile.gettempdir()  # stdlib probes writability once; do it before the guard
    ctypes.util.find_library = functools.cache(ctypes.util.find_library)
    ctypes.util.find_library("c")  # inotify imports this; resolving it may run ldconfig
    sys.addaudithook(guard)
    import odoo.cli.command as command
    from odoo import release
    from odoo.modules import initialize_sys_path
    from odoo.tools import config

    config["addons_path"] = request.get("addons", [])
    initialize_sys_path()
    import odoo.addons

    if request["command"] == "__base__":
        defaults = {
            k: config[k]
            for k in (
                "addons_path",
                "db_host",
                "db_port",
                "db_user",
                "db_sslmode",
                "db_system",
                "data_dir",
            )
            if k in config.options
        }
        defaults["addons_path"] = []  # registration paths are discovery scope, not runtime config
        defaults["db_password"] = ""  # never serialize secrets
        env = {k: v.env_name for k, v in config.options_index.items() if v.env_name}
        commands = {}
        for path in sorted((root / "odoo" / "cli").glob("*.py")):
            if path.stem not in ("__init__", "command"):
                commands[path.stem] = str(path)
        core_commands = set(commands)
        for directory in odoo.addons.__path__:
            for path in sorted(Path(directory).glob("*/cli/*.py")):
                if path.stem != "__init__" and command.Command.is_valid_name(path.stem):
                    if path.stem not in core_commands:
                        commands[path.stem] = str(path)
        return {
            "commands": commands,
            "defaults": defaults,
            "env": env,
            "addons": list(odoo.addons.__path__),
            "version": release.version,
            "server": describe(config.parser),
        }

    # Initial Odoo import parses defaults. Only intercept AFTER that has finished.
    argparse.ArgumentParser.parse_args = capture
    argparse.ArgumentParser.parse_known_args = capture
    optparse.OptionParser.parse_args = capture
    config.parse_config = lambda *a, **kw: capture(config.parser)
    config._parse_config = lambda *a, **kw: capture(config.parser)
    name = request["command"]
    if name == "help":
        return {"options": [], "positionals": [], "children": {}, "help": "Show available commands"}
    cls = command.find_command(name)
    if cls is None:
        raise ValueError("command not found")
    try:
        obj = cls()
        obj.run(["--help"])
    except Captured as captured:
        result = describe(captured.parser)
        result["help"] = cls.__doc__ or result["help"]
        return result
    raise ValueError("command did not reach a supported parser")


if __name__ == "__main__":
    request = json.load(sys.stdin)
    # Keep imported code's output off the protocol channel.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = run(request)
    print(json.dumps(result, default=str))
