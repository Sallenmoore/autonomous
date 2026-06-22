# `_select_related` flag on `AutoModel.all()` / `search()` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, default-off `_select_related: bool | int` parameter to `AutoModel.all()` and `AutoModel.search()` that routes through the existing `QuerySet.select_related()` batch-dereference path, eliminating the reference N+1 without consumers rewriting to `where()`.

**Architecture:** A single module-level private helper `_maybe_select_related(qs, flag)` in `model/automodel.py` translates the flag → `max_depth` (with validation) and applies `qs.select_related(...)`, or returns the queryset unchanged when off. `all()` and `search()` route their queryset through it before `list(...)`; in `search()` it is applied **last** (after `_order_by` / `_limit`) so only returned rows are batched. No change to `select_related` / `DeReference` themselves.

**Tech Stack:** Python 3.12+, the in-tree MongoEngine-derived ODM (`autonomous.db`), pytest. Spec: [`docs/superpowers/specs/2026-06-22-select-related-flag-design.md`](../specs/2026-06-22-select-related-flag-design.md). Issue: Sallenmoore/autonomous#195.

**Repo conventions that shape this plan:**
- **TDD tests are ephemeral.** Write failing tests in `tests/_dev_local/` (gitignored — see "Two-perspective testing" in `CLAUDE.md`). They are your local proof; **do NOT commit them**. Each "Commit" step stages only `src/` + docs, never `tests/_dev_local/`.
- **The committed `tests/unit/` query-count tests are the test agent's job**, written independently downstream from the PR diff (Task 6 is the handoff, not a coding task here).
- Run pytest non-interactively to avoid the global `--pdb` addopts hang: `python -m pytest <path> --override-ini="addopts=--no-cov -rfE --tb=short -q"`.
- Branch: `feat/195-select-related-flag` (already cut from `dev`, holds the spec commit). Activate the venv: `source /opt/projects/autonomous/dev/.venv/bin/activate`.
- End commit messages with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File map

- **Modify** `src/autonomous/model/automodel.py` — add `_maybe_select_related` (module level), add `_select_related` param to `all()` (`:288`) and `search()` (`:293`).
- **Modify** `MIGRATIONS.md` — additive "Added" entry.
- **Ephemeral (not committed)** `tests/_dev_local/test_195_select_related_flag.py` — TDD proof.

---

### Task 1: The `_maybe_select_related` helper

**Files:**
- Modify: `src/autonomous/model/automodel.py` (add module-level helper near the other module-level helpers, above the `AutoModel` class)
- Test (ephemeral): `tests/_dev_local/test_195_select_related_flag.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/_dev_local/test_195_select_related_flag.py
from unittest.mock import MagicMock

import pytest

from autonomous.model.automodel import _maybe_select_related


class TestMaybeSelectRelatedHelper:
    def test_falsy_returns_queryset_unchanged_and_never_calls_select_related(self):
        for off in (False, 0, None):
            qs = MagicMock()
            assert _maybe_select_related(qs, off) is qs
            qs.select_related.assert_not_called()

    def test_true_applies_depth_1(self):
        qs = MagicMock()
        out = _maybe_select_related(qs, True)
        qs.select_related.assert_called_once_with(max_depth=1)
        assert out is qs.select_related.return_value

    def test_int_applies_that_depth(self):
        qs = MagicMock()
        _maybe_select_related(qs, 3)
        qs.select_related.assert_called_once_with(max_depth=3)

    def test_negative_int_raises_value_error(self):
        with pytest.raises(ValueError):
            _maybe_select_related(MagicMock(), -1)

    def test_wrong_type_raises_type_error(self):
        for bad in ("2", 2.0, [1]):
            with pytest.raises(TypeError):
                _maybe_select_related(MagicMock(), bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/_dev_local/test_195_select_related_flag.py -v --override-ini="addopts=--no-cov -rfE --tb=short -q"`
Expected: FAIL — `ImportError: cannot import name '_maybe_select_related'`.

- [ ] **Step 3: Write minimal implementation**

Add this module-level function in `src/autonomous/model/automodel.py` (place it with the other module-level helpers, before `class AutoModel`):

