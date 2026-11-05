"""Opt-in integration against actual Odoo sources and their environment."""

import os

import pytest

from odoo_completion.discovery import classify, coverage, probe
from odoo_completion.index import reference_codes


@pytest.fixture(scope="module")
def checkout():
    root = os.environ.get("ODOO_TEST_ROOT")
    python = os.environ.get("ODOO_TEST_PYTHON")
    if not root or not python:
        pytest.skip("Set ODOO_TEST_ROOT and ODOO_TEST_PYTHON for real Odoo checks")
    return {"root": root, "python": python}


def test_all_parsers_are_captured_and_classified(checkout):
    base = probe(checkout, "__base__")
    commands = {}
    for name in base["commands"]:
        node = probe(checkout, name)
        classify(node, (name,))
        commands[name] = node
    rows = coverage({"commands": commands})
    assert len(rows) > 500
    assert all(row["provider"] and row["reason"] for row in rows)
    assert {"init", "load", "dump", "drop"} <= commands["db"]["children"].keys()
    assert {"install", "upgrade", "uninstall"} <= commands["module"]["children"].keys()
    assert "en_US" in reference_codes(checkout["root"], "lang")
    assert "en" in reference_codes(checkout["root"], "lang", "iso_code")
    assert "BE" in reference_codes(checkout["root"], "country")


def test_addon_capture_cannot_reach_side_effects(checkout, tmp_path):
    addon = tmp_path / "example"
    (addon / "cli").mkdir(parents=True)
    (addon / "__manifest__.py").write_text("{'name': 'Example', 'depends': ['base']}")
    marker = tmp_path / "executed"
    (addon / "cli/custom_complete.py").write_text(f"""
from odoo.cli import Command
class CustomComplete(Command):
    name = 'custom_complete'
    def run(self, args):
        self.parser.add_argument('--mode', choices=['one', 'two'])
        self.parser.parse_args(args)
        open({str(marker)!r}, 'w').write('should never execute')
""")
    entry = {**checkout, "addons": [str(tmp_path)]}
    result = probe(entry, "custom_complete")
    assert result["options"][-1]["choices"] == ["one", "two"]
    assert not marker.exists()
    (addon / "cli/bad_complete.py").write_text(f"""
from odoo.cli import Command
class BadComplete(Command):
    name = 'bad_complete'
    def run(self, args):
        open({str(marker)!r}, 'w').write('before parsing')
""")
    with pytest.raises(RuntimeError, match="blocked a file write"):
        probe(entry, "bad_complete")
    assert not marker.exists()
