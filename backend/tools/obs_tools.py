"""Outils LangChain que le LLM peut invoquer pour interroger obs-platform."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import httpx
from langchain_core.tools import tool

from backend.config import get_settings

log = logging.getLogger(__name__)
cfg = get_settings()


def _obs(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """Appel synchrone vers l'API obs-platform."""
    url = f"{cfg.obs_api_url}{path}"
    with httpx.Client(timeout=15) as client:
        if method == "GET":
            r = client.get(url, headers=cfg.obs_headers)
        else:
            r = client.request(method, url, json=body, headers=cfg.obs_headers)
        r.raise_for_status()
        return r.json()


def _vm_query(promql: str, step: str = "5m") -> list[dict]:
    """Requête PromQL directe sur VictoriaMetrics."""
    with httpx.Client(timeout=15) as client:
        r = client.get(
            f"{cfg.victoriametrics_url}/api/v1/query",
            params={"query": promql},
        )
        r.raise_for_status()
        data = r.json()
        return data.get("data", {}).get("result", [])


# ── Tool 1 : alertes actives ──────────────────────────────────────────

@tool
def get_active_alerts(
    severity: Optional[str] = None,
    service: Optional[str] = None,
    region: Optional[str] = None,
) -> str:
    """
    Récupère les alertes actives depuis obs-platform.
    Paramètres optionnels : severity (critical/warning/info), service, region.
    Retourne la liste des alertes avec leur ID, sévérité, service et message.
    """
    try:
        params = []
        if severity: params.append(f"severity={severity}")
        if service:  params.append(f"service={service}")
        if region:   params.append(f"region={region}")
        qs = "?" + "&".join(params) if params else ""

        # Appel Alertmanager via obs-platform
        with httpx.Client(timeout=10) as client:
            r = client.get(
                f"{cfg.obs_api_url.rstrip('/')}/api/v1/alerts{qs}",
                headers=cfg.obs_headers,
            )
            if r.status_code == 404:
                # Fallback : interroger Alertmanager directement
                r2 = client.get(
                    f"{cfg.obs_api_url.replace('8000','9093')}/api/v2/alerts"
                )
                alerts = r2.json() if r2.status_code == 200 else []
            else:
                alerts = r.json() if isinstance(r.json(), list) else []

        if not alerts:
            return "Aucune alerte active en ce moment."

        lines = [f"**{len(alerts)} alerte(s) active(s) :**\n"]
        for a in alerts[:10]:  # limiter à 10
            sev  = a.get("severity") or a.get("labels", {}).get("severity", "?")
            name = a.get("name") or a.get("labels", {}).get("alertname", "?")
            svc  = a.get("service") or a.get("labels", {}).get("service", "?")
            msg  = a.get("message") or a.get("annotations", {}).get("summary", "")
            aid  = a.get("id") or a.get("fingerprint", "")
            lines.append(f"- [{sev.upper()}] **{name}** ({svc}) — {msg} `id={aid}`")

        if len(alerts) > 10:
            lines.append(f"\n… et {len(alerts)-10} autres.")
        return "\n".join(lines)

    except Exception as e:
        log.exception("get_active_alerts error")
        return f"Erreur lors de la récupération des alertes : {e}"


# ── Tool 2 : métriques PromQL ─────────────────────────────────────────

