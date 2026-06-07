# Configuration

Every environment variable the `autonomous` framework reads is catalogued in
one place: [`autonomous.config`](../api/index). The `Settings` class is a typed
snapshot of the catalog; the module singleton `settings` is built once at import
(after `load_dotenv()` runs).

```python
from autonomous.config import settings

timeout = settings.hpc_request_timeout      # int, guarded — never crashes on a bad value
model   = settings.hpc_text_model           # str
```

## Why a central catalog

Historically each subpackage read `os.environ` directly (~110 reads). That meant:

- **No validation / no shared coercion.** A bare `int(os.environ.get("X", default))`
  raised `ValueError` *at import time* on a malformed (or empty) value, taking the
  whole package down. The catalog's parsers fall back to the documented default and
  log a breadcrumb instead.
- **No central documentation.** Operators had to grep the source. This page is
  generated from the catalog.

## Guarded parsers

The primitives read `os.environ` **live** on each call and never raise — use them
where a value must reflect a runtime config flip:

```python
from autonomous.config import env_int, env_str, env_float, env_bool, env_list

window = env_int("HPC_UNREACHABLE_THROTTLE_SECONDS", 0)   # 0 on unset/empty/malformed
```

| Parser | Behavior |
|---|---|
| `env_str(key, default="")` | Returns the raw value; empty string is meaningful (returned as-is). |
| `env_int(key, default)` | `int()` with fallback to `default` on unset/empty/non-numeric. |
| `env_float(key, default)` | `float()` with the same guard. |
| `env_bool(key, default=False)` | `1/true/yes/on/y/t` → True; `0/false/no/off/n/f`/empty → False. **Note:** an empty value returns `False` regardless of `default` (it is an explicit falsy override), whereas `env_int("")` falls back to `default` (empty is treated as absent for numeric types). |
| `env_list(key, default, sep=",")` | Splits on `sep` and whitespace, dropping empties. |

## Snapshot vs. live reads

`Settings` snapshots the catalog at construction. Code that assigned env values to
class attributes at import time (the AI model adapters) keeps that import-time
timing — it now just reads from `settings` instead of `os.environ`. For a fresh
read after changing the environment (tests, hot-reload), call `reload()`:

```python
from autonomous.config import settings
settings.reload()           # re-read every field from the current os.environ
```

Introspection helpers:

```python
settings.as_dict()          # current values, secrets redacted to "***"
settings.validate()         # list of warnings (e.g. unset secret connection fields)
Settings.describe()         # the static catalog, for tooling / docs
```

## Migration status

