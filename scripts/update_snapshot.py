"""Regenerate the portable Odoo 20 fallback from a registered 20.0 checkout."""

import argparse
import json
from pathlib import Path

from odoo_completion.discovery import classify
from odoo_completion.index import reference_codes
from odoo_completion.storage import load_schema, select

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--command", required=True)
args = parser.parse_args()
entry = select(args.command, str(Path.cwd()))
if entry is None:
    parser.error("Register and refresh the Odoo 20.0 checkout first")
schema = load_schema(entry)
if schema["version"] != "20.0" or schema.get("errors"):
    parser.error("Expected Odoo 20.0 metadata without discovery errors")
commands = {
    name: node
    for name, node in schema["commands"].items()
    if (Path(entry["root"]) / "odoo/cli" / (name + ".py")).is_file()
}
for name, node in commands.items():
    classify(node, (name,))
snapshot = {
    "protocol": 1,
    "version": schema["version"],
    "revision": schema["revision"],
    "commands": commands,
    "env": schema["env"],
    "defaults": {"addons_path": []},
    "index": {
        "language": reference_codes(entry["root"], "lang"),
        "iso_language": reference_codes(entry["root"], "lang", "iso_code"),
        "country": reference_codes(entry["root"], "country"),
    },
}
output = Path(__file__).resolve().parents[1] / "src/odoo_completion/data/odoo20.json"
output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
print(output)
