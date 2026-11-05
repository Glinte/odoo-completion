"""Exercise native completion and the actual edited command line in each shell."""

import os
import shutil
import subprocess

import pexpect
import pytest

from odoo_completion.integration import render
from odoo_completion.storage import config_dir, executable, schema_path, write_json


@pytest.fixture
def shell_setup(schema, tmp_path):
    entry = {"root": str(tmp_path), "python": "/unused"}
    write_json(config_dir() / "registrations.json", {executable("odoo-bin"): entry})
    write_json(schema_path(entry), schema)
    (tmp_path / "report space.conf").touch()
    (tmp_path / "café file.conf").touch()
    for shell in ("bash", "zsh", "fish"):
        (tmp_path / shell).write_text(render(shell))
    return tmp_path


def test_fish_native_candidates(shell_setup):
    if not shutil.which("fish"):
        pytest.skip("fish not installed")
    script = f'source {shell_setup}/fish; complete -C "odoo-bin --log-level=d"'
    result = subprocess.check_output(["fish", "--no-config", "-c", script], text=True)
    assert result.split("\t")[0] == "--log-level=debug"


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("odoo-bin mo", "odoo-bin module "),
        ("odoo-bin --logfile café", "odoo-bin --logfile café\\ file.conf "),
        ("odoo-bin --log-l", "odoo-bin --log-level "),
        ("odoo-bin -uaccount_p", "odoo-bin -uaccount_payment "),
        ("odoo-bin --log-level=d", "odoo-bin --log-level=debug "),
        ("odoo-bin --logfile report", "odoo-bin --logfile report\\ space.conf "),
        ('odoo-bin --logfile "report', 'odoo-bin --logfile "report space.conf" '),
        ("odoo-bin -u sale,account_p", "odoo-bin -u sale,account_payment "),
        ("odoo-bin --log-level=debug\x02\x02", "odoo-bin --log-level=debug "),
        (
            "odoo-bin --test-tags /sale:TestSale.t",
            "odoo-bin --test-tags /sale:TestSale.test_total ",
        ),
    ],
)
def test_interactive_insertion(shell_setup, shell, typed, expected):
    if not shutil.which(shell):
        pytest.skip(f"{shell} not installed")
    flags = {"bash": ["--noprofile", "--norc", "-i"], "zsh": ["-f"], "fish": ["--no-config", "-i"]}
    env = {**os.environ, "TERM": "xterm", "PS1": "READY> ", "PROMPT": "READY> "}
    child = pexpect.spawn(
        shell, flags[shell], cwd=str(shell_setup), env=env, encoding="utf-8", timeout=5
    )
    try:
        if shell == "bash":
            setup = f"""source {shell_setup}/bash; bind -x '"\\C-x\\C-g":printf "\\nRESULT:%s:END\\n" "$READLINE_LINE"'; PS1='READY> ' """
        elif shell == "zsh":
            setup = f"""autoload -Uz compinit; compinit -D; source {shell_setup}/zsh; _capture() {{ print -r -- "RESULT:$BUFFER:END"; }}; zle -N _capture; bindkey '^X^G' _capture; PROMPT='READY> ' """
        else:
            setup = f"""source {shell_setup}/fish; function _capture; printf '\\nRESULT:%s:END\\n' (commandline); commandline -f repaint; end; bind \\cx\\cg _capture; function fish_prompt; printf 'READY> '; end"""
        child.sendline(setup)
        child.expect("READY> ")
        # Drain the prompt before typing; shell setup may echo the prompt text.
        child.sendline("")
        child.expect("READY> ")
        child.send(typed + "\t")
        child.send("\x18\x07")
        child.expect(r"RESULT:([^\r\n]*):END")
        actual = child.match.group(1)
        if shell == "bash" and "\x02" in typed:
            expected = expected.rstrip()
        assert actual == expected, (shell, actual, child.before)
    finally:
        child.close(force=True)
