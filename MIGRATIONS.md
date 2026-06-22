# Migration Notes

Breaking and behavior-affecting changes for consumers of `autonomous`, most
recent first.

## Unreleased

### Bulk reindex no longer silently no-ops past the token TTL (#183)

**What changed.**

- `autonomous.db.db_sync.process_single_object_sync` no longer skips a job when its supersede token has **expired**. The verification guard was `if current_active_token != token: skip`, which treated an absent/expired token (`r.get` returns `None`) the same as a genuinely superseded one. It is now `if current_active_token is not None and current_active_token != token: skip` — only a *different, still-live* token causes a skip; an expired/absent token falls through and indexes.
- New env knob `SYNC_TOKEN_TTL_SECONDS` (default **`300`**) parameterizes the `sync_token:<collection>:<pk>` Redis key TTL (was a hardcoded `ex=300`). Read live via `autonomous.config.env_int`, so a config flip lands without a worker restart. It governs the **real-time supersede-dedup window only** — it is no longer a correctness gate on bulk reindex.

**Behavior change — externally visible.**

- **Repopulating an emptied RAG store now indexes the whole store, not just the first ~15 objects.** A consumer that walks every object calling `request_indexing` (e.g. after dropping the embedding index) previously lost every object whose job ran after its token's 300s TTL lapsed — on a single-worker backlog (~5–20s/object) that was nearly all of them past the first handful, each logging `Skipping sync for <id>: Superseded by a newer save.`. With the expired-token fall-through those jobs now index.
- **Real-time supersede-dedup is unchanged.** A rapid double-save (token `t1` then `t2`, with `t2` live in Redis) still skips the stale `t1` job — only the *expired/absent* token case changed behavior. No change to the indexed wire shape or the `lore:<id>` hash.

**Migration.**

No action required. The fix is automatic. To widen the real-time dedup window on a deployment with bursty, closely-spaced saves, set `SYNC_TOKEN_TTL_SECONDS` higher; the default `300` reproduces the legacy TTL. A malformed value falls back to `300` with a `[CONFIG]` breadcrumb rather than raising.

```bash
# widen the real-time supersede-dedup window to 10 minutes
SYNC_TOKEN_TTL_SECONDS=600
```

### Exponential backoff on the HPC retry budget (#182)

**What changed.**

- `autonomous.ai.retry.retry(...)` gains a `backoff_factor: float = 1.0` keyword. The wait BEFORE attempt `n` (1-indexed) is now `sleep_seconds * backoff_factor ** (n - 1)`. With the default `1.0` this is the **legacy flat backoff** — every gap is exactly `sleep_seconds` — so existing callers are byte-identical. `2.0` yields classic exponential backoff (`sleep_seconds`, `2×`, `4×`, …). The value must be a finite float `>= 1.0` (a shrinking or non-finite factor raises `ValueError`, same guard shape as the existing `jitter` validation).
- `autonomous.http.HttpClient(...)` gains a matching `retry_backoff_factor: float = 1.0` constructor keyword, threaded into its internal `retry(...)` call. Default `1.0` keeps every existing adapter's flat backoff unchanged; it's validated at construction (`>= 1.0`, finite) so a misconfigured module-level client fails at import rather than on the first transient failure.
- The HPC client (`ai.models.openai_compat._HTTP`) opts into exponential backoff via a new env knob `HPC_RETRY_BACKOFF_FACTOR` (default **`2.0`**). With the existing `HPC_RETRY_ATTEMPTS=3` / `HPC_RETRY_BACKOFF=10`, the inter-attempt waits become `10s` then `20s` (was `10s`, `10s`), so the same 3-attempt budget rides out a longer transient-degraded backend window before surfacing `HPCUnreachableError`.

**Behavior change — externally visible.**

- **The HPC client's retry spacing widened (flat → exponential) by default.** A transient `ReadTimeout` (or any transport-class failure) that previously exhausted the retry budget in ~20s of backoff now spans ~30s before raising `HPCUnreachableError`. This is the #182 fix: the observed degraded windows (4 self-healing failures over ~50min–2.5h windows) outlasted the old flat budget. A `ReadTimeout` was **already** riding the retry budget (`requests.ReadTimeout` is a `RequestException`, wrapped into `HPCUnreachableError` by `HttpClient`, caught by the outer retry tuple) — the gap was only the spacing, not a missing retry. **The public exception contract is unchanged**: a permanent failure still surfaces as `HPCUnreachableError` after the budget is exhausted; only the spacing of the retries changed. Worst-case worker pin time per call grows accordingly (bounded by `sum of (connect+read) per attempt + sum of backoffs`).
- **No change for any other adapter.** `local_model`, `flux`, `db_sync`, and `auth.autoauth` construct `HttpClient` / call `retry` without `retry_backoff_factor` / `backoff_factor`, so they keep flat backoff.

**Migration.**

No action required at default settings. To restore the pre-#182 flat HPC backoff, set `HPC_RETRY_BACKOFF_FACTOR=1.0`. A malformed or out-of-range value (`<1.0`, `inf`, `nan`, non-numeric) falls back to the `2.0` default with a `[CONFIG]` breadcrumb rather than crashing import.

```bash
# opt back into legacy flat backoff
HPC_RETRY_BACKOFF_FACTOR=1.0

# or widen the ride-out further (e.g. 10s, 30s, 90s)
HPC_RETRY_BACKOFF_FACTOR=3.0
```

**Out of scope (deferred).** Increasing `HPC_RETRY_ATTEMPTS` beyond 3: each extra attempt adds a full `read`-timeout stall on the fast path (a genuinely-down backend would block the worker longer), so the fix preferred widening the spacing of the existing budget over adding attempts. Operators who want more attempts can still raise `HPC_RETRY_ATTEMPTS`.

### Bounded `(connect, read)` timeouts on the HPC HTTP client (#177)

**What changed.**

- `OpenAIClient._timeout` is now a `(connect, read)` tuple rather than a single int, fed directly to `requests` (which accepts the tuple shape natively). A stalled HPC backend that holds an ESTABLISHED TCP connection without sending any bytes back now surfaces as `HPCUnreachableError` after the bounded `read` window, instead of blocking indefinitely (or for whatever `HPC_REQUEST_TIMEOUT` was set to, which in some deployments was sized for genuinely slow inference and dwarfed the RQ job timeout — the worker just sat).
- Two new env knobs:
  - `HPC_CONNECT_TIMEOUT` (default `10`) — TCP connect timeout. Low default so a dropped VPN fails fast.
  - `HPC_READ_TIMEOUT` (default `120`) — between-bytes read timeout. The actual stall ceiling.
