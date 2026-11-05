import pytest

from odoo_completion.context import effective_config, parse, tokenize
from odoo_completion.engine import complete


def values(schema, line, cwd):
    words, prefix = tokenize(line)
    return [item["value"] for item in complete(schema, words, prefix, str(cwd))]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("mo", "module"),
        ("module i", "install"),
        ("--log-l", "--log-level"),
        ("--log-level d", "debug"),
        ("--log-level=d", "--log-level=debug"),
        ("--dev xml,re", "xml,reload"),
        ("-u sale,acc", "sale,account"),
        ("-uacc", "-uaccount"),
        ("-vuacc", "-vuaccount"),
        ("--test-tags=-post_install,/sale:T", "--test-tags=-post_install,/sale:TestSale"),
        ("--test-tags /sale:TestSale.t", "/sale:TestSale.test_total"),
        ("--test-tags /sale/tests/test_sale.py:T", "/sale/tests/test_sale.py:TestSale"),
        ("module install acc", "account"),
        ("--without-demo --log-l", "--log-level"),
    ],
)
def test_candidates(schema, tmp_path, monkeypatch, line, expected):
    monkeypatch.setattr("odoo_completion.database.candidates", lambda *args: [])
    assert expected in values(schema, line, tmp_path)


def test_no_value_invention(schema, tmp_path):
    assert values(schema, "db init new", tmp_path) == []
    assert values(schema, "--test-tags /sale:T.test[x,", tmp_path) == []
    assert "--log-level" not in values(schema, "-- --log", tmp_path)
    assert values(schema, "--unknown flag ", tmp_path) == []


def test_file_arguments(schema, tmp_path):
    (tmp_path / "dump file.zip").touch()
    assert "dump file.zip" in values(schema, "db load dump", tmp_path)
    assert "dump file.zip" in values(schema, "db load newdb dump", tmp_path)
    assert "dump file.zip" in values(schema, '--logfile "dump', tmp_path)


def test_precedence(schema, tmp_path, monkeypatch):
    config = tmp_path / "odoo.conf"
    config.write_text("[options]\ndb_host = file\n")
    monkeypatch.setenv("PGHOST", "environment")
    context = parse(schema, ["-c", str(config), "--db_host", "cli"])
    assert effective_config(schema, context, str(tmp_path))["db_host"] == "cli"
    context = parse(schema, ["-c", str(config)])
    assert effective_config(schema, context, str(tmp_path))["db_host"] == "environment"
    monkeypatch.delenv("PGHOST")
    assert effective_config(schema, context, str(tmp_path))["db_host"] == "file"


def test_tokenizer_does_not_execute():
    assert tokenize('echo ignored; odoo-bin -c "a b') == (["odoo-bin", "-c"], "a b")
    assert tokenize("odoo-bin --logfile '$(touch /tmp/no)' ") == (
        ["odoo-bin", "--logfile", "$(touch /tmp/no)"],
        "",
    )


def test_method_only_selectors(schema, tmp_path):
    assert "/sale.test_total" in values(schema, "--test-tags /sale.test_", tmp_path)
    assert "standard.test_total" in values(schema, "--test-tags standard.test_", tmp_path)


def test_addon_commands_follow_effective_paths(schema, tmp_path):
    schema["commands"]["custom"] = {
        "options": [],
        "positionals": [],
        "children": {},
        "help": "Custom",
    }
    extra = tmp_path / "extra"
    schema["command_sources"] = {"custom": str(extra / "module/cli/custom.py")}
    assert "custom" not in values(schema, "cu", tmp_path)
    assert "custom" in values(schema, f"--addons-path={extra} cu", tmp_path)


def test_bash_preserves_existing_suffix(schema, tmp_path, monkeypatch):
    from odoo_completion.engine import complete_line

    monkeypatch.setattr("odoo_completion.engine.load_schema", lambda _: schema)
    line = "odoo-bin --log-level=dbug"
    result = complete_line(line, len(line) - 3, str(tmp_path), "bash", "dbug")
    assert result[0]["value"] == "de"
    assert result[0]["kind"] == "nospace"
    incompatible = "odoo-bin --log-level=deb"
    assert complete_line(incompatible, len(incompatible) - 2, str(tmp_path), "bash", "deb") == []


def test_bash_empty_value_after_wordbreak(schema, tmp_path, monkeypatch):
    from odoo_completion.engine import complete_line

    monkeypatch.setattr("odoo_completion.engine.load_schema", lambda _: schema)
    line = "odoo-bin --log-level="
    result = complete_line(line, len(line), str(tmp_path), "bash", "=")
    assert {item["value"] for item in result} == {"debug", "info", "warn"}


def test_mutually_exclusive_options_are_not_offered(schema, tmp_path):
    level = next(
        item for item in schema["commands"]["server"]["options"] if item["dest"] == "log_level"
    )
    level["exclusive_with"] = ["dev_mode"]
    assert "--log-level" not in values(schema, "--dev xml --log-", tmp_path)
