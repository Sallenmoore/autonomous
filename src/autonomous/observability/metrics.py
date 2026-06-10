"""In-process metric primitives — ``Counter`` and ``Histogram``.

Foundation slice for issue #51. Modeled after Prometheus client shapes
so a future ``prometheus_client`` backend swap reuses the call-site
contract (``counter.inc(provider="openai", status=500)``) unchanged.

Backend is in-memory only in this slice. Two follow-up slices:

1. A Redis backend that mirrors the hour-bucket pattern from
   ``db.db_sync.record_embedding_sync_event`` (so the embedding-sync
   health dashboard keeps working).
2. A ``prometheus_client`` backend behind the ``[server]`` extra so
   ``/metrics`` exposure is available when consumers want it.

Thread-safety:

- Each metric uses a single ``threading.Lock`` around mutations.
  Reads (``collect()``) hold the same lock briefly to take a snapshot.
- The registry uses its own lock for ``register()`` to keep
  concurrent metric registration safe (e.g. two modules both calling
  ``counter("x")`` at import time).
"""

from __future__ import annotations

import threading
from typing import Iterable, Mapping


class _MetricBase:
    """Shared fields and validation across ``Counter`` / ``Histogram``."""

    def __init__(
        self,
        name: str,
        *,
        description: str = "",
        label_names: Iterable[str] = (),
    ) -> None:
        if not name:
            raise ValueError("metric name must be a non-empty string")
        # Label-name order is fixed at construction so collect()
        # output is deterministic across processes. Use a tuple, not
        # a set, to preserve declaration order.
        self.name = name
        self.description = description
        self.label_names: tuple[str, ...] = tuple(label_names)
        self._lock = threading.Lock()

    def _label_key(self, labels: Mapping[str, str]) -> tuple[str, ...]:
        """Project ``labels`` into a deterministic key in declared
        ``label_names`` order. Missing labels become ``""`` (matches
        Prometheus's empty-label-value treatment). Unknown labels
        raise ``KeyError`` so typos surface immediately rather than
        silently bucketing to a new series.
        """
        unknown = set(labels) - set(self.label_names)
        if unknown:
            raise KeyError(
                f"Metric '{self.name}' got unknown label(s) "
                f"{sorted(unknown)}; declared: {list(self.label_names)}"
            )
        return tuple(str(labels.get(n, "")) for n in self.label_names)


class Counter(_MetricBase):
    """Monotonically increasing counter, labeled.

    Use for event-shaped facts (HPC unreachable, structured outputs
    fallback fired, embedding sync queued / completed / failed). Do
    NOT use ``Counter`` for values that can decrease — use a ``Gauge``
    primitive (not in this slice; track in a future iteration).
    """

    def __init__(
        self,
        name: str,
        *,
        description: str = "",
        label_names: Iterable[str] = (),
    ) -> None:
        super().__init__(name, description=description, label_names=label_names)
        self._values: dict[tuple[str, ...], float] = {}

    def inc(self, value: float = 1.0, **labels: str) -> None:
        """Increment by ``value`` (default ``1``) at the given label
        combination. ``value`` must be non-negative."""
        if value < 0:
            raise ValueError("Counter.inc value must be non-negative")
        key = self._label_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + value

    def collect(self) -> dict[tuple[str, ...], float]:
        """Snapshot of current values keyed by label tuple."""
        with self._lock:
            return dict(self._values)

    def reset(self) -> None:
        """Drop all observed series. Intended for tests; production
        consumers should treat counters as monotonic for the process
        lifetime."""
        with self._lock:
            self._values.clear()


