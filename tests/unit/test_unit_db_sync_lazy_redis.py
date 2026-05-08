"""Tests for the lazy-redis-import discipline in autonomous.db.db_sync.

After PR #39 (smoke-fail #34), top-level imports of `autonomous.db.db_sync`
(and therefore the entire `autonomous.db` package) must NOT require the
`redis` package. `redis` lives in the `[tasks]` extra and is only needed
when a worker actually invokes `_get_redis()` or `request_indexing()`.

These tests pin the structural contract so a future `import redis` at
module level regresses unit-test time — well before release-smoke would
catch it on PyPI install.

Also pins `pyproject.toml`'s `dynamic` list to include
`optional-dependencies`, the metadata edit that restored the `[all]` /
`[tasks]` extras after the dynamic-deps switchover.
"""

import re
import tomllib
from pathlib import Path

import pytest

import autonomous.db.db_sync as db_sync_mod


REPO_ROOT = Path(__file__).resolve().parents[2]


def _module_top_level_source(module) -> str:
    """Return the source above the first def/class — the module-level region."""
    import inspect

    source = inspect.getsource(module)
    # `def ` and `class ` mark the boundary between top-level code and
    # function/method bodies. Take whichever appears first.
    boundaries = [m.start() for m in re.finditer(r"^(def|class) ", source, re.M)]
    if not boundaries:
        return source
    return source[: min(boundaries)]


class TestLazyImportDiscipline:
    """Pin db_sync.py's top-level import set."""

    def test_no_top_level_redis_import(self):
        top = _module_top_level_source(db_sync_mod)
        assert not re.search(r"^\s*import\s+redis\b", top, re.M), (
            "Top-level 'import redis' detected in db_sync.py — breaks fresh "
            "installs without the [tasks] extra (regressed smoke-fail #34)."
        )
        assert not re.search(r"^\s*from\s+redis\b", top, re.M), (
            "Top-level 'from redis ...' detected in db_sync.py — same hazard."
        )

    def test_no_top_level_taskrunner_import(self):
        # autonomous.taskrunner.autotasks transitively imports `rq` (and
        # historically `redis`), which is only in the [tasks] extra.
        top = _module_top_level_source(db_sync_mod)
        assert "from autonomous.taskrunner" not in top, (
            "Top-level 'from autonomous.taskrunner ...' in db_sync.py — pulls "
            "rq/redis at import time and breaks ORM-only consumers."
        )
        assert "import autonomous.taskrunner" not in top, (
            "Top-level 'import autonomous.taskrunner' in db_sync.py — pulls "
            "rq/redis at import time and breaks ORM-only consumers."
        )

    def test_redis_only_imported_inside_get_redis(self):
        # Functions that need redis must do their own lazy import so the
        # rule survives even if a future cleanup deletes the module-level
        # comment.
        import inspect

        get_redis_src = inspect.getsource(db_sync_mod._get_redis)
        assert "import redis" in get_redis_src, (
            "_get_redis() should lazy-import redis at use site so the "
            "module remains importable without the [tasks] extra."
        )

    def test_request_indexing_lazy_imports_redis_and_taskrunner(self):
        import inspect

        src = inspect.getsource(db_sync_mod.request_indexing)
        assert "import redis" in src, (
            "request_indexing() should lazy-import redis."
        )
        assert "from autonomous.taskrunner" in src, (
            "request_indexing() should lazy-import autonomous.taskrunner."
        )


class TestPyprojectMetadata:
    """Pin pyproject's dynamic list — the metadata fix that restored extras."""

    def _load_pyproject(self) -> dict:
        with open(REPO_ROOT / "pyproject.toml", "rb") as f:
            return tomllib.load(f)

    def test_dynamic_includes_optional_dependencies(self):
        cfg = self._load_pyproject()
        dynamic = cfg["project"].get("dynamic", [])
        assert "optional-dependencies" in dynamic, (
            "pyproject.toml [project] dynamic must include "
            "'optional-dependencies' so [tasks]/[ai]/[all] extras "
            "actually publish in the wheel metadata. Without it, "
            "`pip install autonomous-app[tasks]` becomes a no-op and "
            "redis is silently absent."
        )

    def test_dynamic_includes_dependencies(self):
        cfg = self._load_pyproject()
        dynamic = cfg["project"].get("dynamic", [])
        # The whole point of dynamic deps is requirements.txt drives runtime
        # deps; verify we didn't accidentally drop it during the fix.
        assert "dependencies" in dynamic

    def test_dynamic_includes_version(self):
        cfg = self._load_pyproject()
        dynamic = cfg["project"].get("dynamic", [])
        # release.sh assumes version is dynamic and reads __init__.py.
        assert "version" in dynamic
