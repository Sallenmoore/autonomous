"""Benchmark record_embedding_sync_event with the pipelined Redis path.

Pre-fix: two separate HINCRBY + EXPIRE round-trips. Post-fix: one
pipelined round-trip with transaction=False. Benchmarked against a
fake Redis client that records command counts so we can assert
structural correctness (one execute() per call) in addition to
measuring latency.
"""

from unittest.mock import MagicMock

from autonomous.db import db_sync


class _FakePipeline:
    """Records queued commands; .execute() returns synthetic responses."""

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


class _FakeRedis:
    def __init__(self):
        self.pipelines: list[_FakePipeline] = []

    def pipeline(self, transaction=False):
        p = _FakePipeline()
        self.pipelines.append(p)
        return p


def test_record_event_with_pipeline(benchmark):
    fake = _FakeRedis()
    benchmark(db_sync.record_embedding_sync_event, "success", redis_client=fake)

    # Structural assertions: every call uses exactly one pipeline with
    # two queued commands and one execute(). Pinned here so a regression
    # that silently un-pipelines back to two round-trips fails this
    # test, not just makes the benchmark slower.
    assert fake.pipelines, "pipeline() was never called"
    for p in fake.pipelines:
        assert p.execute_count == 1
        assert len(p.commands) == 2
        assert p.commands[0][0] == "hincrby"
        assert p.commands[1][0] == "expire"
