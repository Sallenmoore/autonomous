"""Centralized, typed environment-variable configuration.

This module is the single catalog of every environment variable the
``autonomous`` framework reads. It exists to fix the problems that come
from ~110 ad-hoc ``os.environ.get`` / ``os.getenv`` reads scattered across
the subpackages (issue #49):

1. **No validation / no shared coercion.** Most numeric reads were bare
   ``int(os.environ.get("X", default))`` calls with no guard — a malformed
   value (or an empty string) raised ``ValueError`` *at import time* and
   took the whole package down. The ``env_*`` parsers below fall back to
   the documented default and log a breadcrumb instead.
2. **No central documentation.** Operators had to grep the source to
   discover env vars. :class:`Settings` is the catalog; :meth:`Settings.describe`
   and ``docs/configuration.md`` are generated from it.
3. **Inconsistent default semantics.** One shared parser per type means
   every site coerces the same way.

Design notes
------------
* **Two layers.** The ``env_*`` functions are the primitive — they read
  ``os.environ`` *live* on each call and are safe to use where a value must
  reflect a runtime config flip (e.g. ``db_sync``'s throttle window).
  :class:`Settings` is a typed **snapshot** built from those primitives at
  construction time; the module singleton :data:`settings` snapshots once at
  import (after :func:`dotenv.load_dotenv` has run via ``autonomous/__init__``).
  Call :meth:`Settings.reload` to rebuild the snapshot (tests, hot-reload).
* **Import-safe.** Every field has a default; nothing here raises at import.
  This preserves the hermetic-unit-test contract (importing ``autonomous``
  never requires env vars or live services).
* **Behavior-preserving.** Each field's default matches the value the
  original call site used, so existing deployments are unaffected.
* **Stdlib only.** No new core dependency (no pydantic) — consistent with
  the framework's minimal-core philosophy.

This is the first slice of issue #49: the catalog plus migration of the
fragile numeric reads in the AI model adapters and ``db_sync``'s throttle
parser. The remaining subpackages (auth, storage, taskrunner, the DB
connection helpers, the GitHub API wrappers) still read ``os.environ``
directly and are documented here for a follow-up per-subpackage migration —
old reads co-exist with the catalog during the transition.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from autonomous.logger import log

__all__ = [
    "Settings",
    "settings",
    "env_str",
    "env_int",
    "env_float",
    "env_bool",
    "env_list",
]


# ---------------------------------------------------------------------------
# Primitive parsers — read os.environ live, coerce, and fall back to the
# documented default (with a logged breadcrumb) rather than raising.
# ---------------------------------------------------------------------------

#: Values (case-insensitive) treated as boolean true by :func:`env_bool`.
_TRUTHY = {"1", "true", "yes", "on", "y", "t"}
_FALSY = {"0", "false", "no", "off", "n", "f", ""}


def env_str(key: str, default: str = "") -> str:
    """Return ``os.environ[key]`` or ``default`` when the key is unset.

    Mirrors ``os.environ.get(key, default)``: the default is used only when
    the key is *absent*. An empty-string env value is returned as-is (an
    empty string can be a meaningful override, e.g. clearing a URL).
    """
    val = os.environ.get(key)
    return default if val is None else val


def env_int(key: str, default: int) -> int:
    """Return ``int(os.environ[key])`` or ``default``.

    Falls back to ``default`` (with a logged breadcrumb) when the var is
    unset, empty, or not parseable as an int — never raises. Note an empty
    string falls back rather than raising ``ValueError`` like a bare
    ``int(os.environ.get(...))`` would.
    """
    val = os.environ.get(key)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        log(f"[CONFIG] {key}={val!r} is not a valid int; using default {default!r}")
        return default


def env_float(key: str, default: float) -> float:
    """Return ``float(os.environ[key])`` or ``default`` (never raises)."""
    val = os.environ.get(key)
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        log(f"[CONFIG] {key}={val!r} is not a valid float; using default {default!r}")
        return default


def env_bool(key: str, default: bool = False) -> bool:
    """Return a boolean from ``os.environ[key]``.

    Recognizes ``1/true/yes/on/y/t`` (true) and ``0/false/no/off/n/f``/empty
    (false), case-insensitively. Unrecognized values fall back to ``default``
    with a logged breadcrumb.
    """
    val = os.environ.get(key)
    if val is None:
        return default
    norm = val.strip().lower()
    if norm in _TRUTHY:
        return True
    if norm in _FALSY:
        return False
    log(f"[CONFIG] {key}={val!r} is not a recognized bool; using default {default!r}")
    return default


def env_list(key: str, default: list[str] | None = None, sep: str = ",") -> list[str]:
    """Return a list parsed from ``os.environ[key]``.

    Splits on ``sep`` (and whitespace), dropping empties. Returns a copy of
    ``default`` (or ``[]``) when the var is unset.
    """
    if default is None:
        default = []
    val = os.environ.get(key)
    if val is None:
        return list(default)
    parts: list[str] = []
    for chunk in val.split(sep):
        parts.extend(chunk.split())
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Field catalog — declarative spec consumed by Settings.__init__, validate(),
# and describe(). Adding a field here adds it to the typed catalog and the
# generated docs in one place.
# ---------------------------------------------------------------------------

_KIND_PARSERS = {
    "str": env_str,
    "int": env_int,
    "float": env_float,
    "bool": env_bool,
    "list": env_list,
}

#: Valid ``Field.kind`` values — checked at Field construction time.
_VALID_KINDS: frozenset[str] = frozenset(_KIND_PARSERS)


@dataclass(frozen=True)
class Field:
    """One env-var entry in the :class:`Settings` catalog."""

    attr: str          # Settings attribute name (snake_case)
    env: str           # environment variable name
    kind: str          # one of _KIND_PARSERS keys
    default: Any       # default value used when the env var is unset
    group: str         # subpackage / functional grouping (for docs)
    description: str = ""
    secret: bool = False   # redact value in describe()/as_dict()
    migrated: bool = True   # False = catalogued but call site still reads os.environ directly

    def __post_init__(self) -> None:
        if self.kind not in _VALID_KINDS:
            raise TypeError(
                f"Field {self.attr!r}: kind={self.kind!r} is not one of {sorted(_VALID_KINDS)}"
            )


# NOTE: defaults below intentionally mirror the original call-site defaults
# exactly. Changing a default is a behavior change and belongs in its own PR.
_SPEC: tuple[Field, ...] = (
    # --- Database (model.automodel, db.db_sync) -----------------------------
    Field("db_host", "DB_HOST", "str", "db", "database", "MongoDB host", migrated=False),
    Field("db_port", "DB_PORT", "int", 27017, "database", "MongoDB port", migrated=False),
    Field("db_username", "DB_USERNAME", "str", "", "database", "MongoDB username", secret=True, migrated=False),
    Field("db_password", "DB_PASSWORD", "str", "", "database", "MongoDB password", secret=True, migrated=False),
    Field("db_db", "DB_DB", "str", "", "database", "MongoDB database name", migrated=False),

    # --- Redis / task queue (taskrunner.autotasks, db.db_sync) --------------
    Field("redis_host", "REDIS_HOST", "str", "cachedb", "redis", "Redis host", migrated=False),
    Field("redis_port", "REDIS_PORT", "int", 6379, "redis", "Redis port", migrated=False),
    Field("redis_db", "REDIS_DB", "int", 0, "redis", "Redis logical DB index", migrated=False),
    Field("redis_username", "REDIS_USERNAME", "str", "", "redis", "Redis username", secret=True, migrated=False),
    Field("redis_password", "REDIS_PASSWORD", "str", "", "redis", "Redis password", secret=True, migrated=False),

    # --- AI: HPC / OpenAI-compatible adapter (ai.models.openai_compat) ------
    Field("hpc_api_base_url", "HPC_API_BASE_URL", "str", "", "ai_hpc", "Open WebUI / HPC base URL"),
    Field("hpc_api_key", "HPC_API_KEY", "str", "", "ai_hpc", "HPC API key", secret=True),
    Field("hpc_text_model", "HPC_TEXT_MODEL", "str", "gpt-oss:20b", "ai_hpc", "Default text model"),
    # hpc_json_model defaults to hpc_text_model — resolved in __init__.
    Field("hpc_json_model", "HPC_JSON_MODEL", "str", "", "ai_hpc", "JSON model (defaults to text model)"),
    Field("hpc_summary_model", "HPC_SUMMARY_MODEL", "str", "gemma4:26b", "ai_hpc", "Summary model"),
    Field("hpc_embedding_model", "HPC_EMBEDDING_MODEL", "str", "dengcao/Qwen3-Embedding-8B:F16", "ai_hpc", "Embedding model"),
    Field("hpc_stt_model", "HPC_STT_MODEL", "str", "whisper-1", "ai_hpc", "Speech-to-text model"),
    Field("hpc_request_timeout", "HPC_REQUEST_TIMEOUT", "int", 120, "ai_hpc", "Per-request timeout (s)"),
    Field("hpc_retry_attempts", "HPC_RETRY_ATTEMPTS", "int", 3, "ai_hpc", "Retry attempts"),
    Field("hpc_retry_backoff", "HPC_RETRY_BACKOFF", "int", 10, "ai_hpc", "Retry backoff (s)"),
    Field("hpc_unreachable_throttle_seconds", "HPC_UNREACHABLE_THROTTLE_SECONDS", "int", 0, "ai_hpc",
          "Throttle window for [HPC-UNREACHABLE] log floods (0 = disabled)"),

    # --- AI: local Ollama + media service (ai.models.local_model) ------------
    Field("ollama_api_base_url", "OLLAMA_API_BASE_URL", "str", "", "ai_local", "Ollama base URL"),
    Field("media_api_base_url", "MEDIA_API_BASE_URL", "str", "", "ai_local", "Media/embeddings service base URL"),
    Field("media_audio_api_base_url", "MEDIA_AUDIO_API_BASE_URL", "str", "", "ai_local", "Media audio base URL"),
    Field("media_image_api_base_url", "MEDIA_IMAGE_API_BASE_URL", "str", "", "ai_local", "Media image base URL"),
    Field("ollama_model", "OLLAMA_MODEL", "str", "gemma4:26b", "ai_local", "Default Ollama model"),
    Field("ollama_text_model", "OLLAMA_TEXT_MODEL", "str", "gemma4:26b", "ai_local", "Ollama eval/text model"),
    Field("ollama_context_limit", "OLLAMA_CONTEXT_LIMIT", "int", 32768, "ai_local", "Context window (tokens)"),
    Field("ollama_retry_sleep", "OLLAMA_RETRY_SLEEP", "int", 30, "ai_local", "Sleep between JSON retries (s)"),
    Field("ollama_json_timeout", "OLLAMA_JSON_TIMEOUT", "int", 1200, "ai_local", "JSON request timeout (s)"),
    Field("ollama_text_timeout", "OLLAMA_TEXT_TIMEOUT", "int", 900, "ai_local", "Text request timeout (s)"),
    Field("ollama_summary_timeout", "OLLAMA_SUMMARY_TIMEOUT", "int", 600, "ai_local", "Summary request timeout (s)"),
    Field("media_request_timeout", "MEDIA_REQUEST_TIMEOUT", "int", 300, "ai_local", "Media request timeout (s)"),

    # --- AI: FLUX / fal.ai adapter (ai.models.flux) -------------------------
    Field("flux_image_model", "FLUX_IMAGE_MODEL", "str", "fal-ai/flux-pro/v1.1-ultra", "ai_flux", "FLUX image model"),
    Field("flux_url_base", "FLUX_URL_BASE", "str", "https://fal.run", "ai_flux", "fal.ai base URL"),
    Field("flux_timeout_s", "FLUX_TIMEOUT_S", "int", 120, "ai_flux", "Request timeout (s)"),
    Field("flux_max_attempts", "FLUX_MAX_ATTEMPTS", "int", 3, "ai_flux", "Retry attempts"),
    Field("flux_retry_sleep", "FLUX_RETRY_SLEEP", "float", 1.0, "ai_flux", "Retry backoff (s)"),
    # FAL_KEY is read live at call time in flux._require_api_key (not snapshotted).
    Field("fal_key", "FAL_KEY", "str", "", "ai_flux", "fal.ai API key", secret=True, migrated=False),

    # --- AI: Gemini adapter (ai.models.gemini) — catalogued, not yet migrated
    Field("gemini_text_model", "GEMINI_TEXT_MODEL", "str", "gemini-2.5-pro", "ai_gemini", "Gemini text model", migrated=False),
    Field("gemini_summary_model", "GEMINI_SUMMARY_MODEL", "str", "gemini-2.5-flash", "ai_gemini", "Gemini summary model", migrated=False),
    Field("gemini_json_model", "GEMINI_JSON_MODEL", "str", "gemini-2.5-pro", "ai_gemini", "Gemini JSON model", migrated=False),
    Field("gemini_stt_model", "GEMINI_STT_MODEL", "str", "gemini-2.5-pro", "ai_gemini", "Gemini STT model", migrated=False),
    Field("gemini_image_model", "GEMINI_IMAGE_MODEL", "str", "gemini-3.1-flash-image-preview", "ai_gemini", "Gemini image model", migrated=False),
    Field("gemini_tts_model", "GEMINI_TTS_MODEL", "str", "gemini-2.5-flash-preview-tts", "ai_gemini", "Gemini TTS model", migrated=False),
    Field("googleai_key", "GOOGLEAI_KEY", "str", "", "ai_gemini", "Google GenAI API key", secret=True, migrated=False),

    # --- AI: agent provider overrides + image routing (ai.*agent) -----------
    # These default to the agent instance's provider, not a constant, so the
    # call sites are NOT migrated; catalogued for documentation only.
    Field("embedding_ai_agent", "EMBEDDING_AI_AGENT", "str", "local", "ai_agents", "Embedding provider override", migrated=False),
    Field("image_hybrid_upscale", "IMAGE_HYBRID_UPSCALE", "bool", False, "ai_agents", "Enable hybrid upscale path", migrated=False),
    Field("autonomous_image_cache_dir", "AUTONOMOUS_IMAGE_CACHE_DIR", "str", "", "ai_agents", "Image cache directory", migrated=False),

    # --- Storage (storage.imagestorage, storage.localstorage) ---------------
    Field("storage_path", "STORAGE_PATH", "str", "static", "storage", "Base storage directory", migrated=False),
    Field("storage_image_path", "STORAGE_IMAGE_PATH", "str", "", "storage", "Image storage override path", migrated=False),
    Field("app_base_url", "APP_BASE_URL", "str", "", "storage", "Public base URL for asset links", migrated=False),

    # --- GitHub API wrappers (apis.version_control) -------------------------
    Field("github_pat", "GITHUB_PAT", "str", "", "github", "GitHub personal access token", secret=True, migrated=False),
    Field("github_username", "GITHUB_USERNAME", "str", "", "github", "GitHub username", migrated=False),
    Field("github_org", "GITHUB_ORG", "str", "", "github", "GitHub organization", migrated=False),
    Field("github_email", "GITHUB_EMAIL", "str", "", "github", "GitHub commit email", migrated=False),
    Field("github_commit_name", "GITHUB_COMMIT_NAME", "str", "", "github", "GitHub commit author name", migrated=False),

    # --- Logging (logger) ---------------------------------------------------
    Field("log_level", "LOG_LEVEL", "str", "", "logging", "Log threshold (DEBUG..CRITICAL)", migrated=False),
    Field("log_to_files", "LOG_TO_FILES", "bool", True, "logging", "Write log files to disk", migrated=False),
)


class Settings:
    """Typed snapshot of the env-var catalog.

    Construct (or :meth:`reload`) to read every catalogued env var once,
    coercing each through its parser. Access fields as plain attributes::

        from autonomous.config import settings
        timeout = settings.hpc_request_timeout   # int

    Construction never raises — malformed values fall back to documented
    defaults with a logged breadcrumb (see the ``env_*`` parsers).
    """

    def __init__(self) -> None:
        for field in _SPEC:
            parser = _KIND_PARSERS[field.kind]
            setattr(self, field.attr, parser(field.env, field.default))
        # Derived default: HPC_JSON_MODEL falls back to the resolved text
        # model. env_str uses the default only when the key is *absent* —
        # exactly reproducing the original
        # ``os.environ.get("HPC_JSON_MODEL", _text_model)`` (an explicitly
        # empty value is preserved, only a missing key falls back).
        self.hpc_json_model = env_str("HPC_JSON_MODEL", self.hpc_text_model)

    def reload(self) -> "Settings":
        """Re-read every field from the current ``os.environ`` in place.

        Returns ``self`` for chaining. Useful in tests after monkeypatching
        env vars, or for a runtime config refresh.
        """
        self.__init__()
        return self

    def as_dict(self, *, redact_secrets: bool = True) -> dict[str, Any]:
        """Return the current field values as a dict.

        Secret fields are redacted to ``"***"`` (when set) unless
        ``redact_secrets=False``.
        """
        out: dict[str, Any] = {}
        for field in _SPEC:
            value = getattr(self, field.attr)
            if field.secret and redact_secrets and value:
                value = "***"
            out[field.attr] = value
        return out

    def validate(self) -> list[str]:
        """Return a list of human-readable configuration warnings.

        Non-fatal by design: reports recommended-but-empty connection
        fields rather than raising, so import never breaks. Callers that
        want hard startup validation can ``raise`` on a non-empty result.
        """
        warnings: list[str] = []
        for field in _SPEC:
            value = getattr(self, field.attr)
            if field.secret and not value:
                warnings.append(
                    f"{field.env} is unset (group={field.group}: {field.description})"
                )
        return warnings

    @staticmethod
    def describe() -> list[dict[str, Any]]:
        """Return the static catalog as a list of dicts (for doc generation)."""
        return [
            {
                "attr": f.attr,
                "env": f.env,
                "kind": f.kind,
                "default": f.default,
                "group": f.group,
                "description": f.description,
                "secret": f.secret,
                "migrated": f.migrated,
            }
            for f in _SPEC
        ]


#: Module-singleton snapshot. Built once at import (after load_dotenv has run
#: via autonomous/__init__). Call ``settings.reload()`` to refresh.
settings = Settings()
