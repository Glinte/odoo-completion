"""User-level shell setup, with reversible managed blocks."""

import os
import shlex
import sys
from pathlib import Path

from .storage import config_dir, read_json, registrations, write_json

SHELL_FILES = {"bash": "bash.sh", "zsh": "zsh.sh", "fish": "fish.fish"}
START = "# >>> odoo-completion >>>"
END = "# <<< odoo-completion <<<"


def helper_command() -> str:
    # This interpreter belongs to the tool environment, not an Odoo checkout.
    return f"{shlex.quote(sys.executable)} -m odoo_completion"


def render(shell: str) -> str:
    template = Path(__file__).parent / "shells" / SHELL_FILES[shell]
    script = template.read_text().replace("ODOO_COMPLETION_HELPER", helper_command())
    commands = set(registrations())
    commands.update(str(Path(entry["root"]) / "odoo-bin") for entry in registrations().values())
    commands.update(Path(command).name for command in list(commands))
    for command in sorted(commands):
        quoted = shlex.quote(command)
        if shell == "bash":
            script += f"complete -o filenames -F _odoo_completion {quoted}\n"
        elif shell == "zsh":
            script += f"compdef _odoo_completion {quoted}\n"
        else:
            # Command names, not executable paths, are what Fish registers.
            name = shlex.quote(Path(command).name)
            script += f"complete -c {name} -f -a '(__odoo_completion)'\n"
    return script


def profile_path(shell: str) -> Path:
    if shell == "bash":
        return Path.home() / ".bashrc"
    if shell == "zsh":
        return Path(os.environ.get("ZDOTDIR", Path.home())) / ".zshrc"
    return config_dir().parent / "fish/conf.d/odoo-completion.fish"


def remove_block(text: str) -> str:
    begin = text.find(START)
    if begin < 0:
        return text
    end = text.find(END, begin)
    if end < 0:
        raise ValueError("Incomplete managed block; refusing to overwrite shell profile")
    end += len(END)
    if text[end : end + 1] == "\n":
        end += 1
    return text[:begin] + text[end:]


def install(shell: str) -> Path:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    script = directory / SHELL_FILES[shell]
    script.write_text(render(shell))
    profile = profile_path(shell)
    profile.parent.mkdir(parents=True, exist_ok=True)
    original = profile.read_text() if profile.exists() else ""
    content = remove_block(original)
    if content and not content.endswith("\n"):
        content += "\n"
    setup = ""
    if shell == "zsh":
        setup = "(( $+functions[compdef] )) || { autoload -Uz compinit; compinit; }\n"
    content += f"{START}\n{setup}source {shlex.quote(str(script))}\n{END}\n"
    profile.write_text(content)
    manifest_path = directory / "installations.json"
    manifest = read_json(manifest_path, {})
    manifest.setdefault(shell, {"profile": str(profile), "original": original})
    write_json(manifest_path, manifest)
    return profile


def uninstall(shell: str) -> Path:
    manifest_path = config_dir() / "installations.json"
    manifest = read_json(manifest_path, {})
    record = manifest.pop(shell, None)
    profile = Path(record["profile"]) if record else profile_path(shell)
    if profile.exists():
        profile.write_text(remove_block(profile.read_text()))
    (config_dir() / SHELL_FILES[shell]).unlink(missing_ok=True)
    write_json(manifest_path, manifest)
    return profile
