"""Smoke tests for the docs build pipeline.

The generator lives at ``scripts/gen_docs.py`` and is intentionally
zero-dep. These tests verify:

- the module imports
- the Markdown subset renders without crashing on real guide content
- ``build()`` produces the expected directory layout

They run under the hermetic suite (no MongoDB, no network).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


@pytest.fixture(scope="module")
def gen_docs():
    sys.path.insert(0, str(SCRIPTS))
    try:
        module = importlib.import_module("gen_docs")
    finally:
        sys.path.pop(0)
    return module


def test_markdown_renders_headings_code_and_tables(gen_docs):
    md = (
        "# Title\n\n"
        "Body with `inline` and **bold**.\n\n"
        "```python\nprint('hi')\n```\n\n"
        "- one\n- two\n\n"
        "| a | b |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n"
    )
    out = gen_docs.markdown_to_html(md)
    assert '<h1 id="title">' in out
    assert "<code>inline</code>" in out
    assert "<strong>bold</strong>" in out
    assert "<pre><code>print" in out
    assert "<ul>" in out and "<li>one</li>" in out
    assert "<table>" in out and "<th>a</th>" in out


def test_markdown_rewrites_internal_links(gen_docs):
    md = "See [ORM](guides/ormodel.md) or [README](../README.md)."
    out = gen_docs.markdown_to_html(md)
    assert 'href="guides/ormodel.html"' in out
    # Out-of-tree link is left untouched (no .md → .html rewrite).
    assert 'href="../README.md"' in out


def test_public_methods_walks_class_dict_without_triggering_descriptors(gen_docs):
    """Regression: AutoModel has a QuerySet descriptor that used to open
    a Mongo connection on getattr during introspection."""

    from autonomous.model.automodel import AutoModel

    methods = gen_docs._public_methods(AutoModel)
    names = {n for n, _ in methods}
    # A few we definitely expect to be there:
    assert {"get", "all", "save", "where"}.issubset(names)
    # Nothing underscore-prefixed:
    assert not any(n.startswith("_") for n in names)


def test_build_produces_expected_tree(gen_docs, tmp_path, monkeypatch):
    """End-to-end: running ``build(clean=True)`` produces index +
    guide pages + reference pages under docs/_build."""

    out = gen_docs.build(clean=True)
    assert (out / "index.html").exists()
    assert (out / "assets" / "style.css").exists()
    assert (out / "guides" / "quickstart.html").exists()
    assert (out / "reference" / "index.html").exists()
    assert (out / "reference" / "automodel.html").exists()

    # Landing page pulled in the tagline.
    home = (out / "index.html").read_text(encoding="utf-8")
    assert "Autonomous" in home
    # Sidebar nav reaches every guide.
    for slug in ("quickstart", "ormodel", "auth", "storage", "tasks", "web", "ai"):
        assert f"guides/{slug}.html" in home

    # AutoModel reference has methods inlined.
    auto = (out / "reference" / "automodel.html").read_text(encoding="utf-8")
    assert "AutoModel" in auto
    assert "id=\"automodel-save\"" in auto
    assert "id=\"automodel-get\"" in auto


def test_missing_optional_dependency_renders_stub(gen_docs, monkeypatch):
    """If an optional backend isn't installed, the generator emits a
    stub page rather than crashing the build."""

    def fail_import(_):
        raise ImportError("fake dep missing")

    monkeypatch.setattr(gen_docs.importlib, "import_module", fail_import)
    body, methods = gen_docs.render_api_reference(
        "nonexistent.module", "NonexistentClass", "", "../assets"
    )
    assert "unavailable" in body
    assert "nonexistent.module" in body
    assert methods == []
