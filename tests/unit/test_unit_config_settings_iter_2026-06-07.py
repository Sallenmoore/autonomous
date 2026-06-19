"""Independent test coverage for the centralized env-var config layer.

PR #57 (dev branch ``iter/2026-06-07-batch``, closes #49) introduced
``autonomous.config`` — guarded primitive parsers (``env_str`` / ``env_int``
/ ``env_float`` / ``env_bool`` / ``env_list``) plus a typed ``Settings``
snapshot, and migrated the AI adapters (``openai_compat``, ``local_model``,
``flux``) and ``db_sync._throttle_window_seconds`` onto it.

These tests are written from a fresh read of the PR diff (test-agent's
independent perspective) — they do NOT consult the dev agent's gitignored
``tests/_dev_local`` ephemerals. They pin the behaviors the PR explicitly
claims:

* the headline fix — a malformed/empty numeric env var falls back to the
  documented default instead of raising ``ValueError`` at import time;
* the two-layer contract — ``env_*`` read live, ``Settings`` is a snapshot;
* the ``HPC_JSON_MODEL`` derived-default parity (empty string preserved,
  only an *absent* key falls back to the text model);
* redaction / validation / catalog-describe surface;
* the ``db_sync`` poster-child now reads live through ``env_int`` and no
  longer crashes on a malformed value.
"""

import os
import subprocess
import sys

import pytest

from autonomous.config import (
    Settings,
    env_bool,
    env_float,
    env_int,
    env_list,
    env_str,
    settings,
)


# ---------------------------------------------------------------------------
# Primitive parsers — read os.environ live, coerce, fall back (never raise).
# ---------------------------------------------------------------------------

