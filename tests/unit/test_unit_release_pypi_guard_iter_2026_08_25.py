"""Guard against a silent non-release (#233 near-miss).

``make package`` runs ``twine upload --skip-existing``. If the version being
released already exists on PyPI, twine skips the upload, exits 0, and
``release.sh`` goes on to commit, push and print ✅ — having published
nothing. The repo then believes a version shipped that PyPI never received.

That did NOT happen for 0.3.175 (verified against the wheel on #233), but
the mechanism is real, and the failure is silent by construction: nothing
downstream of the upload asserts that the artifact actually landed.

``scripts/pypi_release_check.py`` is that assertion. Tests stub the fetcher
— the unit tier is hermetic and the gate has no external egress, so a test
that really hit pypi.org would flake the whole run under ``-x``.
"""

import importlib.util
from pathlib import Path

import pytest

_MODULE = (
    Path(__file__).resolve().parents[2] / "scripts" / "pypi_release_check.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("pypi_release_check", _MODULE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load()


def _fetch(versions):
    return lambda package: versions


class TestCheck:
    def test_absent_expected_and_absent(self, mod):
        # The normal pre-flight: the version we are about to publish is new.
        assert mod.check("p", "0.3.176", "absent", fetch=_fetch({"0.3.175"})) == "ok"

    def test_absent_expected_but_present_is_the_bug(self, mod):
        # THE failure this exists for: releasing a version PyPI already has
        # means --skip-existing publishes nothing while everything reports ok.
        assert mod.check("p", "0.3.175", "absent", fetch=_fetch({"0.3.175"})) == "fail"

    def test_present_expected_and_present(self, mod):
        # The post-upload assertion on a healthy release.
        assert mod.check("p", "0.3.176", "present", fetch=_fetch({"0.3.176"})) == "ok"

    def test_present_expected_but_absent(self, mod):
        # Upload reported success but PyPI does not have it.
        assert mod.check("p", "0.3.176", "present", fetch=_fetch(set())) == "fail"

    def test_unreadable_index_is_unknown_not_fail(self, mod):
        # A flaky index read must not be reported as a definite verdict —
        # the caller decides whether "unknown" blocks (it warns and continues,
        # rather than stranding an upload that may well have succeeded).
        assert mod.check("p", "0.3.176", "absent", fetch=lambda p: None) == "unknown"
        assert mod.check("p", "0.3.176", "present", fetch=lambda p: None) == "unknown"


class TestFetchVersions:
    def test_parses_releases_keys(self, mod):
        import io
        import json as _json

        class _Resp(io.StringIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        payload = _json.dumps({"releases": {"0.3.174": [], "0.3.175": []}})
        got = mod.fetch_versions("p", opener=lambda url, timeout=None: _Resp(payload))
        assert got == {"0.3.174", "0.3.175"}

    def test_network_error_returns_none(self, mod):
        def _boom(url, timeout=None):
            raise OSError("name resolution failed")

        # None, not an exception: release.sh must be able to distinguish
        # "PyPI says no" from "could not ask PyPI".
        assert mod.fetch_versions("p", opener=_boom) is None

    def test_malformed_body_returns_none(self, mod):
        import io

        class _Resp(io.StringIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        assert mod.fetch_versions("p", opener=lambda u, timeout=None: _Resp("<html>")) is None


class TestPresentPolls:
    """The post-upload check must tolerate PyPI's index lag.

    Learned the hard way on 0.3.176: twine uploaded successfully at
    11:17:37Z, the immediate single-shot check read a stale index, called it
    a definite failure, and reverted the version bump — leaving PyPI holding
    a version the repo denied shipping. That is the exact divergence this
    guard exists to prevent, produced by the guard. The project already knew
    the index lags (the release-smoke 404 flake).
    """

    def test_present_retries_until_the_index_catches_up(self, mod):
        seen = {"n": 0}

        def flaky(package):
            seen["n"] += 1
            return {"0.3.176"} if seen["n"] >= 3 else {"0.3.175"}

        slept = []
        assert mod.check(
            "p", "0.3.176", "present",
            fetch=flaky, attempts=5, delay=7, sleep=slept.append,
        ) == "ok"
        assert seen["n"] == 3
        assert slept == [7, 7]  # slept between attempts, not after the last

    def test_present_gives_up_after_the_budget(self, mod):
        slept = []
        assert mod.check(
            "p", "0.3.176", "present",
            fetch=_fetch(set()), attempts=3, delay=1, sleep=slept.append,
        ) == "fail"
        assert len(slept) == 2

    def test_absent_never_polls(self, mod):
        # A version cannot vanish from PyPI, so retrying the pre-flight would
        # only slow down the abort on a real collision.
        seen = {"n": 0}

        def counting(package):
            seen["n"] += 1
            return {"0.3.175"}

        slept = []
        assert mod.check(
            "p", "0.3.175", "absent",
            fetch=counting, attempts=5, delay=1, sleep=slept.append,
        ) == "fail"
        assert seen["n"] == 1
        assert slept == []

    def test_unknown_also_retries(self, mod):
        # A transient read error is as recoverable as a lagging index.
        seen = {"n": 0}

        def flaky(package):
            seen["n"] += 1
            return None if seen["n"] < 2 else {"0.3.176"}

        assert mod.check(
            "p", "0.3.176", "present",
            fetch=flaky, attempts=4, delay=1, sleep=lambda _: None,
        ) == "ok"


class TestExitCodes:
    """release.sh branches on these, so they are the contract."""

    @pytest.mark.parametrize(
        "verdict,expected", [("ok", 0), ("fail", 1), ("unknown", 2)]
    )
    def test_exit_code_mapping(self, mod, verdict, expected):
        assert mod.EXIT_CODES[verdict] == expected