- The legacy `HPC_REQUEST_TIMEOUT` knob is retained as a back-compat fallback: when `HPC_READ_TIMEOUT` is **unset or empty**, the resolved `hpc_read_timeout` inherits whatever `HPC_REQUEST_TIMEOUT` produced (its default is also 120, so the **read leg** is byte-identical to the pre-#177 single-knob behavior; the **connect leg** drops to the new 10s default — see the "Connect timeout dropped..." bullet below for the deliberate connect-leg shrinkage). Deployments that set `HPC_REQUEST_TIMEOUT=N` keep `read=N` and pick up the new low-connect default. Implementation mirrors the existing `HPC_JSON_MODEL` → `hpc_text_model` fallback precedent (`env_int("HPC_READ_TIMEOUT", self.hpc_request_timeout)`), so a blank value in a templated env file inherits the legacy knob rather than silently downgrading to the field default.

**Behavior change — externally visible.**

- **Connect timeout dropped from `hpc_request_timeout` to 10s by default.** A deployment that intentionally raised `HPC_REQUEST_TIMEOUT` to absorb slow-completing inference also unintentionally widened the connect phase to the same value. The split makes connect a separate, small budget. If you need a larger connect phase (slow TLS handshake, corporate proxy chains), set `HPC_CONNECT_TIMEOUT` explicitly.
- **Stalled-backend wedges convert to fast, logged failures.** The 24-minute silent worker pin reported in #177 now surfaces as an `HPCUnreachableError` after `HPC_READ_TIMEOUT` seconds. The error flows through `_HTTP`'s existing transport-class translation (it's a `requests.exceptions.ReadTimeout` → `RequestException`), so retries engage per `hpc_retry_attempts` and RQ frees the worker slot. The library itself emits the `[HPC-UNREACHABLE]` log line on paths where it owns the catch site (currently the embedding sync in `db.db_sync._get_vector_openai`); chat / JSON / summarize call sites raise `HPCUnreachableError` raw to their consumers, who are responsible for their own emission if alert monitoring depends on the literal marker.

**Migration.**

No action required for deployments at default settings. Deployments that set `HPC_REQUEST_TIMEOUT` should consider migrating to the explicit pair:

```bash
# before — single knob, applied to both connect and read phases
HPC_REQUEST_TIMEOUT=900

# after — split, with the connect phase small
HPC_CONNECT_TIMEOUT=10
HPC_READ_TIMEOUT=900
```

The legacy single-knob path stays supported (so the `before` example above is also a working back-compat configuration) but is documented as deprecated in the field's description for future removal.

**Out of scope (deferred).** Per-stream idle/byte-arrival timeout for streamed responses. The current `_chat` call site sets `"stream": False`, so the bounded read-timeout above fully covers it. A streaming code path would need a separate idle timer (the read budget resets on each chunk in `requests` streaming mode).

### Per-call `model=` override on the AI generation pipeline (#173)

**What changed.**

- `TextAgent.generate(...)`, `TextAgent.summarize_text(...)`, and `JSONAgent.generate(...)` accept a new `model=None` keyword. The agent threads it through to the adapter; `None` keeps the role-default model the adapter resolves from env (provider-specific: `HPC_TEXT_MODEL` / `HPC_JSON_MODEL` / `HPC_SUMMARY_MODEL` on openai_compat; `OLLAMA_TEXT_MODEL` on local_model — which uses the text model for JSON and summarization too; `GEMINI_TEXT_MODEL` / `GEMINI_JSON_MODEL` / `GEMINI_SUMMARY_MODEL` on gemini).
- `generate_text`, `generate_json`, and `summarize_text` on every adapter — `openai_compat.OpenAIClient`, `local_model.LocalAIModel`, `gemini.GeminiAIModel`, `mock_model.MockAIModel` — gain a trailing `model=None` parameter. `flux.FluxAIModel.generate_json` also gains it (the method still raises `NotSupportedByProvider`, but the signature matches the protocol so `AIModelProtocol` conformance holds).
- `AIModelProtocol.generate_json` adds `model: str | None = None` to the canonical contract.
- `openai_compat.OpenAIClient.generate_json`: the strict-mode negative cache and the `structured_outputs_unavailable` event payload key on the EFFECTIVE per-call model (i.e. `model or self._json_model`), not the class default. A strict-mode probe failure for an explicit per-call model no longer poisons the cache entry for the env-configured default, and vice versa.
- `local_model.LocalAIModel.generate_json`: the once-per-process `structured_outputs_unavailable` emission and the on-retry `flush_memory(...)` call use the effective model for the same reason — a per-call override gets its own emission and its own KV-cache flush.

**Behavior change — externally visible.**

Purely additive at every call site. Omitting `model` (the default) preserves the pre-#173 wire shape on every adapter, including the persisted `_text_model` / `_json_model` / `_summary_model` lookups and the strict-mode cache keying — the existing `(self._json_model, self._base_url)` key shape is unchanged when no per-call model is supplied. No consumer change required.

**Migration.**

Recommended: replace consumer workarounds that mutate `client._text_model` / `_json_model` / `_summary_model` before a call with the public `model=` kwarg. Storyteller#319 was the originating use case.

```python
# before — fragile (private attr + relies on persist=False client binding)
client = agent.get_client(provider, persist=False)
client._text_model = "mixtral:8x22b-instruct"
agent.generate(prompt)

# after
agent.generate(prompt, model="mixtral:8x22b-instruct")
```

### Shared JSON-chat message build for `local_model` + `openai_compat` (#146)

**What changed.**

- New shared module `autonomous.ai._json_messages` owns:
  - `build_chat_json_messages(message, system_base, context=None, uri="", *, api_enforces_json)` — returns the `(system, user)` tuple, switching JSON-instruction verbosity, context label, and trailing suffix on the `api_enforces_json` flag (False for Ollama prompt-only enforcement; True for OpenAI-compatible `response_format=json_object` enforcement).
  - `STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER` — the shared metric, formerly registered independently in each adapter (the observability registry is idempotent on name, so both registrations always produced the same singleton; this just makes the shared resource explicit at the import site).
- `LocalAIModel.generate_json` and `OpenAIClient.generate_json` resolve the persona at the call site (`system_prompt or self.instructions`) and pass the resolved string to the helper. Caller-side resolution preserves the pre-#146 short-circuit semantics — an explicit `system_prompt=` never triggers `self.instructions`'s descriptor read, which test stubs constructed via `__new__` + `object.__setattr__` rely on.
- Module-level aliases (`_STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER` in each adapter) are retained so existing patch targets continue to resolve.

**Scope notes.**

- The structured-outputs `event()`+counter-inc emission stays inline at each of the three call sites (one in `local_model`, two in `openai_compat`). A cross-adapter `emit_structured_outputs_unavailable` helper was prototyped during #146 and reverted: the existing `tests/unit/` test suites patch the per-adapter `event` symbol directly (`autonomous.ai.models.openai_compat.event`), and routing the emission through a helper in another module invalidates that patch seam. Within `openai_compat` the two emission sites DO share a module-private `_emit_strict_unavailable` helper — same-module resolution preserves the patch seam.
- The issue body's "extract `JSONGenerationMixin`" framing is honored as helpers, not a mixin. The retry shapes (outer `retry()` vs `HttpClient`-internal + strict→loose fallback) and exception-translation ladders are genuinely different per provider; forcing them into a mixin would either bloat the mixin with provider branches or silently regress one side's fail-fast / retry semantics.

**Behavior change — externally visible.** None. The `(system, user)` strings the chat endpoints receive are byte-identical to the pre-#146 paths (`tests/_dev_local/test_146_*` pins this for the full parametrized matrix). The `structured_outputs_unavailable` event payload (level, marker, fields) is unchanged; the counter series name and labels are unchanged.

**Migration.** No action required. The helper extraction is internal — `generate_json` keeps its parameter and exception surfaces. Code that previously patched `autonomous.ai.models.local_model._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER` or `autonomous.ai.models.openai_compat._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER` continues to work via the aliases. Code that wants a single import site can use `autonomous.ai._json_messages.STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER`.

### Quadratic-removal fix in `BaseDocument._mark_as_changed` (#145)

**What changed.** Three behavior-preserving perf wins in the vendored `autonomous.db.base.document.BaseDocument` change-tracking surface: (1) `_mark_as_changed`'s descendant-drop loop dropped from O(k·n) (`list.remove()` per match × O(n) per remove) to O(n) (single list-comprehension rebuild). (2) `_get_changed_fields` + `_nestable_types_changed_fields` no longer materialize a throwaway list per nesting level (`+= [list comp]` → `extend(generator)`). (3) `_delta` no longer rebuilds `new_path` part-by-part in the common case where every part of the path is walked (only re-joins when an `ObjectId` / `DBRef` break actually truncates). See `src/autonomous/db/DIVERGENCE.md` "Change-tracking perf tuning (#145)" for the explicit-deferral rationale on the full tuple-path + set-keyed parent-prefix structural fix.

**Behavior change — externally visible.** None. `_changed_fields` final contents, `_get_changed_fields()` ordering, and `_delta()` `(set, unset)` tuples are unchanged. Worst-case parent-mark behavior is much faster on deeply-nested documents with many already-marked descendants; everything else has the same complexity it had before.

**Migration.** No action required.

### `QuerySet.snapshot()` removed (#154)

**What changed.**

`QuerySet.snapshot(enabled)` is gone. PyMongo 3+ ignored the option entirely, so the method has been a no-op for the whole supported pymongo range (emitting a `DeprecationWarning` on every call). Removing it also drops the dead `_snapshot` flag in `BaseQuerySet.__init__`, the entry in `_clone_into`'s `copy_props` tuple, and the warning re-fire in `_cursor_args`.

**Behavior change.**

Any direct caller of `qs.snapshot(...)` now raises `AttributeError` instead of receiving a no-op + DeprecationWarning. There is no replacement — PyMongo dropped the underlying capability years ago. Callers should simply delete the call.

### `TextAgent.generate` and all `generate_text` adapters gain `system_prompt=` kwarg (#140)

**What changed.**

`TextAgent.generate(...)` accepts a new `system_prompt=None` keyword. The semantic is adapter-specific:

- `openai_compat.generate_text` and `gemini.generate_text` **replace** the persisted persona (`self.instructions`) with `system_prompt` for the call (mirrors `JSONAgent.generate(system_prompt=...)`).
- `local_model.generate_text` has historically never used `self.instructions` in the text path (the system slot was `additional_instructions` alone); `system_prompt` **prepends** to that slot rather than replacing a persona that doesn't exist there.
- `mock_model.generate_text` accepts the kwarg for dispatch parity and ignores it.

In all four adapters, `additional_instructions` still appends as a task-level suffix to whatever system message ends up in play.

**Intra-`local_model` asymmetry (deliberate).** `LocalAIModel.generate_json` already had the **replace-persona** semantic for `system_prompt=` (matching `openai_compat`/`gemini`); only `LocalAIModel.generate_text` keeps the **prepend-without-persona** behavior described above. The two methods on the same class therefore handle `self.instructions` differently — generate_json reads it as a fallback, generate_text never reads it. This is deliberate (text-path has no persona slot historically) and load-bearing for current consumers; future "harmonize sibling methods" PRs need to confront this difference and update the test pin at `tests/unit/test_unit_iter_audit_followups_iter_2026_06_18.py::test_self_instructions_does_not_leak_into_system_slot`.

**Behavior change.**

Additive. `system_prompt=None` (the default) preserves the pre-#140 wire shape on every adapter. No consumer change required.

**Why.**

Previously, a per-call persona passed via `additional_instructions` could only **append** to the agent's persisted `instructions` — it could not **replace** them. Consumers that needed a strong conflicting per-call persona (e.g. "output ONLY a screenplay") had to allocate a throwaway `TextAgent` whose `instructions` were the per-call primer. `JSONAgent.generate` already supported this through `system_prompt=`; #140 closes the asymmetry.

### `local_model` + `flux` adopt `extract_or_malformed` for typed-2xx translation (#142)

**What changed.**

- New shared helper `autonomous.ai._extract.extract_or_malformed(response, endpoint, extractor)`. Same body as the private `_extract_or_malformed` introduced in `openai_compat` (#92); moved out so other adapters can adopt the same translation without a cross-adapter import. `openai_compat._extract_or_malformed` is now a thin re-export — the call-site grep history is unchanged.
- `LocalAIModel.generate_json` (`/api/chat` chat extraction), `LocalAIModel.generate_text` (`/api/chat` chat extraction), and `LocalAIModel.generate_transcription` (`/transcribe` body validation) route their `response.json().get(...)` walks through `extract_or_malformed`. A non-dict 2xx body (list / scalar) now raises `MalformedResponseError` from the shared helper instead of leaking a raw `AttributeError` / `TypeError`.
- `FluxAIModel.generate_image` (`/fal/generate` `images[0]["url"]` walk) routes the same way. The previous explicit `raise ValueError(...)` for "no images" and "missing image URL" both happen *inside* the extractor and are caught by `MALFORMED_2XX_EXCEPTIONS` → translated to `MalformedResponseError` with the original `ValueError` preserved on `__cause__` and embedded in the wrapper message.

**Behavior change — externally visible.**

- `FluxAIModel.generate_image`: previously raised `ValueError` on malformed-2xx (no images / no URL); **now raises `MalformedResponseError`** (the typed shape already in the consumer contract via `openai_compat`). The `__cause__` chain preserves the original `ValueError` and its message, and the wrapper message includes the same descriptive text, so log-scraper consumers see the same human-readable detail. A consumer catching `ValueError` specifically on `FluxAIModel.generate_image` malformed-2xx needs to either:
  - catch `MalformedResponseError` instead (recommended — symmetric with the other adapters), or
  - catch both for transitional compatibility.
- `LocalAIModel.generate_json`: the outer `except` ladder now catches `MalformedResponseError` and re-raises as `GenerateJSONEmptyResponseError` — matches `openai_compat.generate_json`'s pattern. Callers continue to see only the documented `GenerateJSONEmptyResponseError` / `GenerateJSONParseError` surface, so no consumer-side change at this site.
- `LocalAIModel.generate_text` and `LocalAIModel.generate_transcription`: the existing degrade contracts are preserved (`generate_text` returns its initial `"Error generating text."` literal, `generate_transcription` returns `{"segments": [], "text": ""}`). The except tuples gained `MalformedResponseError` alongside the existing `requests.RequestException` / `json.JSONDecodeError` / `ValueError` entries so the typed exception is degraded internally; no consumer-visible change at these sites.

**Migration.**

- Storyteller-side or other consumers catching `ValueError` specifically on `FluxAIModel.generate_image` malformed-2xx: update to catch `MalformedResponseError` (or both transitionally). The `__cause__` chain preserves the original `ValueError` for any observability that walks it.
- Consumers of `LocalAIModel.generate_json` / `.generate_text` / `.generate_transcription`: no action required — the existing contract surface is unchanged at the call-site boundary.

**Why.**

- Three independent angles in the 2026-06-18 multi-agent audit (architecture, duplicate-pattern, test-gap) all surfaced the same finding: `openai_compat` had the shared helper, `local_model` + `flux` had 4 unprotected `response.json()` sites that surfaced raw stdlib exceptions instead of the typed `MalformedResponseError`. This entry closes that asymmetry and is the warm-up for #146 (`JSONGenerationMixin` extraction).

### `AutoUser.authenticate` no longer downgrades elevated roles on login (#136)

**Symptom this fixes.**

`AutoUser.authenticate()` previously set `user.role = "user"`
**unconditionally** on every OAuth login. Any role granted out-of-band
(e.g. an admin UI flipping `role` to `"admin"`, or a direct DB write)
was silently reset to `"user"` the next time that user signed in,
making a persistent `admin` (or any non-default) role impossible for
OAuth users.

**Fix.**

`authenticate()` now only promotes the schema-default `"guest"` role to
`"user"`. Any non-default role is left untouched. New users still land
at `"user"` (they are constructed at the schema default `"guest"` and
get bumped in the same step); existing `admin`/elevated users keep
their role across login.

**Consumer impact.**

Purely fixative for consumers who rely on `is_admin` after granting
`role="admin"` out-of-band. Consumers that worked around the bug with
a subclass override that recaptured-and-restored the elevated role
around `super().authenticate(...)` can drop the override — the upstream
method now does the right thing.

**Files touched.**
- `src/autonomous/auth/user.py` — `AutoUser.authenticate` role-assignment
  branch.

### `lore:<pk>` vector-index hash gains a `world_pk` discriminator (#132)

**New capability.**

`autonomous.db.db_sync.process_single_object_sync` now writes an
additional `world_pk` field on the `lore:<pk>` Redis hash it emits.
Value is the string pk of the indexed object's `world` reference,
extracted directly from the raw BSON (no ORM dereference round-trip),
or the empty string when the doc has no `world` reference. Lets
multi-tenant consumers run **world-scoped KNN retrieval** by adding a
matching `TagField("world_pk")` to their search_index schema and a
`@world_pk:{...}` pre-filter into their KNN query.

**Why.**

Prior to this change the hash carried no tenant/world discriminator, so
a consumer indexing lore from multiple worlds into one `search_index`
got globally-scoped KNN — a query for world A could return world B's
canon as its nearest neighbors. StoryTeller hit this as a false-
positive conflict in continuity judges and a false-positive context in
generation RAG (StoryTeller#303). No consumer-side filter was possible
because the field simply wasn't on the hash.

**Wire shape.**

```
HSET lore:<pk>
  mongo_id     <str>
  collection   <str>
  content      <str>
  vector       <bytes>      # np.float32, dim matches indexer
  last_synced  <iso8601>
  world_pk     <str>        # NEW — "" when no world reference
```

**Consumer impact.**

Purely additive. Single-tenant consumers ignore the new field (existing
`HGETALL` reads of the named fields keep working); multi-tenant
consumers opt in by adding the `TagField` and the pre-filter — example
(StoryTeller flavor):

```python
# Schema (one-time, on index build):
TagField("world_pk")

# Query (per-call):
q = (
    Query(f"@world_pk:{{{world.pk}}} =>"
          f"[KNN {k} @vector $blob AS score]")
    .return_fields("mongo_id", "score")
    .dialect(2)
)
```

`world_pk` is resolved per-shape — the worker uses the raw BSON form
emitted by `ReferenceAttr` / `ReferenceField`, not the ORM, so a missing
or partial `world` field degrades to `""` rather than raising.

**Files touched.**
- `src/autonomous/db/db_sync.py` — new `_extract_world_pk` helper +
  one new field on the `hset` mapping in `process_single_object_sync`.

### `generate_json` now retries loose mode on a strict-mode parse-failure 200 (#124)

**Symptom this fixes.**

`OpenAIClient.generate_json` raised `GenerateJSONParseError` (and the
consumer's generation hard-failed) when a strict-mode
(`response_format: {"type":"json_schema", strict:true}`) request returned
HTTP 200 carrying free-form / non-grammar-constrained content. Observed
in prod against Open WebUI + Ollama (`gpt-oss:20b`) on large/complex
object schemas: the body came back pretty-printed and malformed
(`Expecting ',' delimiter: line 12 column 33 (char 806)`) or
markdown-fenced or with trailing prose. The reliable loose
(`response_format: {"type":"json_object"}`) fallback was wired only into
the `except (MalformedResponseError, requests.HTTPError)` path, so a 200
that failed `json.loads(raw)` AND `json.loads(clean_json_response(raw))`
went straight to the parse-or-raise block with no second chance.

**Fix.**

The parse-or-raise block in `OpenAIClient.generate_json` now mirrors the
HTTPError fallback: when **both** `json.loads(raw)` and
`json.loads(clean_json_response(raw))` fail AND the request was sent in
strict mode, it (a) adds `(model, endpoint)` to
`_UNSUPPORTED_STRICT_MODE`, (b) emits the
`[STRUCTURED-OUTPUTS-UNAVAILABLE]` observability event with
`detection="parse_failure_200"` (distinct from the HTTPError path's
`detection="first"`), (c) bumps the shared
`structured_outputs_unavailable_total` counter, and (d) retries once in
loose `{"type":"json_object"}` mode. If the loose retry parses, the
caller gets a valid dict; if it doesn't, the original
`GenerateJSONParseError` (with strict-mode `raw`) is raised — the
strict-mode body is what the caller asked for, so the diagnostic
preserves it.

**Consumer impact.**

None for callers that don't pass `json_schema=` or whose backend honors
strict mode correctly — the new branch is gated on `use_strict=True`.
Callers that previously caught `GenerateJSONParseError` to roll their
own loose-mode retry can drop that workaround.

**Files touched.**
- `src/autonomous/ai/models/openai_compat.py` — `generate_json`
  parse-or-raise block extended with the strict→loose retry.

### In-process embedding backend (`EMBEDDING_AI_AGENT=in_process`, #125)

**New capability.**

`autonomous.db.db_sync._VECTOR_PROVIDERS` gains an `in_process` provider
that runs `sentence-transformers` in the worker process — no network call,
no dependency on an external embeddings endpoint. Eliminates the
single-point-of-failure mode where the upstream backend (Open WebUI +
Ollama at `MEDIA_API_BASE_URL`) refuses to serve embeddings and RAG
indexing silently degrades.

**Configuration.**

```
EMBEDDING_AI_AGENT=in_process
LOCAL_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2  # default
```

The default model is 384-dim (matches StoryTeller's `search_index` pinned
dim). Operators pick a different model id for a different dim.

**Install.**

The dep is heavy (`sentence-transformers` pulls `torch`, ~700MB on Linux),
so it's gated behind its own extra rather than rolled into `[all]`:

```
pip install autonomous-app[embeddings]
```

**Naming note.**

The env-var value is `in_process`, NOT `local`. The pre-existing
`EMBEDDING_AI_AGENT=local` value already routes to the legacy media_ai
HTTP path (`_get_vector_local`) — that's "local" in the docker-compose
sense, not in-process. Both stay available; the new key is additive.

**Consumer impact.**

None unless the consumer sets `EMBEDDING_AI_AGENT=in_process`. The
default (`local`) is unchanged.

**Files touched.**
- `src/autonomous/db/db_sync.py` — new `_get_vector_in_process`,
  `_get_in_process_embedder` (lazy per-process singleton), and
  `_default_in_process_model` helpers; `_VECTOR_PROVIDERS` gains the
  `in_process` key.
- `requirements-embeddings.txt` (new) + `pyproject.toml`
  `[embeddings]` extra.

### AI transcription return shape: `MockAIModel` + `GeminiAIModel` now return canonical dict (#47 slice 4)

**Slice 4 of #47 — the closing piece.** The `AIModelProtocol` docstring pins `generate_transcription` as returning `dict` with `{"text", "segments"}` keys. The signature-level conformance test (slice 1) can't enforce return shape, so two adapters silently drifted:

- **`MockAIModel.generate_transcription`** returned a bare string (`"This is a mock transcription of the audio file."`). Consumers using the mock provider in tests silently saw a wrong-shape return — any `result["text"]` access in the test exploded with `TypeError: string indices must be integers`. The "mock = realistic stand-in" contract was broken.
- **`GeminiAIModel.generate_transcription`** returned `response.text` directly (a string), bypassing the canonical dict that `LocalAIModel` and `OpenAIClient.generate_transcription` produce. A real production bug: consumers routed through `audioagent.transcribe()` with `provider="gemini"` got a `str` instead of a `dict` and downstream `result["text"]` access broke.

**Both fixed to return the canonical `{"text": str, "segments": list}` shape.** Gemini's `segments` is an empty list (its tool-calling response doesn't expose per-phrase segments the way Whisper does) — but it's a list, not missing/None, so consumers can always iterate without a None guard.

**Consumer impact (medium for gemini, low for mock):**

- **Mock**: any test or fixture relying on the bare-string return needs to read `result["text"]` instead. Grep found no in-tree consumers; storyteller may have offline-mode fixtures worth checking.
- **Gemini**: `audioagent.transcribe()` already documented the return shape as `{"text", "segments"}` — anyone using gemini for transcription via this path was getting buggy output. Now they get the documented shape.
- **`local_model`, `openai_compat`**: no change. Both already return the canonical shape; they were the reference contract gemini was supposed to match.
- **`flux`**: still raises `NotSupportedByProvider` from slice 2. No change.

**New runtime tests** in `tests/unit/test_unit_ai_protocol_conformance.py::TestSlice4ReturnShapes`:
- `test_mock_generate_json_returns_dict` / `test_mock_generate_image_returns_bytes` / `test_mock_upscale_image_returns_bytes` — pin every mock method's return type.
- `test_mock_generate_transcription_returns_canonical_dict` — verifies `{"text", "segments"}` keys + types after the fix.
- `test_gemini_transcription_returns_canonical_dict` + `test_gemini_transcription_handles_none_text` — pin gemini's new return shape with a stubbed `client` (`GeminiAIModel.client` is a no-setter property; same hand-built stub pattern as `_make_gemini_stub` in `test_unit_generate_json_typed_exc_iter_*`).

**Files touched.**
- `src/autonomous/ai/models/mock_model.py` — `generate_transcription` returns dict.
- `src/autonomous/ai/models/gemini.py` — `generate_transcription` wraps `response.text` in canonical dict.
- `tests/unit/test_unit_ai_protocol_conformance.py` — new `TestSlice4ReturnShapes` class.

**#47 closed.** Every adapter signature in `MODEL_REGISTRY` conforms to `AIModelProtocol` (slice 1's signature check, `_KNOWN_DRIFT` empty since slice 3). Every return shape the issue called out is pinned by runtime test (this slice). The dispatch layer is uniform (slice 3). Unsupported methods raise the typed `NotSupportedByProvider` (slice 2). The conformance test stays green as the forcing function for any future adapter or method addition.

### AI adapter unification: `gemini.generate_json` canonical signature; `jsonagent` per-provider branch removed (#47 slice 3)

**Slice 3 of #47 — the architectural one.** Eliminates the `if provider == "gemini":` branch in `JSONAgent.generate` that was the forcing function for every cross-adapter quirk to ripple into the dispatch layer. Translation now lives where it belongs — inside the adapter that needs it.

**`GeminiAIModel.generate_json` signature changed:**

```python
# Pre-slice-3:
def generate_json(self, message, function, additional_instructions="", uri="", context=None, temperature=None):

# Post-slice-3 (matches AIModelProtocol):
def generate_json(
    self,
    message,
    system_prompt=None,
    json_schema=None,
    schema_name="response",
    uri="",
    context=None,
    temperature=None,
):
```

Gemini now internally synthesizes its native `function = {"name": schema_name, "description": "Structured response shape.", "parameters": json_schema}` dict from the canonical kwargs and translates `system_prompt` → its native `additional_instructions`. `json_schema=None` raises `ValueError` (gemini's structured-output path IS tool-calling, which needs a parameter schema) — the previous "silently pass function=None" was a soft no-op that masked the contract violation.

**`JSONAgent.generate` simplified:** the per-provider `if provider == "gemini":` branch is gone. All providers receive the same call:

```python
client.generate_json(
    message,
    system_prompt=system_prompt,
    uri=uri,
    context=context,
    json_schema=json_schema,
    schema_name=schema_name,
    **kwargs,
)
```

**Conformance test cleanup.** The last `_KNOWN_DRIFT` entry (`gemini.generate_json`) was removed; the `strict=True` xfail flipped to XPASS and forced this cleanup. **`_KNOWN_DRIFT` is now empty** — every adapter signature in `MODEL_REGISTRY` conforms to `AIModelProtocol`. Slice 4 (return-shape pins via runtime instance tests) is the next remaining piece.

**Test lockstep (source-and-test inseparable).** Three test files updated to track the migration:
- `tests/unit/test_unit_generate_json_typed_exc_iter_2026_05_25.py` — `TestGeminiExceptionDispatch` fixtures moved from `function=` to `json_schema=` + `schema_name=`. Added `test_missing_json_schema_raises_value_error` for gemini's new contract.
- `tests/unit/test_unit_jsonagent_schema.py` — `_GeminiStubClient` deleted; `TestDispatchGeminiTranslation` rewritten as `TestDispatchGeminiUniform` testing the slice-3 invariant (dispatch parity across providers).
- `tests/unit/test_unit_json_schema_structured_outputs_iter_2026-06-03.py` — `TestJSONAgentGeminiDispatch` rewritten for slice-3 invariant; pre-slice-3 tests asserting JSONAgent synthesizes the function dict no longer apply (the dispatch layer doesn't do translation).

Same precedent as #50 slice B (PR #69), #51 (PR #119), #47 slice 1 (PR #122). Patches and source are inseparable: a `function=`-shaped patch becomes a TypeError after the migration — silent test-pass would be the worst outcome.

**Consumer impact.** Low if going through `JSONAgent.generate` (the dispatch surface is unchanged). Direct callers of `GeminiAIModel.generate_json(message, function=...)` need to migrate to `(message, json_schema=..., schema_name=...)` — this matches the storyteller code path which already routes through `JSONAgent`. No CLAUDE.md / public API entries reference the old gemini signature.

**Files touched.**
- `src/autonomous/ai/models/gemini.py` — new signature + internal translation block.
- `src/autonomous/ai/jsonagent.py` — per-provider branch removed; uniform dispatch.
- `tests/unit/test_unit_ai_protocol_conformance.py` — `_KNOWN_DRIFT` emptied.
- 3 test files updated lockstep (see above).

### AI adapters: `NotSupportedByProvider` migration (#47 slice 2)

**Slice 2 of #47.** Replaces raw `NotImplementedError` raises at adapter boundaries with the typed `NotSupportedByProvider(method, provider)` exception from slice 1's `autonomous.ai.protocol`. Also adds canonical-signature declarations for adapter/method pairs that were previously missing entirely.

**Adapters touched:**
- `FluxAIModel` — gains `generate_json` and `generate_transcription` declarations matching the Protocol; both raise `NotSupportedByProvider` with a routing hint to `provider='local'` or `'openai'`.
- `OpenAIClient.generate_image` / `OpenAIClient.upscale_image` — `*args/**kwargs → NotImplementedError` replaced with explicit signature matching the Protocol + `NotSupportedByProvider`. Routing hints to `IMAGE_AI_AGENT=gemini` preserved.
- `OpenAIClient.generate_audio` — also migrated to `NotSupportedByProvider` (not part of slice 1's Protocol scope but on the same surface; preserved `*args/**kwargs` shape until/unless audio enters the Protocol).

**Consumer impact (low).** `NotSupportedByProvider` subclasses `NotImplementedError`, so existing `except NotImplementedError` catches keep working. New callers should catch the typed exception specifically and introspect `.method` / `.provider` (e.g., to route the same call to a different provider rather than leak the exception).

**Conformance test cleanup.** `tests/unit/test_unit_ai_protocol_conformance.py` `_KNOWN_DRIFT` dropped 4 entries (now down to 1: `gemini.generate_json` for slice 3). Runtime test class `TestSlice2UnsupportedDeclarations` verifies each newly-declared method raises `NotSupportedByProvider` end-to-end and that the subclass relationship to `NotImplementedError` holds.

**Files touched.**
- `src/autonomous/ai/models/flux.py` — import `NotSupportedByProvider`, add two new methods at end of `FluxAIModel`.
- `src/autonomous/ai/models/openai_compat.py` — import `NotSupportedByProvider`, rewrite the three not-implemented methods.
- `tests/unit/test_unit_ai_protocol_conformance.py` — drop 4 stale `_KNOWN_DRIFT` entries, add `TestSlice2UnsupportedDeclarations`.

### AI adapter contract: `AIModelProtocol` + `NotSupportedByProvider` foundation (#47 slice 1)

**Slice 1 of #47** — lays down the canonical adapter contract without changing any adapter behavior. Slices 2-5 will migrate each adapter to conform; this one makes the drift visible to CI.

**New module `autonomous.ai.protocol`.** Exports:

- `AIModelProtocol(typing.Protocol)` — canonical signatures for the four cross-adapter methods (`generate_json`, `generate_transcription`, `generate_image`, `upscale_image`). Pins the kwarg-naming conventions called out in the issue: `generate_image` takes `files=` (plural — img2img source list); `upscale_image` takes `image_content=` (singular — the one image being upscaled).
- `NotSupportedByProvider(NotImplementedError)` — typed exception carrying `method` and `provider` attributes. Subclasses `NotImplementedError` so existing `except NotImplementedError` callers stay correct across the multi-slice migration; new callers should catch `NotSupportedByProvider` for the structured attribution. To be wired into the adapters in **slice 2**.

**New test `tests/unit/test_unit_ai_protocol_conformance.py`.** Parametrized across every (adapter, method) pair from `BaseAgent.MODEL_REGISTRY`. Each pair either passes the conformance check or is marked `xfail(strict=True, reason="#47 slice N — ...")`. The current xfail list IS the TODO list for the rest of #47:

| Adapter | Method | Fix in slice |
|---|---|---|
| `gemini` | `generate_json` | 3 — translate `function=` from `system_prompt=` at adapter boundary |
| `flux` | `generate_json` | 2 — declare with `NotSupportedByProvider` |
| `flux` | `generate_transcription` | 2 — declare with `NotSupportedByProvider` |
| `openai_compat` | `generate_image` | 2 — explicit signature + `NotSupportedByProvider` |
| `openai_compat` | `upscale_image` | 2 — explicit signature + `NotSupportedByProvider` |

The `strict=True` semantics matter: when an adapter is fixed, the xfail flips to XPASS which pytest reports as a FAIL — forcing the migrating PR to delete the now-stale `_KNOWN_DRIFT` entry. You can't half-migrate and silently mask the remaining drift.

> **Resolution status (closing note for the bundle this ships in):** every entry in the table above was resolved in slices 2–4, all of which land in the same `test → main` bundle as this slice. `_KNOWN_DRIFT` is now empty.

**Not in this slice.** Return-shape pins (e.g. `MockAIModel.generate_transcription` returning a string instead of `{"text", "segments"}`) are documented in the Protocol docstring but not enforced — signature inspection can't see return shape. **Slice 4** will add runtime instance tests that pin the return shapes.

**Consumer impact.** None. No adapter behavior changed. The Protocol is for the conformance test and for static type checkers (mypy/pyright) that want to type-narrow AI client variables.

**Files touched.**
- `src/autonomous/ai/protocol.py` — new module.
- `tests/unit/test_unit_ai_protocol_conformance.py` — new test. This test IS the slice's primary deliverable (the issue's "step 5" calls for it); it must live in `tests/unit/` so future PRs get drift detection in CI. Source-and-test inseparable for this shape — same precedent as the #50 slice-B and #51 lockstep patches.

### FileAttr GridFS uploads now ensure `{files_id, n}` chunks index on first use (#117)

**Symptom this fixes.**

Cold reads of binary blobs stored via `FileAttr` (i.e. any field backed
by `GridFSProxy` — `FileField`, `ImageField`) were catastrophically slow
on buckets where the standard GridFS `{files_id: 1, n: 1}` unique index
was missing — measured at ~15.9s for a 3.3 MB blob in a real prod DB,
~0.008s after the index was added manually. Each `readchunk` was doing a
full `fs.chunks` collection scan; cost scales with total stored blobs
(O(chunks × total_chunks) per file).

**Root cause.**

`pymongo.gridfs.GridIn._create_index` (pymongo 4.x) only creates the
index when the chunks collection is empty (it gates on
`find_one(... )` returning `None`). Any bucket where chunks already
exist when the index is missing — `mongorestore` of a dump that never
had the index, live migrations, manual ports — never gets the index.

**Fix.**

`GridFSProxy.fs` now calls `_ensure_chunks_index()` on first
materialization per process, idempotently creating
`{files_id: 1, n: 1}, unique=True, name="files_id_1_n_1"` (matching
pymongo's auto-generated name so vanilla `_ensure_indexes` is a no-op).
Cached at the class level by `(db_alias, collection_name)` so we incur
at most one `create_index` call per bucket per process. `OperationFailure`
is logged and swallowed so upload paths can't break on pre-existing
conflicting index specs.

**Consumer impact.**

None for correct setups — `create_index` for a matching spec is a no-op.
Consumers running the storyteller-style boot-time `db["fs.chunks"].
create_index([("files_id", 1), ("n", 1)], unique=True,
name="files_id_1_n_1")` workaround can now drop it.

**Files touched.**
- `src/autonomous/db/fields.py` — `GridFSProxy._ensured_chunks_indexes`
  cache + `_ensure_chunks_index()` method, called from the `fs` property.

### Structured emission migration: `STRUCTURED-OUTPUTS-UNAVAILABLE` sites + embedding-sync Counter (#51)

**Steps 3 + 4 of the #51 migration path.** The foundation (`observability` module with `event()` / `Counter` / `Histogram` / `Registry`) shipped earlier; this slice does the first per-subsystem migration and adds the first metric-backed wrapper.

**Migration 1 — `[STRUCTURED-OUTPUTS-UNAVAILABLE]` log sites → `observability.event()`.** Both adapters (`autonomous.ai.models.local_model.generate_json` and `autonomous.ai.models.openai_compat.generate_json`) now emit via:

```python
from autonomous.observability import event, counter

event(
    "structured_outputs_unavailable",
    level="warning",
    marker="STRUCTURED-OUTPUTS-UNAVAILABLE",
    print_to_stdout=False,
    provider="local",  # or "openai_compat"
    model=...,
    endpoint=...,
    ...,
)
```

The line passed to the log singleton still begins with `[STRUCTURED-OUTPUTS-UNAVAILABLE]` (it's the `marker` field) so grep-based scrapers (storyteller's health dashboard) continue to hit. Parser-based consumers can now key on `event=structured_outputs_unavailable` and the labeled fields. New Counter `structured_outputs_unavailable_total` (label: `provider`) is bumped on first detection per `(model, endpoint)` per process — same gate as the log emission.

**Migration 2 — `record_embedding_sync_event` → bumps `embedding_sync_events_total` Counter.** The Redis hour-bucket write (`embedding_sync_health:<YYYYMMDDHH>`) is **preserved unchanged** for back-compat with existing consumer scrapers. The new Counter is bumped *before* the Redis write, so a Redis outage shows up as Counter-vs-bucket divergence rather than as a metric gap. Both observability layers carry the same event set (`success` / `hpc_failure` / `silent_skip`).

**Consumer test patches.** Tests that monkeypatched `autonomous.ai.models.local_model.log` to capture the emission must now patch `autonomous.log` (the package-level attribute) instead. `event()` resolves the log singleton via `from autonomous import log` inside its body, so a module-local `log` rebind never sees the call. Recipe:

```python
# Pre-migration:
monkeypatch.setattr(local_model, "log", capture)

# Post-migration:
monkeypatch.setattr("autonomous.log", capture)
```

**Files touched.**
- `src/autonomous/db/db_sync.py` — adds `_EMBEDDING_SYNC_EVENTS_COUNTER`, bumps in `record_embedding_sync_event`.
- `src/autonomous/ai/models/local_model.py` — declares the shared `structured_outputs_unavailable_total` Counter, replaces the `log()` emission with `event()`.
- `src/autonomous/ai/models/openai_compat.py` — same Counter (idempotent registration), same `log()` → `event()` swap.
- `tests/unit/test_unit_local_model_json_schema.py`, `tests/unit/test_unit_json_schema_structured_outputs_iter_2026-06-03.py` — patch seam moved from `local_model.log` to `autonomous.log`. Source-and-patch are inseparable for migrations of this shape (#50 slice B precedent — patches would be silent no-ops post-migration, masking real test failures).

**Not in this slice.** `[HPC-UNREACHABLE]` emission (`db.db_sync._emit_hpc_unreachable`) intentionally stays on its current wire shape — the storyteller scraper at `/debug/lore/health` pins the raw stdout + `[HPC-UNREACHABLE]`-prefixed line shape via committed tests. A future slice can flip the wire after the consumer scraper migrates.

### Consumer test-patch recipe: `local_model._SESSION` → `_HTTP` (#111)

**What this documents.**

The `#50 slice C` migration replaced
`autonomous.ai.models.local_model._SESSION` (a `requests.Session`) with
`_HTTP` (an `autonomous.http.HttpClient`) but never received a dedicated
MIGRATIONS entry — the change rode in alongside slices B / D / E / F and
the consumer-side patch-retargeting recipe was implicit. Surfaced by #111
when consumer suites that monkeypatched the old name reported
order-dependent failures: the consumer fixture was installing
`_SESSION` onto the module itself, then cross-test leakage of that
hand-installed attribute manifested as "global gets clobbered." This
entry adds the explicit recipe so the migration can be completed cleanly
on the consumer side.

**Current state of the patch target.**

- `local_model._SESSION` does **not** exist on the module. There is no
  back-compat alias for the same reason `db_sync._HTTP_SESSION` /
  `flux._SESSION` were not aliased: `HttpClient` routes through
  `session.request("POST", ...)`, so an aliased `_SESSION.post` patch
  would be a silent no-op (the patched method never gets called).
  "Honest break beats a misleading alias."
- The current module global is `_HTTP`, an
  `autonomous.http.HttpClient(timeout=None, max_attempts=1,
  transport_error_cls=requests.ConnectionError)`. Every current call
  site is a POST (`_HTTP.post(...)`); `HttpClient` also exposes `.get`
  and `.request` for the shape 3 wire-level patch recipe below.

**Migration recipe — consumer test patches.**

Mirrors the flux slice E recipe (#50 entry below). Three shapes of patch
target depending on what the test wants to assert:

```python
# Pre-migration (no longer works — _SESSION is not on the module):
with patch("autonomous.ai.models.local_model._SESSION.post") as mock_post:
    ...

# Post-migration shape 1 — non-retry tests (max_attempts=1 means
# _HTTP.post is the call site; patching it directly is fine):
with patch("autonomous.ai.models.local_model._HTTP.post") as mock_post:
    ...

# Post-migration shape 2 — tests that care about the underlying
# requests.Session call (e.g. the `_556_…` isinstance assertion):
import autonomous.ai.models.local_model as lm
assert isinstance(lm._HTTP.session, requests.Session)

# Post-migration shape 3 — tests that need to intercept the wire-level
# call (HttpClient.request → session.request), useful when asserting
# headers/body composition or simulating a transient retry-eligible
# transport failure:
with patch.object(
    autonomous.ai.models.local_model._HTTP.session,
    "request",
) as mock_request:
    mock_request.return_value = MagicMock(
        status_code=200, json=lambda: {...},
    )
    ...
```

**Why the "module-global clobbered" symptom was order-dependent.**

If the consumer fixture installs `_SESSION` onto the module (e.g.
`local_model._SESSION = requests.Session()` in a setUp), pytest's test
ordering changes whether the attribute is present when the next test's
`patch(...)` resolves the dotted path. Tests that ran after a fixture
left a stale value would see that value; tests that ran before any
installation would see `AttributeError`. The fix on the consumer side
is to either (a) migrate patches to `_HTTP` per the recipe above (no
fixture install needed — `_HTTP` is a real module attribute), or
(b) keep the local fixture but make it autouse with explicit teardown.

**No autonomous-side code change.** The migration was deliberate and the
break is documented in `local_model.py:50-58`. This entry exists so the
recipe is discoverable from MIGRATIONS.md.

### `OpenAIClient` malformed-2xx raise sites consolidated + null-safe transcription (#88 / #90 / #92 / #102 / #104)

**What changed.**

- **`generate_transcription` no longer leaks `None`** (#88). The shape
  enforcement used `body.get("text", "")` / `body.get("segments", [])`,
  but `dict.get(key, default)` only fires `default` when the key is
  ABSENT — a legal-JSON `{"text": null, "segments": null}` 2xx body
  (server transcribed no content) returned `{"text": None,
  "segments": None}`, and a caller doing `result["text"].strip()` hit
  `AttributeError: 'NoneType'`. The body is now normalized to the
  documented `str` / `list` contract: a non-`str` `text` collapses to
  `""`, a non-`list` `segments` to `[]`.
- **The three malformed-2xx try/except blocks are DRY** (#92). `_chat`,
  `get_embedding`, and `generate_transcription` now route their
  `response.json()` + walk through one private
  `_extract_or_malformed(response, endpoint, extractor)` helper. The
  per-endpoint walk stays at the call site (passed as the `extractor`
  callable, so an empty `{"choices": []}` still translates instead of
  leaking `IndexError`); the catch tuple, the `MalformedResponseError`
  construction, and the defensive excerpt read centralize.
- **The malformed-2xx catch tuple is a public constant** (#102):
  `autonomous.ai.exceptions.MALFORMED_2XX_EXCEPTIONS`
  `= (AttributeError, KeyError, IndexError, TypeError, ValueError)`.
  Consumers extending the OpenAI-compatible adapter can import it
  instead of re-spelling the 5-tuple (which had drifted to a 4-tuple at
  two of three sites).
- **`MalformedResponseError` excerpt reads are crash-safe** (#90).
  All three raise sites evaluated `body_excerpt=response.text` inside
  the `except` block; a body whose declared charset can't decode (e.g.
  Content-Type utf-8 but latin-1 bytes) made that re-run the broken
  decode and raise `UnicodeDecodeError` UNCAUGHT inside the constructor
  arg — so the typed exception never raised and the caller saw a raw
  stdlib `UnicodeDecodeError`. The new
  `MalformedResponseError.from_response(response, msg, *, endpoint="")`
  classmethod owns a defensive read (falls back to an `errors="replace"`
  decode of `response.content`). The constructor's `body_excerpt`
  coercion also now accepts `memoryview` (#104) alongside `bytes` /
  `bytearray`.

**Migration.** None required — all changes preserve the documented
return types and exception classes. `generate_transcription` callers
that defensively wrote `result["text"] or ""` can drop the guard. The
new `MALFORMED_2XX_EXCEPTIONS` constant and `from_response` classmethod
are additive.

### `FluxAIModel` retries `408` / `429` throttling again (#89)

**What changed.** #85 narrowed flux's `transport_error_cls` to
`requests.ConnectionError` so `raise_for_status`-raised `HTTPError`
fails fast — correct for permanent 4xx (expired signed URL, 403, 404),
but it also stopped retrying transient **429 Too Many Requests** from
fal.ai burst-throttling, which pre-#85 retried under the
`flux_max_attempts` budget. The flux `_HTTP` client now passes
`transport_failure_codes={408, 429}`, routing those two codes through
the transport-failure branch (wrapped as `ConnectionError`, retried)
while every other 4xx still fails fast.

**Migration.** None. A burst-throttled image generation that previously
failed on attempt 1 now recovers after backoff. The CDN GET leg
(`max_attempts=1`) still short-circuits a 429 — a near-expired signed
URL races the clock, so retrying it is latency waste.

### `HttpClient`: `on_failure` 5xx parity + reject over-broad `transport_error_cls` + marker escape guard (#96 / #98 / #103)

**What changed.**

- **`on_failure` now fires on transport-status (5xx + extras) failures**
  (#96). Previously the `is_transport_failure(status_code)` branch raised
  `transport_error_cls` WITHOUT notifying `on_failure`, while the
  exception and (#91) HTTPError branches did — so an adapter wiring
  `on_failure=` to an alerting counter saw 4xx events but NOT 5xx,
  inverted from what a transport-degradation alert wants. All three
  failure paths now fire the hook. Closes the "pre-existing asymmetry …
  tracked as a follow-up" caveat in the #91 entry below.
- **Over-broad `transport_error_cls` is rejected at construction** (#98).
  `HttpClient(transport_error_cls=Exception)` (or `BaseException`) would
  make the retry catch tuple `(Exception,)` match #91's internal
  `_NonTransportHTTPError` marker, silently re-introducing the
  retry-on-4xx bug #91 fixed. The constructor now raises `ValueError`
  if `transport_error_cls` is broad enough to catch the marker. Narrow
  classes (`requests.RequestException`, `requests.ConnectionError`,
  `RuntimeError` subclasses, `HPCUnreachableError`) are unaffected.
- **Defensive marker escape guard** (#103): `request()` now asserts the
  `retry()` result is not a `_NonTransportHTTPError` before returning
  (unreachable today; pins the "marker never escapes `request()`"
  invariant against future refactors that might route it as a value).

**Migration.** Consumers wiring `on_failure` as a transport-error
counter will now also see 5xx events (previously only 4xx via #91). See
the #91 entry's updated on-failure subsection for partitioning guidance.
No adapter in-tree passes a broad `transport_error_cls`, so #98 breaks
nothing shipped; a downstream adapter that lazily passed `Exception`
must narrow it.

### `GeminiAIModel` orphan-cleanup: logged + parallelized (#93 / #94)

**What changed.** The per-file orphan-cleanup delete loop in
`_add_files` (run when the upload poll fails) previously (a) swallowed
every delete failure with a bare `except Exception: pass` — zero signal,
so a future SDK change rejecting some `orphan.name` format would leak
Gemini file quota undetectably (#93) — and (b) ran N deletes serially,
which under degraded Gemini conditions could sum past the outer RQ job
deadline and replace the typed `GeminiFileUploadTimeoutError` with
`rq.exceptions.JobTimeoutError` (#94). Cleanup-delete failures are now
logged (`_print=False`, log file only — the original poll exception is
still what the caller sees) and the deletes run on a bounded
`ThreadPoolExecutor(max_workers=4)`.

**Migration.** None. Operators will see new `Gemini orphan-cleanup
delete failed …` lines in `logs/current_run_error_log.log` when a
cleanup delete fails (previously silent).

### `LocalAIModel.generate_json` outer retry — narrow catch tuple + wrap class (#97 / #106)

**What changed.**

- `LocalAIModel.generate_json`'s outer `retry()` catch tuple narrowed
  from `requests.RequestException` to
  `(requests.ConnectionError, requests.Timeout)` (plus the existing
  `json.JSONDecodeError` / `ValueError` / `KeyError` parse-failure
  classes). Effect: a `raise_for_status`-raised `requests.HTTPError`
  (a `RequestException` but not a `ConnectionError` / `Timeout`) no
  longer matches the catch tuple, so permanent 4xx responses from
  Ollama fail fast after 1 attempt instead of burning the 3-attempt
  budget. Outer-altitude sibling of #91's HttpClient-internal fix.
- `local_model._HTTP`'s `transport_error_cls` simultaneously narrowed
  from `requests.RequestException` to `requests.ConnectionError`
  (mirrors flux #85). Without this companion change the narrowing of
  the outer catch tuple silently dropped real transient transport
  failures (`ConnectionError` / `Timeout` from `session.request`)
  from 3 attempts to 1, because HttpClient was wrapping them as base
  `requests.RequestException(msg)` instances — and a base instance
  is not a `ConnectionError` / `Timeout` subclass instance, so the
  narrowed catch tuple silently stopped matching. With
  `transport_error_cls=ConnectionError` the wrap IS a
  `ConnectionError` instance, so the outer tuple still matches and
  3-attempt retry on transient failures is preserved.

**Migration.**

- `LocalAIModel.generate_json` callers that previously caught
  `requests.RequestException` to receive an HTTPError will need to
  add an explicit `except requests.HTTPError` arm — HTTPError now
  propagates unwrapped past the outer retry, alongside the existing
  `GenerateJSONEmptyResponseError` / `GenerateJSONParseError`
  translations. (The pre-#108 behavior was a bug: 3-attempt retry
  on permanent 4xx burned wall time and tokens for no benefit.)
- `flush_memory`'s `except requests.RequestException` catch still
  matches because `ConnectionError` is-a `RequestException`. No
  caller-side changes required for the wrap-class narrowing.
- Trade-off documented in-line: a bare `requests.ChunkedEncodingError`
  (a `RequestException` subclass that is neither a `ConnectionError`
  nor a `Timeout`) is no longer retried by the outer wrapper.
  Same trade flux #85 made.
- Type-erasure trade: a real `requests.Timeout` from `session.request`
  now reaches callers as a `requests.ConnectionError` instance (the
  wrap class). The original `Timeout` is preserved on `__cause__`,
  so observability that walks the chain still sees the true type.

This closes the "Tracked as a follow-up" note in #91 below: with #91
in HttpClient AND #97/#106 at the outer caller, both retry altitudes
that previously matched HTTPError-via-RequestException now correctly
fail-fast.

### `MalformedResponseError` — structured `endpoint` / `status` / `body_excerpt` fields (#83)

**What changed.**

- `autonomous.ai.exceptions.MalformedResponseError` now exposes three
  diagnostic attributes on the instance: `endpoint` (str, the path that
  returned the malformed body), `status` (int | None, the response
  status code), and `body_excerpt` (str, the first 200 chars of
  `response.text`). The 200-char bound is enforced by the constructor
  via `_EXCERPT_MAX = 200`, so a future raise site cannot accidentally
  pick a different bound or forget the excerpt entirely. Same pattern
  as `GenerateJSONParseError.raw` / `._RAW_MAX`.
- All three raise sites (`OpenAIClient._chat`, `OpenAIClient.get_embedding`,
  `OpenAIClient.generate_transcription` — see #82 below for the third)
  populate the new fields. The body-excerpt is no longer baked into
  the formatted message string.

**Migration.**

- Additive constructor change — every kwarg has a default, so any
  caller still doing `raise MalformedResponseError("msg")` keeps
  working. Consumers triaging programmatically can now read
  `exc.endpoint`, `exc.status`, `exc.body_excerpt` instead of parsing
  the message string.
- Storyteller's structured-observability layer should prefer the new
  fields (`log.warn(endpoint=exc.endpoint, status=exc.status,
  body=exc.body_excerpt)`) — message-regex consumers should migrate
  off message parsing since the body excerpt is no longer in the
  message.
- `body_excerpt=` accepts `str`, `bytes`, or `bytearray`. Bytes-like
  inputs are decoded with `utf-8` / `errors="replace"` so malformed
  encodings degrade to U+FFFD rather than raising
  `UnicodeDecodeError` inside the error-handling path. Other
  non-str types fall back to `str(...)` defensively — a misuse
  doesn't crash the translation site.

### `OpenAIClient.generate_transcription` malformed-2xx translation (#82)

**What changed.**

- `generate_transcription` now wraps `response.json()` + `body.get(...)`
  in `try/except (AttributeError, ValueError)` and translates to
  `MalformedResponseError` with the new structured fields (endpoint
  `/audio/transcriptions`, the response status code, and the body
  excerpt). Closes the "Known gaps" callout under the #76 entry.
- `AttributeError` covers the non-dict body case (`body.get(...)`
  against a list / None / scalar); `ValueError` covers
  `response.json()` raising `json.JSONDecodeError` on non-JSON bodies.

**Migration.**

Storyteller's `AudioAgent` paths that catch
`(KeyError, IndexError, TypeError)` around
`client.generate_transcription(...)` should add
`MalformedResponseError` (and broaden / drop the stdlib catch — the
new translation makes the stdlib catch dead). Same shape as the #76
migration for `generate_text` / `summarize_text` / `get_embedding`.

### `FluxAIModel` retry altitude — narrow `transport_error_cls` to `ConnectionError` (#85)

**What changed.**

- `flux._HTTP` now constructs `HttpClient` with
  `transport_error_cls=requests.ConnectionError` (was
  `requests.RequestException`).
- Effect on retry semantics: `HttpClient._attempt`'s
  `raise_for_status`-raised `requests.HTTPError` no longer matches the
  retry catch tuple (because `HTTPError` is-a `RequestException` but
  not-a `ConnectionError`). So non-transport 4xx responses fail fast
  at the altitude layer instead of burning the configured retry
  budget. The `is_transport_failure` 5xx / 401 path still routes
  through retry (it raises the configured `transport_error_cls` ==
  `ConnectionError` directly).
- The per-call `max_attempts=1` override on the CDN GET (#77) remains
  in place — it still short-circuits retry against the
  `is_transport_failure` 5xx case that the CDN can produce. The fix
  in this entry just means the 4xx case (signed-URL expired / 403 /
  404) gets fail-fast behavior at the altitude layer too, not just
  via the per-call override.

**Migration.**

- Downstream catch in `FluxAIModel.generate_image` (`except
  (requests.RequestException, ValueError, OSError)`) is unchanged —
  `ConnectionError` is-a `RequestException`, so the catch still
  matches retry-exhaustion failures.
- Trade-off worth noting: HttpClient's transport re-raise (the
  `except requests.RequestException` branch inside `_attempt`) now
  wraps `requests.Timeout` / `requests.ChunkedEncodingError` as
  `ConnectionError` for the flux client only. The original is
  preserved on `__cause__`, so observability that walks the chain
  still sees the true type. Other adapters with
  `transport_error_cls=requests.RequestException` (or the default
  `TransportError`) are unaffected.

### `GeminiAIModel._add_files` orphan-cleanup edge-case widening (#84)

**What changed.**

- The outer except in the poll loop widened from
  `(GeminiFileUploadTimeoutError, genai.errors.APIError)` to a bare
  `except Exception`. Rationale: `genai.errors.UnknownApiResponseError`
  subclasses `ValueError` (not `APIError`), so a malformed-payload
  failure on `client.files.get(name=...)` previously bypassed the
  outer except and SKIPPED orphan cleanup. The `raise` re-raises the
  original — the catch is wider but the propagated exception type
  is unchanged.
- The inner cleanup loop now guards against `orphan.name is None`
  (the `google.genai.types.File.name` type is `Optional[str]` —
  partial uploads can yield `name=None`). Calling
  `files.delete(name=None)` would have raised `TypeError` inside
  the cleanup loop and masked the original poll exception.
- The inner per-orphan delete catch broadened from
  `except genai.errors.APIError` to `except Exception` — defensive
  net so any failure during best-effort cleanup (APIError, TypeError,
  transient network blip) doesn't mask the original poll exception
  that the trailing `raise` re-throws.

**Migration.**

No consumer-side action required — the exception contract is
unchanged (the original poll exception still propagates). Only the
side-effect on Gemini's stored-files quota improves.

### `HttpClient` retry no longer catches `raise_for_status`-raised `HTTPError` (#91)

**What changed.**

- `HttpClient.request` previously set the retry catch tuple to
  `(self.transport_error_cls,)`. When an adapter passed
  `transport_error_cls=requests.RequestException` (the natural choice
  for downstream-catch compatibility — every legacy adapter has
  `except requests.RequestException` somewhere), the tuple also
  matched `requests.HTTPError` because `HTTPError` is a
  `RequestException` subclass. Result: a permanent 4xx (403, 404, etc.)
  would burn the full `max_attempts` × `retry_backoff` budget before
  propagating, defeating fail-fast semantics for non-transport
  client errors.
- Post-#91, `HttpClient._attempt` wraps `response.raise_for_status()`'s
  `HTTPError` in a private `_NonTransportHTTPError(Exception)` marker
  that is NOT a subclass of any plausible `transport_error_cls`, so
  the retry catch tuple never matches it. `HttpClient.request`
  catches the marker at the boundary and re-raises the original
  `HTTPError` via `raise ... from None`, so callers see exactly the
  type they saw pre-#91. Their `except requests.RequestException`
  catches still match.

**Effect on adapters at the HttpClient layer.**

- `db_sync` passes `transport_error_cls=requests.RequestException`
  (`local_model` was since narrowed to `requests.ConnectionError` by
  #97/#106 — for a DIFFERENT reason: keeping its OUTER `retry()` catch
  tuple matching, not the HttpClient-layer fail-fast this entry covers).
  `db_sync` was latent at the HttpClient layer pre-#91 (`max_attempts=1`
  means no retry budget to burn), and the moment HttpClient's
  `max_attempts` is tuned above 1 it would have exposed the same
  retry-on-4xx bug `flux` had pre-#85. **Post-#91 it's safe at any
  HttpClient `max_attempts`** — the `_NonTransportHTTPError` marker
  removes the HTTPError-overlap problem at the altitude layer, so the
  #85-style per-adapter narrowing is structurally UNNECESSARY for
  `db_sync`. **Decision (#101):** keep `db_sync` on
  `requests.RequestException` rather than narrow it. Rationale: #91
  protects correctness, `db_sync`'s downstream `except Exception` /
  future `except requests.RequestException` keep matching the wrap
  class unchanged, and at `max_attempts=1` the narrowing would be pure
  cosmetics. This is an intentional keep-as-is, not silent inertia — a
  future agent should NOT "defensively" narrow it.
- `flux` narrowed `transport_error_cls` to
  `requests.ConnectionError` in #85 (sibling entry above). With #91
  in place the narrowing is structurally redundant for fail-fast on
  4xx — but stays in place because `ConnectionError` is still the
  semantically tighter wrap class for flux's network-only failure
  surface.
- `openai_compat` passes `HPCUnreachableError` (a `RuntimeError`
  subclass that's never a parent of `HTTPError`), so its retry
  tuple never matched HTTPError pre-#91. Zero behavior change.

**On-failure observability.**

The new `try/except requests.HTTPError` in `_attempt` calls
`_safe_hook(self.on_failure, ...)` before wrapping — so the
`on_failure` hook now fires for non-transport HTTPError attempts
where pre-#91 it fired only for transport-class exceptions. This is
consistent with the documented contract ("fires on every caught
exception during an attempt") but the catch surface is genuinely
broader. Adapters wiring `on_failure` to a counter/sentry tag should
expect 4xx events in addition to the prior transport-class set.

**Counter semantics for consumers wiring `on_failure` (#100).** Pre-#91
this hook fired only for transport-class failures (5xx, configured-extras
codes, transport-class exceptions). Post-#91 it ALSO fires for
non-transport HTTPError attempts (4xx other than configured extras).
Consumers using `on_failure` as a transport-error counter should
partition by exception type (`isinstance(exc, requests.HTTPError)`) to
preserve pre-#91 semantics, or accept the wider definition of "failure"
as the new contract.

**Asymmetry resolved (#96).** The `is_transport_failure(status_code)`
branch (5xx + configured extras) previously did NOT call `on_failure`,
so a counter saw 4xx (via the HTTPError branch above) but missed 5xx —
exactly inverted from what a transport-degradation alert wants. As of
#96 that branch fires `on_failure` too, so all three failure paths
(config-class exception, transport-class exception, transport-status
response, non-transport HTTPError response) notify the hook uniformly.
The pre-#91 "tracked as a follow-up" caveat is closed.

**Migration.**

No consumer-side action required. The contract documented on
`HttpClient.request` is unchanged:
> Any non-transport HTTP error (4xx other than configured extras) is
> surfaced via `response.raise_for_status()` so the caller gets a
> `requests.HTTPError` with the original response attached.

That contract is now actually upheld for adapters with broad
`transport_error_cls` choices, not just narrow ones. The propagated
HTTPError has `__cause__=None` and `__suppress_context__=True` (set
by `raise ... from None`). The implementation raises the unwrapped
HTTPError OUTSIDE the `except _NonTransportHTTPError` block so
Python does not set `__context__` to the marker class — the marker
stays fully private even from programmatic chain-walkers (sentry,
structlog).

### `OpenAIClient` malformed-200 translation + new `MalformedResponseError` (#76)

**What changed.**

- New typed exception `autonomous.ai.exceptions.MalformedResponseError`
  (a `RuntimeError` subclass) — raised when a 2xx body shape is
  unextractable (no `choices[0].message.content` in chat, no
  `data[0].embedding` in embeddings, or a non-JSON 2xx body).
- `OpenAIClient._chat` and `OpenAIClient.get_embedding` translate
  `KeyError` / `IndexError` / `TypeError` / `ValueError` (the last covers
  `json.JSONDecodeError`) at the extraction point and raise
  `MalformedResponseError` instead. Pre-#76 these stdlib exceptions
  leaked raw past the typed-exception contract — see issue #76's repro.
- `OpenAIClient.generate_text` and `OpenAIClient.summarize_text` (both
  thin wrappers over `_chat`) now propagate `MalformedResponseError`
  to the caller on malformed 200. Same for `get_embedding`.
- `OpenAIClient.generate_json`'s contract is **preserved**: it still
  raises `GenerateJSONEmptyResponseError` on malformed body. The new
  `MalformedResponseError` from `_chat` is caught and re-translated
  internally so callers don't see the new exception type.

**Migration.**

Storyteller / other consumers catching `(KeyError, IndexError,
TypeError)` around `client.generate_text(...)`, `summarize_text(...)`,
or `get_embedding(...)` should add `MalformedResponseError` to their
catch tuple — the stdlib exceptions no longer fire on the malformed-200
path. `generate_json` consumers need no change.

**Known gaps.** The `generate_transcription` leak called out in the
initial #76 ship is closed by #82 (see entry above). No remaining
gaps in this slice.

### `HttpClient.request` per-call `max_attempts=` override + flux CDN GET fail-fast (#77)

**What changed.**

- `autonomous.http.HttpClient.request` (and all of `get` / `post` /
  `put` / `delete` via `**kwargs`) accepts a new
  `max_attempts: int | None = None` keyword argument. When passed,
  it overrides `self.max_attempts` for that single call. `None`
  (the default) preserves the instance setting. Must be `>= 1`.
- `FluxAIModel.generate_image`'s CDN GET now passes `max_attempts=1`,
  short-circuiting retry on the fal.ai signed-URL fetch. The POST to
  fal.ai still uses the full `settings.flux_max_attempts` budget.
- Behavior change vs `#50 slice E`: that slice moved the CDN fetch
  UNDER the retry loop (so transient CDN 5xx would retry 3×). #77
  reverts that for the CDN leg only — signed URLs are short-lived,
  so retrying against a near-expired URL races the clock; permanent
  4xx (signed-URL expired, 403, 404) is always wasted budget.

**Migration.**

No consumer-side action required for default usage. Adapters that wrap
`HttpClient` and forwarded kwargs to `request` are now subject to one
reserved kwarg name (`max_attempts`) being consumed at the HttpClient
layer rather than flowing through to `session.request`. No in-tree
adapter currently does this.

### `GeminiAIModel._add_files` orphan-cleanup on poll-loop failure (#75)

**What changed.**

- The bounded poll loop introduced by `#50 slice A` (PR #68) now wraps
  in a `try/except` that best-effort deletes every file appended to
  `uploaded_files` on `GeminiFileUploadTimeoutError` OR
  `genai.errors.APIError` raised from the poll. Pre-#75 the timeout
  raised straight out and the uploaded-but-stranded files remained on
  Gemini's storage indefinitely.
- The poll itself was switched from `self.client.get_file(name)` to
  `self.client.files.get(name=name)` — `client.get_file` does not
  exist on `google-genai >= 2.0`; the prior call would have raised
  `AttributeError` at runtime against the real SDK on any file taking
  >0.5s to leave PROCESSING. Tests passed pre-#75 only because they
  stubbed `client.get_file` directly. Without this correction the
  orphan-cleanup added by #75 would itself be dead code.

**Migration.**

No consumer-side action required. The function's exception contract
(raises `GeminiFileUploadTimeoutError` on poll-cap exhaustion) is
unchanged; only the side-effect on Gemini's stored-files quota
improves. Consumers that previously relied on the existence of
stranded PROCESSING files post-timeout (none known) would need to
re-upload on the retry path.

### `db_sync._HTTP_SESSION` → `_HTTP` HttpClient migration (#50 slice D)

**What changed.**

- `autonomous.db.db_sync._HTTP_SESSION` (a `requests.Session`) is replaced by
  `_HTTP` (an `autonomous.http.HttpClient`). The lone call site —
  `_get_vector_local`, the legacy media_ai embeddings POST — now goes
  through `_HTTP.post(...)`. Connection pooling is preserved (HttpClient
  holds its own internal `requests.Session`); the call signature is unchanged.

**Why.**

- Continues the per-adapter migration from `#50`'s "Suggested fix shape" — each
  call site moves through `HttpClient` so a future transport-class refinement
  ships to every adopter via the central predicate rather than being maintained
  per-adapter.
- Aligns `db_sync` with `autonomous.auth.autoauth` (slice B, #69) and
  `autonomous.ai.models.local_model` (slice C, #70).

**Behavior change on the `[HPC-UNREACHABLE]` marker for 5xx production responses.**

- Pre-migration: a 5xx response from media_ai flowed through the in-flow
  non-200 branch and emitted `local:http:5xx` (e.g. `local:http:503`).
- Post-migration: a 5xx response in **production** goes through
  `HttpClient.is_transport_failure` (which returns True for ≥500) and gets
  wrapped into the configured `transport_error_cls=requests.RequestException`.
  The except block emits `local:exc:RequestException` instead of
  `local:http:503`.
- 4xx is preserved as `local:http:{code}` — the new `except requests.HTTPError`
  branch extracts `e.response.status_code`. The pre-migration in-flow check
  is retained as defense-in-depth (HttpClient bypassed in tests that patch
  `_HTTP.post` directly with a mock response — the in-flow path still
  emits `local:http:{code}` in that case).
- Connection failures: HttpClient wraps `requests.ConnectionError` (and the
  other `requests.RequestException` subclasses) as the configured wrapper,
  with `__cause__` set. The except branch unwraps `__cause__` one level so
  the signature reports the original class — `local:exc:ConnectionError`
  matches pre-migration.

**Net signature mapping (production):**

| Failure mode | Pre-migration | Post-migration |
|---|---|---|
| 4xx response | `local:http:{code}` (via in-flow check) | `local:http:{code}` (via `HTTPError` branch) — preserved |
| 5xx response | `local:http:{code}` | `local:exc:RequestException` — **changed** |
| Connection error / timeout | `local:exc:ConnectionError` (or similar) | `local:exc:ConnectionError` (via `__cause__` unwrap) — preserved |
| Other (KeyError on `.json()`, etc.) | `local:exc:{class}` | `local:exc:{class}` — preserved |

**Migration for log scrapers.**

Consumer dashboards that match `\[HPC-UNREACHABLE\] local embedding failed: HTTP 5[0-9]{2}` for 5xx tier counting will see those events shift to the `local:exc:RequestException` signature. The marker family (`[HPC-UNREACHABLE]`) and the per-call counter (`hpc_unreachable_total`) are unchanged. If the scraper relied on per-5xx-code distinction, it should:

```python
# Pre-#50-slice-D
if re.match(r"local:http:5\d{2}", signature): ...

# Post-#50-slice-D — same intent, new shape
if signature == "local:exc:RequestException": ...
# OR (forward-compatible) match either form:
if re.match(r"local:(http:5\d{2}|exc:RequestException)", signature): ...
```

**Test fixture migration.**

- `tests/unit/test_unit_db_sync_batch_iter_2026_05_13.py`,
  `tests/unit/test_unit_db_sync_batch_iter_2026_05_14.py`,
  `tests/unit/test_unit_embedding_retry_throttle_iter_2026-06-06.py`,
  `tests/unit/test_unit_http_session_pooling.py`,
  `tests/unit/test_unit_perf_iter_2026_05_15.py`,
  `tests/perf/test_perf_http_session.py` — 17 patches across 6 files
  re-targeted from `db_sync._HTTP_SESSION` (.post or whole-object swap) to
  `db_sync._HTTP`. No aliasing — `_HTTP_SESSION` removed cleanly.
- External consumers that monkeypatch `autonomous.db.db_sync._HTTP_SESSION`
  directly must update to `_HTTP`. No backward-compat alias because
  `HttpClient` routes through `session.request(...)` rather than
  `session.post(...)`, so an aliased `_HTTP_SESSION.post` patch would be a
  silent no-op.

### `flux._SESSION` + `retry()` → `_HTTP` HttpClient migration (#50 slice E)

**What changed.**

- `autonomous.ai.models.flux._SESSION` (`requests.Session`) and the inner
  `_post()` + `autonomous.ai.retry.retry(...)` wrapper inside
  `generate_image` are replaced by `_HTTP = HttpClient(...)` at module scope.
  `HttpClient.max_attempts` + `HttpClient.retry_backoff` absorb the retry
  policy; the call sites collapse to `_HTTP.post(...)` / `_HTTP.get(...)`.
- The `_max_attempts` / `_retry_sleep` class attrs on `FluxAIModel` are
  removed (their values live on `_HTTP` now, read from the same
  `settings.flux_max_attempts` / `settings.flux_retry_sleep` settings).
- The `from autonomous.ai.retry import retry` import is removed (no
  callers left in this module).

**Behavior change worth flagging: CDN GET now retries.**

Pre-migration, the retry policy wrapped ONLY the `_SESSION.post` call to
fal.ai. The subsequent `_SESSION.get(image_url, ...)` against fal.ai's CDN
ran outside the retry loop — a transient CDN failure failed the whole
`generate_image` call.

Post-migration, `HttpClient`'s retry policy applies uniformly to both
`_HTTP.post` and `_HTTP.get`. A transient CDN failure now retries up to
`max_attempts` times (default 3) instead of failing immediately. This is
strictly better than the pre-migration behavior — fal.ai's CDN failures
are nearly always transient, and the previous single-attempt GET was a
weak spot in the user-visible reliability story.

**Behavior change worth flagging: retry-exhaustion exception class.**

Pre-migration, when retries were exhausted the original
`requests.ConnectionError` (or other `requests.RequestException`
subclass) propagated to the caller.

Post-migration, `HttpClient` wraps the caught exception into the
configured `transport_error_cls=requests.RequestException` on retry
exhaustion (via `raise transport_error_cls(...) from exc`). The original
class is on `__cause__`; the wrapper has the original exception's
message embedded (`f"POST URL failed (ConnectionError): permanent"`).

Consumer impact: `except requests.RequestException` (the parent class)
still catches both pre- and post-migration. `except requests.ConnectionError`
specifically catches only pre-migration; post-migration the wrapper class
is `RequestException`, so a `ConnectionError`-specific catch silently
falls through.

If a caller depends on the original class, they can unwrap one level:

```python
try:
    flux.generate_image(...)
except requests.RequestException as e:
    original = e.__cause__ if e.__cause__ is not None else e
    if isinstance(original, requests.ConnectionError):
        ...
```

**Test fixture migration.**

`tests/unit/test_unit_flux.py` updated in lockstep:
- 7 patches across 5 test methods retargeted from `flux_mod._SESSION.post/get`
  to either `flux_mod._HTTP.post/get` (non-retry tests, direct patch is fine)
  or `flux_mod._HTTP.session.request` (retry tests — patching `_HTTP.post`
  directly would bypass HttpClient's internal retry budget, leaving the
  flaky-then-succeeds tests with `calls["post"] == 1` instead of 3).
- `monkeypatch.setattr(FluxAIModel, "_retry_sleep", 0.0)` becomes
  `monkeypatch.setattr(_HTTP, "retry_backoff", 0.0)` — same speed-up
  intent, different attribute now that the retry config lives on the
  HttpClient instance.
- `pytest.raises(requests.ConnectionError, match="permanent")` becomes
  `pytest.raises(requests.RequestException, match="permanent")` for the
  retry-exhaustion test (reflecting the new wrapper class).

External consumers who monkeypatch `autonomous.ai.models.flux._SESSION`
directly must update to `_HTTP` (or `_HTTP.session.request` for retry
exercises). No backward-compat alias — same rationale as slices C/D.

### `openai_compat._SESSION` + `_post()` exception ladder → `HttpClient` (#50 slice F — closes #50)

**What changed.**

- `autonomous.ai.models.openai_compat._SESSION` (`requests.Session`) plus
  the inner `_attempt()` closure + manual exception ladder + manual
  `_is_transport_failure` check + manual `raise_for_status` + outer
  `autonomous.ai.retry.retry(...)` wrapper inside `_post()` are
  replaced by `_HTTP = HttpClient(...)` at module scope. HttpClient
  absorbs the entire pattern: config-error carve-out, transport-class
  classification, transport_error wrapping, retry budget.
- The `_post()` method body collapses from ~70 lines to ~12: URL
  construction, then `_HTTP.post(url, headers=..., json=..., timeout=...)`.
- `OpenAIClient._retry_attempts` / `_retry_backoff` class attrs are
  removed (their values now live on `_HTTP.max_attempts` /
  `_HTTP.retry_backoff`, read from the same `settings.hpc_*` keys).
- `from autonomous.ai.retry import retry` is removed (no callers left
  in this module).

**HttpClient extension: `extra_non_transport_exceptions=` constructor kwarg.**

`openai_compat`'s pre-migration config-error ladder listed two more
`requests.exceptions.*` types than HttpClient's default
`_NON_TRANSPORT_REQUESTS_EXCEPTIONS` tuple: `SSLError` and `ProxyError`.
For the HPC deployment those are corporate-cert-bundle /
corporate-proxy misconfigs (retry can't fix), but for adapters over
the public internet (fal.ai, etc.) they can be transient — so the
classification is per-deployment.

Slice F extends `HttpClient.__init__` with an
`extra_non_transport_exceptions: Iterable[type[BaseException]] = ()`
parameter that, at instance construction time, is concatenated onto
the module-level tuple. The per-instance tuple lives on
`self._non_transport_exceptions` and is what the `except` clause in
`HttpClient.request` checks. Adapters that need per-deployment
extension pass the relevant types; the public-internet adapters leave
it empty (default behavior unchanged).

**HPCUnreachableError message format change.**

HttpClient instantiates `transport_error_cls` (set to `HPCUnreachableError`)
with its own format strings:

- status-code raise: `f"POST {url} returned {status}: {text[:200]}"`
- exception raise: `f"POST {url} failed ({type(exc).__name__}): {exc}"`

Pre-migration formats were:

- status: `f"HPC returned {status} for {path}: {text[:200]}"`
- exception: `f"HPC unreachable ({type(exc).__name__}): {exc}"`

The exception **class is unchanged** (`HPCUnreachableError`). Only the
embedded message string format differs. Log scrapers grepping for the
literal "HPC unreachable" or "HPC returned" prefixes need to widen the
regex; `except HPCUnreachableError` consumers are unaffected.

**Test fixture migration — 32 patches across 9 unit files + 2 perf + 1 perf-iter tuple.**

External consumers who monkeypatch `autonomous.ai.models.openai_compat._SESSION` directly must update to `_HTTP` (or `_HTTP.session.request` for retry exercises). No backward-compat alias — same rationale as slices C/D/E.

**This closes #50.** All six slices ship: slice A (#68) bounds the gemini `files.upload` PROCESSING poll loop (not an HttpClient migration — separate fix for the same parent issue's unbounded-poll branch); slices B–F (#69–#73) migrate per-adapter HTTP (autoauth, local_model, db_sync, flux, openai_compat) so the per-adapter `_SESSION`/`_post`/`retry` patterns are now centralized in `autonomous.http.HttpClient`.

### `autonomous.db.dereference` eagerly bound at package import (#63)

**What changed.**

- `autonomous.db.__init__.py` now eagerly imports the `dereference`
  submodule alongside `connection`, `db_sync`, `document`, etc. The
  submodule had been omitted from the import tuple, which meant the
  lazy `_import_class("DeReference")` call in
  `autonomous.db.common.py:56` (`from autonomous.db import dereference`)
  raced on cold workers and intermittently raised
  `ImportError: cannot import name 'dereference' from 'autonomous.db'`
  on the first `ReferenceAttr` deref of the process lifetime.

**Migration.**

No source change required for consumers. The storyteller-side workaround
(`import autonomous.db.dereference` at app startup) can come out once
the consumer upgrades to a release containing this fix.

### `db_sync.HPC-UNREACHABLE` events now bump an in-process Counter (#51, slice 2)

**What's new.**

- A process-wide `Counter("hpc_unreachable_total", label_names=("signature",))`
  from the default `autonomous.observability` registry is now bumped
  by every call to `db_sync._emit_hpc_unreachable` — **including
  throttle-suppressed calls** — so dashboards see the true HPC-failure
  rate even when the printed-line stream is silenced. Read via
  `autonomous.observability.REGISTRY.get("hpc_unreachable_total").collect()`.

**Not changed.**

- The printed-line wire shape (raw stdout, `[HPC-UNREACHABLE]` prefix
  at line-start, `(N suppressed in last Ws)` annotation appended) is
  intentionally preserved. The structured-event line shape from
  `observability.event()` (`[MARKER] event=<name> key=value ...`) is
  incompatible with the committed-test contract pinning
  `out.startswith("[HPC-UNREACHABLE]")` and verbatim-message
  substrings. A later slice can flip the wire shape once consumer
  log scrapers (e.g. storyteller's `/debug/lore/health`) migrate
  off the prefix-grep contract.
- `record_embedding_sync_event` Redis hour-bucket counter unchanged.

**Migration.**

No source change required. The Counter is observable from any process
that imports `autonomous.observability`; integrate via:

```python
from autonomous.observability import REGISTRY
data = REGISTRY.get("hpc_unreachable_total").collect()
# {("openai:HPCUnreachableError",): 12, ("local:http:500",): 3, ...}
```

### `openai_compat._is_transport_failure` delegates to the central predicate (#50, slice 2)

**What changed.**

- `autonomous.ai.models.openai_compat._is_transport_failure` is now a
  thin wrapper around `autonomous.http.is_transport_failure`,
  passing `_TRANSPORT_FAILURE_CODES` as the extras set. Behavior is
  identical (same 5xx-range + 401-extra semantics, same defensive
  `False` return on non-orderable inputs) — the consolidation just
  moves the implementation to one place so a future transport-class
  refinement (opt-in 408/429 for throttle-aware adapters, etc.)
  ships to every adopter via the central helper rather than being
  redundantly maintained per-adapter.

**Migration.**

No source change required. The symbol name, call signature, and
return semantics are unchanged. `_TRANSPORT_FAILURE_CODES` is still
the per-deployment extras set — passes through to the central
predicate.

The wider `_post()` → `HttpClient` migration is **deferred** to a
future slice: committed tests across the suite patch
`openai_compat._SESSION.post` directly (and `requests.get` in
`autoauth`), which assumes the call shape `Session.post(...)`. A
clean `HttpClient.post(url, ...)` migration that funnels through
`session.request("POST", ...)` would break those patches; the
migration needs test-fixture coordination to land safely.

### New `autonomous.http` module — consolidated HTTP client (#50, slice 1)

**What's new.**

- `autonomous.http.HttpClient` — `requests.Session` wrapper with
  configurable timeout, retry (delegates to `autonomous.ai.retry.retry`),
  transport-failure classification (5xx range + opt-in extras like 401
  for revoked-token flows), and pluggable observability hooks
  (`on_request` / `on_response` / `on_failure`).
- `autonomous.http.TransportError` — generic transport-class exception;
  adapters can pass their own typed equivalent via
  `transport_error_cls=`.
- `autonomous.http.is_transport_failure(status, *, extra_codes=())` —
  module-level predicate matching the per-instance check.
- `HttpClient.poll(fetch, predicate=..., max_attempts=..., sleep_seconds=...)`
  — bounded polling helper that replaces the bare `while + time.sleep`
  pattern (e.g. `ai.models.gemini` file-state polling, README #6 —
  enforces a wall-clock cap the existing loop lacks).

**Migration.**

No source change required for this slice — it's pure addition.
Existing adapters (`ai.models.openai_compat`, `ai.models.local_model`,
`ai.models.gemini`, `ai.models.flux`, `db.db_sync`, `auth.autoauth`)
continue to use their per-module `requests.Session()` and ad-hoc
retry/timeout logic. A follow-up slice retargets each adapter onto
`HttpClient` one by one — each migration ships as its own PR with a
MIGRATIONS entry covering the per-adapter behavior change (timeout
defaults, retry budgets, observability hooks adopted).

New adapters being added now SHOULD use `HttpClient` directly rather
than mint another module-level `requests.Session()`:

```python
from autonomous.http import HttpClient

class MyAdapter:
    def __init__(self):
        self._http = HttpClient(
            timeout=30.0,
            max_attempts=3,
            retry_backoff=5,
            transport_failure_codes={401, 429},
        )

    def fetch(self, url, payload):
        resp = self._http.post(url, json=payload, headers=self._headers())
        return resp.json()
```

### New `autonomous.observability` module — structured events + metrics (#51, slice 1)

**What's new.**

- `autonomous.observability.Counter` / `Histogram` — process-wide
  metric primitives with Prometheus-style label semantics. In-memory
  backed in this slice; a Redis backend (matching the hour-bucket
  pattern in `db.db_sync.record_embedding_sync_event`) and a
  `prometheus_client` backend ship in follow-up slices.
- `autonomous.observability.counter(name, ...)` /
  `histogram(name, ...)` — register-and-return helpers idempotent on
  name (matching `prometheus_client`'s shape).
- `autonomous.observability.REGISTRY` — default process registry; tests
  construct fresh `Registry()` instances and pass them via
  `registry=` for isolation.
- `autonomous.observability.event(name, *, level, marker, **fields)` —
  structured event emission that renders to a human-readable line
  (preserving legacy sentinel prefixes via `marker=`) AND returns the
  event dict for attachment to RQ job meta / API response bodies.

**Migration.**

No source change required for this slice — pure addition. The
existing `[HPC-UNREACHABLE]`, `[STRUCTURED-OUTPUTS-UNAVAILABLE]`, and
free-form `log()` emission sites continue to work unchanged. A
follow-up slice migrates emission sites field-by-field; the
`marker=` parameter ensures grep-based scrapers (e.g. storyteller's
`/debug/lore/health`) keep matching during the transition.

New emission sites being added now SHOULD use `event()` rather than
free-form `log()` interpolation:

```python
from autonomous.observability import event, counter

_HPC_UNREACHABLE = counter(
    "hpc_unreachable_total",
    description="HPC transport-class failures",
    label_names=("provider", "status"),
)

# At the failure site:
event(
    "hpc_unreachable",
    marker="HPC-UNREACHABLE",
    level="warning",
    provider="openai",
    status=resp.status_code,
    signature=signature,
)
_HPC_UNREACHABLE.inc(provider="openai", status=str(resp.status_code))
```

The two primitives compose: `HttpClient`'s `on_failure` hook is the
natural place to call `event()` + `counter().inc()` once adapters
migrate, replacing the per-call-site sentinel `print()` and
`log(_print=True)` calls.

### Centralized typed configuration — `autonomous.config` (#49, first slice)

**What changed.**

- New module `autonomous.config` provides a single typed catalog of every
  environment variable the framework reads. Two layers:
  - **Guarded parsers** — `env_str`, `env_int`, `env_float`, `env_bool`,
    `env_list`. They read `os.environ` live on each call, coerce, and fall
    back to the documented default (with a logged breadcrumb) instead of
    raising. A malformed/empty numeric env value that previously raised
    `ValueError` *at import time* (e.g. `int(os.environ.get("HPC_REQUEST_TIMEOUT", 120))`)
    now falls back to the default.
  - **`Settings`** — a typed snapshot of the catalog, plus the module
    singleton `settings` (built once at import). `settings.reload()`
    re-reads the environment; `settings.as_dict()` / `validate()` /
    `Settings.describe()` support introspection and doc generation.
- **Migrated this slice** (call sites now read from the catalog): the AI
  model adapters `openai_compat`, `local_model`, and `flux`, plus
  `db_sync._throttle_window_seconds`. The remaining subpackages (database
  connection helpers, redis/taskrunner, auth providers, storage, Gemini
  adapter, GitHub API wrappers, per-agent provider overrides) still read
  `os.environ` directly and are catalogued for a follow-up per-subpackage
  migration — both forms co-exist.
- New stdlib-only implementation; **no new core dependency** (no pydantic).
- New doc page `docs/guides/configuration.md` lists every variable, its
  type, default, and migration status.

**Migration.**

No source change required for consumers. All existing env-var **names and
defaults are unchanged** — `Settings` reads them by name and every default
mirrors the prior call-site default, so behavior is preserved. The only
behavioral difference is strictly more robust: a malformed numeric env value
now falls back to the default (with a logged note) rather than crashing the
import. New code can read typed values via:

```python
from autonomous.config import settings, env_int

timeout = settings.hpc_request_timeout            # snapshot (int)
window  = env_int("HPC_UNREACHABLE_THROTTLE_SECONDS", 0)   # live read
```

### `GenerateJSONParseError.payload` exposes the parsed object on schema-validation failure (#54)

**What changed.**

- `GenerateJSONParseError` gained an optional, **un-truncated**
  `.payload` attribute carrying the fully-parsed object (dict/list)
  that failed `json_schema` validation. Previously the only artifact
  of a schema miss was `.raw`, a *500-char truncated re-dump* — so any
  payload larger than ~500 chars was unrecoverable: `json.loads(e.raw)`
  on the fragment raised, and consumers had no way to run tolerant
  recovery (synonym/key normalization, default-fill, re-validate) short
  of re-calling the model without a schema.
- `.payload` is populated only on the schema-*validation*-miss path
  (`JSONAgent.generate(..., json_schema=...)` where the body parsed but
  didn't match the shape). It is `None` for every other failure mode —
  unparseable text, empty body, non-dict result, or a structurally
  invalid caller-supplied schema (where the model output isn't at
  fault).
- `.raw` semantics are **unchanged**: still the bounded
  (`_RAW_MAX = 500`) human-diagnostic string. The constructor signature
  gained a keyword-only `payload=None`; all existing positional/keyword
  call sites are unaffected.

**Migration.**

No source change required — purely additive. Consumers driving
key-drifting models (gemma/llama over Ollama, which don't enforce
`required` in their structured-output grammar) can now recover in-hand:

```python
from autonomous.ai.exceptions import GenerateJSONParseError

# Note: JSONAgent.generate(message, ...) — the first positional arg is
# named ``message``, not ``prompt``. The example below passes it
# positionally; if you switch to a keyword form, use ``message=`` to
# avoid TypeError.
try:
    data = JSONAgent().generate(prompt, json_schema=schema, schema_name="lore")
except GenerateJSONParseError as e:
    if e.payload is not None:
        data = my_tolerant_normalizer(e.payload)  # no second round-trip
    else:
        raise
```

### Additional OAuth providers: Facebook, Discord, Microsoft (#44)

**What changed.**

- Three new `AutoAuth` subclasses, exported from `autonomous.auth`
  alongside the existing `GoogleAuth` / `GithubAuth`:
  - `FacebookAuth` — Facebook Login via the Graph API. Stable subject
    is the Graph `/me` `id`.
  - `DiscordAuth` — Discord OAuth2. Stable subject is the `/users/@me`
    numeric snowflake `id`.
  - `MicrosoftAuth` — Microsoft identity platform (Azure AD + personal
    accounts). Stable subject is the OIDC `sub` (falls back to `oid`).
- All three follow the **static-endpoint** idiom of `GithubAuth`
  (no discovery-doc fetch at construction → no network call when
  instantiated, unlike `GoogleAuth`), but ship with the providers'
  well-known authorize/token/userinfo endpoints baked in as defaults,
  so the minimal config is just client id/secret/redirect.
- Each reads `<PROVIDER>_AUTH_*` env vars mirroring the existing
  convention:
  - `FACEBOOK_AUTH_CLIENT_ID`, `FACEBOOK_AUTH_CLIENT_SECRET`,
    `FACEBOOK_AUTH_REDIRECT_URL`, `FACEBOOK_AUTH_SCOPE`
    (default `["email", "public_profile"]`), and optional
    `FACEBOOK_AUTH_{AUTHORIZE_URL,TOKEN_URL,USERINFO_URL}` overrides.
  - `DISCORD_AUTH_CLIENT_ID`, `DISCORD_AUTH_CLIENT_SECRET`,
    `DISCORD_AUTH_REDIRECT_URL`, `DISCORD_AUTH_SCOPE`
    (default `["identify", "email"]`), and optional
    `DISCORD_AUTH_{AUTHORIZE_URL,TOKEN_URL,USERINFO_URL}` overrides.
  - `MICROSOFT_AUTH_CLIENT_ID`, `MICROSOFT_AUTH_CLIENT_SECRET`,
    `MICROSOFT_AUTH_REDIRECT_URL`, `MICROSOFT_AUTH_SCOPE`
    (default `["openid", "email", "profile"]`),
    `MICROSOFT_AUTH_TENANT` (default `common`; selects the tenant
    segment of the authorize/token URLs), and optional
    `MICROSOFT_AUTH_{AUTHORIZE_URL,TOKEN_URL,USERINFO_URL}` full-URL
    overrides (a full URL wins over the tenant-built default).

**Migration.**

No change required for existing consumers — purely additive. To wire a
new provider, instantiate it like the existing ones and route its
callback through `handle_response`, then `User.authenticate(user_info,
token)`; the `(oauth_provider, oauth_sub)` stable-identity pair from
#40 is injected automatically because each subclass sets
`provider_name` and overrides `_extract_sub`. Example:

```python
from autonomous.auth import DiscordAuth

auth = DiscordAuth()
url, state = auth.authenticate()          # redirect the user here
# ... on the callback route:
user_info, token = auth.handle_response(callback_url)
user = User.authenticate(user_info, token)
```

**Not included — Sign in with Apple (deferred).** Apple was named in
#44 but is intentionally NOT in this change. Unlike every other
provider — all of which source identity via an HTTP userinfo GET —
"Sign in with Apple" requires (a) a client
secret that is an ES256-signed JWT generated from a `.p8` private key
(team id + key id + services id), regenerated before expiry, and
(b) identity sourced from the `id_token` JWT returned in the **token
response** — Apple exposes no userinfo GET endpoint, so it does not
fit `AutoAuth.handle_response`'s `requests.get(self.req_uri)` flow.
Adding it cleanly needs a small base-class seam (e.g. an overridable
`_fetch_userinfo(token)` hook so a subclass can decode the id_token
instead of GETting a URL) plus JWT-client-secret generation. Tracked
as a follow-up rather than shipped half-working.

### Embedding `[HPC-UNREACHABLE]` log throttle + 5xx retry coverage (#39)

**What changed.**

- `openai_compat._TRANSPORT_FAILURE_CODES` was previously the fixed
  set `{401, 502, 503, 504}` — every other 5xx code (500, 501, 505,
  and the partner-CDN range 521-529) bypassed the `retry()` wrapper
  entirely because `retry` catches `HPCUnreachableError` and those
  statuses raised `requests.HTTPError` from `raise_for_status`
  instead. The check is now a function `_is_transport_failure(status)`
  covering 401 plus the full 5xx range (500-599 via a single
  `status >= 500` branch, so the partner-CDN 5xx tier is included by
  construction rather than by enumeration). Bounded retry (default
  3 attempts, 10s backoff, env-tunable via `HPC_RETRY_ATTEMPTS` /
  `HPC_RETRY_BACKOFF`) now engages on the entire 5xx family — the
  headline observed-in-prod case was 500 (issue #39's reported flood),
  but the same fix closes 501/505/521-529.
- New helper `db_sync._emit_hpc_unreachable(signature, message)`
  replaces direct `print()` calls in `_get_vector_local` /
  `_get_vector_openai`. Default behavior is unchanged — the message
  prints verbatim with the same `[HPC-UNREACHABLE]` prefix.
- New opt-in env var `HPC_UNREACHABLE_THROTTLE_SECONDS` (default 0 =
  off). When set to a positive integer N, identical-signature prints
  within N seconds are throttled per process; the next print outside
  the window includes a `(M suppressed in last Ns)` annotation. The
  upstream-health counter `record_embedding_sync_event` is NOT
  throttled — every failure still bumps the Redis bucket.

**Migration.**

No source change required for existing consumers — the marker string,
print destination, and per-call print rate are unchanged at default
settings. Operators wanting log-volume dedup during sustained
upstream degradation set `HPC_UNREACHABLE_THROTTLE_SECONDS=60` (or
similar) in their worker env.

### OAuth (provider, sub) identity on `AutoUser` (#40)

**What changed.**

- Two new optional fields on `AutoUser` (and therefore the default
  `User` subclass): `oauth_provider: StringAttr` and
  `oauth_sub: StringAttr`. The pair stores the OIDC-stable identity —
  the provider name plus its `sub` claim (or its provider-specific
  equivalent, e.g. Google's `id` from `oauth2/v2/userinfo`, GitHub's
  numeric `id` from `/user`).
- `AutoUser.authenticate(user_info, token=None)` now looks up by
  `(oauth_provider, oauth_sub)` first when both are present in
  `user_info`, then falls back to email-based lookup for legacy
  records. The OAuth pair is backfilled on every successful login so
  the next call uses the preferred lookup.
- New base-class machinery on `AutoAuth`:
  - `provider_name: str = ""` — short identifier for the IdP. Set on
    subclasses (`GoogleAuth.provider_name = "google"`,
    `GithubAuth.provider_name = "github"`).
  - `_extract_sub(raw_userinfo) -> Any | None` — provider-specific
    extraction of the stable subject identifier. Base implementation
    returns `raw_userinfo.get("sub")`; `GoogleAuth` reads
    `sub or id` (since `oauth2/v2/userinfo` returns the value under
    `id`); `GithubAuth` reads numeric `id`. Override on custom
    `AutoAuth` subclasses that use a different userinfo shape.
- `AutoAuth.handle_response` now injects `oauth_provider` and
  `oauth_sub` into the returned `user_info` dict before returning it
  (non-overriding — callers that pre-populated those keys win).
  Consumers that pass the dict straight to `User.authenticate` get
  the new lookup automatically.

**Migration.**

No source change required for existing consumers. Callers that pass
plain `{"name", "email"}` user_info dicts (tests, custom OAuth flows
that don't use `AutoAuth.handle_response`) keep working — the
(provider, sub) lookup branch is skipped when those keys are absent
and the existing email-based lookup runs.

Consumers building a custom `AutoAuth` subclass should set
`provider_name` and override `_extract_sub` to point at the right
field in their provider's userinfo shape.

Out of scope (filed as follow-ups in the issue body):
- `linked_accounts: ListAttr` of `(provider, sub)` pairs so one user
  can authenticate via multiple providers.
- Migration helper for existing records to populate
  `(oauth_provider, oauth_sub)` from the next successful login's ID
  token. (Backfill already happens on next login for users that
  re-authenticate; explicit batch backfill is the follow-up.)

### JSON Schema / Structured Outputs support (Item 25)

**What changed.**

- New optional kwargs on `JSONAgent.generate`: `json_schema=None`,
  `schema_name="response"`. When `json_schema` is set, the response is
  validated against the schema before return; mismatches raise
  `GenerateJSONParseError` with the raw response on `.raw`.
- New optional kwargs on `OpenAIClient.generate_json`: `json_schema=None`,
  `schema_name="response"`. When set AND the (model, endpoint) is not
  known-unsupported, builds an OpenAI strict-mode `response_format`
  payload (`{"type": "json_schema", "json_schema": {...}, "strict": true}`).
  Conservative 400/422 detection (looks for `json_schema`,
  `response_format`, `unsupported_parameter`, `structured output` in the
  error body) triggers a one-time fallback to loose mode and caches the
  combo for the rest of the process. Operator log marker on first
  detection: `[STRUCTURED-OUTPUTS-UNAVAILABLE]`.
- New optional kwargs on `LocalAIModel.generate_json`: `json_schema=None`,
  `schema_name="response"`. Local has no equivalent of strict mode;
  passing a schema logs `[STRUCTURED-OUTPUTS-UNAVAILABLE]` once per
  (model, endpoint) and proceeds via the existing prompt-only path.
  Client-side validation in `JSONAgent.generate` still applies.
- `MockAIModel.generate_json` absorbs the new kwargs via `**kwargs`.
- `GeminiAIModel.generate_json` is unchanged — its existing `function=`
  parameter already takes a JSON schema. `JSONAgent.generate` translates
  `json_schema=` into the gemini `function` dict at the dispatch layer.
- New core dependency: `jsonschema>=4.0`. The client-side validation
  safety net is unconditionally available (not gated on the `[ai]` extra).
- New helper: `autonomous.ai.models.openai_compat._reset_unsupported_cache()`
  — clears the negative cache. Tests use this for isolation; operators
  may use it after deploying a server-side fix to re-probe strict-mode
  support without restarting the worker.

**Migration.**

No source change required for existing consumers. With `json_schema`
unset (the default), `JSONAgent.generate` behaves identically to today,
and the validation no-ops.

To opt in (per call site):

```python
LORE_BLUEPRINT_SCHEMA = {
    "type": "object",
    "properties": {...},
    "required": [...],
    "additionalProperties": False,
}

result = self.world.system.generate_json(
    prompt=stage1_prompt,
    primer=stage1_primer,
    json_schema=LORE_BLUEPRINT_SCHEMA,
    schema_name="lore_blueprint",   # optional; defaults to "response"
)
```

Behavior when something goes wrong:
- Strict-mode unavailable on the (model, endpoint): one-time
  `[STRUCTURED-OUTPUTS-UNAVAILABLE]` log + fallback to loose mode +
  cache for the process. Subsequent calls go directly to loose mode.
- Response fails client-side validation: `GenerateJSONParseError`
  raised with `.raw` populated.

**Provider support matrix (as known on 2026-06-02).**

| Provider | Strict-mode native | Client-side validation |
|---|---|---|
| `GeminiAIModel` (via `function=`) | Yes (function-calling) | Yes (defense in depth) |
| `OpenAIClient` (chat.binghamton.edu, OpenAI direct) | Endpoint-dependent — fallback handles mismatch | Yes |
| `LocalAIModel` (Ollama) | No (prompt-only) | Yes |
| `MockAIModel` | n/a (deterministic) | Yes — test authors must construct conforming mock data |

**Tracked in:** `Sallenmoore/storyteller#12` (filed against the consumer's tracker; library work happens in autonomous).

### Image-gen FLUX provider + routing layer (Item 24)

**What changed.**

- New provider `FluxAIModel` under `autonomous.ai.models.flux`. Registered
  in `BaseAgent.MODEL_REGISTRY` as `"flux"`. Targets fal.ai's
  `fal-ai/flux-pro/v1.1-ultra` endpoint.
- New env var `IMAGE_PROVIDER_ROUTING` (default off). When set to a
  truthy value (`1`/`true`/`yes`), `ImageAgent` overrides `self.provider`
  on dispatch: high-tier calls (`4K`, `4KPortrait`, `Map`) go to
  `gemini`; everything else goes to `flux`.
- New env var `FAL_KEY` (required when FLUX is dispatched). Module
  imports without it; the first dispatch raises `RuntimeError`.
- New env vars (defaults shown): `FLUX_IMAGE_MODEL=fal-ai/flux-pro/v1.1-ultra`,
  `FLUX_URL_BASE=https://fal.run`, `FLUX_TIMEOUT_S=120`,
  `FLUX_MAX_ATTEMPTS=3`, `FLUX_RETRY_SLEEP=1.0`.
- New `ImageAgent.fallback_provider` instance attribute (default `None`).
- New `ImageAgent.generate(..., fallback_provider, route)` kwargs.
  `fallback_provider` defaults to a sentinel; pass `None` to disable
  fallback for the call, a provider string to override the instance
  default. `route=False` bypasses the routing layer for that call.
- Same new kwargs on `ImageAgent.upscale()`.
- New unconditional job_meta keys written by `generate`/`upscale`:
  `effective_provider`, `cost_estimate_usd`, and (on fallback)
  `provider_fallback_used`, `fallback_succeeded`.
- **Fix:** the existing hybrid-upscale gate (`IMAGE_HYBRID_UPSCALE=1`)
  now checks the *effective* (routed) provider instead of `self.provider`.
  Calls that route from gemini to flux no longer double-process through
  the local upscaler.
- **Behavior change (affects callers regardless of routing):**
  `GeminiAIModel._get_image_config` aspect-ratio table was rebalanced.
  The cheap-default tier maps to `1K` (smallest Gemini-accepted size);
  4K-tier callers are clamped to `2K` against the current default model
  (`gemini-3.1-flash-image-preview`) which rejects `4K`. The original
  cycle (PR #19/#23) targeted `0.5K`/`4K` but those are NOT valid
  values for the Gemini API — issues #29/#30 corrected the table in
  PR #31 (this section reflects the post-correction shipping values):
  - `Portrait` → `(3:4, 2K)` is now `(3:4, 1K)`
  - Default fallback for unknown aspect_ratio: `(1:1, 1K)` is now
    `(3:4, 1K)`
  - `Landscape` continues to map to `(16:9, 1K)`
  - `2K`/`2KPortrait` continue to map to `2K`
  - `4K`/`Map`/`4KPortrait` are silently clamped to `2K` (the model
    rejects `4K`). A `[GEMINI-IMAGE-CLAMP]` breadcrumb is emitted to
    the log so the downgrade is visible to operators. Set
    `GEMINI_IMAGE_MODEL` to a 4K-capable variant to lift the clamp.
  - Bare ratio inputs (`1:1`/`3:4`/`4:3`/`9:16`/`16:9`) inherit the
    `1K` default.

  This matches the new caller contract: the bare `Portrait`/`Landscape`
  tokens are the cheap default, and callers wanting 2K must opt in
  explicitly via `2K`/`2KPortrait` (or use the new `quality="high"`
  dial which remaps `Portrait → 4KPortrait`). Note that the `quality`
  dial's `4KPortrait` output is now clamped to `2K` against
  `flash-image-preview`.

**Migration.**

For routing (the FLUX dispatch layer): no source change required for
existing consumers. With `IMAGE_PROVIDER_ROUTING` unset, dispatch
behavior is identical to pre-change.

For the aspect-ratio resolution remap: consumers that pass bare
`Portrait` to `ImageAgent.generate()` and expected 2K-resolution output
must now pass `2KPortrait` explicitly. The visible symptom of an
un-migrated caller is smaller image files at the same prompt. Callers
on `4K`/`Map`/`4KPortrait` get 2K against `flash-image-preview` and
should monitor for `[GEMINI-IMAGE-CLAMP]` log entries if 4K is
required (then either swap the model via `GEMINI_IMAGE_MODEL` or
re-route the high-res path through a 4K-capable provider).

To opt in:
1. `export FAL_KEY=<your fal.ai key>` in the deployment env.
2. Run `python scripts/image_provider_eval.py --prompts
   scripts/_eval_prompts.json --providers gemini,flux,local --out
   eval-YYYY-MM-DD/` and review `index.html` for creative-quality parity.
3. `export IMAGE_PROVIDER_ROUTING=1`.

Roll back by `unset IMAGE_PROVIDER_ROUTING`. Instant; no data migration.

**Cost-estimate caveat.**

`cost_estimate_usd` job_meta is from a static table —
useful for trend/comparison but **not audit-grade**. Replacing it with
parsed billing data is a necessary follow-up
(spec: `docs/superpowers/specs/2026-06-02-image-gen-cost-design.md`).

### `AutoTask.exc_info` now reads current job state, not sticky history (Issue #14)

**What changed.** `AutoTask.exc_info` previously delegated to `Job.exc_info` (rq attribute). It now delegates to `Job.latest_result().exc_string`. Return contract `str | None` is unchanged, but the underlying semantics shifted from rq's deprecated "last seen exception" attribute to the modern "current Result's exc_string" accessor.

**Why.** rq 2.x deprecates `Job.exc_info` (a future rq major will remove it). PR #18 migrates ahead of the removal, matching PR #7's earlier `Job.result` → `Job.return_value()` shape. Same pattern, sibling attribute.

**Behavior change scope.** For most consumers the new behavior is identical — a job that failed (and was not retried successfully) still surfaces its formatted traceback via `task.exc_info`, and a job that never failed still returns `None`. The observable difference is for **retried jobs**: pre-PR-#18, `Job.exc_info` remained populated with the most recent exception string even after a successful retry, so `task.exc_info` was effectively a "this job has ever failed" sentinel. Post-PR-#18, `task.exc_info` reflects the *current* state — for a job that failed and then succeeded on retry, it returns `None`.

If your code uses `task.exc_info` as a "did this job ever fail at any point" check, switch to inspecting the full result history (or persist your own failure flag at enqueue time). For the more common case ("is this job currently in a failed terminal state"), the new behavior is what you wanted anyway.

**Migration.**

```python
# Before — implicitly relied on rq's sticky-attribute semantics
if task.exc_info:
    log_error_once(task.exc_info)

# After — explicit current-state check, unchanged for failed/finished jobs
if task.status == "failed" and task.exc_info:
    log_error_once(task.exc_info)
```

No symbol renames; no required code change for the common-case usage.

### `generate_json` now raises typed exceptions on failure (Issue #124)

**What changed.** `OpenAIClient.generate_json`, `LocalAIModel.generate_json`,
and `GeminiAIModel.generate_json` previously returned an empty dict `{}` on
empty / unparseable responses. They now raise typed exceptions from a new
module, `autonomous.ai.exceptions`:

| Mode | Exception | When |
|------|-----------|------|
| Empty body, no candidates, missing keys | `GenerateJSONEmptyResponseError` | Server returned 200 with empty content, Gemini returned no candidates, Ollama response missing `message.content`. Often transient — retry can help. |
| Non-JSON / wrong-shape output | `GenerateJSONParseError` | Model returned prose, called a non-matching tool, or produced JSON that `clean_json_response()` still couldn't parse. The first ~500 chars of the raw response is on `.raw` for diagnostics. Retry with the same prompt usually won't help. |
| Any of the above | `GenerateJSONError` | Base class. Catch this to treat all failure modes uniformly. |

`MockAIModel.generate_json` is unchanged — it still returns a dict (possibly
empty) by design, since it's the offline testing escape hatch and has no
failure mode to translate.

**Why.** The silent `{}` return collapsed three distinct failure modes into one
shape — callers couldn't tell whether the model produced no output (retry
unlikely to help), the transport blipped (retry likely to help), or the
model returned prose (prompt change needed). Storyteller's consumer-side
workaround at `lore_generator.py:164` papered over the symptom by checking
`if not result.get('responses')`, but the underlying ambiguity stayed.
Surfaced by StoryTeller#675 on 2026-05-25 — a prod outage where the chat
endpoint returned an empty/truncated 200 during the same window that the
embedding endpoint was emitting `[HPC-UNREACHABLE]` events.

**Behavior change scope.** `LocalAIModel.generate_json` previously swallowed
**transport** failures too (the `retry(..., default={})` shape ate
`requests.RequestException` after 3 attempts). Those now propagate as the
underlying `requests` exception, matching `OpenAIClient`'s long-standing
behavior of raising `HPCUnreachableError` (defined in
`autonomous.ai.models.openai_compat`) on transport failure. If you
were relying on `generate_json` to mask network failures with `{}`, wrap
the call in your own try/except.

**`JSONAgent.generate` is the entry point most consumers hit.** It
delegates to the underlying provider's `generate_json` without an outer
try/except (`src/autonomous/ai/jsonagent.py:28`), so the new typed
exceptions propagate raw through `JSONAgent` to the caller. Note also
that `JSONAgent.generate` raises `ValueError` for shape-not-dict
results (line 29-35) — that's distinct from the new `RuntimeError`-based
hierarchy. Downstream code catching only `ValueError` to mean "any AI
failure" will start missing the new failure classes; switch to
`except (ValueError, GenerateJSONError)` or refactor to branch on the
specific subclass.

**Migration.**

```python
# Before
result = agent.generate_json("...")
if not result or not result.get("responses"):
    handle_failure()
else:
    use(result)

# After (mode-aware)
from autonomous.ai.exceptions import (
    GenerateJSONError,
    GenerateJSONEmptyResponseError,
    GenerateJSONParseError,
)

try:
    result = agent.generate_json("...")
except GenerateJSONEmptyResponseError:
    # transient — retry or fall back
    handle_transient_failure()
except GenerateJSONParseError as exc:
    # deterministic — log exc.raw, change prompt
    handle_parse_failure(exc.raw)
use(result)

# Or, if you want uniform handling:
try:
    result = agent.generate_json("...")
except GenerateJSONError:
    handle_failure()
else:
    use(result)
```

Storyteller's `lore_generator.py:164` defensive check (`if not result or not
result.get('responses')`) will still work — the new exception just escapes
past it instead of being caught by the `if`. Migration to typed `except` is
recommended but not required at the call site to avoid breakage.

### autonomous.db fork — dead surface removal (Item 23)

**What changed.** ~1800 LOC of unreferenced mongoengine carry-over was
deleted from `src/autonomous/db/`. Nothing in `autonomous.model.*`
imports these names and no tests covered them, but a subclass reaching
directly into `autonomous.db.fields` (for example, a custom `AutoModel`
that declared `from autonomous.db import URLField`) will now fail at
import. Substitutes below.

**Removed field classes.**

| Removed | Replacement |
|---------|-------------|
| `URLField` | `StringField` + your own regex / validator |
| `LongField` | `IntField` (Python 3's `int` is already 64-bit) |
| `DecimalField`, `Decimal128Field` | `FloatField` for inexact; store as `StringField` if you need exact precision |
| `ComplexDateTimeField` | `DateTimeField` (Mongo's BSON datetime has millisecond precision; store a separate microsecond field if you need more) |
| `BinaryField` | `StringField` with your own `bytes.hex()` / `bytes.fromhex()` round-trip, or hold the bytes outside Mongo in `LocalStorage` |
| `UUIDField` | `StringField` holding `str(uuid.uuid4())` |
| `SortedListField` | `ListField` — sort in Python on access |
| `MapField` | `DictField` — it doesn't enforce a homogeneous value type, but first-party code never depended on that |
| `GenericEmbeddedDocumentField` | `EmbeddedDocumentField` pinned to the concrete class |
| `SequenceField` | `ObjectIdField` (the default primary key) |
| `CachedReferenceField` | `ReferenceField` |
| `LazyReferenceField`, `GenericLazyReferenceField` | `ReferenceField` / `GenericReferenceField` (always eagerly dereferenced via `ReferenceAttr`) |
| `GeoPointField`, `PointField`, `LineStringField`, `PolygonField`, `MultiPointField`, `MultiLineStringField`, `MultiPolygonField`, `GeoJsonBaseField` | no replacement — drop geo queries or add geo support back on the caller side |

Also removed:

- `autonomous.db.base.LazyReference` — the proxy returned by the lazy
  reference fields.
- `autonomous.db.document.MapReduceDocument` — MongoDB's mapReduce
  command is deprecated. Use `.objects.aggregate(pipeline)` instead.
- `QuerySet.map_reduce()`, `QuerySet.item_frequencies()` — both were
  server-side-JS paths (the `mapReduce` and `eval` commands). The
  `eval` command was removed in Mongo 4.2; `mapReduce` is deprecated
  in 5.0. Replace with an aggregation pipeline.
- Geo query operators: `within_*`, `near`, `near_sphere`, `geo_*`,
  `max_distance`, `min_distance`. The `_geo_index` / `_geo_indices`
  index-generation hooks are gone too; indexes now come from explicit
  `meta = {"indexes": [...]}` plus `_unique_with_indexes`.

**Deferred.** `DynamicDocument` / `DynamicEmbeddedDocument` /
`EmbeddedDocument` (+ their field descriptors and the related
datastructures) stay in the tree for now — removing them cleanly
requires a targeted pass on `base/document.py` and the metaclass. Do
not add new callers; they'll disappear in a follow-up.

**Why.** The fork was vendored from mongoengine, grew with the project,
and never had unused surface pruned. Every removed class was either
zero-consumed, shadowed by a simpler alternative, or wired to a
deprecated MongoDB command. Narrower public surface means faster
imports, fewer code paths for bugs to hide in, and a shorter mental
map for new contributors.

**Migration.**

- Grep your codebase for each name in the table. If you used one, pick
  the listed replacement (most are one-line substitutions).
- If you constructed any geo operator via `.filter(field__near=...)`
  etc., rewrite the query to use an aggregation stage — or restore
  `GeoJsonBaseField` + its fields out-of-tree if you need them.
- `QuerySet.map_reduce()` / `QuerySet.item_frequencies()` callers
  should switch to `AutoModel.objects.aggregate(...)`. See the Mongo
  aggregation docs for equivalents of the emit/reduce pattern.
- Fork-level details, including the "what's still deferred" list,
  live in `src/autonomous/db/DIVERGENCE.md`.

### `AutoModel.where()` — chainable query API (Item 20)

**What changed.** New classmethod ``AutoModel.where(**kwargs)`` returns
the underlying mongoengine ``QuerySet`` for chaining. Uses the same
``str -> __icontains`` convenience mapping as ``search`` but does not
materialize a list, so callers can keep composing:

```python
# Top-ten latest "hello"-ish posts
posts = Post.where(title="hello").order_by("-created").limit(10)

# First match of an exact lookup
author = Post.where(author_id=pk).first()

# Count without fetching rows
n = Post.where(published=True).count()

# Mix convenience and raw operators
Post.where(name="alice", views__gt=1000, tags__in=["python"])
```

Rules for kwargs:
- A ``str`` value with a plain field name (no ``__`` suffix) becomes
  ``<field>__icontains=<value>`` — case-insensitive substring match.
- Anything else (including keys that already contain ``__``) passes
  straight through to mongoengine.

**Why.** ``AutoModel.search`` returns a ``list``, which dead-ends
chaining. Consumers who discovered ``Model.objects.filter(...)`` could
chain, but that's undocumented and requires knowing mongoengine.
``.where()`` makes chaining discoverable with the same ergonomic
defaults as ``search``.

**Migration.** Additive. ``search`` still returns a list for
backward compatibility; prefer ``where`` for new code. There is no
deprecation warning — ``search`` is useful when you know you want the
list and don't care about chaining.

### autonomous.db fork cleanup (Item 22)

**What changed.** Focused pass over the vendored-then-forked
mongoengine tree at `src/autonomous/db/`. Not a re-sync with upstream;
concrete wins only.

- Narrowed every broad `except Exception` in first-party-ish code to
  the concrete errors each site actually expects (15 sites):
  - `base/fields.py` ObjectIdField to_python / to_mongo / validate,
    change-detection comparison (tz-naive vs tz-aware TypeError only).
  - `common.py` `_import_class` — catches `(ImportError, AttributeError,
    ValueError)`; re-raises as `ImportError` with `from e`.
  - `connection.py` `_create_connection` — catches
    `(pymongo.errors.PyMongoError, ValueError, TypeError)`.
  - `fields.py` BinaryField decode, ComplexDateTimeField parse, GridFS
    get/read/delete, ImageField validate — narrowed per site.
  - `document.py` DBRef key cast — catches `(TypeError, ValueError)`;
    re-raises as `TypeError`.
  - `queryset/base.py` sort translation, `queryset/transform.py` field
    lookup — catch `(LookupError, AttributeError)`.
- Removed 15 `# log(...)` debug stubs from `db/fields.py`,
  `db/base/fields.py`, `db/base/document.py`, `db/base/datastructures.py`.
- Dropped an unused `# EmbeddedDocumentList` import comment and a stale
  `# from autonomous.db.common import _import_class` comment.
- Added `src/autonomous/db/DIVERGENCE.md` documenting why the fork
  exists, every behavior delta vs upstream mongoengine that users rely
  on, and the rule for adding future divergence.

**Why.** The fork is maintained independently of upstream (per the
project owner) and had accumulated broad catches, dead comments, and no
written record of what the fork's guarantees are. Narrowing the
catches preserves tracebacks for unexpected errors. DIVERGENCE.md makes
the fork survivable across maintainers.

**Migration.**

- If you caught exotic errors (`MemoryError`, `KeyboardInterrupt`,
  `AssertionError`) leaking from within these call sites because the
  library swallowed them, those now propagate. Catch at your call site.
- Error subtypes within the expected categories still behave the same —
  an `InvalidId` still ends up as a `ValidationError` via
  `ObjectIdField.validate`, etc.

**Explicitly deferred** (audit suggested, not done here): type
annotations on the `Document` / `QuerySet` / `Field` public surface
(item #6 in the audit), `DocumentMetaclass` simplification (#11), and
GridFS handle-leak audit (#14). All three risk destabilizing
mongoengine's metaclass magic and deserve their own focused passes.

### Unit vs integration test split (Item 21)

**What changed.**

- ``pytest`` with no args now discovers only the hermetic suite under
  ``tests/unit/`` — no Mongo / Redis / AI services required.
- Previously-unit tests that actually needed the full service stack
  (``test_unit_ai.py``, ``test_unit_auth.py``, ``test_unit_automodel.py``,
  ``test_unit_storage.py``, ``test_unit_tasks.py``) moved to
  ``tests/integration/`` and were renamed to ``test_int_*.py``.
- ``tests/integration/conftest.py`` auto-applies the
  ``@pytest.mark.integration`` marker so ``pytest -m integration`` works.
- The marker is registered in ``pyproject.toml`` so pytest no longer
  warns about unknown markers.
- ``tests/docker-compose.yml`` was added with Mongo + Redis services
  matching the integration-test env vars. ``tests/.testenv`` ships the
  matching env defaults so ``pytest`` picks them up.
- ``Makefile`` targets:
  - ``make test`` — hermetic unit tests (fast, no services needed)
  - ``make test-int`` — integration tests (spins up compose stack first)
  - ``make test-all`` / ``make tests`` — both
  - ``make inittests`` — bring up the compose stack
  - ``make cleantests`` — tear it down

**Why.** The unit directory had grown to contain tests that required a
live Mongo + Redis, forcing every local ``pytest`` invocation to bring
up Docker or fail. The split makes the cheap tests run in under 3
seconds on a bare laptop and isolates the integration stack to the one
target that needs it.

**Migration.**

- If your CI invoked ``pytest`` and assumed it ran everything, switch
  to ``make test-all`` or ``pytest tests/unit tests/integration``.
- If you relied on a hand-rolled compose file at ``tests/docker-compose.yml``,
  the new version expects env vars matching ``tests/.testenv``; diff and
  merge.
- Test files moved to ``tests/integration/`` were renamed from
  ``test_unit_*.py`` to ``test_int_*.py``. Import paths are unchanged;
  CI patterns that grep for ``test_unit_`` may need updating.

### Retry helper extracted from local_model.py (Item 17)

**What changed.** New module ``autonomous.ai.retry`` exposes a
single ``retry(func, *, max_attempts, sleep_seconds, catch, on_retry,
default)`` helper that centralizes the "try-N-times-with-backoff-and-
between-attempt-side-effects" pattern previously inlined inside
``LocalAIModel.generate_json``.

The hook signature ``on_retry(attempt, exc)`` lets the caller plug in
side effects that the AI adapter needs between attempts — for example
``flush_memory`` after an empty Ollama response — without baking them
into the retry helper.

``LocalAIModel.generate_json`` is now ~30 lines shorter; the request
work and the recovery hook live in two clearly-named closures, and the
retry plumbing is one ``retry(...)`` call.

**Why.** The retry logic was tangled with payload construction and
logging. The next retry-style adapter (Gemini text, audio, image
generation) was on track to copy-paste the same loop with subtle
differences. Pulling it out keeps callers focused on what's being
retried, not how.

**Migration.** No behavioral changes for callers of ``generate_json``:

- Same number of attempts (3).
- Same sleep between attempts (``self._retry_sleep``).
- Same catch tuple (``RequestException``, ``JSONDecodeError``,
  ``ValueError``, ``KeyError``).
- Same default on total failure (``{}``).
- Same ``flush_memory`` side effect on empty-response retries.

If you want to use the helper in your own code:

```python
from autonomous.ai.retry import retry

result = retry(
    do_thing,
    max_attempts=3,
    sleep_seconds=1.0,
    catch=(MyError,),
    on_retry=lambda attempt, exc: log(f"retry {attempt}: {exc}"),
    default=None,        # omit to re-raise on exhaustion
)
```

### `Response.body` accepts iterables for streaming (Item 16)

**What changed.** ``autonomous.web.response.Response`` now accepts any
iterable of ``bytes`` / ``str`` chunks as ``body``, in addition to the
existing ``bytes`` / ``str`` whole-payload form.

- A single ``bytes`` / ``str`` body is yielded as one chunk (legacy).
- A ``list``, ``tuple``, generator, or other iterable is consumed
  chunk-by-chunk; each ``str`` chunk is utf-8-encoded.
- File streaming idiom: ``Response(body=iter(lambda: fh.read(8192), b""))``.
- Empty ``b""`` body still yields one ``b""`` chunk so WSGI servers
  see a finite iterable.
- Both ``__iter__`` and the WSGI callable ``__call__(environ,
  start_response)`` route through the new ``iter_chunks()`` method, so
  any consumer that does ``list(response)`` or ``b"".join(response)``
  continues to work.

**Why.** The previous Response materialized the whole body in memory.
Serving a multi-GB file or proxying an upstream response forced the
entire payload through the heap. Iterables let the WSGI server flush
chunks incrementally — chunked transfer encoding kicks in
automatically when ``Content-Length`` is absent and the iterable yields
more than one chunk.

**Migration.**

- If you stored the WSGI body and asserted ``body == [b"..."]`` in a
  test, switch to ``list(body) == [b"..."]`` — ``__call__`` now returns
  a generator, not a list.
- If you constructed ``Response(body=...)`` with a generator before
  (the old code only iterated the body once and lost everything past
  the first ``yield``), it now works correctly.
- Generator bodies are single-pass — calling ``list(response)`` twice
  on the same response yields ``[]`` the second time. This matches
  WSGI semantics; previously the bug was masked by the materialization.

### `SignedCookieSession` gains optional expiry + issuer binding (Item 15)

**What changed.** ``SignedCookieSession`` now accepts two optional
keyword arguments and embeds matching claims in a reserved ``__meta__``
key inside the payload:

- ``max_age`` (seconds): producer attaches ``exp = iat + max_age``;
  consumer rejects tokens past ``exp``.
- ``issuer`` (str): producer attaches ``iss``; consumer rejects tokens
  with no matching ``iss``.

Both are independently optional and asymmetric:

- A consumer with **neither** set behaves exactly as before — backward
  compatible with cookies minted by older versions (no ``__meta__`` at
  all).
- A consumer with ``max_age`` set rejects tokens with no ``exp``
  (downgrade defense — an attacker can't strip the claim by re-signing
  with a leaked key on an old cookie).
- A consumer with ``issuer`` set rejects tokens missing or mismatching
  ``iss`` (cross-app token-reuse defense).
- A consumer that doesn't set ``issuer`` ignores any ``iss`` present
  (allows third-party verifiers).

The reserved payload key ``__meta__`` is stripped on load, so a caller
who happens to store ``session["__meta__"] = ...`` cannot clobber the
envelope or leak it back into their dict.

**Why.** The previous signed cookie was infinitely valid. If the
signing key ever leaked, every historical session was usable
indefinitely. Pinning expiry and issuer narrows the blast radius — you
can rotate the key, drop the issuer, or shorten ``max_age`` and old
cookies stop verifying.

**Migration.** Zero changes for existing apps. To opt in:

```python
session = SignedCookieSession.from_cookie(
    secret, request.cookies.get("session"),
    max_age=86400,        # 24h
    issuer="my-app",
)
```

Use the same ``max_age`` / ``issuer`` on the producer side
(``SignedCookieSession(secret, initial, max_age=..., issuer=...)``).
Skew older cookies that lack the metadata are rejected, so deploy
producer-side first, wait one cookie-lifetime, then enable on the
consumer side — or just let the brief gap log out users once.

### `auto_pre_init` hardened; falsy values preserved; opt-out added (Item 13)

**What changed.** ``AutoModel.auto_pre_init`` (the pre-init signal hook
that side-loads stored fields when you write ``Model(pk=x)``) is now:

- Defensive against missing / empty ``values`` kwargs.
- Defensive against malformed primary keys (``Model(pk="not-an-oid")``
  no longer raises ``InvalidId`` from inside ``__init__``).
- Defensive against ``OperationFailure`` / ``ConnectionFailure`` from
  Mongo — the merge is skipped and instantiation continues. The error
  is logged via ``log()``.
- **Bug-fix:** the merge condition changed from ``not values.get(k)``
  (which clobbered legitimate falsy values like ``0``, ``False``, ``""``,
  ``[]``) to ``k not in values``. The caller's explicit values are
  always honored.

**New class attribute:** ``auto_load_on_init: bool = True``. Set to
``False`` on a subclass that doesn't want a Mongo round trip per
``Model(pk=x)`` construction. The default keeps the existing
"reload-on-init" pattern intact.

**Why.** The old hook had three real bugs (silent clobber of falsy
values, raise on bad pk, raise on DB outage) and no opt-out. Combined
they made ``Model(pk=x, count=0)`` silently lose the explicit ``0``
overwrite, made bad input crash the constructor, and made every read
path hit Mongo even in batch jobs that already had the data.

**Migration.**

- If your code used to write ``Model(pk=x, name="")`` expecting the
  empty string to be ignored, you now get ``""``. If you wanted the
  stored value, drop the kwarg.
- ``Model("not-a-real-oid")`` now constructs a fresh instance (no
  side-load) instead of raising. ``Model.get(...)`` is still the right
  way to look up by pk if you want None on miss.
- High-throughput read paths can disable the side-load by setting
  ``auto_load_on_init = False`` on the subclass.

### `AutoTasks` opens Redis lazily; supports injection (Item 12)

**What changed.**

- ``AutoTasks()`` no longer opens a Redis socket in ``__init__``. The
  process-wide ``AutoTasks._process_connection`` is built lazily on the
  first method that needs it (``task``, ``get_task``, ``get_tasks``,
  ``kill``, etc.).
- The ``config`` class attribute (which froze env vars at class-definition
  time) is gone. Env vars are read fresh inside ``_build_connection`` —
  so changing ``REDIS_HOST`` between import and first call works.
- New constructor kwargs: ``AutoTasks(redis_client=...)`` injects an
  arbitrary client (great for tests, multi-cluster apps).
  ``AutoTasks(host=..., port=..., password=..., username=..., db=...)``
  builds a per-instance client without affecting the singleton.
- New ``AutoTasks.reset_connection()`` classmethod drops the singleton
  so it gets rebuilt on the next call. Test helper.
- ``self._connection`` is now a property that returns whichever
  connection is appropriate (instance > singleton > lazy build).

**Why.** The class-attribute ``config = {... os.environ.get(...) ...}``
ran at import. Tests had to either spin up Redis or monkeypatch the
class. Multi-tenant deployments couldn't change config without restart.

**Migration.**

- If you imported ``AutoTasks`` in a process that doesn't have Redis
  available (e.g. a CLI tool that only uses the ORM), zero changes —
  the import is now silent.
- If you read ``AutoTasks.config`` directly, that attribute is gone;
  use the env vars or the new constructor kwargs.
- If you assigned to ``AutoTasks._connection`` to inject a fake in
  tests, switch to ``AutoTasks(redis_client=fake)`` (or set
  ``AutoTasks._process_connection = fake`` if you really need
  process-wide override).
- Direct ``tasks._connection`` reads still work — the property returns
  the right thing.

### Public surface is now type-hinted (Item 11)

**What changed.** Added type annotations and ``from __future__ import
annotations`` to the project's user-facing classes:

- ``autonomous.model.automodel.AutoModel`` — ``get / random / all / find /
  search / save / delete / model_name / get_model / load_model``, plus a
  ``PrimaryKey`` alias and ``-> Self | None`` returns where appropriate.
- ``autonomous.storage.localstorage.LocalStorage`` — every public method,
  with a new ``AssetRef`` alias for the ``{"asset_id", "url"}`` dict.
- ``autonomous.storage.imagestorage.ImageStorage`` — every public method,
  including ``Iterator[str]`` for ``scan_storage``.
- ``autonomous.auth.autoauth.AutoAuth`` — ``__init__``, ``current_user``,
  ``authenticate``, ``handle_response``, ``auth_required``, plus the
  internal ``_touch_user`` / ``_refresh_session_user`` / ``_build_session``.

The ``autonomous.web`` module was already typed in earlier items.

A guard test (``tests/unit/test_unit_type_hints.py``) inspects each
public method via ``inspect.signature`` and fails CI if a future change
silently drops a return / argument annotation.

**Why.** Hints make IDE autocomplete useful, give mypy / pyright something
to chew on, and serve as machine-checkable documentation.

**Migration.** Zero code changes. ``from __future__ import annotations``
keeps everything as strings at runtime, so even runtime ``isinstance``
checks against the annotation values are unaffected. Subclasses that
override these methods are not forced to add annotations.

### ImageStorage cache: mtime invalidation, atomic write, safe failure (Item 10)

**What changed.**

- ``ImageStorage.get_url(asset_id, size=...)`` now compares the cached
  variant's mtime against the original. If the original is newer (e.g.
  after ``rotate``/``flip``, or after a manual replacement), the variant
  is regenerated automatically.
- The variant write goes through a sibling ``.tmp`` + ``os.replace`` so
  a half-written file can't be served if two requests race.
- After regeneration the variant's mtime is pinned to the original's, so
  the freshness comparison stays stable across sub-second writes and
  clocks that don't tick.
- ``full_url=True`` now works for ``size="orig"`` and for already-cached
  variants, not just the post-resize branch.
- A failed resize logs and returns ``None``. **It no longer calls
  ``self.remove(asset_id)``**, which previously wiped the entire asset
  on a single bad call.
- ``get_url("")`` still returns ``""``; ``get_url(None)`` and
  ``get_url("../etc/passwd")`` return ``None`` (item 7's traversal
  hardening was already in place).

**Why.** The old code never invalidated, so any in-place edit of the
original left stale variants forever (or until ``clear_cached`` was
called manually). The destructive failure mode was a footgun — one
corrupted source took down the whole asset.

**Migration.**

- If you relied on ``get_url`` returning a relative URL even when
  ``APP_BASE_URL`` was set and ``full_url=True``, that was a bug; the
  full URL is now returned consistently.
- If you relied on ``get_url`` deleting the asset on resize failure (an
  odd thing to rely on), call ``storage.remove(asset_id)`` yourself.
- Manual variant clearing via ``clear_cached`` still works but is no
  longer required after ``rotate`` / ``flip`` — mtime invalidation
  handles it.

### Optional dependencies moved to extras (Item 9)

**What changed.** ``requirements.txt`` shrank to just the deps that
``autonomous`` imports unconditionally (``python-dotenv``, ``pymongo``,
``blinker``, ``Authlib``, ``requests``). Everything else moved into named
extras configured under
``[tool.setuptools.dynamic.optional-dependencies]`` in ``pyproject.toml``:

| Extra | Adds | Used by |
|-------|------|---------|
| ``tasks`` | ``redis``, ``rq`` | ``autonomous.taskrunner.AutoTasks`` |
| ``images`` | ``pillow`` | ``autonomous.storage.ImageStorage`` |
| ``ai`` | ``google-genai``, ``pydub`` | ``autonomous.ai.models.gemini`` + audio |
| ``github`` | ``PyGithub``, ``pygit2`` | ``autonomous.apis.version_control.*`` |
| ``server`` | ``gunicorn`` | production WSGI server |
| ``all`` | (every other extra) | catch-all |

Each lives in its own ``requirements-<extra>.txt`` so it's still easy to
``pip install -r requirements-tasks.txt`` standalone.

Dropped from runtime entirely (no imports anywhere):
``setuptools`` (build-only), ``Flask``, ``jsmin``, ``ollama`` (the
client; the URL is hit via ``requests``), ``sentence-transformers``,
``dateparser``, ``python-slugify``.

**Why.** A 25-dep core dragged in a Postgres-sized install for users who
only wanted the ORM. Splitting into extras shrinks ``pip install
autonomous-app`` from ~1.5GB (sentence-transformers + torch + cuda
wheels) to a handful of MB; consumers opt into what they actually use.

**Migration.**

- If you used ``ImageStorage``, install ``autonomous-app[images]``.
- If you used ``AutoTasks``, install ``autonomous-app[tasks]``.
- If you used ``GeminiAIModel``, install ``autonomous-app[ai]``.
- If you used ``autonomous.apis.version_control.*``, install
  ``autonomous-app[github]``.
- Or: ``pip install autonomous-app[all]`` for the previous behaviour.
- Drop ``flask``, ``jsmin``, ``ollama``, ``sentence-transformers``,
  ``dateparser``, ``python-slugify`` from your own ``requirements.txt``
  if you don't import them yourself.

A new ``tests/unit/test_unit_packaging.py`` will fail CI if a future
change accidentally lists an unused dep in core, drops one of the extras
files, or forgets to register a new extra in ``pyproject.toml``.

### `auth_required` no longer writes on every request (Item 8)

**What changed.** The `@AutoAuth.auth_required()` decorator stopped
hammering the database and the session on every authenticated request:

- ``user.last_login`` is persisted at most once per
  ``cls.last_login_throttle_seconds`` (default ``60``). Subsequent
  requests within the window read the existing user but skip
  ``user.save()``.
- ``session["user"] = user.to_json()`` only runs if the rendered JSON
  differs from what's already in the session.
- New class attribute ``last_login_throttle_seconds`` controls the
  interval. Set it to ``0`` to restore the legacy "save on every
  request" behaviour.
- New helpers ``AutoAuth._touch_user(user)`` and
  ``AutoAuth._refresh_session_user(session, user)`` extracted for
  subclasses that need to override the policy.

**Why.** The old code did one Mongo write and one session write per
authed pageview. For a busy app that's hundreds of pointless writes per
second; in dev it floods the save signals. ``last_login`` doesn't need
second-level granularity.

**Migration.**

- If your app relies on ``last_login`` being current to the second, set
  ``AutoAuth.last_login_throttle_seconds = 0`` (or to a smaller window).
- If you observed side effects of ``user.save()`` firing on every
  request (cache invalidation, audit hooks), they now fire at most once
  per minute. Consider moving them to explicit triggers.
- If you store derived data in the session under ``"user"`` and rely on
  it being rewritten every request, push that data through a separate
  session key (or override ``_refresh_session_user``).

### Storage layers reject path traversal (Item 7)

**What changed.** ``LocalStorage`` and ``ImageStorage`` now sanitize every
user-supplied ``folder`` and ``asset_id`` before joining it under the
storage root.

- New helper ``_sanitize_relative(part)``: rejects absolute paths and any
  fragment whose normalized form contains a ``..`` segment. ``"a/../b"``
  collapses to ``"b"`` and is fine; ``"../etc"`` and ``"/etc/passwd"``
  raise ``ValueError``.
- New per-instance helper ``_safe_join(*parts)``: joins under the resolved
  ``base_path`` and asserts the resolved result is the base or a
  descendant. Anything else raises ``ValueError``.
- All public file-system entry points use ``_safe_join``:
  ``LocalStorage.save / get / get_path / search / move / remove``,
  ``ImageStorage.get_path / search``.

Read-side methods (``get``, ``remove``, ``search``) swallow the
``ValueError`` and return ``None`` / ``False`` / ``[]`` so a malformed
asset reference doesn't crash a request. Write-side methods (``save``,
``move``) raise so the caller sees the bad input.

**Why.** A user-supplied ``folder="../../etc"`` or
``asset_id="../../etc/passwd"`` previously concatenated straight onto the
storage root, letting an attacker (or a buggy upstream) read or
overwrite arbitrary files outside the storage tree.

**Migration.**

- If your app passed only safe, app-controlled folders, zero changes.
- If you ever passed user input as ``folder`` or ``asset_id``, callers
  that previously got back garbage now get ``ValueError`` (writes) or
  empty results (reads). Catch it at the boundary you accept user input.
- ``"...etc"`` and other names that merely *look* like ``..`` are still
  accepted — the check is on path *segments*, not prefix.

### OAuth state is now validated against the session (Items 6 & 19)

**What changed.** ``AutoAuth.authenticate()`` rotates ``self.state`` on
every call and stores the issued nonce in the active session under
``state_session_key`` (default ``"oauth_state"``).
``AutoAuth.handle_response()`` reads it back, refuses callbacks with no
stored state, and clears the session entry whether the exchange succeeded
or failed (so a replayed callback can't be re-validated).

If the caller passes ``state=`` explicitly, that value still wins —
backward compatible with apps that already round-tripped state through
their own session.

**Why.** Previously the issued state was generated once in ``__init__``,
overwritten on every ``authenticate()``, and never enforced on the
callback. An attacker could send a victim a crafted callback URL and the
library would happily exchange the code for a token under the victim's
session — classic OAuth login CSRF.

**Migration.**

- If you bound a session store via ``autonomous.web.bind_session(...)`` (or
  the Flask snippet in the README), zero code changes — state moves
  through that store automatically.
- If you stored the state yourself between ``authenticate()`` and
  ``handle_response()``, keep doing it; pass ``state=`` to
  ``handle_response`` and the session lookup is bypassed.
- If you do not bind a session, ``handle_response()`` raises
  ``MismatchingStateError``. Bind a session at startup, or store and pass
  the state explicitly.
- Subclasses with multiple providers in one app should override
  ``state_session_key`` to keep providers' state from colliding.

### Narrowed exception catches + bare `raise` (Items 5 & 14)

**What changed.** Broad `except Exception` blocks in first-party code were
tightened to the specific errors each site actually expects:

| File | Site | New catch |
|------|------|-----------|
| `model/automodel.py` `AutoModel.get` | DB failure | `pymongo.errors.OperationFailure`, `pymongo.errors.ConnectionFailure` (bare `raise`, no more `raise e`) |
| `db/db_sync.py` `get_vector` | embedding HTTP | `requests.RequestException`, `ValueError`, `KeyError` |
| `db/db_sync.py` oid coercion | bson parse | `bson.errors.InvalidId`, `TypeError` |
| `db/db_sync.py` `request_indexing` | enqueue | `redis.RedisError`, `ConnectionError` |
| `taskrunner/autotasks.py` `get_task` | fetch | `rq.exceptions.NoSuchJobError`, `redis.RedisError` |
| `ai/models/local_model.py` `flush_memory`, `generate_text`, `generate_json` retry, `summarize_text`, `generate_transcription`, `generate_audio`, `generate_image` | HTTP / JSON / audio | combinations of `requests.RequestException`, `json.JSONDecodeError`, `ValueError`, `OSError`, `KeyError` |
| `ai/models/gemini.py` 5 sites | Google genai | `google.genai.errors.APIError` + relevant parse errors; stopped `raise e`ing |

Rule applied: catch only expected failures; re-raise with a bare `raise`
(preserves the original traceback); let unexpected errors (`AttributeError`
from typos, `MemoryError`, `KeyboardInterrupt`) propagate.

**Why.** Broad catches hid bugs and destroyed tracebacks via `raise e`. The
retry loop in `generate_json` also slept 30 s on any error — including
transient programming errors — masking regressions during development.

**Migration.** If your code deliberately raised unusual types from callbacks
inside `AutoModel.get`, `LocalAIModel.generate_*`, or `GeminiAIModel.generate_*`
and relied on the library silently logging them, those now propagate. Catch
them at your call site instead.

### Logger is lazy + proxied; file I/O is optional (Item 4)

**What changed.**

- Importing `autonomous.logger` (or `from autonomous import log`) no longer
  creates a `logs/` directory or touches the filesystem. Path setup is
  deferred to the first actual `log(...)` call.
- Constructing a `Logger()` likewise has no side effects.
- The module-level `log` is now a proxy (`_DefaultLoggerProxy`) that lazily
  instantiates the real `Logger` on first use. All attribute access and calls
  delegate to the underlying instance, so ``from autonomous import log`` and
  ``log.enable(False)`` / ``log.set_level("DEBUG")`` continue to work.
- New factory `autonomous.get_logger(name="gunicorn.error")` returns an
  independent `Logger` for tests and subsystems that want isolation.
- New env var `LOG_TO_FILES=0` disables the archive/current-run file writes
  without having to subclass. Per-call `logger.enable_file_logging(False)`
  does the same at runtime.
- File write errors (read-only disk, permission denied) no longer crash the
  caller — the handler swallows `OSError`.

**Why.** The old code ran `os.makedirs("logs")` at import and opened two
files on every call, which broke test isolation, tripped up read-only
filesystems, and made importing the ORM / auth layers depend on CWD being
writable.

**Migration.** Zero code changes required for normal use. A few edge cases:

- If you relied on `logs/` existing simply because you imported the package,
  call `log("startup")` once or `os.makedirs("logs", exist_ok=True)`
  yourself.
- If you patched `autonomous.logger.log` in tests (replacing it with a mock),
  that still works because the proxy is at the same attribute name.
- If you want a per-test or per-subsystem logger that you can disable
  independently, use `from autonomous import get_logger` rather than sharing
  the default.

### Mutable default args replaced with None sentinel (Item 3)

**What changed.** The AI-model entry points no longer use mutable literals
(`context={}`, `filters=[]`) as default values. Defaults are now `None`, and
each function normalizes to a fresh empty container internally.

Affected signatures:

- `LocalAIModel.generate_json(..., context=None, ...)`
- `LocalAIModel.generate_text(..., context=None, ...)`
- `MockAIModel.generate_json(..., context=None)`
- `MockAIModel.generate_text(..., context=None)`
- `GeminiAIModel.generate_json(..., context=None)`
- `GeminiAIModel.generate_text(..., context=None)`
- `GeminiAIModel.list_voices(filters=None)`

**Why.** A shared mutable default dict persists across calls. If one caller
mutated `context`, every subsequent caller would observe the mutation —
intermittent, rare, hard-to-debug failures.

**Migration.** Zero code changes needed. Passing `context={}` / `filters=[]`
still works identically; only the default changed.

### Storage paths come from env vars (Item 2)

**What changed.** `LocalStorage(path=...)` and `ImageStorage(path=...)` no
longer have hardcoded string defaults in the signature. If `path` is omitted
they consult env vars:

| Class | Env var | Fallback |
|------|---------|----------|
| `LocalStorage` | `STORAGE_PATH` | `static` |
| `ImageStorage` | `STORAGE_IMAGE_PATH` | `<STORAGE_PATH>/images` |

`LocalStorage.base_url` also stopped rendering `None/...` when
`APP_BASE_URL` is unset; it now falls back to a site-relative `"/<path>"`.

**Why.** Hardcoding `"static"` tied every deployment to the same on-disk
layout. The env-var indirection lets you point at a mounted volume, a
per-environment bucket mount, or a test tmpdir without subclassing.

**Migration.** If you always passed `path=` explicitly, nothing changes. If
you relied on the string default `"static"` / `"static/images"`, nothing
changes either — that's still the fallback. If you set `APP_BASE_URL=""` and
depended on the old `"None/..."` URL shape, update your consumers to handle
`"/..."`.

### Flask is no longer a dependency (already landed)

- `flask` is gone from `requirements.txt`. If you relied on it being pulled in
  transitively by `autonomous`, add it to your own `requirements.txt`.
- `autonomous.auth.autoauth` no longer imports from `flask`. Consumers wire
  their session store and login URL explicitly:

  ```python
  from autonomous.auth import AutoAuth
  from autonomous.web import bind_session
  from flask import session as flask_session, url_for  # still works

  AutoAuth.login_url = "/auth/login"  # or url_for("auth.login") per-request

  @app.before_request
  def _bind():
      bind_session(flask_session)
  ```

- Decorated views (`@AutoAuth.auth_required()`) now return a WSGI-compatible
  `autonomous.web.Response` on redirect. Flask views can return it unchanged;
  other frameworks can call it as a WSGI app.

### Deferred MongoDB connection (Item 1)

**What changed.** `autonomous.model.automodel` no longer calls `connect(...)`
at import time. The connection is opened lazily on the first ORM operation
(`get`, `all`, `find`, `search`, `random`, `save`, `delete`), so importing the
ORM no longer triggers network I/O or fails when env vars are unset.

**Why.** Import-time side effects break tests, break alt-DB configs, and make
`autonomous` unusable in processes that don't need MongoDB (CLI scripts, docs
builds, linters).

**Migration.** Zero changes required if you set `DB_HOST`, `DB_PORT`,
`DB_USERNAME`, `DB_PASSWORD`, `DB_DB` before the first ORM call — the lazy
path picks them up the same way the old import-time code did.

Recommended: call `autonomous.init()` (or `autonomous.db.connect(...)`
directly) once at app startup for clearer failure modes and to override
settings programmatically:

```python
import autonomous
autonomous.init()  # uses env vars
# or
autonomous.init(host="mongo.prod", db="app", username="u", password="p")
```

`autonomous.db.db_sync` likewise replaced its module-level Redis/Mongo clients
with internal lazy getters. If you imported `from autonomous.db.db_sync import
r`, `mongo`, `db`, `MONGO_URI`, `MEDIA_URL`, `REDIS_HOST`, or `REDIS_PORT`,
those names are no longer exported — call the public functions (`get_vector`,
`request_indexing`, `process_single_object_sync`) instead.
