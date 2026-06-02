"""
Sphinx configuration for autonomous-app docs.

Run from repo root:
    sphinx-build -W -b html docs/ docs/_build/html

or via the makefile:
    make docs
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Put the in-tree library on sys.path so autodoc imports the local
# source (not whatever's pip-installed). Matches tests/conftest.py.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _read_version() -> str:
    """Single-source the version from src/autonomous/__init__.py.

    Mirrors how pyproject.toml does it — avoids hand-syncing two
    files. We parse the file textually rather than importing the
    package because autonomous's __init__ runs load_dotenv() and
    pulls in the log singleton, which we don't want side-effects from
    during a doc build.
    """
    init_path = ROOT / "src" / "autonomous" / "__init__.py"
    for line in init_path.read_text().splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


# -- Project information -----------------------------------------------------
project = "autonomous-app"
author = "Steven A. Moore"
copyright = "%Y, Steven A. Moore"
version = _read_version()
release = version

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",     # Google / NumPy docstring formats
    "sphinx.ext.viewcode",     # source code links from API ref
    "sphinx.ext.intersphinx",  # cross-link to stdlib / third-party docs
    "myst_parser",             # Markdown source files (the guides)
]

# Markdown files are first-class source — guides/* are Markdown.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# myst extensions enabled — colon-fence supports ```{toctree}``` style
# directives, which read like Markdown rather than RST.
myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "linkify",
    "smartquotes",
    "substitution",
]
myst_heading_anchors = 3

master_doc = "index"

exclude_patterns = [
    "_build",
    "_templates",
    "Thumbs.db",
    ".DS_Store",
    "superpowers/**",
]

# -- Autodoc / autosummary ---------------------------------------------------
# autosummary regenerates API-ref stubs from the templates in
# _templates/autosummary/ on every build, so a new public class
# doesn't need a hand-edited .rst file.
autosummary_generate = True
autosummary_imported_members = False

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
    "member-order": "bysource",
}

# Mock heavy / optional deps that may not be installable in the
# RTD build environment. Sphinx will substitute a magic-mock object
# so autodoc can introspect signatures even if the real package is
# absent. Keep this list minimal — fewer mocks = more accurate docs.
autodoc_mock_imports = [
    "google",          # google-genai (image / TTS / text)
    "pydub",           # audio decode/encode
    "PIL",             # image storage variants
    "pygit2",          # apis/version_control
    "github",          # PyGithub
    "rq",              # taskrunner
]

# Show typehints in the description, not in the signature, for readability.
autodoc_typehints = "description"

# Napoleon: parse Google-style docstrings (which is what the codebase
# uses — see baseagent.py get_client() for the canonical example).
napoleon_google_docstring = True
napoleon_numpy_docstring = False

# -- Intersphinx -------------------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "requests": ("https://requests.readthedocs.io/en/latest/", None),
}

# -- HTML output -------------------------------------------------------------
html_theme = "furo"
html_title = f"autonomous-app {version}"
html_static_path = ["assets"]
html_css_files = ["style.css"]  # carry over the existing custom style (lives in docs/assets/)
html_show_sourcelink = False
html_show_sphinx = False

# -- Suppress harmless warnings ----------------------------------------------
# Avoid -W treating these specific patterns as build-breaking:
#   - duplicate cross-references when autosummary re-emits a class
#     that the source's docstring also references with `:class:`
#   - missing-reference noise from unmocked stdlib symbols
suppress_warnings = [
    "myst.header",  # we allow non-monotonic header levels in guides
    # Vendored MongoEngine docstrings (autonomous.db.*) cross-link to
    # mongoengine's own doc tree (e.g. :doc:`guide/defining-documents`).
    # We don't host those targets, and rewriting the vendor's docstrings
    # is out of scope — drop the noise rather than have it gate -W.
    "ref.doc",
    "ref.ref",
]

# Skip private submodules of autonomous.db (vendored mongoengine fork).
# These have non-Sphinx docstrings that produce dozens of "Unexpected
# indentation" warnings and don't belong in the public reference.
def _skip_vendored(app, what, name, obj, skip, options):
    if name.startswith("autonomous.db.base") or name.startswith("autonomous.db.queryset"):
        return True
    return skip


def setup(app):
    app.connect("autodoc-skip-member", _skip_vendored)
