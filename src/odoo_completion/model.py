"""The JSON-serializable parser model shared by discovery and completion."""

from typing import NotRequired, TypedDict


class Argument(TypedDict):
    flags: list[str]
    dest: str
    nargs: int | str
    choices: list[str]
    help: str
    hidden: bool
    repeat: bool
    type: str
    env: NotRequired[str]
    provider: NotRequired[str]
    reason: NotRequired[str]


class Command(TypedDict):
    options: list[Argument]
    positionals: list[Argument]
    children: dict[str, "Command"]
    help: str


class Candidate(TypedDict):
    value: str
    description: str
    kind: str


def candidate(value: str, description: str = "", kind: str = "plain") -> Candidate:
    return {"value": value, "description": description, "kind": kind}
