"""Tests for the iter/2026-05-17-pr107-followups batch (PR #111).

Independent test-agent coverage for the 2-issue hygiene completion
addressing /review-pr findings on PR #107:

- **#108** — Sweep the 6 issue-refs PR #107 missed: 4 in gemini.py
  (lines 151, 156, 200, 206) + 2 in openai_compat.py (lines 38-39).
  PR #111 also added two protective ``NOTE:`` markers at the
  gemini.py discriminator-phrase sites (responding to the
  brittleness sub-note in #108) so future hygiene passes don't
  silently break the precedence test by rewording either of the
  load-bearing signature phrases.
- **#109** — Restore the in-source WHY for the deliberate exclusion
  of ``ContentDecodingError`` from the openai_compat config-error
  carve-out (the negative-pin test enforces the FACT; #109 restores
  the in-source breadcrumb so future maintainers hitting the red
  test see the rationale without chasing git blame).

This file pins:

- **Extended ``#\\d+``-free coverage**: my prior cycle's pin
  covered the both-keys + value-shape error messages only. PR
  #111 cleaned the remaining 2 gemini error messages (list-entry
  + outer-fallback), so this iter extends the pin to all 4 error
  sites uniformly.
- **Protective ``NOTE:`` marker presence**: source-text pin that
  the protective load-bearing markers survive future hygiene
  passes. Without these markers, the recursion the dev called out
  (each hygiene pass uncovers what the last pass missed) could
  resume — and a reworded signature phrase silently breaks the
  precedence test.
- **ContentDecodingError WHY presence**: source-text pin that the
  in-source rationale for the exclusion survives a future cleanup.
  Pinned by substantive content (proximity of "ContentDecodingError"
  + "transient" + "retry") rather than literal string — survives
  rewording, catches deletion.

This is the 4th consecutive iter touching these surfaces. The
convergence is real (each iter smaller than the last) but the
test agent's role is to make the convergence durable — these
pins prevent the next hygiene pass from undoing this one.
"""

import io
import pathlib
import re

import pytest


# ===========================================================================
# #108 — extended #\d+-free coverage on all 4 gemini error messages
# ===========================================================================


class TestGeminiAllErrorMessagesIssueRefFree:
    """Pin that ALL FOUR live error messages in ``gemini._add_files``
    are now free of ``#\\d+`` issue refs.

    Prior cycle (PR #107) pinned 2 of 4 (both-keys + value-shape).
    PR #111 cleaned the remaining 2 (list-entry + outer-fallback).
    This iter extends the pin to all 4 sites so the next hygiene
    regression — accidental re-add of an issue ref at any of the
    four — is caught uniformly.
    """

    def _stub(self):
        from autonomous.ai.models.gemini import GeminiAIModel

        class _ClientFilesStub:
            @staticmethod
            def list():
                return []

        class _ClientStub:
            files = _ClientFilesStub()

        class _Stub:
            MAX_FILES = 0
            client = _ClientStub()

            def __init__(self):
                self.files = []
                self.file_refs = []

            def save(self):
                pass

        return GeminiAIModel, _Stub()

    _ISSUE_REF_RE = re.compile(r"#\d+")

    def test_list_entry_shape_error_no_issue_refs(self):
        # The "list entries must be {'name', 'file'} dicts" error.
        # Pre-#111: "... See #85." — was the original #108 finding.
        GeminiAIModel, stub = self._stub()
        with pytest.raises(TypeError) as exc:
            GeminiAIModel._add_files(stub, ["not-a-dict"])
        msg = str(exc.value)
        assert self._ISSUE_REF_RE.findall(msg) == [], (
            f"list-entry-shape error must be #\\d+-free per #108. "
            f"Got: {msg!r}"
        )

    def test_outer_fallback_error_no_issue_refs(self):
        # The "expects a list-of-dicts or {filename: fileobj} dict"
        # outer-fallback error. Triggered by passing a non-list,
        # non-dict (e.g. an int).
        # Pre-#111: "... See #85."
        GeminiAIModel, stub = self._stub()
        with pytest.raises(TypeError) as exc:
            GeminiAIModel._add_files(stub, 12345)
        msg = str(exc.value)
        assert self._ISSUE_REF_RE.findall(msg) == [], (
            f"outer-fallback error must be #\\d+-free per #108. "
            f"Got: {msg!r}"
        )


# ===========================================================================
# #108 sub-note — protective NOTE markers preserve discriminator phrases
# ===========================================================================