class TestEnvStr:
    def test_absent_key_returns_default(self, monkeypatch):
        monkeypatch.delenv("AUTONOMOUS_TEST_STR", raising=False)
        assert env_str("AUTONOMOUS_TEST_STR", "fallback") == "fallback"

    def test_default_default_is_empty_string(self, monkeypatch):
        monkeypatch.delenv("AUTONOMOUS_TEST_STR", raising=False)
        assert env_str("AUTONOMOUS_TEST_STR") == ""

    def test_set_value_is_returned(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_STR", "live")
        assert env_str("AUTONOMOUS_TEST_STR", "fallback") == "live"

    def test_empty_string_value_is_preserved_not_defaulted(self, monkeypatch):
        """An explicitly-empty value is a meaningful override (e.g. clearing
        a URL); only an *absent* key falls back. This mirrors
        ``os.environ.get(key, default)`` exactly."""
        monkeypatch.setenv("AUTONOMOUS_TEST_STR", "")
        assert env_str("AUTONOMOUS_TEST_STR", "fallback") == ""


class TestEnvInt:
    def test_valid_value_coerced(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_INT", "42")
        assert env_int("AUTONOMOUS_TEST_INT", 7) == 42

    def test_absent_key_returns_default(self, monkeypatch):
        monkeypatch.delenv("AUTONOMOUS_TEST_INT", raising=False)
        assert env_int("AUTONOMOUS_TEST_INT", 7) == 7

    def test_empty_string_returns_default_without_raising(self, monkeypatch):
        """The headline fix: a bare ``int(os.environ.get("X", 120))`` raises
        ValueError on an empty-string env value and crashed the import.
        ``env_int`` returns the default instead."""
        monkeypatch.setenv("AUTONOMOUS_TEST_INT", "")
        assert env_int("AUTONOMOUS_TEST_INT", 120) == 120

    def test_malformed_value_returns_default_without_raising(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_INT", "not-a-number")
        assert env_int("AUTONOMOUS_TEST_INT", 99) == 99

    def test_float_string_is_malformed_for_int(self, monkeypatch):
        """``int("1.5")`` raises — falls back rather than truncating."""
        monkeypatch.setenv("AUTONOMOUS_TEST_INT", "1.5")
        assert env_int("AUTONOMOUS_TEST_INT", 3) == 3

    def test_negative_value_coerced(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_INT", "-5")
        assert env_int("AUTONOMOUS_TEST_INT", 0) == -5


class TestEnvFloat:
    def test_valid_value_coerced(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_FLOAT", "1.25")
        assert env_float("AUTONOMOUS_TEST_FLOAT", 0.0) == 1.25

    def test_integer_string_coerces_to_float(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_FLOAT", "3")
        result = env_float("AUTONOMOUS_TEST_FLOAT", 0.0)
        assert result == 3.0 and isinstance(result, float)

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_FLOAT", "")
        assert env_float("AUTONOMOUS_TEST_FLOAT", 1.0) == 1.0

    def test_malformed_value_returns_default(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_FLOAT", "abc")
        assert env_float("AUTONOMOUS_TEST_FLOAT", 2.5) == 2.5


class TestEnvBool:
    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "Yes", "on", "y", "t", "  True  "])
    def test_truthy_variants(self, monkeypatch, raw):
        monkeypatch.setenv("AUTONOMOUS_TEST_BOOL", raw)
        assert env_bool("AUTONOMOUS_TEST_BOOL", False) is True

    @pytest.mark.parametrize("raw", ["0", "false", "FALSE", "No", "off", "n", "f"])
    def test_falsy_variants(self, monkeypatch, raw):
        monkeypatch.setenv("AUTONOMOUS_TEST_BOOL", raw)
        assert env_bool("AUTONOMOUS_TEST_BOOL", True) is False

    def test_empty_string_is_falsy_regardless_of_default(self, monkeypatch):
        """Empty string is in the FALSY set, so it returns False even when
        the default is True (distinct from an absent key)."""
        monkeypatch.setenv("AUTONOMOUS_TEST_BOOL", "")
        assert env_bool("AUTONOMOUS_TEST_BOOL", True) is False

    def test_absent_key_returns_default(self, monkeypatch):
        monkeypatch.delenv("AUTONOMOUS_TEST_BOOL", raising=False)
        assert env_bool("AUTONOMOUS_TEST_BOOL", True) is True
        assert env_bool("AUTONOMOUS_TEST_BOOL", False) is False

    def test_unrecognized_value_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_BOOL", "maybe")
        assert env_bool("AUTONOMOUS_TEST_BOOL", True) is True
        assert env_bool("AUTONOMOUS_TEST_BOOL", False) is False


class TestEnvList:
    def test_absent_key_returns_default_copy(self, monkeypatch):
        monkeypatch.delenv("AUTONOMOUS_TEST_LIST", raising=False)
        default = ["a", "b"]
        result = env_list("AUTONOMOUS_TEST_LIST", default)
        assert result == ["a", "b"]
        # Must be a *copy* — mutating the result must not corrupt the
        # caller's default list (a shared-mutable-default footgun).
        result.append("c")
        assert default == ["a", "b"]

    def test_absent_key_default_none_returns_empty_list(self, monkeypatch):
        monkeypatch.delenv("AUTONOMOUS_TEST_LIST", raising=False)
        assert env_list("AUTONOMOUS_TEST_LIST") == []

    def test_splits_on_separator(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_LIST", "a,b,c")
        assert env_list("AUTONOMOUS_TEST_LIST") == ["a", "b", "c"]

    def test_drops_empties_and_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_LIST", "a, b ,,  c ")
        assert env_list("AUTONOMOUS_TEST_LIST") == ["a", "b", "c"]

    def test_whitespace_acts_as_secondary_separator(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_LIST", "a b c")
        assert env_list("AUTONOMOUS_TEST_LIST") == ["a", "b", "c"]

    def test_custom_separator(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_TEST_LIST", "a;b;c")
        assert env_list("AUTONOMOUS_TEST_LIST", sep=";") == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Settings — typed snapshot built from the primitives.
# ---------------------------------------------------------------------------

class TestSettingsSnapshot:
    def test_construction_never_raises_on_malformed_numerics(self, monkeypatch):
        """Import-safety contract: every numeric field falls back to its
        default rather than letting a malformed value blow up construction."""
        monkeypatch.setenv("HPC_REQUEST_TIMEOUT", "garbage")
        monkeypatch.setenv("OLLAMA_CONTEXT_LIMIT", "")
        monkeypatch.setenv("FLUX_RETRY_SLEEP", "not-a-float")
        s = Settings()  # must not raise
        assert s.hpc_request_timeout == 120
        assert s.ollama_context_limit == 32768
        assert s.flux_retry_sleep == 1.0

    def test_snapshot_does_not_track_env_until_reload(self, monkeypatch):
        monkeypatch.setenv("HPC_REQUEST_TIMEOUT", "55")
        s = Settings()
        assert s.hpc_request_timeout == 55
        # Flip env *after* construction — the snapshot is frozen until reload.
        monkeypatch.setenv("HPC_REQUEST_TIMEOUT", "77")
        assert s.hpc_request_timeout == 55
        assert s.reload() is s  # reload returns self for chaining
        assert s.hpc_request_timeout == 77

    def test_field_types_are_coerced(self):
        s = Settings()
        assert isinstance(s.hpc_request_timeout, int)
        assert isinstance(s.flux_retry_sleep, float)
        assert isinstance(s.log_to_files, bool)
        assert isinstance(s.hpc_text_model, str)

    def test_defaults_mirror_documented_call_site_values(self, monkeypatch):
        """Behavior-preservation: with a clean env every default matches the
        value the original call site used."""
        for var in ("HPC_REQUEST_TIMEOUT", "OLLAMA_CONTEXT_LIMIT", "FLUX_TIMEOUT_S",
                    "HPC_TEXT_MODEL", "OLLAMA_MODEL", "FLUX_URL_BASE"):
            monkeypatch.delenv(var, raising=False)
        s = Settings()
        assert s.hpc_request_timeout == 120
        assert s.ollama_context_limit == 32768
        assert s.flux_timeout_s == 120
        assert s.hpc_text_model == "gpt-oss:20b"
        assert s.ollama_model == "gemma4:26b"
        assert s.flux_url_base == "https://fal.run"


class TestHpcJsonModelDerivedDefault:
    """The trickiest parity claim in the PR: HPC_JSON_MODEL defaults to the
    *resolved* text model, but an explicitly-empty value is preserved."""

    def test_absent_falls_back_to_default_text_model(self, monkeypatch):
        monkeypatch.delenv("HPC_JSON_MODEL", raising=False)
        monkeypatch.delenv("HPC_TEXT_MODEL", raising=False)
        s = Settings()
        assert s.hpc_json_model == s.hpc_text_model == "gpt-oss:20b"

    def test_absent_tracks_custom_text_model(self, monkeypatch):
        monkeypatch.delenv("HPC_JSON_MODEL", raising=False)
        monkeypatch.setenv("HPC_TEXT_MODEL", "custom-text:1b")
        s = Settings()
        assert s.hpc_json_model == "custom-text:1b"

    def test_explicit_empty_string_is_preserved(self, monkeypatch):
        """An empty HPC_JSON_MODEL must stay empty — it does NOT fall back to
        the text model. This is the exact ``os.environ.get`` key-absent vs
        empty-value distinction the PR claims to reproduce."""
        monkeypatch.setenv("HPC_TEXT_MODEL", "custom-text:1b")
        monkeypatch.setenv("HPC_JSON_MODEL", "")
        s = Settings()
        assert s.hpc_json_model == ""
        assert s.hpc_text_model == "custom-text:1b"

    def test_explicit_value_wins(self, monkeypatch):
        monkeypatch.setenv("HPC_TEXT_MODEL", "custom-text:1b")
        monkeypatch.setenv("HPC_JSON_MODEL", "custom-json:2b")
        s = Settings()
        assert s.hpc_json_model == "custom-json:2b"


class TestSettingsAsDict:
    def test_secret_set_value_is_redacted_by_default(self, monkeypatch):
        monkeypatch.setenv("HPC_API_KEY", "super-secret")
        s = Settings()
        assert s.as_dict()["hpc_api_key"] == "***"

    def test_secret_shown_when_redaction_disabled(self, monkeypatch):
        monkeypatch.setenv("HPC_API_KEY", "super-secret")
        s = Settings()
        assert s.as_dict(redact_secrets=False)["hpc_api_key"] == "super-secret"

    def test_empty_secret_is_not_redacted_to_stars(self, monkeypatch):
        """Redaction only fires on a truthy value — an unset secret stays
        empty so an operator can see it's missing."""
        monkeypatch.delenv("HPC_API_KEY", raising=False)
        s = Settings()
        assert s.as_dict()["hpc_api_key"] == ""

    def test_non_secret_value_never_redacted(self, monkeypatch):
        monkeypatch.setenv("HPC_TEXT_MODEL", "visible-model")
        s = Settings()
        assert s.as_dict()["hpc_text_model"] == "visible-model"

    def test_as_dict_covers_every_catalogued_field(self):
        s = Settings()
        attrs = {f["attr"] for f in Settings.describe()}
        assert set(s.as_dict().keys()) == attrs


class TestSettingsValidate:
    def test_unset_secret_produces_warning(self, monkeypatch):
        monkeypatch.delenv("HPC_API_KEY", raising=False)
        s = Settings()
        warnings = s.validate()
        assert any("HPC_API_KEY" in w for w in warnings)

    def test_set_secret_produces_no_warning(self, monkeypatch):
        monkeypatch.setenv("HPC_API_KEY", "present")
        s = Settings()
        assert not any("HPC_API_KEY" in w for w in s.validate())

    def test_validate_is_non_fatal_returns_list(self):
        s = Settings()
        assert isinstance(s.validate(), list)


class TestSettingsDescribe:
    def test_describe_is_static_and_nonempty(self):
        catalog = Settings.describe()
        assert isinstance(catalog, list) and catalog

    def test_every_entry_has_the_documented_keys(self):
        required = {"attr", "env", "kind", "default", "group", "description",
                    "secret", "migrated"}
        for entry in Settings.describe():
            assert required <= set(entry.keys()), entry

    def test_kinds_are_all_known_parsers(self):
        known = {"str", "int", "float", "bool", "list"}
        assert {e["kind"] for e in Settings.describe()} <= known

    def test_attrs_and_env_names_are_unique(self):
        catalog = Settings.describe()
        attrs = [e["attr"] for e in catalog]
        envs = [e["env"] for e in catalog]
        assert len(attrs) == len(set(attrs)), "duplicate attr in catalog"
        assert len(envs) == len(set(envs)), "duplicate env var in catalog"

    def test_migrated_callsites_are_flagged_migrated(self):
        """The fields whose call sites this PR actually moved onto the
        catalog must be marked migrated=True; the documentation-only entries
        (DB/redis/gemini/etc) stay migrated=False."""
        by_attr = {e["attr"]: e for e in Settings.describe()}
        for attr in ("hpc_request_timeout", "ollama_context_limit",
                     "flux_timeout_s", "flux_retry_sleep"):
            assert by_attr[attr]["migrated"] is True, attr
        for attr in ("db_host", "redis_port", "gemini_text_model"):
            assert by_attr[attr]["migrated"] is False, attr


# ---------------------------------------------------------------------------
# Migrated call sites.
# ---------------------------------------------------------------------------

class TestThrottleWindowLiveReads:
    """``db_sync._throttle_window_seconds`` — the #39 poster-child the issue
    called out. It now delegates to ``env_int`` and reads live every call."""

    def test_absent_returns_zero(self, monkeypatch):
        monkeypatch.delenv("HPC_UNREACHABLE_THROTTLE_SECONDS", raising=False)
        from autonomous.db import db_sync
        assert db_sync._throttle_window_seconds() == 0

    def test_valid_value(self, monkeypatch):
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "30")
        from autonomous.db import db_sync
        assert db_sync._throttle_window_seconds() == 30

    def test_malformed_returns_zero_without_raising(self, monkeypatch):
        """The bespoke try/except this replaced existed precisely because a
        malformed value used to be a live hazard. Must stay graceful."""
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "not-a-number")
        from autonomous.db import db_sync
        assert db_sync._throttle_window_seconds() == 0

    def test_reads_live_between_calls(self, monkeypatch):
        """No snapshot here — a config flip must land on the very next call
        without a reload/restart."""
        from autonomous.db import db_sync
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "10")
        assert db_sync._throttle_window_seconds() == 10
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "20")
        assert db_sync._throttle_window_seconds() == 20


class TestFieldPostInit:
    """N2 — Field.__post_init__ validates kind at construction time."""

    def test_valid_kind_accepted(self):
        from autonomous.config import Field
        for kind in ("str", "int", "float", "bool", "list"):
            Field("x", "X", kind, "" if kind in ("str", "list") else 0, "test")

    def test_invalid_kind_raises_type_error(self):
        from autonomous.config import Field
        with pytest.raises(TypeError, match="kind="):
            Field("x", "X", "date", "", "test")


class TestMigratedAdapterImportSafety:
    """End-to-end proof of the headline claim: a malformed numeric env var no
    longer crashes the import of a migrated AI adapter. Pre-PR these class
    attributes were ``int(os.environ.get(...))`` and a bad value raised
    ValueError at module import.

    Run in a *subprocess* with a fresh interpreter — importing a migrated
    adapter in-process and reloading it mutates global mongoengine class
    registries and module-level caches, polluting sibling tests. A subprocess
    isolates the import-time behavior that is exactly what this guards.
    """

    def _import_in_subprocess(self, env_overrides, snippet):
        from pathlib import Path
        env = dict(os.environ, **env_overrides)
        # Inject src/ into PYTHONPATH so the subprocess can find `autonomous`
        # under all setuptools editable-install modes (including the direct-URL
        # mode used by setuptools 64+ in GitHub Actions, which does not create
        # a .pth file discoverable by a fresh interpreter).
        src = Path(__file__).resolve().parent.parent.parent / "src"
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src}:{existing}" if existing else str(src)
        proc = subprocess.run(
            [sys.executable, "-c", snippet],
            env=env, capture_output=True, text=True,
        )
        return proc

    def test_openai_compat_tolerates_malformed_timeout(self):
        # Post-#177 _timeout is a (connect, read) tuple. Malformed
        # HPC_REQUEST_TIMEOUT falls back to the field default 120, which
        # then propagates into hpc_read_timeout (the back-compat
        # derived-default in Settings.__init__); hpc_connect_timeout
        # is its own field at default 10. Same import-safe-fallback
        # intent as pre-#177, new shape.
        snippet = (
            "from autonomous.ai.models.openai_compat import OpenAIClient;"
            "assert OpenAIClient._timeout == (10, 120),"
            "f'expected (10, 120) fallback, got {OpenAIClient._timeout!r}';"
            "print('OK')"
        )
        proc = self._import_in_subprocess(
            {"HPC_REQUEST_TIMEOUT": "definitely-not-an-int"}, snippet
        )
        assert proc.returncode == 0, (
            f"import crashed on malformed HPC_REQUEST_TIMEOUT:\n{proc.stderr}"
        )
        assert "OK" in proc.stdout

    def test_local_model_tolerates_malformed_context_limit(self):
        snippet = (
            "from autonomous.ai.models.local_model import LocalAIModel;"
            "assert LocalAIModel._context_limit == 32768,"
            "f'expected 32768 fallback, got {LocalAIModel._context_limit!r}';"
            "print('OK')"
        )
        proc = self._import_in_subprocess(
            {"OLLAMA_CONTEXT_LIMIT": "not-an-int"}, snippet
        )
        assert proc.returncode == 0, (
            f"import crashed on malformed OLLAMA_CONTEXT_LIMIT:\n{proc.stderr}"
        )
        assert "OK" in proc.stdout

    def test_module_singleton_is_a_settings_instance(self):
        assert isinstance(settings, Settings)
