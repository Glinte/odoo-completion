import argparse
import optparse

import pytest

from odoo_completion.discovery import classify
from odoo_completion.probe import Captured, capture, describe


def test_nested_parser_metadata():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers().add_parser("dump")
    sub.add_argument("database")
    sub.add_argument("--format", choices=["zip", "dump"])
    sub.add_argument("-v", action="count")
    node = describe(parser)
    classify(node, ("db",))
    dump = node["children"]["dump"]
    assert dump["positionals"][0]["provider"] == "database"
    assert dump["options"][1]["choices"] == ["zip", "dump"]
    assert dump["options"][2]["repeat"]


def test_capture_does_not_convert_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--value", type=lambda _: pytest.fail("converter executed"))
    with pytest.raises(Captured) as caught:
        capture(parser, ["--value", "anything"])
    assert caught.value.parser is parser


def test_optparse_groups():
    parser = optparse.OptionParser()
    group = optparse.OptionGroup(parser, "Extra")
    group.add_option("--names", action="append")
    parser.add_option_group(group)
    option = describe(parser)["options"][-1]
    assert option["repeat"]
    assert option["nargs"] == 1


def test_new_database_is_unrestricted():
    parser = argparse.ArgumentParser()
    parser.add_argument("database")
    node = describe(parser)
    classify(node, ("db", "init"))
    assert node["positionals"][0]["provider"] == "text"


def test_mutually_exclusive_arguments_are_recorded():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--script")
    group.add_argument("--from", dest="from_version")
    node = describe(parser)
    script = next(item for item in node["options"] if item["dest"] == "script")
    assert script["exclusive_with"] == ["from_version"]
