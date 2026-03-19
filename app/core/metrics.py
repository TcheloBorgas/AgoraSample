import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class MetricsCollector:
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    timers_total_ms: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    timers_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def inc(self, key: str, value: int = 1) -> None:
        self.counters[key] += value

    def observe(self, key: str, duration_ms: float) -> None:
        self.timers_total_ms[key] += duration_ms
        self.timers_count[key] += 1

    def timed(self, key: str):
        start = time.perf_counter()

        def _stop() -> float:
            duration_ms = (time.perf_counter() - start) * 1000
            self.observe(key, duration_ms)
            return duration_ms

        return _stop

    def snapshot(self) -> dict:
        averages = {}
        for key, total in self.timers_total_ms.items():
            count = self.timers_count[key]
            averages[key] = round(total / count, 2) if count else 0.0
        return {
            "counters": dict(self.counters),
            "timers_avg_ms": averages,
        }


metrics = MetricsCollector()
