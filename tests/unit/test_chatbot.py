"""Tests unitaires — tools, agent et API chatbot."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient


# ── Tests Tools ───────────────────────────────────────────────────────

class TestObsTools:

    @patch("backend.tools.obs_tools.httpx.Client")
    def test_get_active_alerts_with_data(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"id": "a1", "name": "CPUHigh", "severity": "critical",
             "service": "api-gateway", "region": "eu-west-1", "message": "CPU at 95%"},
            {"id": "a2", "name": "MemHigh", "severity": "warning",
             "service": "db-primary",  "region": "eu-west-1", "message": "Mem at 82%"},
        ]
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

        from backend.tools.obs_tools import get_active_alerts
        result = get_active_alerts.invoke({"severity": None, "service": None, "region": None})

        assert "2 alerte(s)" in result
        assert "CPUHigh" in result
        assert "CRITICAL" in result

    @patch("backend.tools.obs_tools.httpx.Client")
    def test_get_active_alerts_empty(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

        from backend.tools.obs_tools import get_active_alerts
        result = get_active_alerts.invoke({})
        assert "Aucune alerte" in result

    @patch("backend.tools.obs_tools._vm_query")
    def test_get_metrics_cpu(self, mock_vm):
        mock_vm.return_value = [
            {"metric": {"service": "api-gateway"}, "value": [0, "72.5"]}
        ]
        from backend.tools.obs_tools import get_metrics
        result = get_metrics.invoke({"metric": "cpu", "service": "api-gateway", "region": None, "duration": "5m"})
        assert "72.5" in result or "72" in result
        assert "cpu" in result.lower()

    @patch("backend.tools.obs_tools._vm_query")
    def test_get_metrics_no_data(self, mock_vm):
        mock_vm.return_value = []
        from backend.tools.obs_tools import get_metrics
        result = get_metrics.invoke({"metric": "cpu", "service": None, "region": None, "duration": "5m"})
        assert "Aucune donnée" in result

    @patch("backend.tools.obs_tools._obs")
    def test_get_forecast_ok(self, mock_obs):
        mock_obs.return_value = {
            "risk_level": "warning",
            "current_value": 65.0,
            "predicted_30d": 78.0,
            "growth_rate_pct": 20.0,
            "predicted_peak": 82.0,
            "days_until_saturation": 25,
        }
        from backend.tools.obs_tools import get_forecast
        result = get_forecast.invoke({"metric": "cpu_usage", "horizon_days": 30})
        assert "78.0" in result or "78" in result
        assert "25" in result
        assert "warning" in result.lower() or "⚠️" in result

    @patch("backend.tools.obs_tools._obs")
    def test_acknowledge_alert_success(self, mock_obs):
        mock_obs.return_value = {"status": "acknowledged", "silence_id": "sil-123"}
        from backend.tools.obs_tools import acknowledge_alert
        result = acknowledge_alert.invoke({
            "alert_id": "alert-abc",
            "reason": "Test ack",
            "silence_hours": 2,
        })
        assert "acquittée" in result.lower()
        assert "alert-abc" in result

    @patch("backend.tools.obs_tools._obs")
    @patch("backend.tools.obs_tools._vm_query")
    def test_generate_report_structure(self, mock_vm, mock_obs):
        mock_obs.return_value = {
            "cpu_usage": {"risk_level": "ok", "current_value": 45.0,
                          "predicted_30d": 50.0, "growth_rate_pct": 5.0,
                          "days_until_saturation": None}
        }
        mock_vm.return_value = [{"metric": {}, "value": [0, "45.0"]}]

        from backend.tools.obs_tools import generate_report
        result = generate_report.invoke({"period": "day", "region": None})

        assert "Rapport" in result
        assert "Métriques" in result or "métriques" in result


# ── Tests API ─────────────────────────────────────────────────────────

class TestChatbotAPI:

    @pytest.fixture
    def client(self):
        from backend.main import app
        return TestClient(app)

    def test_health(self, client):
        with patch("httpx.AsyncClient") as mock:
            mock.return_value.__aenter__.return_value.get = AsyncMock(
                return_value=MagicMock(status_code=200)
            )
            r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "model" in data

    @patch("backend.main.get_agent")
    def test_chat_rest_endpoint(self, mock_get_agent, client):
        mock_agent = AsyncMock()
        mock_agent.chat = AsyncMock(return_value={
            "answer": "2 alertes critiques actives : CPUHigh, MemHigh.",
            "steps":  [{"tool": "get_active_alerts", "input": "{}", "output": "2 alertes"}],
            "error":  None,
        })
        mock_get_agent.return_value = mock_agent

        r = client.post("/api/chat", json={
            "message":    "Quelles alertes actives ?",
            "session_id": "test-session-001",
        })
        assert r.status_code == 200
        data = r.json()
        assert "answer" in data
        assert "session_id" in data
        assert data["session_id"] == "test-session-001"

    @patch("backend.main.get_agent")
    def test_chat_rest_new_session(self, mock_get_agent, client):
        mock_agent = AsyncMock()
        mock_agent.chat = AsyncMock(return_value={
            "answer": "OK", "steps": [], "error": None
        })
        mock_get_agent.return_value = mock_agent

        # Sans session_id → doit en créer un
        r = client.post("/api/chat", json={"message": "test"})
        assert r.status_code == 200
        data = r.json()
        assert len(data["session_id"]) > 0

    def test_delete_session(self, client):
        with patch("backend.main.delete_session") as mock_del:
            r = client.delete("/api/chat/test-session-001")
        assert r.status_code == 200
        mock_del.assert_called_once_with("test-session-001")


# ── Tests Agent session management ────────────────────────────────────

class TestAgentSessions:

    def test_get_agent_creates_new(self):
        from backend.agents.obs_agent import get_agent, delete_session, _sessions
        sid = "test-unique-session-xyz"
        delete_session(sid)  # s'assurer qu'il n'existe pas
        agent = get_agent(sid)
        assert agent is not None
        assert sid in _sessions
        delete_session(sid)

    def test_get_agent_returns_same_instance(self):
        from backend.agents.obs_agent import get_agent, delete_session
        sid = "test-same-instance"
        delete_session(sid)
        a1 = get_agent(sid)
        a2 = get_agent(sid)
        assert a1 is a2
        delete_session(sid)

    def test_delete_session_removes_agent(self):
        from backend.agents.obs_agent import get_agent, delete_session, _sessions
        sid = "test-delete"
        get_agent(sid)
        assert sid in _sessions
        delete_session(sid)
        assert sid not in _sessions

    def test_reset_clears_history(self):
        from backend.agents.obs_agent import ObsAgent
        from langchain_core.messages import HumanMessage
        agent = ObsAgent.__new__(ObsAgent)
        agent._history = [HumanMessage(content="test")]
        agent.reset()
        assert agent._history == []
