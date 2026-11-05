"""Parse incomplete command lines without executing shell expansions."""

import os
from dataclasses import dataclass, field


def tokenize(line):
    words, buf = [], []
    quote = None
    escaped = False
    started = False
    for char in line:
        if escaped:
            buf.append(char)
            escaped = False
            started = True
        elif char == "\\" and quote != "'":
            escaped = True
            started = True
        elif quote:
            if char == quote:
                quote = None
            else:
                buf.append(char)
        elif char in "\"'":
            quote = char
            started = True
        elif char in "|;&\n":
            words, buf, started = [], [], False
        elif char.isspace():
            if started:
                words.append("".join(buf))
            buf, started = [], False
        else:
            buf.append(char)
            started = True
    return words, "".join(buf)


@dataclass
class Context:
    node: dict
    path: list[str]
    values: dict = field(default_factory=dict)
    used: set[str] = field(default_factory=set)
    pending: dict | None = None
    remaining: int | str = 0
    position: int = 0
    positional_used: int = 0
    end_options: bool = False
    invalid: bool = False
    choosing: bool = False

    @property
    def options(self) -> dict:
        return {flag: item for item in self.node["options"] for flag in item["flags"]}

    def record(self, argument: dict, value: str | bool) -> None:
        self.values[argument["dest"]] = value
        self.used.add(argument["dest"])

    def consume_pending(self, token: str) -> bool:
        if self.pending is None:
            return False
        flexible = self.remaining in ("?", "*", "+")
        if flexible and token.partition("=")[0] in self.options:
            self.pending = None
            return False
        self.record(self.pending, token)
        if isinstance(self.remaining, int):
            self.remaining -= 1
            if self.remaining == 0:
                self.pending = None
        elif self.remaining == "?":
            self.pending = None
        return True

    def consume_option(self, token: str) -> None:
        flag, separator, value = token.partition("=")
        argument = self.options.get(flag)
        if argument is None and not token.startswith("--"):
            argument, value = self.consume_cluster(token)
            separator = bool(value)
        if argument is None:
            self.invalid = True
            return
        self.used.add(argument["dest"])
        count = argument["nargs"]
        if count == 0:
            self.record(argument, True)
        elif not separator:
            self.pending, self.remaining = argument, count
        else:
            self.record(argument, value)
            if isinstance(count, int) and count > 1:
                self.pending, self.remaining = argument, count - 1
            elif count in ("+", "*"):
                self.pending, self.remaining = argument, "*"

    def consume_cluster(self, token: str) -> tuple[dict | None, str]:
        argument = None
        for offset, letter in enumerate(token[1:], 2):
            argument = self.options.get("-" + letter)
            if argument is None:
                return None, ""
            if argument["nargs"]:
                return argument, token[offset:]
            self.record(argument, True)
        return argument, ""

    def consume_positional(self, token: str) -> None:
        if token in self.node["children"] and self.position == 0:
            self.node = self.node["children"][token]
            self.path.append(token)
            self.used.clear()
            return
        if self.position >= len(self.node["positionals"]):
            self.invalid = True
            return
        argument = self.node["positionals"][self.position]
        self.record(argument, token)
        self.positional_used += 1
        count = argument["nargs"]
        if count in ("*", "+"):
            return
        required = count if isinstance(count, int) else 1
        if self.positional_used >= required:
            self.position += 1
            self.positional_used = 0

    def consume(self, token: str) -> None:
        if self.consume_pending(token):
            return
        if token == "--" and not self.end_options:
            self.end_options = True
        elif token.startswith("-") and token != "-" and not self.end_options:
            self.consume_option(token)
        else:
            self.consume_positional(token)


def parse(schema: dict, words: list[str]) -> Context:
    commands = schema["commands"]
    context = Context(commands["server"], ["server"])
    args = list(words)
    if args and args[0].startswith("--addons-path="):
        context.values["addons_path"] = args.pop(0).partition("=")[2]
    if not args:
        context.choosing = True
    elif not args[0].startswith("-"):
        name = args.pop(0)
        if name not in commands:
            context.invalid = True
            return context
        context.node, context.path = commands[name], [name]
    for token in args:
        context.consume(token)
        if context.invalid:
            break
    return context


def effective_config(schema, ctx, cwd):
    import configparser
    from pathlib import Path

    result = dict(schema.get("defaults", {}))
    home = Path.home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    candidates = [config_home / "odoo/odoo.conf", home / ".odoorc", home / ".openerp_serverrc"]
    default = next((p for p in candidates if p.exists()), candidates[0])
    filename = (
        ctx.values.get("config")
        or os.environ.get("ODOO_RC")
        or os.environ.get("OPENERP_SERVER")
        or str(default)
    )
    filename = Path(cwd) / os.path.expandvars(os.path.expanduser(str(filename)))
    parser = configparser.RawConfigParser()
    try:
        parser.read(filename)
        if parser.has_section("options"):
            result.update(dict(parser.items("options")))
    except (configparser.Error, OSError, ValueError):
        pass
    for dest, env in schema.get("env", {}).items():
        if env in os.environ:
            result[dest] = os.environ[env]
    result.update(ctx.values)
    for key in ("db_host", "db_user", "db_password", "db_port"):
        if result.get(key) in (False, "False", "false", "None", ""):
            result[key] = None
    paths = result.get("addons_path", [])
    if isinstance(paths, str):
        paths = paths.split(",")
    root = schema.get("root")
    builtin = [str(Path(root) / "odoo/addons"), str(Path(root) / "addons")] if root else []
    data_dir = result.get("data_dir")
    if data_dir:
        builtin.insert(
            1,
            str(
                Path(os.path.expanduser(str(data_dir)))
                / "addons"
                / schema.get("version", "20.0").split("a")[0]
            ),
        )
    result["addons_path"] = list(
        dict.fromkeys(
            str((Path(cwd) / os.path.expandvars(os.path.expanduser(str(p)))).resolve())
            for p in [*builtin, *paths]
            if p
        )
    )
    return result
