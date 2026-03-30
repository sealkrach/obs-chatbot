"""In-memory metrics store using OpenTelemetry data model.
No dependency on any backend module — pure Python only.
"""
from __future__ import annotations

import time
import threading
from collections import deque


class MetricsStore:
    def __init__(self, max_points: int = 10_000):
        self._data: deque = deque(maxlen=max_points)
        self._lock = threading.Lock()
        self._resource: dict = {}

    def set_resource(self, attrs: dict):
        self._resource.update(attrs)

    def add(self, metric_name: str, value: float, unit: str, attributes: dict | None = None):
        point = {
            "metric_name": metric_name,
            "value": round(value, 2),
            "unit": unit,
            "timestamp_ns": int(time.time() * 1e9),
            "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "attributes": attributes or {},
            "resource": dict(self._resource),
        }
        with self._lock:
            self._data.append(point)

    def query(self, metric_name: str | None = None, last_n: int = 100, since_seconds: int | None = None) -> list[dict]:
        cutoff = int((time.time() - since_seconds) * 1e9) if since_seconds else 0
        with self._lock:
            results = []
            for p in reversed(self._data):
                if metric_name and p["metric_name"] != metric_name:
                    continue
                if cutoff and p["timestamp_ns"] < cutoff:
                    break
                results.append(p)
                if len(results) >= last_n:
                    break
        results.reverse()
        return results

    def latest(self, metric_name: str | None = None) -> list[dict]:
        seen: dict[str, dict] = {}
        with self._lock:
            for p in reversed(self._data):
                key = f"{p['metric_name']}|{str(sorted(p['attributes'].items()))}"
                if metric_name and p["metric_name"] != metric_name:
                    continue
                if key not in seen:
                    seen[key] = p
        return list(seen.values())

    def available_metrics(self) -> list[str]:
        with self._lock:
            return sorted(set(p["metric_name"] for p in self._data))

    def stats(self) -> dict:
        with self._lock:
            return {
                "total_points": len(self._data),
                "max_capacity": self._data.maxlen,
                "metrics": sorted(set(p["metric_name"] for p in self._data)),
                "oldest_ns": self._data[0]["timestamp_ns"] if self._data else None,
                "newest_ns": self._data[-1]["timestamp_ns"] if self._data else None,
            }


# Singleton — importable from anywhere
store = MetricsStore()