```python
def _maybe_select_related(qs, flag):
    """Apply ``.select_related(max_depth=...)`` to ``qs`` per ``flag``, else
    return ``qs`` unchanged.

    ``flag``: falsy (``False`` / ``0`` / ``None``) → off; ``True`` → depth 1;
    int ``N`` (≥ 1) → depth ``N``. ``bool`` is an ``int`` subclass, so both
    pass the type check; other types raise ``TypeError``; negative ints raise
    ``ValueError``.
    """
    if not flag:                       # False / 0 / None → off
        return qs
    if not isinstance(flag, int):      # bool & int pass; str/float/list rejected
        raise TypeError("_select_related must be a bool or int")
    if flag < 1:                       # negative (truthy) int
        raise ValueError("_select_related must be True or a positive int")
    return qs.select_related(max_depth=int(flag))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/_dev_local/test_195_select_related_flag.py -v --override-ini="addopts=--no-cov -rfE --tb=short -q"`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit (src only — the ephemeral test is gitignored)**

```bash
git add src/autonomous/model/automodel.py
git commit -m "feat(model): add _maybe_select_related helper for #195

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wire the flag into `all()`

**Files:**
- Modify: `src/autonomous/model/automodel.py` — `all()` (currently `:288`)
- Test (ephemeral): append to `tests/_dev_local/test_195_select_related_flag.py`

- [ ] **Step 1: Write the failing test**

This patches the module seams so no MongoDB is needed: `_ensure_connected` → no-op, the model's `objects` → a sentinel queryset, and `_maybe_select_related` → a spy capturing `(qs, flag)`. Use any concrete `AutoModel` subclass from the suite; if none is convenient, the minimal stub below works.

```python
# append to tests/_dev_local/test_195_select_related_flag.py
import autonomous.model.automodel as am


class _M(am.AutoModel):
    meta = {"collection": "m_195_probe"}


class TestAllRoutesFlag:
    def _patch(self, monkeypatch):
        monkeypatch.setattr(am, "_ensure_connected", lambda: None)
        captured = {}
        monkeypatch.setattr(
            am, "_maybe_select_related",
            lambda qs, flag: (captured.__setitem__("qs", qs),
                              captured.__setitem__("flag", flag), [])[-1],
        )
        # stub the QuerySetManager descriptor with a plain callable so
        # ``cls.objects(**kw)`` returns our sentinel without a DB connection
        monkeypatch.setattr(_M, "objects", staticmethod(lambda *a, **k: "QS"))
        return captured

    def test_all_default_passes_falsy_flag(self, monkeypatch):
        cap = self._patch(monkeypatch)
        assert _M.all() == []
        assert cap["qs"] == "QS"
        assert cap["flag"] is False

    def test_all_forwards_flag_value(self, monkeypatch):
        cap = self._patch(monkeypatch)
        _M.all(_select_related=2)
        assert cap["flag"] == 2
```

> If patching `objects` via the metaclass property is awkward in the suite, follow the hermetic model-stub pattern already used in `tests/unit/test_unit_select_related_iter_2026-06-21.py` (the test agent's Tier-1 test) — build the queryset stub the same way and patch `cls.objects` accordingly. The assertion is the same: `all()` forwards `(cls.objects(), _select_related)` to `_maybe_select_related`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/_dev_local/test_195_select_related_flag.py::TestAllRoutesFlag -v --override-ini="addopts=--no-cov -rfE --tb=short -q"`
Expected: FAIL — `all()` doesn't accept `_select_related` (TypeError: unexpected keyword argument), and/or doesn't call the helper.

- [ ] **Step 3: Write minimal implementation**

Replace `all()` in `src/autonomous/model/automodel.py`:

```python
    @classmethod
    def all(cls, _select_related: bool | int = False) -> list[Self]:
        """Return every instance of this model. Use ``search`` for filtering.

        ``_select_related`` (default ``False``) opts into batch dereference of
        reference fields: ``True`` → depth 1, int ``N`` → depth ``N``. Off by
        default — behavior is unchanged for existing callers.
        """
        _ensure_connected()
        return list(_maybe_select_related(cls.objects(), _select_related))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/_dev_local/test_195_select_related_flag.py::TestAllRoutesFlag -v --override-ini="addopts=--no-cov -rfE --tb=short -q"`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit (src only)**

