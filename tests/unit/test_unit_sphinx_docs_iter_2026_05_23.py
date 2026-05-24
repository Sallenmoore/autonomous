"""Independent coverage for PR #118 (Sphinx docs migration).

PR #118 replaced the bespoke ``scripts/gen_docs.py`` Markdown→HTML
generator with a Sphinx + furo + myst-parser pipeline. The prior
``tests/unit/test_unit_docs.py`` was deleted alongside the generator
because it asserted on rendered HTML output.

These tests pin the *configuration* surface instead — extensions,
mocks, theme, makefile wiring, RTD config, and the relocation of the
old generator into ``_archive/``. They don't run the Sphinx build
(that's gated by ``make docs`` + the RTD build) but they catch the
"silently dropped extension" / "forgot to bump requirements-docs.txt"
class of regression at unit-gate time.

Hermetic: pure filesystem + AST parsing, no Sphinx import required.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
SCRIPTS = REPO / "scripts"


# ---------------------------------------------------------------------------
# requirements-docs.txt — the single source of doc-build deps
# ---------------------------------------------------------------------------


class TestRequirementsDocs:
    @pytest.fixture(scope="class")
    def reqs(self):
        path = REPO / "requirements-docs.txt"
        assert path.exists(), (
            "requirements-docs.txt is missing — RTD + make docs both "
            "install from it."
        )
        return path.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "pkg",
        [
            "sphinx",
            "furo",
            "myst-parser",
            "linkify-it-py",  # required by myst's linkify extension
            "sphinx-autobuild",  # backs `make docs-serve`
        ],
    )
    def test_required_package_present(self, reqs, pkg):
        # Loose match: allow version specifiers, comments on the same
        # line, and case-insensitivity for the package name.
        pattern = re.compile(rf"(?im)^\s*{re.escape(pkg)}\b")
        assert pattern.search(reqs), f"{pkg} missing from requirements-docs.txt"


# ---------------------------------------------------------------------------
# docs/conf.py — extensions, theme, mocks
# ---------------------------------------------------------------------------


class TestSphinxConfig:
    @pytest.fixture(scope="class")
    def conf(self):
        path = DOCS / "conf.py"
        assert path.exists(), "docs/conf.py was not created by PR #118"
        return path.read_text(encoding="utf-8")

    @pytest.fixture(scope="class")
    def conf_module(self, conf):
        """Parse conf.py via ast and pull out top-level assignments to a
        dict. We deliberately avoid exec/import because conf.py mutates
        sys.path and the version is read at import time — both unwanted
        in a unit test."""
        tree = ast.parse(conf)
        bindings = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    try:
                        bindings[target.id] = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        # Skip dynamic exprs (e.g. f-strings, function calls).
                        pass
        return bindings

    @pytest.mark.parametrize(
        "ext",
        [
            "sphinx.ext.autodoc",
            "sphinx.ext.autosummary",
            "sphinx.ext.napoleon",
            "sphinx.ext.viewcode",
            "sphinx.ext.intersphinx",
            "myst_parser",
        ],
    )
    def test_extension_enabled(self, conf_module, ext):
        assert ext in conf_module.get("extensions", []), (
            f"{ext} dropped from docs/conf.py extensions list"
        )

    def test_html_theme_is_furo(self, conf_module):
        assert conf_module.get("html_theme") == "furo"

    def test_autosummary_generate_is_on(self, conf_module):
        """If this turns off, autodoc stops regenerating per-module
        stubs and the API ref decays silently."""
        assert conf_module.get("autosummary_generate") is True

    def test_napoleon_google_docstrings_on(self, conf_module):
        """The codebase uses Google-style docstrings (see baseagent.py).
        Turning this off makes the rendered docs look wrong but the
        Sphinx build still passes — easy regression to miss."""
        assert conf_module.get("napoleon_google_docstring") is True

    @pytest.mark.parametrize(
        "mod",
        ["google", "pydub", "PIL", "pygit2", "github", "rq"],
    )
    def test_mock_import_present(self, conf_module, mod):
        """Removing a mock here will fail the RTD build on any system
        where the real dep can't be installed (`google-genai` is the
        usual culprit). Keep the contract explicit."""
        assert mod in conf_module.get("autodoc_mock_imports", [])


# ---------------------------------------------------------------------------
# docs/api/index.rst — top-level autosummary tree
# ---------------------------------------------------------------------------


class TestApiIndex:
    @pytest.fixture(scope="class")
    def index(self):
        path = DOCS / "api" / "index.rst"
        assert path.exists(), "docs/api/index.rst is missing"
        return path.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "module",
        [
            "autonomous.model.automodel",
            "autonomous.model.autoattr",
            "autonomous.ai.baseagent",
            "autonomous.ai.imageagent",
            "autonomous.ai.retry",
            "autonomous.auth.autoauth",
            "autonomous.web.response",
            "autonomous.storage.imagestorage",
            "autonomous.taskrunner.autotasks",
        ],
    )
    def test_public_module_listed(self, index, module):
        """If a public module disappears from the autosummary tree, its
        API ref pages stop regenerating — the docs go silently stale."""
        assert module in index, f"{module} no longer listed in api/index.rst"


# ---------------------------------------------------------------------------
# .readthedocs.yaml — RTD build pinning
# ---------------------------------------------------------------------------


class TestReadTheDocsConfig:
    @pytest.fixture(scope="class")
    def rtd(self):
        path = REPO / ".readthedocs.yaml"
        assert path.exists(), ".readthedocs.yaml missing — RTD won't build"
        return path.read_text(encoding="utf-8")

    def test_references_sphinx_conf(self, rtd):
        assert "docs/conf.py" in rtd

    def test_installs_docs_requirements(self, rtd):
        assert "requirements-docs.txt" in rtd

    def test_installs_all_extra_for_autodoc(self, rtd):
        """[all] is needed so autodoc has real imports to introspect
        rather than only the autodoc_mock_imports fallback."""
        assert "all" in rtd, (
            "Read the Docs config no longer installs the [all] extra; "
            "autodoc will fall back to mock signatures for everything."
        )

    def test_warning_failures_enforced(self, rtd):
        """fail_on_warning is what makes broken cross-refs / stale
        autosummary entries surface as red RTD builds. If this drops,
        docs can rot without anyone noticing."""
        assert "fail_on_warning" in rtd
        assert re.search(r"fail_on_warning\s*:\s*true", rtd, re.IGNORECASE)


# ---------------------------------------------------------------------------
# makefile + pyproject + .gitignore wiring
# ---------------------------------------------------------------------------


class TestMakefileDocsTarget:
    @pytest.fixture(scope="class")
    def makefile(self):
        return (REPO / "makefile").read_text(encoding="utf-8")

    def test_docs_target_invokes_sphinx_build(self, makefile):
        """Old behaviour was `python scripts/gen_docs.py --clean`. After
        the migration the docs target must invoke sphinx."""
        # Find the `docs:` recipe and inspect its body.
        match = re.search(
            r"^docs:\s*\n((?:\t.*\n)+)", makefile, re.MULTILINE
        )
        assert match, "No `docs:` recipe in makefile"
        body = match.group(1)
        assert "sphinx" in body, (
            "make docs no longer invokes Sphinx — recipe body:\n" + body
        )
        assert "gen_docs.py" not in body, (
            "make docs still calls the archived gen_docs.py"
        )

    def test_docs_target_treats_warnings_as_errors(self, makefile):
        """-W is the local mirror of RTD's fail_on_warning. Both layers
        need it or local builds will silently diverge from CI."""
        match = re.search(
            r"^docs:\s*\n((?:\t.*\n)+)", makefile, re.MULTILINE
        )
        body = match.group(1)
        assert re.search(r"\s-W\b", body), "make docs missing -W flag"


class TestPyprojectDocsExtra:
    def test_docs_extra_defined(self):
        """pyproject.toml must expose [docs] so `pip install
        autonomous-app[docs]` installs the doc-build deps."""
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        assert re.search(
            r"^docs\s*=\s*\{file\s*=\s*\[\s*[\"']requirements-docs\.txt[\"']\s*\]\s*\}",
            text,
            re.MULTILINE,
        )


class TestGitignoreSphinxArtifacts:
    def test_autosummary_generated_dir_ignored(self):
        """docs/api/generated/ is regenerated on every build from the
        templates in docs/_templates/autosummary/. Committing it would
        churn the diff on every public-API change."""
        text = (REPO / ".gitignore").read_text(encoding="utf-8")
        assert "docs/api/generated/" in text


# ---------------------------------------------------------------------------
# gen_docs.py was moved, not deleted — keep audit trail intact
# ---------------------------------------------------------------------------


class TestArchivedGenerator:
    def test_old_path_is_gone(self):
        assert not (SCRIPTS / "gen_docs.py").exists(), (
            "scripts/gen_docs.py still exists — the docs migration should "
            "have moved it to scripts/_archive/."
        )

    def test_archived_copy_exists(self):
        """Preserving the source in _archive/ keeps the audit trail
        for the prior generation pipeline (Markdown subset rules,
        etc.) intact rather than relying on git history alone."""
        assert (SCRIPTS / "_archive" / "gen_docs.py").exists(), (
            "scripts/_archive/gen_docs.py is missing — the docs migration "
            "promised to keep an archived copy."
        )


# ---------------------------------------------------------------------------
# Real sphinx -W build (caught the kind of conf.py bug that pure-config
# tests miss, e.g. html_static_path pointing at a nonexistent directory)
# ---------------------------------------------------------------------------


def _sphinx_importable() -> bool:
    """Return True if the doc-build deps are installed.

    requirements-docs.txt is its own extra (`pip install .[docs]`),
    so a hermetic test env often won't have sphinx + furo + myst.
    Skip rather than fail when they're absent — CI / RTD always have
    them, so the build check still runs where it matters.
    """
    try:
        import sphinx  # noqa: F401
        import furo  # noqa: F401
        import myst_parser  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.mark.skipif(
    not _sphinx_importable(),
    reason="sphinx + furo + myst-parser not installed in this env",
)
def test_sphinx_build_succeeds_under_warning_gate(tmp_path):
    """Real ``sphinx -W -b html`` build. The pure-config tests above
    parse conf.py textually and assert on declared values, but they
    can't tell when a declared path is bogus (the historical
    ``html_static_path = ["_static"]`` pointing at a nonexistent
    directory). A real build catches the entire class of "config
    asserts correct values but the values reference missing files"
    bug at unit-gate time, before the RTD build trips it."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "sphinx", "-W", "-b", "html",
         str(DOCS), str(tmp_path / "html")],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        pytest.fail(
            f"sphinx -W build failed (exit {result.returncode}):\n"
            f"--- STDOUT (tail) ---\n{result.stdout[-2000:]}\n"
            f"--- STDERR (tail) ---\n{result.stderr[-2000:]}"
        )
