"""MCP-abstracted tools for querying collected OpenTelemetry metrics.

These LangChain tools act as an MCP resource/tool layer over the OTLP store.
The LLM calls them to query local system metrics without knowing the storage internals.
"""
from __future__ import annotations

import json
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
    metric : nom de la métrique (ex: system.cpu.utilization, system.memory.utilization, system.disk.utilization, system.network.bytes_recv, system.load.1m, system.battery.percent). Laisser vide pour obtenir les dernières valeurs de toutes les métriques.
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
        for d in data[-10:]:  # Last 10 points
            attrs = ", ".join(f"{k}={v}" for k, v in d["attributes"].items()) if d["attributes"] else "global"
            lines.append(f"- [{d['timestamp_iso']}] **{d['value']}{d['unit']}** ({attrs})")
    else:
        # Group by metric name, show latest
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
def get_system_summary() -> str:
    """
    Retourne un résumé complet de l'état du système macOS local avec toutes les métriques clés : CPU, mémoire, disque, réseau, batterie, charge.
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
        p = points[0]
        return f"{p['value']} {p['unit']}"

    def val_with_attrs(name: str) -> list[str]:
        points = by_name.get(name, [])
        result = []
        for p in points:
            attrs = ", ".join(f"{k}={v}" for k, v in p["attributes"].items()) if p["attributes"] else "global"
            result.append(f"  - {attrs}: **{p['value']} {p['unit']}**")
        return result

    lines = [
        "## État du système macOS\n",
        f"### CPU",
        f"- Utilisation globale : **{val('system.cpu.utilization')}**",
        f"- Cœurs : {val('system.cpu.count')}",
        f"- Fréquence : {val('system.cpu.frequency')}",
        f"- Charge 1/5/15 min : {val('system.load.1m')} / {val('system.load.5m')} / {val('system.load.15m')}",
        f"\n### Mémoire",
        f"- Utilisation : **{val('system.memory.utilization')}**",
        f"- Utilisée / Total : {val('system.memory.used')} / {val('system.memory.total')}",
        f"- Disponible : {val('system.memory.available')}",
        f"- Swap : {val('system.swap.utilization')}",
    ]

    disk_points = by_name.get("system.disk.utilization", [])
    if disk_points:
        lines.append("\n### Disque")
        for p in disk_points:
            mp = p["attributes"].get("disk.mountpoint", "?")
            lines.append(f"- {mp} : **{p['value']} {p['unit']}**")

    lines.extend([
        f"\n### Réseau",
        f"- Envoyé : {val('system.network.bytes_sent')}",
        f"- Reçu : {val('system.network.bytes_recv')}",
        f"- Erreurs : {val('system.network.errors_in')} in / {val('system.network.errors_out')} out",
    ])

    bat = by_name.get("system.battery.percent")
    if bat:
        plugged = by_name.get("system.battery.plugged", [{}])
        plug_str = " (branché)" if plugged and plugged[0].get("value") == 1.0 else " (sur batterie)"
        lines.append(f"\n### Batterie\n- **{bat[0]['value']}%**{plug_str}")

    lines.append(f"\n### Processus\n- Total : {val('system.process.count')}")
    top_procs = by_name.get("system.process.cpu", [])
    if top_procs:
        lines.append("- Top CPU :")
        for p in top_procs[:5]:
            name = p["attributes"].get("process.name", "?")
            lines.append(f"  - {name} : {p['value']}%")

    # Health assessment
    cpu_val = by_name.get("system.cpu.utilization", [{}])
    mem_val = by_name.get("system.memory.utilization", [{}])
    cpu_pct = cpu_val[0].get("value", 0) if cpu_val else 0
    mem_pct = mem_val[0].get("value", 0) if mem_val else 0

    lines.append("\n### Diagnostic")
    if cpu_pct > 85:
        lines.append(f"- 🔴 **CPU critique** ({cpu_pct}%) — action recommandée")
    elif cpu_pct > 70:
        lines.append(f"- 🟡 **CPU élevé** ({cpu_pct}%) — à surveiller")
    else:
        lines.append(f"- ✅ CPU normal ({cpu_pct}%)")

    if mem_pct > 85:
        lines.append(f"- 🔴 **Mémoire critique** ({mem_pct}%) — action recommandée")
    elif mem_pct > 70:
        lines.append(f"- 🟡 **Mémoire élevée** ({mem_pct}%) — à surveiller")
    else:
        lines.append(f"- ✅ Mémoire normale ({mem_pct}%)")

    return "\n".join(lines)


@tool
def list_collected_metrics() -> str:
    """
    Liste toutes les métriques OTLP actuellement collectées avec des statistiques sur le store.
    Utile pour savoir quelles métriques sont disponibles.
    """
    stats = store.stats()
    if not stats["metrics"]:
        return "Aucune métrique collectée. Le collecteur n'est peut-être pas activé."

    lines = [
        f"**Store OpenTelemetry** : {stats['total_points']} / {stats['max_capacity']} points\n",
        "**Métriques disponibles** :",
    ]
    for m in stats["metrics"]:
        lines.append(f"- `{m}`")

    return "\n".join(lines)


# All MCP tools to register with the agent
MCP_TOOLS = [
    get_local_metrics,
    get_system_summary,
    list_collected_metrics,
]
