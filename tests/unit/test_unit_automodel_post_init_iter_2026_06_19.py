"""Issue #151: pin ``AutoModel.auto_post_init`` ``last_updated`` stamp.

``auto_post_init`` stamps ``document.last_updated = datetime.now()`` on
every construction via ``signals.post_init.connect(_auto_post_init)``.

The four ``_auto_*`` signal delegators (``_auto_pre_init``,
``_auto_post_init``, ``_auto_pre_save``, ``_auto_post_save``) are
near-identical boilerplate and a likely target for a future "DRY-up"
refactor. Without a test pinning the construction-time stamp, such a
refactor could drop or reorder the post_init wiring — ``last_updated``
would silently stop updating, a data-freshness bug invisible until a
consumer notices stale timestamps.

This file pins:

1. ``AutoModel.auto_post_init`` writes a recent ``datetime`` to
   ``document.last_updated``.
2. ``AutoModel._auto_post_init`` (the signal delegator) routes the
   class hook through the ``sender``-supplied subclass so a subclass
   override of ``auto_post_init`` would be honored.
3. ``signals.post_init.connect(AutoModel._auto_post_init)`` is wired at
   module load — the most-likely failure mode of a DRY-up refactor is
   simply dropping the connect call.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock


class TestAutoPostInitStampsLastUpdated:
    def test_stamps_last_updated_with_recent_datetime(self):
        from autonomous.model.automodel import AutoModel

        doc = SimpleNamespace(last_updated=None)
        AutoModel.auto_post_init(MagicMock(), document=doc)

        assert isinstance(doc.last_updated, datetime)
        # Recency check — within the last few seconds keeps the test
        # robust against clock skew but tight enough to catch a hook
        # that's writing a stale/fixed datetime.
        assert (datetime.now() - doc.last_updated).total_seconds() < 5

    def test_stamp_advances_across_calls(self):
        """A second call writes a NEWER timestamp — guards against a
        memoization-style refactor that caches the first value."""
        import time

        from autonomous.model.automodel import AutoModel

        doc = SimpleNamespace(last_updated=None)
        AutoModel.auto_post_init(MagicMock(), document=doc)
        first = doc.last_updated

        # datetime.now() has microsecond resolution; a small sleep is
        # enough to guarantee strict-greater-than across calls without
        # racing the second->datetime boundary.
        time.sleep(0.001)
        AutoModel.auto_post_init(MagicMock(), document=doc)
        second = doc.last_updated

        assert second > first


class TestSignalDelegatorRoutesThroughSender:
    """``_auto_post_init`` delegates to ``sender.auto_post_init``. A
    DRY-up that bypasses the per-sender hook would skip subclass
    overrides — this pins the routing."""

    def test_delegator_calls_sender_auto_post_init(self):
        from autonomous.model.automodel import AutoModel

        doc = SimpleNamespace()
        sender = MagicMock()

        AutoModel._auto_post_init(sender, document=doc, extra="kwarg")

        # The delegator forwards sender + document positionally
        # (`sender.auto_post_init(sender, document, **kwargs)`), so the
        # assertion must match positional shape.
        sender.auto_post_init.assert_called_once_with(
            sender, doc, extra="kwarg"
        )

    def test_subclass_override_is_honored_through_delegator(self):
        """If a subclass overrides ``auto_post_init`` (e.g. to attach
        provenance to ``last_updated``), the delegator must route to
        the subclass's method, not ``AutoModel``'s."""

        class SubSender:
            calls = []

            @classmethod
            def auto_post_init(cls, sender, document, **kwargs):
                cls.calls.append((sender, document))

        from autonomous.model.automodel import AutoModel

        doc = SimpleNamespace()
        AutoModel._auto_post_init(SubSender, document=doc)

        assert SubSender.calls == [(SubSender, doc)]


class TestSignalsPostInitWiringAtModuleLoad:
    """The most likely failure of a DRY-up refactor is dropping the
    ``signals.post_init.connect(AutoModel._auto_post_init)`` call at
    module load. Without that, ``last_updated`` silently stops being
    stamped on construction. Pin the wiring directly."""

    @staticmethod
    def _wired_functions(signal):
        """Walk a blinker signal's receivers and return the underlying
        ``__func__`` of every live callable. blinker stores receivers
        as ``WeakMethod``s on bound methods; ``ref()`` returns a freshly-
        rebound method object that is NOT ``is``-equal to a subsequent
        attribute access on the class. Comparing ``__func__`` sidesteps
        the bound-method-rebinding identity trap."""
        out = []
        for ref in signal.receivers.values():
            cb = ref() if callable(ref) else ref
            if cb is None:
                continue
            out.append(getattr(cb, "__func__", cb))
        return out

    def test_auto_post_init_is_connected_to_signals_post_init(self):
        from autonomous.db import signals
        from autonomous.model.automodel import AutoModel

        wired_funcs = self._wired_functions(signals.post_init)
        assert AutoModel._auto_post_init.__func__ in wired_funcs, (
            "AutoModel._auto_post_init is not connected to "
            "autonomous.db.signals.post_init — last_updated will silently "
            "stop being stamped on construction."
        )

    def test_auto_pre_init_is_connected_to_signals_pre_init(self):
        """Sibling guard — the pre_init wiring is the well-tested side
        and breaking it would have downstream consequences too. Cheap
        to lock the symmetric invariant."""
        from autonomous.db import signals
        from autonomous.model.automodel import AutoModel

        wired_funcs = self._wired_functions(signals.pre_init)
        assert AutoModel._auto_pre_init.__func__ in wired_funcs