class TestGeminiDiscriminatorProtectionMarkers:
    """Pin that the protective ``NOTE:`` markers added by PR #111
    near the both-keys and value-shape error messages are present
    in source.

    Background: the precedence pin in
    ``test_unit_followup_iter_2026_05_17_pr94_pr96.py`` discriminates
    via two signature phrases — ``"with both 'name' and 'file' keys"``
    (both-keys error only) and ``"file-like object or bytes"``
    (value-shape error only). pr-test-analyzer flagged that if either
    phrase appears in the OTHER block (e.g. a future "wrap your
    file-like object in a list" rewording of the both-keys error),
    the discriminator silently degrades. PR #111 added ``NOTE:`` +
    ``load-bearing`` markers near both sites as a forward-warning
    to future hygiene editors.

    Pin the markers' substantive presence (not literal text) so
    they survive minor reformatting but a wholesale deletion is
    caught.
    """

    def test_gemini_source_has_load_bearing_markers(self):
        src = pathlib.Path(
            "src/autonomous/ai/models/gemini.py"
        ).read_text()
        # Both markers use the phrase "load-bearing" near the
        # discriminator phrases. Count: must be >= 2 (one per
        # discriminator-phrase site).
        count = len(re.findall(r"load-bearing", src))
        assert count >= 2, (
            f"gemini.py must contain at least 2 'load-bearing' "
            f"protective markers (one per discriminator-phrase "
            f"site) per PR #111's protective-marker addition. "
            f"Got: {count} occurrence(s). A future hygiene pass "
            f"that deletes these markers would re-open the door "
            f"to silently breaking the precedence-pinning test."
        )

    def test_gemini_source_has_test_cross_ref_in_markers(self):
        # The markers explicitly reference that the phrases are
        # used as test discriminators. Pin via PROXIMITY: each
        # "discriminator" mention must be within ~200 chars of a
        # "load-bearing" mention — proves the cross-ref is in the
        # marker block, not in an unrelated comment elsewhere.
        # Without proximity, a future unrelated comment mentioning
        # "discriminator" (e.g. in a different function) would mask
        # deletion of the marker cross-ref. Tightening per the
        # /review-pr pr-test-analyzer NIT.
        src = pathlib.Path(
            "src/autonomous/ai/models/gemini.py"
        ).read_text().lower()
        # Find every "load-bearing" index and check at least one
        # has "discriminator" within +/- 200 chars.
        lb_indices = [
            m.start() for m in re.finditer(r"load-bearing", src)
        ]
        assert lb_indices, (
            "no 'load-bearing' markers in source — covered by the "
            "test above, but the proximity check needs at least one"
        )
        near_count = 0
        for idx in lb_indices:
            window = src[max(0, idx - 200): idx + 200]
            if "discriminator" in window:
                near_count += 1
        assert near_count >= 1, (
            f"at least one 'load-bearing' marker must have "
            f"'discriminator' within +/- 200 chars (proves the "
            f"marker actually cross-references the test layer, "
            f"rather than 'discriminator' appearing unrelated "
            f"elsewhere in the file). Got {near_count} co-located "
            f"pairs out of {len(lb_indices)} load-bearing markers."
        )


# ===========================================================================
# #109 — ContentDecodingError WHY restored to source
# ===========================================================================


class TestContentDecodingErrorRationaleInSource:
    """Pin that the in-source WHY for ContentDecodingError's
    deliberate exclusion from the openai_compat carve-out is
    present (restored by PR #111 after PR #107 deleted it).

    The fact (exclusion) is enforced by the negative-pin test in
    ``test_unit_followup_iter_2026_05_16_pr88.py``. The WHY (the
    reason for the deliberate exclusion) is non-obvious — a
    maintainer "fixing" the carve-out by adding ContentDecodingError
    would hit the red test with no in-source breadcrumb. PR #109
    requested the WHY be restored in-source so the breadcrumb is
    co-located with the contract.

    Pin by substantive content (proximity of "ContentDecodingError"
    + "transient" + "retry") rather than literal-string match —
    survives rewording, catches deletion.
    """

    def test_openai_compat_source_explains_content_decoding_exclusion(self):
        src = pathlib.Path(
            "src/autonomous/ai/models/openai_compat.py"
        ).read_text()
        # Find a substring window of ~400 chars containing all 3
        # substantive markers. A real rationale comment will have
        # all three near each other; a coincidental mention of
        # "ContentDecodingError" elsewhere (e.g. an import or a
        # different context) won't.
        has_class = "ContentDecodingError" in src
        has_transient = "transient" in src.lower()
        has_retry_concept = (
            "retry" in src.lower() or "retried" in src.lower()
        )
        assert has_class, (
            "openai_compat.py source must mention "
            "'ContentDecodingError' (the rationale targets this "
            "class by name)"
        )
        assert has_transient, (
            "openai_compat.py source must explain that "
            "ContentDecodingError can be 'transient' (the "
            "load-bearing WHY for the deliberate exclusion)"
        )
        assert has_retry_concept, (
            "openai_compat.py source must mention the 'retry' "
            "path (the WHY only matters in contrast with what "
            "the deliberate-non-carve-out leads to — retry path)"
        )

        # Proximity check: all three terms within ~400 chars of
        # each other (rough heuristic for "they are in the same
        # comment block"). Avoids false positives from
        # "ContentDecodingError" appearing in a completely
        # different context that happens to be in the same file.
        idx_class = src.lower().find("contentdecodingerror")
        # Find the nearest "transient" and "retry" / "retried"
        window_start = max(0, idx_class - 400)
        window_end = min(len(src), idx_class + 400)
        window = src[window_start:window_end].lower()
        assert "transient" in window, (
            "'transient' must appear within ~400 chars of the "
            "ContentDecodingError mention. PR #109 restored the "
            "WHY as a single co-located comment block; if a "
            "future cleanup splits them, the breadcrumb is lost."
        )
        assert "retry" in window or "retried" in window, (
            "'retry' (or 'retried') must appear within ~400 chars "
            "of the ContentDecodingError mention — the WHY is "
            "'retry is the safer default for transient gzip "
            "corruption', so both halves of the contrast must "
            "be co-located."
        )
