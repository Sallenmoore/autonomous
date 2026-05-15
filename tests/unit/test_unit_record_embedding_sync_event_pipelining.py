"""Behavioral pin: record_embedding_sync_event uses ONE pipeline()
context with TWO queued commands per call.

Catches a regression that silently un-pipelines (someone reverts back
to two separate r.hincrby() + r.expire() round-trips). The pipeline
saves one Redis RTT per save on the worker hot path — important enough
to pin structurally.
"""

from autonomous.db import db_sync


class _RecordingPipeline:
    def __init__(self):
        self.commands = []
        self.execute_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def hincrby(self, key, field, amount):
        self.commands.append(("hincrby", key, field, amount))
        return self

    def expire(self, key, ttl):
        self.commands.append(("expire", key, ttl))
        return self

    def execute(self):
        self.execute_count += 1
        return [1, True]


class _RecordingRedis:
    def __init__(self):
        self.pipelines: list[_RecordingPipeline] = []
        self.hincrby_calls = 0
        self.expire_calls = 0

    def pipeline(self, transaction=False):
        # Pin the optimization: transaction=False is the contract
        # (MULTI/EXEC is unnecessary; the two ops are commutative for
        # the consumer's HGETALL view).
        assert transaction is False, (
            "record_embedding_sync_event must use pipeline(transaction=False); "
            "MULTI/EXEC adds unneeded latency to a best-effort observability path"
        )
        p = _RecordingPipeline()
        self.pipelines.append(p)
        return p

    def hincrby(self, *args, **kwargs):
        # If this fires, someone reverted to non-pipelined round-trips.
        self.hincrby_calls += 1

    def expire(self, *args, **kwargs):
        self.expire_calls += 1


def test_record_event_pipelines_two_commands_in_one_roundtrip():
    fake = _RecordingRedis()
    db_sync.record_embedding_sync_event("success", redis_client=fake)

    assert len(fake.pipelines) == 1
    p = fake.pipelines[0]
    assert p.execute_count == 1, "pipeline().execute() must fire exactly once"
    assert len(p.commands) == 2, "pipeline must queue exactly 2 commands"
    assert p.commands[0][0] == "hincrby"
    assert p.commands[1][0] == "expire"

    # Bare (non-pipelined) calls must NOT happen — regression guard.
    assert fake.hincrby_calls == 0
    assert fake.expire_calls == 0


def test_record_event_unknown_event_skips_redis_entirely():
    """Unknown event names still no-op (preserves the #53 guard)."""
    fake = _RecordingRedis()
    db_sync.record_embedding_sync_event("typo", redis_client=fake)

    assert fake.pipelines == []
    assert fake.hincrby_calls == 0
    assert fake.expire_calls == 0
