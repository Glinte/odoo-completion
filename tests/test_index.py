from odoo_completion.index import build_index


def test_static_inheritance_and_tags(tmp_path):
    module = tmp_path / "addons/demo"
    tests = module / "tests"
    tests.mkdir(parents=True)
    (module / "__manifest__.py").write_text('raise RuntimeError("must not execute")')
    (tests / "test_demo.py").write_text("""
raise RuntimeError("must not execute")
class Base:
    def test_inherited(self): pass
@tagged('-at_install', 'post_install')
class TestDemo(Base):
    def test_local(self): pass
""")
    index = build_index([str(module.parent)], str(tmp_path))
    child = next(test for test in index["tests"] if test["class"] == "TestDemo")
    assert child["methods"] == ["test_inherited", "test_local"]
    assert child["tags"] == ["post_install", "standard"]


def test_inherited_removed_tags_are_not_reintroduced(tmp_path):
    module = tmp_path / "demo"
    (module / "tests").mkdir(parents=True)
    (module / "__manifest__.py").touch()
    (module / "tests/test_demo.py").write_text("""
@tagged('-at_install', 'post_install')
class Base:
    def test_example(self): pass
class Child(Base): pass
""")
    index = build_index([str(tmp_path)], str(tmp_path))
    child = next(test for test in index["tests"] if test["class"] == "Child")
    assert child["tags"] == ["post_install", "standard"]
