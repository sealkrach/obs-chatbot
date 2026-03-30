"""MCP-abstracted tools for querying collected OpenTelemetry metrics.

These LangChain tools act as an MCP resource/tool layer over the OTLP store.
The LLM calls them to query local system metrics without knowing the storage internals.
"""
from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from backend.collector.metrics_store import store


@tool
def get_local_metrics(
    metric: Optional[str] = None,
    last_minutes: int = 5,
) -> str:
    """
    Récupère les métriques système locales (macOS) collectées par le module OpenTelemetry.
    metric : nom de la métrique (ex: system.cpu.utilization, system.memory.utilization, system.disk.utilization, system.network.bytes_recv, system.load.1m, system.battery.percent, process.cpu.utilization, process.memory.rss, process.disk.read, process.network.connections). Laisser vide pour obtenir les dernières valeurs de toutes les métriques.
    last_minutes : fenêtre de temps en minutes (défaut 5).
    Retourne les données au format OTLP avec timestamp, valeur, unité et attributs.
    """
    if metric:
        data = store.query(metric_name=metric, last_n=50, since_seconds=last_minutes * 60)
    else:
        data = store.latest()

    if not data:
        return "Aucune métrique locale collectée. Vérifiez que le collecteur est activé dans les paramètres."

    lines = [f"**Métriques locales** ({len(data)} points) :\n"]

    if metric:
        for d in data[-15:]:
            attrs = ", ".join(f"{k}={v}" for k, v in d["attributes"].items()) if d["attributes"] else "global"
            lines.append(f"- [{d['timestamp_iso']}] **{d['value']}{d['unit']}** ({attrs})")
    else:
        by_name: dict[str, list] = {}
        for d in data:
            by_name.setdefault(d["metric_name"], []).append(d)
        for name, points in sorted(by_name.items()):
            p = points[0]
            attrs = ", ".join(f"{k}={v}" for k, v in p["attributes"].items()) if p["attributes"] else ""
            label = f" ({attrs})" if attrs else ""
            lines.append(f"- **{name}** : {p['value']} {p['unit']}{label}")

    return "\n".join(lines)


@tool
def get_top_processes(sort_by: str = "cpu", top_n: int = 10) -> str:
    """
    Retourne les processus les plus gourmands du système macOS local.
    sort_by : critère de tri — 'cpu' (défaut), 'memory', 'disk', 'network'
    top_n : nombre de processus à retourner (défaut 10)
    """
    metric_map = {
        "cpu": "process.cpu.utilization",
        "memory": "process.memory.rss",
        "disk": "process.disk.read",
        "network": "process.network.connections",
    }
    metric = metric_map.get(sort_by, "process.cpu.utilization")
    data = store.latest(metric_name=metric)

    if not data:
        return f"Aucune donnée processus disponible. Vérifiez que le collecteur est activé avec les métriques 'processes'."

    # Sort by value descending
    data.sort(key=lambda d: d["value"], reverse=True)

    lines = [f"**Top {min(top_n, len(data))} processus par {sort_by}** :\n"]
    lines.append(f"| # | Processus | PID | {sort_by.upper()} | User |")
    lines.append("|---|-----------|-----|------|------|")

    for i, d in enumerate(data[:top_n]):
        name = d["attributes"].get("process.name", "?")
        pid = d["attributes"].get("process.pid", "?")
        user = d["attributes"].get("process.user", "?")
        lines.append(f"| {i+1} | {name} | {pid} | {d['value']} {d['unit']} | {user} |")

    # Also show complementary metrics for top process
    if data:
        top_pid = data[0]["attributes"].get("process.pid")
        top_name = data[0]["attributes"].get("process.name", "?")
        lines.append(f"\n**Détails de {top_name} (PID {top_pid})** :")
        for m in ["process.cpu.utilization", "process.memory.utilization", "process.memory.rss",
                   "process.threads", "process.disk.read", "process.disk.write", "process.network.connections"]:
            pts = store.latest(metric_name=m)
            for p in pts:
                if p["attributes"].get("process.pid") == top_pid:
                    lines.append(f"- {m.split('.')[-1]} : **{p['value']} {p['unit']}**")
                    break

    return "\n".join(lines)


