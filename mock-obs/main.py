"""Mock obs-platform API — retourne des données réalistes simulées."""
import random
import time
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Mock obs-platform", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Données simulées ────────────────────────────────────────────────

SERVICES = ["api-gateway", "auth-service", "payment-service", "user-service", "notification-service", "search-service"]
REGIONS = ["eu-west-1", "eu-central-1", "us-east-1"]

def _rand_alerts():
    templates = [
        {"name": "HighCPU", "severity": "critical", "message": "CPU usage above 90% for 10 minutes"},
        {"name": "HighMemory", "severity": "warning", "message": "Memory usage above 80%"},
        {"name": "HighErrorRate", "severity": "critical", "message": "Error rate above 5% on 5xx responses"},
        {"name": "DiskSpaceLow", "severity": "warning", "message": "Disk usage above 85%"},
        {"name": "HighLatency", "severity": "warning", "message": "P99 latency above 2s"},
        {"name": "PodCrashLoop", "severity": "critical", "message": "Pod restarting repeatedly"},
        {"name": "CertExpiringSoon", "severity": "warning", "message": "TLS certificate expires in 7 days"},
        {"name": "DatabaseConnectionPoolExhausted", "severity": "critical", "message": "Connection pool at 98%"},
    ]
    count = random.randint(2, 6)
    alerts = []
    for i, t in enumerate(random.sample(templates, min(count, len(templates)))):
        alerts.append({
            "id": f"alert-{1000 + i}",
            "name": t["name"],
            "severity": t["severity"],
            "service": random.choice(SERVICES),
            "region": random.choice(REGIONS),
            "message": t["message"],
            "started_at": (datetime.now(timezone.utc) - timedelta(minutes=random.randint(5, 180))).isoformat(),
            "status": "firing",
        })
    return alerts

ALERTS = _rand_alerts()


# ── Endpoints ────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/alerts")
def get_alerts(severity: str = None, service: str = None, region: str = None):
    result = ALERTS
    if severity:
        result = [a for a in result if a["severity"] == severity]
    if service:
        result = [a for a in result if a["service"] == service]
    if region:
        result = [a for a in result if a["region"] == region]
    return result


@app.post("/api/v1/alerts/acknowledge")
def ack_alert(body: dict):
    alert_id = body.get("alert_id", "")
    for a in ALERTS:
        if a["id"] == alert_id:
            a["status"] = "acknowledged"
            return {"status": "ok", "alert_id": alert_id, "acknowledged": True}
    return {"status": "not_found", "alert_id": alert_id}


@app.get("/api/v1/forecasts/{metric}")
def get_forecast(metric: str, horizon_days: int = 30):
    base_values = {
        "cpu_usage": random.uniform(55, 75),
        "memory_usage": random.uniform(60, 80),
        "disk_usage": random.uniform(50, 70),
        "rps": random.uniform(1200, 3500),
        "error_rate": random.uniform(0.5, 3.0),
    }
    current = base_values.get(metric, random.uniform(40, 70))
    growth = random.uniform(0.5, 4.0)
    predicted = current + (growth * horizon_days / 30)
    peak = predicted * random.uniform(1.05, 1.2)
    days_to_sat = None
    risk = "ok"
    if predicted > 90:
        days_to_sat = int((90 - current) / (growth / 30)) if growth > 0 else None
        risk = "critical"
    elif predicted > 75:
        days_to_sat = int((90 - current) / (growth / 30)) if growth > 0 else None
        risk = "warning"

    return {
        "metric": metric,
        "current_value": round(current, 1),
        "predicted_30d": round(predicted, 1),
        "predicted_peak": round(peak, 1),
        "growth_rate_pct": round(growth, 1),
        "days_until_saturation": days_to_sat,
        "risk_level": risk,
        "horizon_days": horizon_days,
    }


@app.get("/api/v1/forecasts")
def get_all_forecasts():
    metrics = ["cpu_usage", "memory_usage", "disk_usage", "rps", "error_rate"]
    return {m: get_forecast(m) for m in metrics}


# ── Mock VictoriaMetrics PromQL ──────────────────────────────────────

@app.get("/api/v1/query")
def promql_query(query: str = ""):
    """Simule une réponse VictoriaMetrics PromQL."""
    now = time.time()

    if "cpu" in query.lower():
        value = random.uniform(35, 88)
    elif "memory" in query.lower() or "mem" in query.lower():
        value = random.uniform(50, 85)
    elif "disk" in query.lower() or "filesystem" in query.lower():
        value = random.uniform(40, 75)
    elif "error" in query.lower() or "5.." in query:
        value = random.uniform(0.2, 4.5)
    elif "latency" in query.lower() or "duration" in query.lower():
        value = random.uniform(0.05, 2.8)
    elif "request" in query.lower() or "http" in query.lower():
        value = random.uniform(500, 5000)
    else:
        value = random.uniform(10, 90)

    results = []
    for svc in random.sample(SERVICES, min(3, len(SERVICES))):
        results.append({
            "metric": {"__name__": "mock_metric", "service": svc, "region": "eu-west-1"},
            "value": [now, str(round(value + random.uniform(-5, 5), 2))],
        })

    return {"status": "success", "data": {"resultType": "vector", "result": results}}
