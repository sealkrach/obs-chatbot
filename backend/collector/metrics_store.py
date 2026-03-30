"""Persistent metrics store using OpenTelemetry data model.
Stores in-memory ring buffer + flushes periodically to JSONL on disk.
"""
from __future__ import annotations

import json
import os
import time
import threading
import logging
from collections import deque
from pathlib import Path

log = logging.getLogger(__name__)

STORE_PATH = Path(os.getenv("METRICS_STORE_PATH", "/app/data/metrics.jsonl"))
MAX_FILE_LINES = 50_000  # rotate after this many lines


class MetricsStore:
    def __init__(self, max_points: int = 50_000):
        self._data: deque = deque(maxlen=max_points)
        self._lock = threading.Lock()
        self._resource: dict = {}
        self._unflushed: int = 0
        self._load_from_disk()

    def _load_from_disk(self):
        if not STORE_PATH.exists():
            return
        try:
            count = 0
            with open(STORE_PATH, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self._data.append(json.loads(line))
                        count += 1
                    except json.JSONDecodeError:
                        pass
            if count:
                log.info("Loaded %d metric points from %s", count, STORE_PATH)
        except Exception as e:
            log.warning("Failed to load metrics from disk: %s", e)

    def _flush_to_disk(self, points: list[dict]):
        try:
            STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
            # Check file size and rotate if needed
            if STORE_PATH.exists():
                line_count = sum(1 for _ in open(STORE_PATH))
                if line_count > MAX_FILE_LINES:
                    # Keep last half
                    with open(STORE_PATH, "r") as f:
                        lines = f.readlines()
                    with open(STORE_PATH, "w") as f:
                        f.writelines(lines[len(lines) // 2:])
                    log.info("Rotated metrics file (kept %d lines)", len(lines) // 2)
            # Append new points
            with open(STORE_PATH, "a") as f:
                for p in points:
                    f.write(json.dumps(p) + "\n")
        except Exception as e:
            log.warning("Failed to flush metrics to disk: %s", e)

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
            self._unflushed += 1

    def flush(self):
        """Flush unflushed points to disk."""
        with self._lock:
            if self._unflushed <= 0:
                return
            points = list(self._data)[-self._unflushed:]
            self._unflushed = 0
        self._flush_to_disk(points)

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
                "persisted_file": str(STORE_PATH),
                "file_exists": STORE_PATH.exists(),
                "metrics": sorted(set(p["metric_name"] for p in self._data)),
                "oldest_ns": self._data[0]["timestamp_ns"] if self._data else None,
                "newest_ns": self._data[-1]["timestamp_ns"] if self._data else None,
            }


store = MetricsStore()
