"""ObsAgent — LangChain agent avec Ollama et tools d'observabilité."""
from __future__ import annotations

import logging

from langchain.agents import AgentExecutor, initialize_agent, AgentType
from langchain_core.messages import AIMessage, HumanMessage
from langchain_ollama import ChatOllama
from langchain_core.callbacks import AsyncCallbackHandler
from langchain.memory import ConversationBufferWindowMemory

from backend.config import get_settings
from backend.tools.obs_tools import ALL_TOOLS

log = logging.getLogger(__name__)
cfg = get_settings()


SYSTEM_PREFIX = """Tu es un assistant expert en observabilité infra, connecté à une plateforme de monitoring en temps réel.

Tu peux utiliser ces outils :
- `get_active_alerts` : lister les alertes actives (filtres : severity, service, region)
- `get_metrics` : obtenir la valeur actuelle d'une métrique (cpu, memory, disk, rps, error_rate, latency_p99)
- `get_forecast` : prédiction de croissance et date de saturation pour une métrique
- `acknowledge_alert` : acquitter une alerte (stoppe les notifications)
- `generate_report` : rapport de synthèse de l'infrastructure (period: day/week/hour)

Règles :
1. Utilise toujours un outil pour obtenir des données réelles — ne jamais inventer des valeurs
2. Pour acquitter une alerte, demande confirmation si l'utilisateur n'a pas fourni l'alert_id exact
3. Réponds en français, de manière concise et structurée avec du Markdown
4. Si une métrique dépasse 80%, signale-le clairement
5. Pour les rapports, utilise generate_report puis synthétise les résultats
"""


class StreamingCallbackHandler(AsyncCallbackHandler):
    """Callback pour streamer les tokens au fur et à mesure."""

    def __init__(self, queue) -> None:
        self.queue = queue

    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        await self.queue.put(token)

    async def on_agent_finish(self, finish, **kwargs) -> None:
        await self.queue.put(None)


class ObsAgent:
    """Agent principal — instancié une fois par session WebSocket."""

    def __init__(self) -> None:
        self._llm = ChatOllama(
            base_url=cfg.ollama_base_url,
            model=cfg.ollama_model,
            temperature=0.1,
            num_predict=2048,
        )
        self._memory = ConversationBufferWindowMemory(
            memory_key="chat_history",
            return_messages=True,
            k=10,
        )
        self._executor = initialize_agent(
            tools=ALL_TOOLS,
            llm=self._llm,
            agent=AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
            verbose=True,
            memory=self._memory,
            max_iterations=6,
            handle_parsing_errors=True,
            agent_kwargs={
                "prefix": SYSTEM_PREFIX,
            },
        )

    async def chat(self, message: str) -> dict:
        """Traitement — retourne réponse + étapes intermédiaires."""
        try:
            result = await self._executor.ainvoke({"input": message})

            answer = result.get("output", "Je n'ai pas pu obtenir de réponse.")
            steps = [
                {"tool": s[0].tool, "input": s[0].tool_input, "output": str(s[1])[:500]}
                for s in result.get("intermediate_steps", [])
            ]

            return {"answer": answer, "steps": steps, "error": None}

        except Exception as e:
            log.exception("Agent error: %s", e)
            return {
                "answer": f"Une erreur s'est produite : {e}\nVérifie qu'Ollama est démarré.",
                "steps": [],
                "error": str(e),
            }

    def reset(self) -> None:
        """Réinitialise l'historique de la session."""
        self._memory.clear()


# ── Pool d'agents par session ─────────────────────────────────────────

_sessions: dict[str, ObsAgent] = {}


def get_agent(session_id: str) -> ObsAgent:
    if session_id not in _sessions:
        _sessions[session_id] = ObsAgent()
        log.info("New agent session: %s", session_id)
    return _sessions[session_id]


def delete_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