This is the first slice of the central-config refactor (issue #49). The AI model
adapters (`openai_compat`, `local_model`, `flux`) and `db_sync`'s throttle parser
now read from the catalog. The remaining subpackages still read `os.environ`
directly and are catalogued below for a follow-up per-subpackage migration — both
forms co-exist during the transition, so existing deployments are unaffected. The
**Migrated** column marks which call sites have been switched over.

## Catalog

> Existing env-var names and defaults are unchanged — `Settings` reads them by
> name. New deployments simply get typed coercion and validation.

### Database (MongoDB)

| Env var | Type | Default | `settings` attr | Migrated | Description |
|---|---|---|---|:--:|---|
| `DB_HOST` | str | `db` | `db_host` | — | MongoDB host |
| `DB_PORT` | int | `27017` | `db_port` | — | MongoDB port |
| `DB_USERNAME` | str | _(secret)_ | `db_username` | — | MongoDB username |
| `DB_PASSWORD` | str | _(secret)_ | `db_password` | — | MongoDB password |
| `DB_DB` | str | _(empty)_ | `db_db` | — | MongoDB database name |

### Redis / task queue

| Env var | Type | Default | `settings` attr | Migrated | Description |
|---|---|---|---|:--:|---|
| `REDIS_HOST` | str | `cachedb` | `redis_host` | — | Redis host |
| `REDIS_PORT` | int | `6379` | `redis_port` | — | Redis port |
| `REDIS_DB` | int | `0` | `redis_db` | — | Redis logical DB index |
| `REDIS_USERNAME` | str | _(secret)_ | `redis_username` | — | Redis username |
| `REDIS_PASSWORD` | str | _(secret)_ | `redis_password` | — | Redis password |

### AI — HPC / OpenAI-compatible adapter

| Env var | Type | Default | `settings` attr | Migrated | Description |
|---|---|---|---|:--:|---|
| `HPC_API_BASE_URL` | str | _(empty)_ | `hpc_api_base_url` | ✅ | Open WebUI / HPC base URL |
| `HPC_API_KEY` | str | _(secret)_ | `hpc_api_key` | ✅ | HPC API key |
| `HPC_TEXT_MODEL` | str | `gpt-oss:20b` | `hpc_text_model` | ✅ | Default text model |
| `HPC_JSON_MODEL` | str | _(HPC_TEXT_MODEL)_ | `hpc_json_model` | ✅ | JSON model; unset → falls back to resolved `HPC_TEXT_MODEL` value. An explicit empty value is preserved. |
| `HPC_SUMMARY_MODEL` | str | `gemma4:26b` | `hpc_summary_model` | ✅ | Summary model |
| `HPC_EMBEDDING_MODEL` | str | `dengcao/Qwen3-Embedding-8B:F16` | `hpc_embedding_model` | ✅ | Embedding model |
| `HPC_STT_MODEL` | str | `whisper-1` | `hpc_stt_model` | ✅ | Speech-to-text model |
| `HPC_REQUEST_TIMEOUT` | int | `120` | `hpc_request_timeout` | ✅ | Per-request timeout (s) |
| `HPC_RETRY_ATTEMPTS` | int | `3` | `hpc_retry_attempts` | ✅ | Retry attempts |
| `HPC_RETRY_BACKOFF` | int | `10` | `hpc_retry_backoff` | ✅ | Retry backoff (s) |
| `HPC_UNREACHABLE_THROTTLE_SECONDS` | int | `0` | `hpc_unreachable_throttle_seconds` | ✅ | Throttle window for [HPC-UNREACHABLE] log floods (0 = disabled) |

### AI — local Ollama + media service

| Env var | Type | Default | `settings` attr | Migrated | Description |
|---|---|---|---|:--:|---|
| `OLLAMA_API_BASE_URL` | str | _(empty)_ | `ollama_api_base_url` | ✅ | Ollama base URL |
| `MEDIA_API_BASE_URL` | str | _(empty)_ | `media_api_base_url` | ✅ | Media/embeddings service base URL |
| `MEDIA_AUDIO_API_BASE_URL` | str | _(empty)_ | `media_audio_api_base_url` | ✅ | Media audio base URL |
| `MEDIA_IMAGE_API_BASE_URL` | str | _(empty)_ | `media_image_api_base_url` | ✅ | Media image base URL |
| `OLLAMA_MODEL` | str | `gemma4:26b` | `ollama_model` | ✅ | Default Ollama model |
| `OLLAMA_TEXT_MODEL` | str | `gemma4:26b` | `ollama_text_model` | ✅ | Ollama eval/text model |
| `OLLAMA_CONTEXT_LIMIT` | int | `32768` | `ollama_context_limit` | ✅ | Context window (tokens) |
| `OLLAMA_RETRY_SLEEP` | int | `30` | `ollama_retry_sleep` | ✅ | Sleep between JSON retries (s) |
| `OLLAMA_JSON_TIMEOUT` | int | `1200` | `ollama_json_timeout` | ✅ | JSON request timeout (s) |
| `OLLAMA_TEXT_TIMEOUT` | int | `900` | `ollama_text_timeout` | ✅ | Text request timeout (s) |
| `OLLAMA_SUMMARY_TIMEOUT` | int | `600` | `ollama_summary_timeout` | ✅ | Summary request timeout (s) |
| `MEDIA_REQUEST_TIMEOUT` | int | `300` | `media_request_timeout` | ✅ | Media request timeout (s) |

### AI — FLUX / fal.ai adapter

| Env var | Type | Default | `settings` attr | Migrated | Description |
|---|---|---|---|:--:|---|
| `FLUX_IMAGE_MODEL` | str | `fal-ai/flux-pro/v1.1-ultra` | `flux_image_model` | ✅ | FLUX image model |
| `FLUX_URL_BASE` | str | `https://fal.run` | `flux_url_base` | ✅ | fal.ai base URL |
| `FLUX_TIMEOUT_S` | int | `120` | `flux_timeout_s` | ✅ | Request timeout (s) |
| `FLUX_MAX_ATTEMPTS` | int | `3` | `flux_max_attempts` | ✅ | Retry attempts |
| `FLUX_RETRY_SLEEP` | float | `1.0` | `flux_retry_sleep` | ✅ | Retry backoff (s) |
| `FAL_KEY` | str | _(secret)_ | `fal_key` | — | fal.ai API key (read live at call time) |

### AI — Gemini adapter

| Env var | Type | Default | `settings` attr | Migrated | Description |
|---|---|---|---|:--:|---|
| `GEMINI_TEXT_MODEL` | str | `gemini-2.5-pro` | `gemini_text_model` | — | Gemini text model |
| `GEMINI_SUMMARY_MODEL` | str | `gemini-2.5-flash` | `gemini_summary_model` | — | Gemini summary model |
| `GEMINI_JSON_MODEL` | str | `gemini-2.5-pro` | `gemini_json_model` | — | Gemini JSON model |
| `GEMINI_STT_MODEL` | str | `gemini-2.5-pro` | `gemini_stt_model` | — | Gemini STT model |
| `GEMINI_IMAGE_MODEL` | str | `gemini-3.1-flash-image-preview` | `gemini_image_model` | — | Gemini image model |
| `GEMINI_TTS_MODEL` | str | `gemini-2.5-flash-preview-tts` | `gemini_tts_model` | — | Gemini TTS model |
| `GOOGLEAI_KEY` | str | _(secret)_ | `googleai_key` | — | Google GenAI API key |

### AI — agent overrides & image routing

| Env var | Type | Default | `settings` attr | Migrated | Description |
|---|---|---|---|:--:|---|
| `EMBEDDING_AI_AGENT` | str | `local` | `embedding_ai_agent` | — | Embedding provider override |
| `IMAGE_HYBRID_UPSCALE` | bool | `False` | `image_hybrid_upscale` | — | Enable hybrid upscale path |
| `AUTONOMOUS_IMAGE_CACHE_DIR` | str | _(empty)_ | `autonomous_image_cache_dir` | — | Image cache directory |

### Storage

| Env var | Type | Default | `settings` attr | Migrated | Description |
|---|---|---|---|:--:|---|
| `STORAGE_PATH` | str | `static` | `storage_path` | — | Base storage directory |
| `STORAGE_IMAGE_PATH` | str | _(empty)_ | `storage_image_path` | — | Image storage override path |
| `APP_BASE_URL` | str | _(empty)_ | `app_base_url` | — | Public base URL for asset links |

### GitHub API wrappers

| Env var | Type | Default | `settings` attr | Migrated | Description |
|---|---|---|---|:--:|---|
| `GITHUB_PAT` | str | _(secret)_ | `github_pat` | — | GitHub personal access token |
| `GITHUB_USERNAME` | str | _(empty)_ | `github_username` | — | GitHub username |
| `GITHUB_ORG` | str | _(empty)_ | `github_org` | — | GitHub organization |
| `GITHUB_EMAIL` | str | _(empty)_ | `github_email` | — | GitHub commit email |
| `GITHUB_COMMIT_NAME` | str | _(empty)_ | `github_commit_name` | — | GitHub commit author name |

### Logging

| Env var | Type | Default | `settings` attr | Migrated | Description |
|---|---|---|---|:--:|---|
| `LOG_LEVEL` | str | _(empty)_ | `log_level` | — | Log threshold (DEBUG..CRITICAL) |
| `LOG_TO_FILES` | bool | `True` | `log_to_files` | — | Write log files to disk |
