"""System metrics collector using psutil — works in Docker and on macOS host."""
from __future__ import annotations

import asyncio
import logging
import platform
import time

from backend.collector.metrics_store import store

log = logging.getLogger(__name__)

_psutil_initialized = False

_config = {
    "enabled": False,
    "interval_seconds": 15,
    "metrics": {
        "cpu": True,
        "memory": True,
        "disk": True,
        "network": True,
        "processes": True,
        "battery": True,
        "load_avg": True,
    },
}
_task: asyncio.Task | None = None


def get_collector_config() -> dict:
    return dict(_config)


def update_collector_config(
    enabled: bool | None = None,
    interval_seconds: int | None = None,
    metrics: dict | None = None,
):
    if enabled is not None:
        _config["enabled"] = enabled
    if interval_seconds is not None:
        _config["interval_seconds"] = max(5, interval_seconds)
    if metrics is not None:
        _config["metrics"].update(metrics)


def collect_once():
    """Collect all enabled metrics once — safe for Docker."""
    import psutil
    global _psutil_initialized
    if not _psutil_initialized:
        psutil.cpu_percent(interval=None)
        _psutil_initialized = True

    uname = platform.uname()
    store.set_resource({"host.name": uname.node, "os.type": uname.system, "host.arch": uname.machine})
    m = _config["metrics"]

    if m.get("cpu"):
        store.add("system.cpu.utilization", psutil.cpu_percent(interval=None), "%")
        store.add("system.cpu.count", psutil.cpu_count(logical=True), "cores")

    if m.get("memory"):
        mem = psutil.virtual_memory()
        store.add("system.memory.utilization", mem.percent, "%")
        store.add("system.memory.used", round(mem.used / (1024**3), 2), "GiB")
        store.add("system.memory.total", round(mem.total / (1024**3), 2), "GiB")
        store.add("system.memory.available", round(mem.available / (1024**3), 2), "GiB")

    if m.get("disk"):
        try:
            usage = psutil.disk_usage("/")
            store.add("system.disk.utilization", usage.percent, "%", {"disk.mountpoint": "/"})
            store.add("system.disk.used", round(usage.used / (1024**3), 2), "GiB", {"disk.mountpoint": "/"})
            store.add("system.disk.total", round(usage.total / (1024**3), 2), "GiB", {"disk.mountpoint": "/"})
        except Exception:
            pass

    if m.get("network"):
        try:
            net = psutil.net_io_counters()
            store.add("system.network.bytes_sent", round(net.bytes_sent / (1024**2), 2), "MiB")
            store.add("system.network.bytes_recv", round(net.bytes_recv / (1024**2), 2), "MiB")
        except Exception:
            pass

    if m.get("processes"):
        try:
            store.add("system.process.count", len(psutil.pids()), "processes")
        except Exception:
            pass

    if m.get("battery"):
        try:
            bat = psutil.sensors_battery()
            if bat:
                store.add("system.battery.percent", bat.percent, "%")
                store.add("system.battery.plugged", 1.0 if bat.power_plugged else 0.0, "bool")
        except Exception:
            pass

    if m.get("load_avg"):
        try:
            load1, load5, load15 = psutil.getloadavg()
            store.add("system.load.1m", round(load1, 2), "load")
            store.add("system.load.5m", round(load5, 2), "load")
            store.add("system.load.15m", round(load15, 2), "load")
        except Exception:
            pass

    log.debug("Collected metrics: %d points in store", len(store._data))


async def _collection_loop():
    log.info("Collector loop started (interval=%ds)", _config["interval_seconds"])
    while True:
        if _config["enabled"]:
            try:
                await asyncio.to_thread(collect_once)
            except Exception as e:
                log.exception("Collection error: %s", e)
        await asyncio.sleep(_config["interval_seconds"])


def start_collector():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_collection_loop())


def stop_collector():
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