@tool
def get_system_summary() -> str:
    """
    Retourne un résumé complet de l'état du système macOS local avec toutes les métriques clés : CPU, mémoire, disque, réseau, batterie, charge et top processus.
    Utilise cette fonction quand l'utilisateur demande l'état général du système ou un diagnostic.
    """
    latest = store.latest()
    if not latest:
        return "Aucune métrique locale collectée. Vérifiez que le collecteur est activé."

    by_name: dict[str, list] = {}
    for d in latest:
        by_name.setdefault(d["metric_name"], []).append(d)

    def val(name: str) -> str:
        points = by_name.get(name, [])
        if not points:
            return "N/A"
        return f"{points[0]['value']} {points[0]['unit']}"

    lines = [
        "## État du système\n",
        f"### CPU",
        f"- Utilisation globale : **{val('system.cpu.utilization')}**",
        f"- Cœurs logiques/physiques : {val('system.cpu.count')} / {val('system.cpu.count.physical')}",
        f"- Fréquence : {val('system.cpu.frequency.current')} (max {val('system.cpu.frequency.max')})",
        f"- Charge 1/5/15 min : {val('system.load.1m')} / {val('system.load.5m')} / {val('system.load.15m')}",
        f"\n### Mémoire",
        f"- Utilisation : **{val('system.memory.utilization')}**",
        f"- Utilisée / Total : {val('system.memory.used')} / {val('system.memory.total')}",
        f"- Disponible : {val('system.memory.available')}",
        f"- Swap : {val('system.swap.utilization')} ({val('system.swap.used')} / {val('system.swap.total')})",
    ]

    lines.extend([
        f"\n### Disque",
        f"- Utilisation / : **{val('system.disk.utilization')}**",
        f"- Utilisé / Total : {val('system.disk.used')} / {val('system.disk.total')}",
        f"- Libre : {val('system.disk.free')}",
        f"- I/O lecture : {val('system.disk.io.read')} ({val('system.disk.io.read_count')})",
        f"- I/O écriture : {val('system.disk.io.write')} ({val('system.disk.io.write_count')})",
    ])

    lines.extend([
        f"\n### Réseau",
        f"- Envoyé : {val('system.network.bytes_sent')}",
        f"- Reçu : {val('system.network.bytes_recv')}",
        f"- Paquets : {val('system.network.packets_sent')} envoyés / {val('system.network.packets_recv')} reçus",
        f"- Erreurs : {val('system.network.errors_in')} in / {val('system.network.errors_out')} out",
        f"- Connexions : {val('system.network.connections.established')} actives / {val('system.network.connections.total')} total",
    ])

    bat = by_name.get("system.battery.percent")
    if bat:
        plugged = by_name.get("system.battery.plugged", [{}])
        plug_str = " (branché)" if plugged and plugged[0].get("value") == 1.0 else " (sur batterie)"
        time_left = val("system.battery.time_left")
        extra = f" — {time_left} restantes" if time_left != "N/A" else ""
        lines.append(f"\n### Batterie\n- **{bat[0]['value']}%**{plug_str}{extra}")

    # Top processes
    lines.append(f"\n### Processus ({val('system.process.count')})")
    proc_cpu = by_name.get("process.cpu.utilization", [])
    proc_mem = {p["attributes"].get("process.pid"): p for p in by_name.get("process.memory.rss", [])}
    proc_cpu.sort(key=lambda p: p["value"], reverse=True)
    if proc_cpu:
        lines.append("| Processus | CPU | RAM | Threads | User |")
        lines.append("|-----------|-----|-----|---------|------|")
        for p in proc_cpu[:10]:
            pid = p["attributes"].get("process.pid", "?")
            name = p["attributes"].get("process.name", "?")
            user = p["attributes"].get("process.user", "?")
            mem = proc_mem.get(pid)
            mem_str = f"{mem['value']} {mem['unit']}" if mem else "?"
            threads_pts = [t for t in by_name.get("process.threads", []) if t["attributes"].get("process.pid") == pid]
            thr = threads_pts[0]["value"] if threads_pts else "?"
            lines.append(f"| {name} | {p['value']}% | {mem_str} | {thr} | {user} |")

    # Diagnostic
    cpu_pct = by_name.get("system.cpu.utilization", [{}])
    mem_pct = by_name.get("system.memory.utilization", [{}])
    disk_pct = by_name.get("system.disk.utilization", [{}])
    cpu_v = cpu_pct[0].get("value", 0) if cpu_pct else 0
    mem_v = mem_pct[0].get("value", 0) if mem_pct else 0
    disk_v = disk_pct[0].get("value", 0) if disk_pct else 0

    lines.append("\n### Diagnostic")
    for label, v in [("CPU", cpu_v), ("Mémoire", mem_v), ("Disque", disk_v)]:
        if v > 85:
            lines.append(f"- 🔴 **{label} critique** ({v}%)")
        elif v > 70:
            lines.append(f"- 🟡 **{label} élevé** ({v}%)")
        else:
            lines.append(f"- ✅ {label} normal ({v}%)")

    return "\n".join(lines)


@tool
def list_collected_metrics() -> str:
    """
    Liste toutes les métriques OTLP actuellement collectées avec des statistiques sur le store.
    """
    stats = store.stats()
    if not stats["metrics"]:
        return "Aucune métrique collectée. Le collecteur n'est peut-être pas activé."

    lines = [
        f"**Store OpenTelemetry** : {stats['total_points']} / {stats['max_capacity']} points",
        f"**Persisté** : {stats['persisted_file']} ({'oui' if stats['file_exists'] else 'non'})\n",
        "**Métriques disponibles** :",
    ]
    for m in stats["metrics"]:
        lines.append(f"- `{m}`")

    return "\n".join(lines)


MCP_TOOLS = [
    get_local_metrics,
    get_top_processes,
    get_system_summary,
    list_collected_metrics,
]