@tool
def get_metrics(
    metric: str,
    service: Optional[str] = None,
    region: Optional[str] = None,
    duration: str = "5m",
) -> str:
    """
    Interroge VictoriaMetrics pour obtenir la valeur actuelle d'une métrique.
    metric : nom PromQL ou mot-clé (cpu, memory, disk, rps, error_rate, latency_p99).
    service : filtre par service (ex: api-gateway).
    duration : fenêtre de temps (ex: 5m, 1h, 24h).
    Retourne la valeur actuelle et une interprétation.
    """
    ALIASES = {
        "cpu":         'avg(rate(node_cpu_seconds_total{{mode!="idle"}}[{d}])) * 100',
        "memory":      "avg(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100",
        "disk":        "avg((node_filesystem_size_bytes - node_filesystem_free_bytes) / node_filesystem_size_bytes) * 100",
        "rps":         "sum(rate(http_requests_total[{d}]))",
        "error_rate":  'sum(rate(http_requests_total{{status=~"5.."}}[{d}])) / sum(rate(http_requests_total[{d}])) * 100',
        "latency_p99": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[{d}])) by (le))",
    }

    try:
        # Résolution de l'alias
        q = ALIASES.get(metric.lower(), metric)
        q = q.format(d=duration)

        # Ajout filtre service
        if service and "{" in q:
            q = q.replace("{", f'{{service="{service}",', 1)
        elif service:
            q = f'{q}{{service="{service}"}}'

        results = _vm_query(q)
        if not results:
            return f"Aucune donnée pour la métrique `{metric}`" + (f" (service={service})" if service else "") + "."

        lines = [f"**Métrique `{metric}`** — {datetime.now().strftime('%H:%M UTC')}:\n"]
        for r in results[:5]:
            labels = r.get("metric", {})
            value  = float(r.get("value", [0, 0])[1])
            lbl    = ", ".join(f"{k}={v}" for k, v in labels.items() if k not in ("__name__",))
            unit   = "%" if metric in ("cpu", "memory", "disk", "error_rate") else ""
            lines.append(f"- {lbl or 'global'} : **{value:.2f}{unit}**")

        return "\n".join(lines)

    except Exception as e:
        log.exception("get_metrics error")
        return f"Erreur lors de la récupération de la métrique : {e}"


# ── Tool 3 : forecast capacité ────────────────────────────────────────

@tool
def get_forecast(metric: str = "cpu_usage", horizon_days: int = 30) -> str:
    """
    Retourne la prédiction de croissance et le risque de saturation pour une métrique.
    metric : cpu_usage, memory_usage, disk_usage, rps, error_rate.
    horizon_days : horizon de prédiction en jours (défaut 30).
    Retourne le taux de croissance, la valeur prédite et la date de saturation estimée.
    """
    try:
        data = _obs(f"/api/v1/forecasts/{metric}?horizon_days={horizon_days}")

        risk  = data.get("risk_level", "?")
        cur   = data.get("current_value", 0)
        pred  = data.get("predicted_30d", 0)
        growth = data.get("growth_rate_pct", 0)
        sat   = data.get("days_until_saturation")
        peak  = data.get("predicted_peak", 0)

        risk_emoji = {"ok": "✅", "warning": "⚠️", "critical": "🔴"}.get(risk, "❓")

        lines = [
            f"**Forecast `{metric}` — {horizon_days} jours** {risk_emoji}\n",
            f"- Valeur actuelle : **{cur:.1f}%**",
            f"- Valeur prédite (J+{horizon_days}) : **{pred:.1f}%**",
            f"- Taux de croissance : **{growth:+.1f}%**",
            f"- Pic prédit : **{peak:.1f}%**",
        ]
        if sat is not None:
            lines.append(f"- ⏱ Saturation estimée dans : **{sat} jours**")
        else:
            lines.append("- ✅ Aucune saturation prévue sur l'horizon")

        if risk == "critical":
            lines.append(f"\n🚨 **Action recommandée** : provisionner de la capacité sous {sat} jours.")
        elif risk == "warning":
            lines.append(f"\n⚠️ **À surveiller** : planifier une extension dans les {sat} jours.")

        return "\n".join(lines)

    except Exception as e:
        log.exception("get_forecast error")
        return f"Erreur lors du forecast `{metric}` : {e}"


# ── Tool 4 : acquittement alerte ──────────────────────────────────────

