"""Item 9: validate the optional-dependencies layout in pyproject.toml.

Catches packaging regressions without spinning up a build:

- core requirements.txt only lists deps unconditionally imported by the
  package (no provider-specific bloat)
- each requirements-<extra>.txt file referenced from
  [tool.setuptools.dynamic.optional-dependencies] exists and is non-empty
- the [all] extra references every other extras file
- previously-listed-but-unused deps don't sneak back into core
"""

import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - py3.10 only
    import tomli as tomllib

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def pyproject():
    with open(REPO / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


@pytest.fixture(scope="module")
def core_lines():
    text = (REPO / "requirements.txt").read_text()
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _read_extras_file(name: str) -> list[str]:
    """Return the parsed dep names in a requirements-style file.

    Strips full-line comments, inline ``# ...`` comments, blank lines,
    and any version specifier so test assertions can compare names only.
    """
    deps = []
    for raw in (REPO / name).read_text().splitlines():
        line = raw.split("#", 1)[0].strip()  # drop inline comments
        if not line:
            continue
        # Drop version specifier — keep just the project name.
        for sep in ("==", ">=", "<=", "~=", ">", "<", ";"):
            if sep in line:
                line = line.split(sep, 1)[0].strip()
        deps.append(line)
    return deps


class TestCore:
    def test_core_has_only_unconditionally_used_deps(self, core_lines):
        # The dependencies that import directly at package load time.
        expected_core = {
            "python-dotenv",
            "pymongo",
            "blinker",
            "Authlib",
            "requests",
        }
        # We accept exact matches; unpinned deps may have version specs.
        actual = {line.split(";")[0].split("=")[0].split("<")[0].split(">")[0].strip()
                  for line in core_lines}
        assert expected_core == actual, (
            f"Core requirements drifted from the audited set.\n"
            f"Expected: {sorted(expected_core)}\nActual:   {sorted(actual)}"
        )

    def test_unused_deps_are_gone_from_core(self, core_lines):
        unused_or_optional = {
            "setuptools", "Flask", "jsmin", "ollama",
            "sentence-transformers", "dateparser", "python-slugify",
            "PyGithub", "pygit2", "pillow", "redis", "rq",
            "google-genai", "pydub", "gunicorn",
        }
        actual = {line.split(";")[0].strip() for line in core_lines}
        leaks = actual & unused_or_optional
        assert not leaks, f"Unused/optional deps in core requirements: {leaks}"


class TestExtras:
    @pytest.mark.parametrize(
        "extra,filename",
        [
            ("tasks", "requirements-tasks.txt"),
            ("images", "requirements-images.txt"),
            ("ai", "requirements-ai.txt"),
            ("github", "requirements-github.txt"),
            ("server", "requirements-server.txt"),
        ],
    )
    def test_extras_file_exists_and_nonempty(self, extra, filename):
        lines = _read_extras_file(filename)
        assert lines, f"Extra '{extra}' file {filename} has no deps"

    def test_pyproject_references_all_extras_files(self, pyproject):
        opt_deps = pyproject["tool"]["setuptools"]["dynamic"][
            "optional-dependencies"
        ]
        for extra in ("tasks", "images", "ai", "github", "server", "all"):
            assert extra in opt_deps, f"Missing extra: {extra}"
            files = opt_deps[extra]["file"]
            for f in files:
                assert (REPO / f).is_file(), f"Missing extras file: {f}"

    def test_all_extra_aggregates_others(self, pyproject):
        opt_deps = pyproject["tool"]["setuptools"]["dynamic"][
            "optional-dependencies"
        ]
        all_files = set(opt_deps["all"]["file"])
        for extra in ("tasks", "images", "ai", "github", "server"):
            single = opt_deps[extra]["file"][0]
            assert single in all_files, (
                f"[all] extra is missing {single} from [{extra}]"
            )

    def test_tasks_extra_contains_redis_and_rq(self):
        deps = set(_read_extras_file("requirements-tasks.txt"))
        assert {"redis", "rq"} <= deps

    def test_images_extra_contains_pillow(self):
        deps = set(_read_extras_file("requirements-images.txt"))
        assert "pillow" in deps

    def test_ai_extra_contains_gemini_deps(self):
        deps = set(_read_extras_file("requirements-ai.txt"))
        assert {"google-genai", "pydub"} <= deps

    def test_github_extra_contains_pygithub_and_pygit2(self):
        deps = set(_read_extras_file("requirements-github.txt"))
        assert {"PyGithub", "pygit2"} <= deps
