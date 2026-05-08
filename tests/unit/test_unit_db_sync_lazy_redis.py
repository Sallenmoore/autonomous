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

import ast
import inspect
import re
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import autonomous.db.db_sync as db_sync_mod


REPO_ROOT = Path(__file__).resolve().parents[2]


def _module_level_imports(module) -> list[str]:
    """Return only top-level imports — uses AST so it ignores comments,
    strings, and imports nested inside function or class bodies. The earlier
    "split at first def/class" approach missed imports between functions.
    """
    tree = ast.parse(inspect.getsource(module))
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append(node.module or "")
    return out


# Anchored pattern: matches actual `import x` statements (not comments,
# not strings, not substrings of larger names like `import redis_helper`).
_IMPORT_STMT = lambda mod: re.compile(  # noqa: E731
    rf"^\s*(?:import\s+{re.escape(mod)}\b|from\s+{re.escape(mod)}\b)", re.M
)


class TestLazyImportDiscipline:
    """Pin db_sync.py's top-level import set."""

    def test_no_top_level_redis_import(self):
        # AST scan: ignores comments and nested imports, catches the
        # "import redis between functions" pattern the regex-only check missed.
        imports = _module_level_imports(db_sync_mod)
        assert "redis" not in imports, (
            f"Top-level 'import redis' detected in db_sync.py "
            f"(top-level imports: {imports}) — breaks fresh installs "
            "without the [tasks] extra (regressed smoke-fail #34)."
        )

    def test_no_top_level_taskrunner_import(self):
        # autonomous.taskrunner.autotasks transitively imports `rq` (and
        # historically `redis`), which is only in the [tasks] extra.
        imports = _module_level_imports(db_sync_mod)
        offenders = [m for m in imports if m.startswith("autonomous.taskrunner")]
        assert not offenders, (
            f"Top-level autonomous.taskrunner imports in db_sync.py: "
            f"{offenders} — pulls rq/redis at import time and breaks "
            "ORM-only consumers."
        )

    def test_redis_only_imported_inside_get_redis(self):
        # Anchored regex over actual function source — won't match a
        # comment containing the literal string "import redis".
        get_redis_src = inspect.getsource(db_sync_mod._get_redis)
        assert _IMPORT_STMT("redis").search(get_redis_src), (
            "_get_redis() should lazy-import redis at use site (anchored "
            "'import redis' or 'from redis ...' statement, not a comment)."
        )

    def test_request_indexing_lazy_imports_redis_and_taskrunner(self):
        src = inspect.getsource(db_sync_mod.request_indexing)
        assert _IMPORT_STMT("redis").search(src), (
            "request_indexing() should lazy-import redis (anchored stmt)."
        )
        assert _IMPORT_STMT("autonomous.taskrunner").search(src), (
            "request_indexing() should lazy-import autonomous.taskrunner."
        )


class TestEndToEndImportSmoke:
    """Subprocess test that masks `redis` to verify the WHOLE
    `autonomous.db` import path tolerates a missing [tasks] extra —
    catches a sibling module re-introducing top-level redis, which
    the structural db_sync.py-only checks above would miss.
    """

    def test_autonomous_db_imports_without_redis(self):
        # Pre-poison sys.modules so any `import redis` raises ImportError,
        # then verify the public ORM surface still loads. This is the same
        # contract release-smoke enforces, but at unit-test speed.
        code = textwrap.dedent("""
            import sys
            sys.modules["redis"] = None  # subsequent `import redis` raises
            try:
                import autonomous
                import autonomous.db
                from autonomous.db import Document  # the canonical ORM entrypoint
            except Exception as e:
                print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
                raise SystemExit(1)
            print("ok")
        """)
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0 and "ok" in result.stdout, (
            "`from autonomous.db import Document` must succeed when redis "
            "is unavailable (smoke-fail #34 regression).\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
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