class Histogram(_MetricBase):
    """Bucketed distribution, labeled. Records ``count`` + ``sum`` +
    per-bucket cumulative counts so ``count / sum`` gives the average
    and per-bucket counts give percentiles via linear interpolation.

    Bucket-edge semantics mirror Prometheus: each bucket counts the
    number of observations ``<= upper_bound``. The implicit ``+Inf``
    bucket equals the total observation count.
    """

    # Default buckets target sub-millisecond to 10s wall-clock
    # observations. AI adapters and OAuth fetches both fit comfortably
    # in this range; callers with different scales pass their own.
    DEFAULT_BUCKETS: tuple[float, ...] = (
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
    )

    def __init__(
        self,
        name: str,
        *,
        description: str = "",
        buckets: Iterable[float] = DEFAULT_BUCKETS,
        label_names: Iterable[str] = (),
    ) -> None:
        super().__init__(name, description=description, label_names=label_names)
        bucket_list = sorted(set(buckets))
        if not bucket_list:
            raise ValueError("Histogram requires at least one bucket edge")
        if any(not (b > 0) for b in bucket_list):
            raise ValueError("Histogram bucket edges must be positive numbers")
        self.buckets: tuple[float, ...] = tuple(bucket_list)
        # Per-label-key state. Each entry is {count, sum, buckets[]}.
        # bucket_counts is cumulative (Prometheus style).
        self._series: dict[tuple[str, ...], dict] = {}

    def _empty_series(self) -> dict:
        return {
            "count": 0,
            "sum": 0.0,
            "buckets": [0] * len(self.buckets),
        }

    def observe(self, value: float, **labels: str) -> None:
        """Record one observation under the given label combination."""
        key = self._label_key(labels)
        with self._lock:
            series = self._series.setdefault(key, self._empty_series())
            series["count"] += 1
            series["sum"] += float(value)
            for i, edge in enumerate(self.buckets):
                if value <= edge:
                    series["buckets"][i] += 1

    def collect(self) -> dict[tuple[str, ...], dict]:
        """Snapshot of all label series. Each value is a dict with
        ``count``, ``sum``, and per-bucket cumulative counts."""
        with self._lock:
            return {
                key: {
                    "count": s["count"],
                    "sum": s["sum"],
                    "buckets": dict(zip(self.buckets, s["buckets"])),
                }
                for key, s in self._series.items()
            }

    def reset(self) -> None:
        """Drop all observed series. Tests only."""
        with self._lock:
            self._series.clear()


class Registry:
    """Holds the process's known metrics by name.

    The default global registry is ``REGISTRY``. Tests construct fresh
    ``Registry()`` instances and pass them to the ``counter()`` /
    ``histogram()`` helpers via the ``registry=`` kwarg to avoid
    pollution across cases.
    """

    def __init__(self) -> None:
        self._metrics: dict[str, _MetricBase] = {}
        self._lock = threading.Lock()

    def register(self, metric: _MetricBase) -> None:
        with self._lock:
            existing = self._metrics.get(metric.name)
            if existing is not None and existing is not metric:
                raise ValueError(
                    f"Metric name conflict: '{metric.name}' already registered "
                    f"as {type(existing).__name__}"
                )
            self._metrics[metric.name] = metric

    def get(self, name: str) -> _MetricBase | None:
        with self._lock:
            return self._metrics.get(name)

    def collect(self) -> dict[str, dict]:
        """Snapshot of every registered metric, keyed by metric name.

        Each value is ``{"type": "counter"|"histogram", "description":
        ..., "data": <collect() output>}``. Designed for future
        ``/metrics`` endpoint rendering and JSON dumps.
        """
        with self._lock:
            metrics = list(self._metrics.values())
        out: dict[str, dict] = {}
        for m in metrics:
            kind = "histogram" if isinstance(m, Histogram) else "counter"
            out[m.name] = {
                "type": kind,
                "description": m.description,
                "label_names": list(m.label_names),
                "data": m.collect(),
            }
        return out

    def clear(self) -> None:
        """Drop every registered metric. Tests use this for isolation."""
        with self._lock:
            self._metrics.clear()


REGISTRY = Registry()


def counter(
    name: str,
    *,
    description: str = "",
    label_names: Iterable[str] = (),
    registry: Registry | None = None,
) -> Counter:
    """Construct + register a ``Counter`` on the given (or default)
    registry. If a counter with the same name is already registered
    on the registry it's returned as-is, matching Prometheus's
    idempotent ``Counter(name)`` shape so two callers from different
    modules don't fight at import time."""
    reg = registry if registry is not None else REGISTRY
    existing = reg.get(name)
    if existing is not None:
        if not isinstance(existing, Counter):
            raise ValueError(
                f"Metric '{name}' already registered as {type(existing).__name__}, "
                "not Counter"
            )
        return existing
    c = Counter(name, description=description, label_names=label_names)
    reg.register(c)
    return c


def histogram(
    name: str,
    *,
    description: str = "",
    buckets: Iterable[float] = Histogram.DEFAULT_BUCKETS,
    label_names: Iterable[str] = (),
    registry: Registry | None = None,
) -> Histogram:
    """Construct + register a ``Histogram`` on the given (or default)
    registry. Idempotent on name like ``counter()``."""
    reg = registry if registry is not None else REGISTRY
    existing = reg.get(name)
    if existing is not None:
        if not isinstance(existing, Histogram):
            raise ValueError(
                f"Metric '{name}' already registered as {type(existing).__name__}, "
                "not Histogram"
            )
        return existing
    h = Histogram(
        name, description=description, buckets=buckets, label_names=label_names
    )
    reg.register(h)
    return h