@tool
def acknowledge_alert(
    alert_id: str,
    reason: str = "Acknowledged via chatbot",
    silence_hours: int = 2,
) -> str:
    """
    Acquitte une alerte dans obs-platform (stoppe les notifications).
    alert_id : identifiant de l'alerte (obtenu via get_active_alerts).
    reason : raison de l'acquittement.
    silence_hours : durée du silence Alertmanager en heures (défaut 2h).
    Retourne la confirmation d'acquittement.
    """
    try:
        result = _obs("/api/v1/alerts/acknowledge", method="POST", body={
            "alert_id":     alert_id,
            "reason":       reason,
            "silence_hours": silence_hours,
            "acked_by":     "chatbot",
        })
        return (
            f"✅ **Alerte `{alert_id}` acquittée** avec succès.\n"
            f"- Raison : {reason}\n"
            f"- Silence actif pendant {silence_hours}h\n"
            f"- Statut : {result.get('status', 'ok')}"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"❌ Alerte `{alert_id}` introuvable. Vérifie l'ID avec `get_active_alerts`."
        return f"❌ Erreur acquittement : {e}"
    except Exception as e:
        log.exception("acknowledge_alert error")
        return f"❌ Erreur lors de l'acquittement : {e}"


# ── Tool 5 : rapport synthèse ─────────────────────────────────────────

@tool
def generate_report(
    period: str = "day",
    region: Optional[str] = None,
) -> str:
    """
    Génère un rapport de synthèse de l'infrastructure.
    period : 'day' (dernières 24h), 'week' (7 jours), 'hour' (1h).
    region : filtrer par région (optionnel).
    Retourne un résumé consolidé des métriques, alertes et tendances.
    """
    try:
        # Récupérer toutes les données nécessaires
        alerts_raw   = []
        forecasts_raw = {}
        metrics_raw  = {}

        with httpx.Client(timeout=20) as client:
            # Alertes
            try:
                r = client.get(f"{cfg.obs_api_url}/api/v1/alerts", headers=cfg.obs_headers)
                alerts_raw = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []
            except Exception:
                pass

            # Forecasts
            try:
                r = client.get(f"{cfg.obs_api_url}/api/v1/forecasts", headers=cfg.obs_headers)
                forecasts_raw = r.json() if r.status_code == 200 else {}
            except Exception:
                pass

        # Métriques actuelles
        metric_queries = {
            "cpu":        'avg(rate(node_cpu_seconds_total{mode!="idle"}[1h])) * 100',
            "memory":     "avg(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100",
            "error_rate": 'sum(rate(http_requests_total{status=~"5.."}[1h])) / sum(rate(http_requests_total[1h])) * 100',
        }
        for name, q in metric_queries.items():
            try:
                res = _vm_query(q)
                if res:
                    metrics_raw[name] = float(res[0]["value"][1])
            except Exception:
                pass

        # Construction du rapport
        now    = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
        period_label = {"day": "24 dernières heures", "week": "7 derniers jours", "hour": "Dernière heure"}.get(period, period)
        region_label = f" — {region}" if region else ""

        lines = [
            f"## Rapport d'infrastructure{region_label}",
            f"*{period_label} · Généré le {now}*\n",
            "### Métriques clés",
        ]

        for name, val in metrics_raw.items():
            status = "🔴" if val > 85 else "🟡" if val > 70 else "✅"
            lines.append(f"- {status} **{name.upper()}** : {val:.1f}%")

        lines.append("\n### Alertes actives")
        if alerts_raw:
            criticals = [a for a in alerts_raw if a.get("severity") == "critical"]
            warnings  = [a for a in alerts_raw if a.get("severity") == "warning"]
            lines.append(f"- 🔴 Critiques : **{len(criticals)}**")
            lines.append(f"- 🟡 Warnings : **{len(warnings)}**")
            for a in criticals[:3]:
                lines.append(f"  - {a.get('name','?')} ({a.get('service','?')})")
        else:
            lines.append("- ✅ Aucune alerte active")

        lines.append("\n### Prédictions de capacité")
        risks = {"critical": [], "warning": [], "ok": []}
        for metric, data in forecasts_raw.items():
            risks[data.get("risk_level", "ok")].append(
                f"{metric} (saturation dans {data.get('days_until_saturation', '—')}j)"
            )
        if risks["critical"]:
            lines.append(f"- 🔴 Risque critique : {', '.join(risks['critical'])}")
        if risks["warning"]:
            lines.append(f"- 🟡 À surveiller : {', '.join(risks['warning'])}")
        if risks["ok"]:
            lines.append(f"- ✅ Stable : {', '.join(risks['ok'])}")

        lines.append("\n### Recommandations")
        recs = []
        for m, v in metrics_raw.items():
            if v > 85:
                recs.append(f"- 🔴 **{m.upper()} critique** ({v:.0f}%) : action immédiate requise")
            elif v > 70:
                recs.append(f"- 🟡 **{m.upper()} élevé** ({v:.0f}%) : surveiller")
        if criticals:
            recs.append(f"- 🔴 **{len(criticals)} alertes critiques** à traiter en priorité")
        if not recs:
            lines.append("- ✅ Aucune action urgente — infrastructure stable")
        else:
            lines.extend(recs)

        return "\n".join(lines)

    except Exception as e:
        log.exception("generate_report error")
        return f"Erreur lors de la génération du rapport : {e}"


# ── Registre des outils ───────────────────────────────────────────────

ALL_TOOLS = [
    get_active_alerts,
    get_metrics,
    get_forecast,
    acknowledge_alert,
    generate_report,
]
