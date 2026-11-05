"""Shell-independent candidate selection for an incomplete Odoo command."""

from pathlib import Path

from .context import effective_config, parse, tokenize
from .model import Candidate, candidate
from .providers import complete_value
from .storage import load_schema, select


def attached_value(options: dict, prefix: str) -> tuple[dict | None, str, str]:
    flag, separator, value = prefix.partition("=")
    if separator and flag in options and options[flag]["nargs"]:
        return options[flag], flag + "=", value
    if prefix.startswith("-") and not prefix.startswith("--"):
        for offset, letter in enumerate(prefix[1:], 2):
            argument = options.get("-" + letter)
            if argument is None:
                break
            if argument["nargs"] and len(prefix) >= offset:
                return argument, prefix[:offset], prefix[offset:]
    return None, "", ""


def option_candidates(context, prefix: str) -> list[Candidate]:
    return [
        candidate(flag, argument["help"])
        for argument in context.node["options"]
        if not set(argument.get("exclusive_with", [])).intersection(context.used)
        and not argument.get("hidden")
        and (argument.get("repeat") or argument["dest"] not in context.used)
        for flag in argument["flags"]
        if flag.startswith(prefix)
    ]


def complete(schema: dict, words: list[str], prefix: str, cwd: str) -> list[Candidate]:
    context = parse(schema, words)
    if context.invalid:
        return []
    config = effective_config(schema, context, cwd)
    available = available_commands(schema, config)
    if context.path[0] not in available:
        return []
    pending = context.pending
    if pending is not None:
        flexible = context.remaining in ("?", "*", "+")
        if not (
            flexible
            and prefix.startswith("-")
            and any(flag.startswith(prefix) for flag in context.options)
        ):
            return complete_value(pending, prefix, schema, config, cwd)
    if not context.end_options:
        argument, head, value = attached_value(context.options, prefix)
        if argument:
            return [
                {**item, "value": head + item["value"]}
                for item in complete_value(argument, value, schema, config, cwd)
            ]
        if prefix.startswith("-"):
            return option_candidates(context, prefix)
    results = []
    if context.choosing:
        results.extend(
            candidate(name, node["help"])
            for name, node in available.items()
            if name.startswith(prefix)
        )
    results.extend(
        candidate(name, child["help"])
        for name, child in context.node["children"].items()
        if name.startswith(prefix)
    )
    positionals = context.node["positionals"]
    if context.position < len(positionals):
        arguments = [positionals[context.position]]
        # `db load [database] dump_file` needs file completion at either position.
        if arguments[0]["nargs"] in ("?", "*"):
            arguments.extend(positionals[context.position + 1 : context.position + 2])
        for argument in arguments:
            results.extend(complete_value(argument, prefix, schema, config, cwd))
    if not prefix and not context.end_options:
        results.extend(option_candidates(context, prefix))
    return results


def complete_line(
    line: str, point: int, cwd: str, shell: str = "bash", word: str | None = None
) -> list[Candidate]:
    line = line[:point]
    words, prefix = tokenize(line)
    if not words:
        return []
    entry = select(words[0], cwd)
    schema = load_schema(entry)
    if not schema.get("commands"):
        return []
    results = complete(schema, words[1:], prefix, cwd)
    # Readline replaces only the part before the cursor, and breaks at '=' and
    # ':'. Preserve any existing suffix rather than duplicating it on insertion.
    trim, suffix = "", ""
    if shell == "bash" and word is not None:
        word = word.strip("\"'")
        if word in ("=", ":") and prefix.endswith(word):
            word = ""
        boundaries = [0] + [i + 1 for i, char in enumerate(prefix) if char in "=:"]
        for boundary in boundaries:
            fragment = prefix[boundary:]
            if word.startswith(fragment):
                trim, suffix = prefix[:boundary], word[len(fragment) :]
                break
    unique = {}
    for item in results:
        value = item["value"]
        if trim and value.startswith(trim):
            value = value[len(trim) :]
        if suffix:
            if not value.endswith(suffix):
                continue
            value = value[: -len(suffix)]
            item = {**item, "kind": "nospace"}
        if any(char in value for char in "\t\n\r\x00"):
            continue
        description = " ".join(item["description"].split())
        unique[value] = {**item, "value": value, "description": description}
    return [unique[value] for value in sorted(unique)]


def available_commands(schema: dict, config: dict) -> dict:
    """Do not offer addon commands outside this invocation's search path."""
    sources = schema.get("command_sources", {})
    core = Path(schema.get("root", ".")) / "odoo/cli"
    addon_paths = {Path(path).resolve() for path in config.get("addons_path", [])}
    result = {}
    for name, node in schema["commands"].items():
        source = sources.get(name)
        if source is None or Path(source).parent == core:
            result[name] = node
        elif Path(source).parent.parent.parent.resolve() in addon_paths:
            result[name] = node
    return result
