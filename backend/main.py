"""Backend FastAPI — WebSocket chat + REST + Teams webhook."""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import get_settings
from backend.llm_config import get_llm_config, update_llm_config
from backend.agents.obs_agent import get_agent, delete_session, clear_all_sessions

log = logging.getLogger(__name__)
cfg = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("obs-chatbot starting — model=%s ollama=%s", cfg.ollama_model, cfg.ollama_base_url)
    yield
    log.info("obs-chatbot shutting down")


app = FastAPI(
    title="obs-chatbot API",
    version="1.0.0",
    description="Chatbot d'observabilité — Ollama + LangChain",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    import httpx
    llm_cfg = get_llm_config()
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{cfg.ollama_base_url}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:
        pass
    return {
        "status": "ok",
        "ollama": ollama_ok,
        "provider": llm_cfg["provider"],
        "model": llm_cfg["openai_model"] if llm_cfg["provider"] == "openai" else llm_cfg["ollama_model"],
    }


# ── LLM config endpoints ─────────────────────────────────────────────

class LLMConfigRequest(BaseModel):
    provider: str = "ollama"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_model: str = "llama3.1"


@app.get("/api/llm/config")
async def get_llm_config_endpoint():
    llm_cfg = get_llm_config()
    return {
        "provider": llm_cfg["provider"],
        "openai_api_key_set": bool(llm_cfg["openai_api_key"]),
        "openai_api_key_preview": llm_cfg["openai_api_key"][:8] + "…" if llm_cfg["openai_api_key"] else "",
        "openai_model": llm_cfg["openai_model"],
        "openai_base_url": llm_cfg["openai_base_url"],
        "ollama_model": llm_cfg["ollama_model"],
    }


@app.put("/api/llm/config")
async def update_llm_config_endpoint(req: LLMConfigRequest):
    update_llm_config(
        provider=req.provider,
        openai_api_key=req.openai_api_key,
        openai_model=req.openai_model,
        openai_base_url=req.openai_base_url,
        ollama_model=req.ollama_model,
    )
    clear_all_sessions()
    llm_cfg = get_llm_config()
    return {"status": "ok", "provider": llm_cfg["provider"]}


@app.post("/api/llm/test")
async def test_llm_connection():
    """Test connectivity with the currently configured LLM provider."""
    import httpx
    llm_cfg = get_llm_config()

    if llm_cfg["provider"] == "openai":
        if not llm_cfg["openai_api_key"]:
            return {"ok": False, "error": "Aucune clé API configurée"}
        try:
            base = llm_cfg["openai_base_url"].rstrip("/")
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    f"{base}/models",
                    headers={"Authorization": f"Bearer {llm_cfg['openai_api_key']}"},
                )
            if r.status_code == 200:
                models = r.json().get("data", [])
                model_ids = [m.get("id", "") for m in models[:10]]
                target = llm_cfg["openai_model"]
                found = any(target in mid for mid in model_ids)
                return {
                    "ok": True,
                    "provider": "openai",
                    "model": target,
                    "model_available": found,
                    "models_sample": model_ids[:5],
                }
            elif r.status_code == 401:
                return {"ok": False, "error": "Clé API invalide (401 Unauthorized)"}
            else:
                return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except httpx.ConnectError:
            return {"ok": False, "error": f"Impossible de contacter {llm_cfg['openai_base_url']}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    else:  # ollama
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{cfg.ollama_base_url}/api/tags")
            if r.status_code != 200:
                return {"ok": False, "error": f"Ollama HTTP {r.status_code}"}
            models = [m["name"] for m in r.json().get("models", [])]
            target = llm_cfg["ollama_model"]
            found = any(target in m for m in models)
            return {
                "ok": True,
                "provider": "ollama",
                "model": target,
                "model_available": found,
                "models_available": models,
            }
        except httpx.ConnectError:
            return {"ok": False, "error": f"Impossible de contacter Ollama ({cfg.ollama_base_url})"}
        except Exception as e:
            return {"ok": False, "error": str(e)}


@app.post("/api/llm/models")
async def list_available_models():
    """Fetch available models from the current provider."""
    import httpx
    llm_cfg = get_llm_config()

    if llm_cfg["provider"] == "openai":
        if not llm_cfg["openai_api_key"]:
            return {"ok": False, "models": [], "error": "Aucune clé API configurée"}
        try:
            base = llm_cfg["openai_base_url"].rstrip("/")
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(
                    f"{base}/models",
                    headers={"Authorization": f"Bearer {llm_cfg['openai_api_key']}"},
                )
            if r.status_code == 200:
                all_models = [m.get("id", "") for m in r.json().get("data", [])]
                # Filter to chat models only
                chat_models = sorted([m for m in all_models if any(k in m for k in ("gpt", "o1", "o3", "claude", "mistral", "llama", "gemma", "command", "deepseek"))])
                return {"ok": True, "models": chat_models if chat_models else sorted(all_models)}
            elif r.status_code == 401:
                return {"ok": False, "models": [], "error": "Clé API invalide"}
            else:
                return {"ok": False, "models": [], "error": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "models": [], "error": str(e)}
    else:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(f"{cfg.ollama_base_url}/api/tags")
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                return {"ok": True, "models": sorted(models)}
            return {"ok": False, "models": [], "error": f"Ollama HTTP {r.status_code}"}
        except Exception as e:
            return {"ok": False, "models": [], "error": str(e)}


# ── Collector config + query endpoints ────────────────────────────────

class CollectorConfigRequest(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = None
    metrics: dict | None = None


@app.get("/api/collector/config")
async def get_collector_config_endpoint():
    from backend.collector.macos_collector import get_collector_config as gcc
    return gcc()


@app.put("/api/collector/config")
async def update_collector_config_endpoint(req: CollectorConfigRequest):
    from backend.collector.macos_collector import update_collector_config as ucc, get_collector_config as gcc, start_collector, stop_collector
    ucc(enabled=req.enabled, interval_seconds=req.interval_seconds, metrics=req.metrics)
    if req.enabled:
        start_collector()
    elif req.enabled is False:
        stop_collector()
    return {"status": "ok", **gcc()}


@app.post("/api/collector/collect")
async def trigger_collection():
    import asyncio
    from backend.collector.macos_collector import collect_once
    try:
        await asyncio.wait_for(asyncio.to_thread(collect_once), timeout=10)
        return {"status": "ok", "message": "Collection done"}
    except asyncio.TimeoutError:
        return {"status": "partial", "message": "Collection timed out but partial data may be available"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/collector/metrics")
async def query_metrics(metric: str | None = None, last_minutes: int = 5, last_n: int = 100):
    from backend.collector.metrics_store import store
    if metric:
        data = store.query(metric_name=metric, last_n=last_n, since_seconds=last_minutes * 60)
    else:
        data = store.latest()
    return {"count": len(data), "data": data}


@app.get("/api/collector/stats")
async def collector_stats():
    from backend.collector.metrics_store import store
    return store.stats()


# ── REST chat (simple, sans streaming) ────────────────────────────────

class ChatRequest(BaseModel):
    message:    str
    session_id: str = ""

class ChatResponse(BaseModel):
    answer:     str
    steps:      list[dict]
    session_id: str
    error:      str | None = None


@app.post("/api/chat", response_model=ChatResponse)
async def chat_rest(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    agent      = get_agent(session_id)
    result     = await agent.chat(req.message)
    return ChatResponse(session_id=session_id, **result)


@app.delete("/api/chat/{session_id}")
async def reset_session(session_id: str):
    delete_session(session_id)
    return {"status": "reset", "session_id": session_id}


# ── WebSocket chat (avec streaming des étapes) ────────────────────────

@app.websocket("/ws/chat/{session_id}")
async def websocket_chat(ws: WebSocket, session_id: str):
    await ws.accept()
    log.info("WS connected: %s", session_id)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"message": raw}

            msg = data.get("message", "").strip()
            if not msg:
                continue

            # Re-fetch agent each message so config changes take effect
            agent = get_agent(session_id)

            if msg.lower() in ("/reset", "/clear"):
                agent.reset()
                await ws.send_json({"type": "system", "text": "Historique réinitialisé."})
                continue

            await ws.send_json({"type": "thinking", "text": "Analyse en cours…"})

            result = await agent.chat(msg)

            for step in result.get("steps", []):
                await ws.send_json({
                    "type":   "tool_call",
                    "tool":   step["tool"],
                    "input":  str(step["input"])[:200],
                    "output": step["output"][:300],
                })

            if result.get("error"):
                await ws.send_json({"type": "error", "text": result["answer"]})
            else:
                await ws.send_json({"type": "answer", "text": result["answer"]})

    except WebSocketDisconnect:
        log.info("WS disconnected: %s", session_id)
    except Exception as e:
        log.exception("WS error: %s", e)
        try:
            await ws.send_json({"type": "error", "text": str(e)})
        except Exception:
            pass


# ── Teams incoming webhook (Bot Framework) ───────────────────────────

@app.post("/api/teams/messages")
async def teams_messages(request_body: dict):
    from teams_bot.bot import handle_teams_message
    try:
        response = await handle_teams_message(request_body)
        return response
    except Exception as e:
        log.exception("Teams bot error: %s", e)
        raise HTTPException(500, str(e))


# ── Entry point ────────────────────────────────────────────────────────

def main():
    import uvicorn
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run("backend.main:app",
                host=cfg.chatbot_host,
                port=cfg.chatbot_port,
                reload=True)


if __name__ == "__main__":
    main()
