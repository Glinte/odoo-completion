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