```bash
git add src/autonomous/model/automodel.py
git commit -m "feat(model): _select_related flag on AutoModel.all() (#195)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Wire the flag into `search()` — applied after `_order_by` / `_limit`

**Files:**
- Modify: `src/autonomous/model/automodel.py` — `search()` (currently `:293`)
- Test (ephemeral): append to `tests/_dev_local/test_195_select_related_flag.py`

- [ ] **Step 1: Write the failing test**

The ordering assertion: the queryset handed to `_maybe_select_related` must be the **post-`_limit`** object, not the raw queryset. Model the queryset as a chainable mock whose slice returns a distinct sentinel.

```python
# append to tests/_dev_local/test_195_select_related_flag.py
class TestSearchRoutesFlag:
    def _patch(self, monkeypatch):
        monkeypatch.setattr(am, "_ensure_connected", lambda: None)
        captured = {}
        monkeypatch.setattr(
            am, "_maybe_select_related",
            lambda qs, flag: (captured.__setitem__("qs", qs),
                              captured.__setitem__("flag", flag), [])[-1],
        )
        qs = MagicMock(name="base_qs")
        qs.order_by.return_value = qs
        qs.__getitem__.return_value = "LIMITED_QS"   # any slice → distinct sentinel
        monkeypatch.setattr(_M, "objects", staticmethod(lambda *a, **k: qs))
        return captured

    def test_search_default_off(self, monkeypatch):
        cap = self._patch(monkeypatch)
        _M.search(name="x")
        assert cap["flag"] is False

    def test_search_forwards_depth(self, monkeypatch):
        cap = self._patch(monkeypatch)
        _M.search(name="x", _select_related=2)
        assert cap["flag"] == 2

    def test_search_applies_after_limit(self, monkeypatch):
        cap = self._patch(monkeypatch)
        _M.search(name="x", _limit=5, _select_related=True)
        # the helper must receive the post-slice queryset, not the raw one
        assert cap["qs"] == "LIMITED_QS"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/_dev_local/test_195_select_related_flag.py::TestSearchRoutesFlag -v --override-ini="addopts=--no-cov -rfE --tb=short -q"`
Expected: FAIL — `search()` doesn't accept `_select_related`.

- [ ] **Step 3: Write minimal implementation**

Replace `search()` in `src/autonomous/model/automodel.py` (preserve the existing `str -> __icontains` translation and `_order_by` / `_limit` handling; add the param and the helper call **last**):

```python
    @classmethod
    def search(
        cls,
        _order_by: tuple[str, ...] | list[str] | None = None,
        _limit: int | list[int] | None = None,
        _select_related: bool | int = False,
        **kwargs: Any,
    ) -> list[Self]:
        """Case-insensitive substring search across the supplied fields.

        String values become ``__icontains`` queries; non-string values
        become exact matches. ``_order_by`` is forwarded to mongoengine;
        ``_limit`` accepts either a slice end or a ``[start, end]`` pair.
        ``_select_related`` (default ``False``) opts into batch dereference
        of reference fields on the returned rows: ``True`` → depth 1, int
        ``N`` → depth ``N``. Applied after ``_order_by`` / ``_limit`` so only
        returned rows are fetched. Off by default — unchanged for existing
        callers.
        """
        _ensure_connected()
        new_kwargs: dict[str, Any] = {}
        for k, v in kwargs.items():
            if isinstance(v, str):
                new_kwargs[f"{k}__icontains"] = v
            else:
                new_kwargs[k] = v
        results = cls.objects(**new_kwargs)
        if _order_by:
            results = results.order_by(*_order_by)
        if _limit:
            if isinstance(_limit, list):
                results = results[_limit[0] : _limit[-1]]
            else:
                results = results[:_limit]
        results = _maybe_select_related(results, _select_related)
        return list(results)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/_dev_local/test_195_select_related_flag.py -v --override-ini="addopts=--no-cov -rfE --tb=short -q"`
Expected: PASS (all classes — helper + all() + search()).

- [ ] **Step 5: Commit (src only)**

```bash
git add src/autonomous/model/automodel.py
git commit -m "feat(model): _select_related flag on AutoModel.search(), applied after limit (#195)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: MIGRATIONS.md entry

**Files:**
- Modify: `MIGRATIONS.md` (top / "Unreleased" section, most-recent-first)

- [ ] **Step 1: Add the entry**

