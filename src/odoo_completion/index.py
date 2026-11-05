"""Refresh-time source indexes. No addon imports or manifest evaluation."""

import ast
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

IGNORED_DIRECTORIES = {"static", "node_modules", ".git", "__pycache__"}


@dataclass
class TestClass:
    module: str
    file: str
    name: str
    methods: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=lambda: {"standard", "at_install"})
    bases: list[str] = field(default_factory=list)
    removed_tags: set[str] = field(default_factory=set)

    def serialize(self) -> dict:
        return {
            "module": self.module,
            "file": self.file,
            "class": self.name,
            "methods": sorted(self.methods),
            "tags": sorted(self.tags),
        }


def module_paths(addons: list[str]) -> dict[str, Path]:
    modules = {}
    for directory in addons:
        try:
            children = sorted(Path(directory).iterdir())
        except OSError:
            continue
        for path in children:
            if any(
                (path / manifest).is_file() for manifest in ("__manifest__.py", "__openerp__.py")
            ):
                modules.setdefault(path.name, path)
    return modules


def parse_source(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_bytes(), filename=str(path))
    except (OSError, SyntaxError, ValueError):
        return None


def model_names(node: ast.ClassDef) -> set[str]:
    names = set()
    for statement in node.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id in ("_name", "_inherit") for t in statement.targets
        ):
            continue
        if isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
            names.add(statement.value.value)
    return names


def test_class(node: ast.ClassDef, module: str, filename: str) -> TestClass:
    result = TestClass(module, filename, node.name)
    result.bases = [ast.unparse(base).split(".")[-1] for base in node.bases]
    result.methods = {
        method.name
        for method in node.body
        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
        and method.name.startswith("test")
    }
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = ast.unparse(decorator.func).split(".")[-1]
        if name != "tagged":
            continue
        for argument in decorator.args:
            if not isinstance(argument, ast.Constant) or not isinstance(argument.value, str):
                continue
            tag = argument.value
            if tag.startswith("-"):
                result.removed_tags.add(tag[1:])
            else:
                result.tags.add(tag)
    result.tags.difference_update(result.removed_tags)
    return result


def resolve_inheritance(tests: list[TestClass]) -> None:
    by_name: dict[str, list[TestClass]] = {}
    for test in tests:
        by_name.setdefault(test.name, []).append(test)

    def visit(test: TestClass, visiting: set[int]) -> None:
        if id(test) in visiting:
            return
        visiting = visiting | {id(test)}
        for name in test.bases:
            candidates = by_name.get(name, [])
            local = [base for base in candidates if base.module == test.module]
            candidates = local or candidates
            if len(candidates) != 1:
                continue
            parent = candidates[0]
            visit(parent, visiting)
            test.methods.update(parent.methods)
            test.tags.update(parent.tags)
        test.tags.difference_update(test.removed_tags)

    for test in tests:
        visit(test, set())


def reference_codes(root: str, model: str) -> list[str]:
    path = Path(root) / "odoo/addons/base/data" / f"res_{model}_data.xml"
    try:
        document = ET.parse(path)
    except (OSError, ET.ParseError):
        return []
    selector = f".//record[@model='res.{model}']/field[@name='code']"
    return sorted({node.text for node in document.findall(selector) if node.text})


def build_index(addons: list[str], root: str) -> dict:
    tests, models = [], set()
    for module, directory in module_paths(addons).items():
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(directory)
            if IGNORED_DIRECTORIES.intersection(relative.parts):
                continue
            tree = parse_source(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                models.update(model_names(node))
                if "tests" in relative.parts:
                    tests.append(test_class(node, module, f"{module}/{relative.as_posix()}"))
    resolve_inheritance(tests)
    return {
        "tests": [test.serialize() for test in tests if test.methods],
        "models": sorted(models),
        "language": reference_codes(root, "lang"),
        "country": reference_codes(root, "country"),
    }
