import sys

import pytest

from odoo_completion import integration
from odoo_completion.discovery import apply_overrides
from odoo_completion.providers import external_values
from odoo_completion.storage import config_dir, load_schema, schema_path, select, write_json


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_install_is_idempotent_and_reversible(shell, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("ZDOTDIR", str(tmp_path))
    profile = integration.profile_path(shell)
    profile.parent.mkdir(parents=True, exist_ok=True)
    original = "# Personal configuration\n"
    profile.write_text(original)
    integration.install(shell)
    once = profile.read_text()
    integration.install(shell)
    assert profile.read_text() == once
    assert once.count(integration.START) == 1
    profile.write_text(once + "# Later user edit\n")
    integration.uninstall(shell)
    assert profile.read_text() == original + "# Later user edit\n"


def test_checkout_resolution_does_not_depend_on_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    first = {"root": str(tmp_path / "first"), "python": "/venv-one/bin/python"}
    second = {"root": str(tmp_path / "second"), "python": "/venv-two/bin/python"}
    write_json(
        config_dir() / "registrations.json",
        {"/bin/wrapper": first, str(tmp_path / "second/odoo-bin"): second},
    )
    assert select("/bin/wrapper", second["root"]) == first
    assert select("./odoo-bin", second["root"]) == second
    assert select("./odoo-bin", first["root"]) == first


def test_corrupt_metadata_uses_bundled_core(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    entry = {"root": "/missing", "python": "/missing/python"}
    filename = schema_path(entry)
    filename.parent.mkdir(parents=True)
    filename.write_text("{broken")
    schema = load_schema(entry)
    assert "server" in schema["commands"]
    assert "db" in schema["commands"]


def test_overrides_and_external_provider(schema, tmp_path):
    path = tmp_path / "overrides.toml"
    path.write_text("""[[argument]]
command = "server"
dest = "log_level"
choices = ["custom"]
""")
    apply_overrides(schema, path)
    argument = next(x for x in schema["commands"]["server"]["options"] if x["dest"] == "log_level")
    assert argument["choices"] == ["custom"]
    script = 'import json,sys; request=json.load(sys.stdin); print(json.dumps([request["prefix"]+"value"]))'
    assert (
        external_values([sys.executable, "-c", script], "custom-", str(tmp_path))[0]["value"]
        == "custom-value"
    )


def test_external_provider_timeout(tmp_path):
    assert (
        external_values([sys.executable, "-c", "import time; time.sleep(5)"], "", str(tmp_path))
        == []
    )


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_custom_wrappers_register_their_command_name(shell, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    write_json(
        config_dir() / "registrations.json",
        {
            "/custom/bin/my-odoo": {"root": "/src/odoo", "python": "/venv/bin/python"},
        },
    )
    assert "my-odoo" in integration.render(shell).splitlines()[-1] or any(
        line.endswith(" my-odoo") or "-c my-odoo " in line
        for line in integration.render(shell).splitlines()
    )