Add under the most-recent / Unreleased heading (match the file's existing entry format):

```markdown
### Added — `_select_related` flag on `AutoModel.all()` / `search()` (#195)

`all()` and `search()` gained an optional `_select_related: bool | int = False`
control argument that batch-dereferences reference fields via the existing
`QuerySet.select_related()` path (one `$in` per referenced collection instead of
N lazy fetches). **Default off — no change for existing callers.**

- `_select_related=True` → `max_depth=1`; `_select_related=N` → `max_depth=N`.
- In `search()` it is applied after `_order_by` / `_limit`, so only returned
  rows are fetched.
- Negative int → `ValueError`; non-bool/non-int → `TypeError`.

This is the ergonomic surface over the batch path documented in
`db/DIVERGENCE.md` ("Reference dereference is N+1 by default"); for single-doc
or chained queries continue to use `where(...).select_related()`.
```

- [ ] **Step 2: Commit**

```bash
git add MIGRATIONS.md
git commit -m "docs(migrations): document _select_related flag on all()/search() (#195)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Full local gate + self-review

**Files:** none (verification)

- [ ] **Step 1: Run the unit suite**

Run: `python -m pytest tests/unit --override-ini="addopts=--no-cov -rfE --tb=short -q"`
Expected: PASS, 0 failed (the change is additive + default-off; nothing existing should break).

- [ ] **Step 2: Syntax-gate lint**

Run: `flake8 src/autonomous/model/automodel.py --select=E9,F63,F7,F82`
Expected: clean (no output).

- [ ] **Step 3: Self-review the diff against the spec**

Run: `git diff dev...HEAD -- src/autonomous/model/automodel.py MIGRATIONS.md`
Confirm: default-off path is byte-identical for existing callers; `search()` applies `select_related` after `_limit`; validation matches the spec (ValueError/TypeError); no change to `select_related`/`DeReference`/`fields.py`.

- [ ] **Step 4: Drop the ephemeral test**

The TDD test lives only locally. Confirm it is NOT staged anywhere: `git status --porcelain` shows nothing under `tests/_dev_local/` (it's gitignored). Leave the file in place as a local probe if you like; it will never be committed.

---

### Task 6: Pipeline handoff (coordinator-driven — not a coding task)

This is the dev→test→main→release flow; it happens after the code tasks, driven in the collaborative session.

- [ ] **Step 1: Push the branch + open the `dev → test` PR**

```bash
git push -u origin feat/195-select-related-flag
gh pr create -R Sallenmoore/autonomous --base test --head feat/195-select-related-flag \
  --title "feat(model): _select_related flag on all()/search() (#195)" \
  --body "Closes #195. Opt-in default-off batch-dereference flag (spec: docs/superpowers/specs/2026-06-22-select-related-flag-design.md). New public capability → warrants a release (auto-release)."
```

Watch CI to green (Python matrix). The PR **should carry `auto-release`** — this is a real public capability → a 0.3.169 release.

- [ ] **Step 2: Test agent writes the committed query-count tests**

The test agent (dispatched by the coordinator) writes `tests/unit/test_unit_..._select_related_flag_iter_2026-06-22.py` independently: default-off ⇒ N+1 / no `select_related`; `=True` ⇒ one `in_bulk` per collection + zero per-access derefs; depth maps through; `search()` batches only post-`_limit` rows; generic-reference/`ReferenceAttr` covered; invalid input ⇒ `ValueError` / `TypeError`. (Mirror the seam used in `tests/unit/test_unit_select_related_iter_2026-06-21.py`.)

- [ ] **Step 3: Coordinator promotes + releases**

`test → main` PR with `auto-release` → CI green → **user-authorized** merge + `release.sh` → **0.3.169** → smoke → `main → dev` back-merge. Close #195.

---

## Notes for the implementer

- **YAGNI:** do not touch `find()`/`get()`/`random()`/`where()`, and do not modify `select_related`/`DeReference`. The whole change is one helper + two signatures + a MIGRATIONS note.
- **The default-off path must be byte-identical** to today — `_maybe_select_related(qs, False)` returns `qs` and never calls `select_related`, so existing call sites are provably unaffected.
- If the metaclass-`objects` patching in the ephemeral tests is fiddly, reuse the hermetic `Document.__new__` + hand-set `_data` stub pattern from `tests/unit/test_unit_select_related_iter_2026-06-21.py`; the assertions (flag routing, after-limit ordering) are unchanged.
