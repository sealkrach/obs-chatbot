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
from backend.agents.obs_agent import get_agent, delete_session

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


# ── LLM runtime config (mutable) ─────────────────────────────────────

_llm_config = {
    "provider": cfg.llm_provider,
    "openai_api_key": cfg.openai_api_key,
    "openai_model": cfg.openai_model,
    "openai_base_url": cfg.openai_base_url,
    "ollama_model": cfg.ollama_model,
}


def get_llm_config() -> dict:
    return _llm_config


# ── Health ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    import httpx
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
        "provider": _llm_config["provider"],
        "model": _llm_config["openai_model"] if _llm_config["provider"] == "openai" else _llm_config["ollama_model"],
    }


# ── LLM config endpoints ─────────────────────────────────────────────

class LLMConfigRequest(BaseModel):
    provider: str = "ollama"             # "ollama" or "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_model: str = "llama3.1"


@app.get("/api/llm/config")
async def get_llm_config_endpoint():
    return {
        "provider": _llm_config["provider"],
        "openai_api_key_set": bool(_llm_config["openai_api_key"]),
        "openai_api_key_preview": _llm_config["openai_api_key"][:8] + "…" if _llm_config["openai_api_key"] else "",
        "openai_model": _llm_config["openai_model"],
        "openai_base_url": _llm_config["openai_base_url"],
        "ollama_model": _llm_config["ollama_model"],
    }


@app.put("/api/llm/config")
async def update_llm_config(req: LLMConfigRequest):
    from backend.agents.obs_agent import clear_all_sessions
    _llm_config["provider"] = req.provider
    if req.openai_api_key:
        _llm_config["openai_api_key"] = req.openai_api_key
    _llm_config["openai_model"] = req.openai_model
    _llm_config["openai_base_url"] = req.openai_base_url
    _llm_config["ollama_model"] = req.ollama_model
    # Reset all agent sessions so they pick up the new LLM
    clear_all_sessions()
    return {"status": "ok", "provider": _llm_config["provider"]}


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
    """Endpoint REST — envoie un message, reçoit la réponse complète."""
    session_id = req.session_id or str(uuid.uuid4())
    agent      = get_agent(session_id)
    result     = await agent.chat(req.message)
    return ChatResponse(session_id=session_id, **result)


@app.delete("/api/chat/{session_id}")
async def reset_session(session_id: str):
    """Réinitialise l'historique d'une session."""
    delete_session(session_id)
    return {"status": "reset", "session_id": session_id}


# ── WebSocket chat (avec streaming des étapes) ────────────────────────

@app.websocket("/ws/chat/{session_id}")
async def websocket_chat(ws: WebSocket, session_id: str):
    """
    WebSocket bidirectionnel.
    Protocole :
      Client → {"message": "..."} 
      Server → {"type": "thinking", "tool": "...", "input": "..."}  (étapes)
              → {"type": "answer",   "text": "..."}                 (réponse finale)
              → {"type": "error",    "text": "..."}                 (erreur)
    """
    await ws.accept()
    log.info("WS connected: %s", session_id)
    agent = get_agent(session_id)

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

            if msg.lower() in ("/reset", "/clear"):
                agent.reset()
                await ws.send_json({"type": "system", "text": "Historique réinitialisé."})
                continue

            # Envoyer un indicateur "en cours de réflexion"
            await ws.send_json({"type": "thinking", "text": "Analyse en cours…"})

            result = await agent.chat(msg)

            # Envoyer les étapes intermédiaires (tools utilisés)
            for step in result.get("steps", []):
                await ws.send_json({
                    "type":   "tool_call",
                    "tool":   step["tool"],
                    "input":  str(step["input"])[:200],
                    "output": step["output"][:300],
                })

            # Réponse finale
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
    """
    Reçoit les messages Teams via Bot Framework.
    Configure l'URL dans le portail Azure Bot comme messaging endpoint.
    """
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
