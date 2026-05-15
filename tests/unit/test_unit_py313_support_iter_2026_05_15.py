"""Tests for the iter/2026-05-15 Python 3.13 support batch (PR #75).

Independent test-agent coverage for the matrix/classifier change:

- CI matrix drops Python 3.11 from `.github/workflows/python-package.yml`.
- `pyproject.toml` adds the `Python :: 3.13` trove classifier.

The change is config-only (no source diff), but Python-version
declarations live in **three** places that need to stay consistent:

1. `pyproject.toml :: project.requires-python` — minimum supported.
2. `pyproject.toml :: project.classifiers` — PyPI's advertised list.
3. `.github/workflows/python-package.yml :: matrix.python-version` —
   what CI actually tests.

A drive-by edit to any one of those without updating the others
would silently misadvertise support or skip a version on CI. These
tests pin the consistency invariants. They're structural pins, not
behavioral — the right shape for a config-only change.
"""

import pathlib
import re

try:
    import tomllib  # 3.11+
except ImportError:  # pragma: no cover — predates 3.11
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import yaml  # PyYAML — available in dev deps
    _HAVE_YAML = True
except ImportError:  # pragma: no cover
    _HAVE_YAML = False


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "python-package.yml"
)


def _load_pyproject() -> dict:
    return tomllib.loads(PYPROJECT_PATH.read_text())


def _classifier_python_versions(pyproject: dict) -> set[str]:
    """Extract `X.Y` strings from the `Python :: X.Y` classifier lines."""
    versions = set()
    for c in pyproject.get("project", {}).get("classifiers", []):
        m = re.match(r"Programming Language :: Python :: (\d+\.\d+)$", c)
        if m:
            versions.add(m.group(1))
    return versions


def _ci_matrix_python_versions() -> set[str]:
    text = WORKFLOW_PATH.read_text()
    if _HAVE_YAML:
        # Parse YAML so a future restructure of the matrix block
        # doesn't silently break the test (vs a brittle string-match).
        doc = yaml.safe_load(text)
        for job in doc.get("jobs", {}).values():
            matrix = (
                job.get("strategy", {}).get("matrix", {}).get(
                    "python-version", []
                )
            )
            if matrix:
                return {str(v) for v in matrix}
        return set()
    # Fallback regex if PyYAML isn't installed. Looks for a list-form
    # `python-version: [...]` line.
    m = re.search(
        r"python-version:\s*\[([^\]]+)\]", text
    )
    if not m:
        return set()
    raw = m.group(1)
    return {p.strip().strip('"').strip("'") for p in raw.split(",")}


# ---------------------------------------------------------------------------
# The two diff-specific pins
# ---------------------------------------------------------------------------


def test_ci_matrix_does_not_include_python_311():
    # The substance of PR #75's CI side: 3.11 removed from the
    # build matrix because storyteller-dev / autonomous-test only
    # supports 3.12+. A regression that re-adds 3.11 would waste
    # CI minutes on a version that isn't actually supported.
    matrix = _ci_matrix_python_versions()
    assert "3.11" not in matrix, (
        f"CI matrix should NOT include Python 3.11 anymore "
        f"(supported floor is 3.12); got: {sorted(matrix)}"
    )


def test_pyproject_classifiers_include_python_313():
    # The substance of PR #75's classifier side: 3.13 added to the
    # PyPI-advertised trove classifiers so consumers searching for
    # 3.13-compatible packages find autonomous-app.
    pyproject = _load_pyproject()
    versions = _classifier_python_versions(pyproject)
    assert "3.13" in versions, (
        f"pyproject.toml classifiers should advertise Python 3.13 "
        f"per PR #75; got: {sorted(versions)}"
    )


# ---------------------------------------------------------------------------
# Cross-file consistency — catches drive-by drift on either side
# ---------------------------------------------------------------------------


def test_classifiers_and_ci_matrix_agree_on_python_versions():
    # Hard contract: every version on CI must be classifier-advertised,
    # and every classifier-advertised version must be on CI. Drift in
    # either direction is a misadvertisement.
    pyproject = _load_pyproject()
    classifiers = _classifier_python_versions(pyproject)
    matrix = _ci_matrix_python_versions()
    assert classifiers == matrix, (
        f"pyproject classifiers and CI matrix must agree on Python "
        f"versions. classifiers={sorted(classifiers)} "
        f"matrix={sorted(matrix)} "
        f"only-in-classifiers={sorted(classifiers - matrix)} "
        f"only-in-matrix={sorted(matrix - classifiers)}"
    )


def test_requires_python_floor_consistent_with_supported_set():
    # `requires-python = ">=X.Y"` is a hard install gate. It must be
    # ≤ the lowest version in the supported set (CI matrix +
    # classifiers). A floor higher than the lowest tested version
    # means consumers install but can't run (or CI tests an
    # uninstallable version).
    pyproject = _load_pyproject()
    requires = pyproject.get("project", {}).get(
        "requires-python", ""
    )
    m = re.match(r">=(\d+\.\d+)", requires)
    assert m, (
        f"requires-python should use `>=X.Y` form; got: {requires!r}"
    )
    floor = m.group(1)
    matrix = _ci_matrix_python_versions()
    classifiers = _classifier_python_versions(pyproject)
    supported = sorted(matrix | classifiers, key=lambda v: tuple(
        int(x) for x in v.split(".")
    ))
    lowest = supported[0] if supported else None
    assert lowest is not None
    # Compare lexicographically by (major, minor) tuple.
    floor_tuple = tuple(int(x) for x in floor.split("."))
    lowest_tuple = tuple(int(x) for x in lowest.split("."))
    assert floor_tuple <= lowest_tuple, (
        f"requires-python floor {floor!r} is HIGHER than the lowest "
        f"tested/advertised version {lowest!r} — consumers on that "
        f"version would be blocked at pip install"
    )
