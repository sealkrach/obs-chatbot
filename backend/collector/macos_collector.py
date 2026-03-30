"""System metrics collector using psutil — with detailed per-process metrics."""
from __future__ import annotations

import asyncio
import logging
import platform

from backend.collector.metrics_store import store

log = logging.getLogger(__name__)

_psutil_initialized = False

_config = {
    "enabled": False,
    "interval_seconds": 15,
    "top_n_processes": 15,
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
    top_n_processes: int | None = None,
):
    if enabled is not None:
        _config["enabled"] = enabled
    if interval_seconds is not None:
        _config["interval_seconds"] = max(5, interval_seconds)
    if metrics is not None:
        _config["metrics"].update(metrics)
    if top_n_processes is not None:
        _config["top_n_processes"] = max(1, min(50, top_n_processes))


def collect_once():
    """Collect all enabled metrics once."""
    import psutil
    global _psutil_initialized
    if not _psutil_initialized:
        psutil.cpu_percent(interval=None)
        _psutil_initialized = True

    uname = platform.uname()
    store.set_resource({
        "host.name": uname.node,
        "os.type": uname.system,
        "os.version": uname.release,
        "host.arch": uname.machine,
    })
    m = _config["metrics"]

    # ── CPU ──
    if m.get("cpu"):
        store.add("system.cpu.utilization", psutil.cpu_percent(interval=None), "%")
        store.add("system.cpu.count", psutil.cpu_count(logical=True), "cores")
        store.add("system.cpu.count.physical", psutil.cpu_count(logical=False) or 0, "cores")
        try:
            freq = psutil.cpu_freq()
            if freq:
                store.add("system.cpu.frequency.current", freq.current, "MHz")
                store.add("system.cpu.frequency.max", freq.max, "MHz")
        except Exception:
            pass
        try:
            for i, pct in enumerate(psutil.cpu_percent(percpu=True, interval=None)):
                store.add("system.cpu.utilization.per_core", pct, "%", {"cpu.core": str(i)})
        except Exception:
            pass

    # ── Memory ──
    if m.get("memory"):
        mem = psutil.virtual_memory()
        store.add("system.memory.utilization", mem.percent, "%")
        store.add("system.memory.used", round(mem.used / (1024**3), 2), "GiB")
        store.add("system.memory.total", round(mem.total / (1024**3), 2), "GiB")
        store.add("system.memory.available", round(mem.available / (1024**3), 2), "GiB")
        store.add("system.memory.cached", round(getattr(mem, 'cached', 0) / (1024**3), 2), "GiB")
        swap = psutil.swap_memory()
        store.add("system.swap.utilization", swap.percent, "%")
        store.add("system.swap.used", round(swap.used / (1024**3), 2), "GiB")
        store.add("system.swap.total", round(swap.total / (1024**3), 2), "GiB")

    # ── Disk ──
    if m.get("disk"):
        try:
            usage = psutil.disk_usage("/")
            store.add("system.disk.utilization", usage.percent, "%", {"disk.mountpoint": "/"})
            store.add("system.disk.used", round(usage.used / (1024**3), 2), "GiB", {"disk.mountpoint": "/"})
            store.add("system.disk.total", round(usage.total / (1024**3), 2), "GiB", {"disk.mountpoint": "/"})
            store.add("system.disk.free", round(usage.free / (1024**3), 2), "GiB", {"disk.mountpoint": "/"})
        except Exception:
            pass
        try:
            io = psutil.disk_io_counters()
            if io:
                store.add("system.disk.io.read", round(io.read_bytes / (1024**3), 2), "GiB")
                store.add("system.disk.io.write", round(io.write_bytes / (1024**3), 2), "GiB")
                store.add("system.disk.io.read_count", io.read_count, "ops")
                store.add("system.disk.io.write_count", io.write_count, "ops")
        except Exception:
            pass

    # ── Network ──
    if m.get("network"):
        try:
            net = psutil.net_io_counters()
            store.add("system.network.bytes_sent", round(net.bytes_sent / (1024**2), 2), "MiB")
            store.add("system.network.bytes_recv", round(net.bytes_recv / (1024**2), 2), "MiB")
            store.add("system.network.packets_sent", net.packets_sent, "pkts")
            store.add("system.network.packets_recv", net.packets_recv, "pkts")
            store.add("system.network.errors_in", net.errin, "errors")
            store.add("system.network.errors_out", net.errout, "errors")
            store.add("system.network.drops_in", net.dropin, "drops")
            store.add("system.network.drops_out", net.dropout, "drops")
        except Exception:
            pass
        try:
            conns = psutil.net_connections(kind="inet")
            established = sum(1 for c in conns if c.status == "ESTABLISHED")
            store.add("system.network.connections.established", established, "conns")
            store.add("system.network.connections.total", len(conns), "conns")
        except Exception:
            pass

    # ── Processes (detailed) ──
    if m.get("processes"):
        try:
            top_n = _config.get("top_n_processes", 15)
            store.add("system.process.count", len(psutil.pids()), "processes")

            procs = []
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent",
                                              "memory_info", "num_threads", "status", "username"]):
                try:
                    info = proc.info
                    if info.get("pid", 0) == 0:
                        continue
                    procs.append(info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Top N by CPU
            procs_by_cpu = sorted(procs, key=lambda p: p.get("cpu_percent", 0) or 0, reverse=True)
            for p in procs_by_cpu[:top_n]:
                attrs = {
                    "process.name": p.get("name", "?"),
                    "process.pid": str(p.get("pid", 0)),
                    "process.user": p.get("username") or "?",
                    "process.status": p.get("status", "?"),
                }
                store.add("process.cpu.utilization", p.get("cpu_percent", 0) or 0, "%", attrs)
                store.add("process.memory.utilization", p.get("memory_percent", 0) or 0, "%", attrs)
                mem_info = p.get("memory_info")
                if mem_info:
                    store.add("process.memory.rss", round(mem_info.rss / (1024**2), 1), "MiB", attrs)
                    store.add("process.memory.vms", round(mem_info.vms / (1024**2), 1), "MiB", attrs)
                store.add("process.threads", p.get("num_threads", 0) or 0, "threads", attrs)

            # Per-process I/O (disk + network not available per-process in Docker, but try)
            for p in procs_by_cpu[:top_n]:
                try:
                    proc_obj = psutil.Process(p["pid"])
                    io_counters = proc_obj.io_counters()
                    if io_counters:
                        attrs = {"process.name": p.get("name", "?"), "process.pid": str(p["pid"])}
                        store.add("process.disk.read", round(io_counters.read_bytes / (1024**2), 1), "MiB", attrs)
                        store.add("process.disk.write", round(io_counters.write_bytes / (1024**2), 1), "MiB", attrs)
                        store.add("process.disk.read_ops", io_counters.read_count, "ops", attrs)
                        store.add("process.disk.write_ops", io_counters.write_count, "ops", attrs)
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    pass

            # Per-process connections count
            for p in procs_by_cpu[:top_n]:
                try:
                    proc_obj = psutil.Process(p["pid"])
                    conns = proc_obj.net_connections(kind="inet")
                    if conns:
                        attrs = {"process.name": p.get("name", "?"), "process.pid": str(p["pid"])}
                        store.add("process.network.connections", len(conns), "conns", attrs)
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    pass

        except Exception as e:
            log.debug("Process collection error: %s", e)

    # ── Battery ──
    if m.get("battery"):
        try:
            bat = psutil.sensors_battery()
            if bat:
                store.add("system.battery.percent", bat.percent, "%")
                store.add("system.battery.plugged", 1.0 if bat.power_plugged else 0.0, "bool")
                if bat.secsleft > 0:
                    store.add("system.battery.time_left", round(bat.secsleft / 60, 0), "min")
        except Exception:
            pass

    # ── Load average ──
    if m.get("load_avg"):
        try:
            load1, load5, load15 = psutil.getloadavg()
            store.add("system.load.1m", round(load1, 2), "load")
            store.add("system.load.5m", round(load5, 2), "load")
            store.add("system.load.15m", round(load15, 2), "load")
        except Exception:
            pass

    # Flush to disk periodically
    store.flush()


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
