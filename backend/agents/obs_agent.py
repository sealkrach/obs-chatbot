"""ObsAgent — LangChain ReAct agent avec Ollama et tools d'observabilité."""
from __future__ import annotations

import logging
from typing import AsyncIterator

from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_community.chat_models import ChatOllama
from langchain_core.callbacks import AsyncCallbackHandler

from backend.config import get_settings
from backend.tools.obs_tools import ALL_TOOLS

log = logging.getLogger(__name__)
cfg = get_settings()


SYSTEM_PROMPT = """Tu es un assistant expert en observabilité infra, connecté à une plateforme de monitoring en temps réel.

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

Contexte actuel :
- Région principale : {region}
- Environnement : {environment}
"""


class StreamingCallbackHandler(AsyncCallbackHandler):
    """Callback pour streamer les tokens au fur et à mesure."""

    def __init__(self, queue) -> None:
        self.queue = queue

    async def on_llm_new_token(self, token: str, **kwargs) -> None:
        await self.queue.put(token)

    async def on_agent_finish(self, finish, **kwargs) -> None:
        await self.queue.put(None)  # signal de fin


class ObsAgent:
    """Agent principal — instancié une fois par session WebSocket."""

    def __init__(self) -> None:
        self._llm = ChatOllama(
            base_url=cfg.ollama_base_url,
            model=cfg.ollama_model,
            temperature=0.1,      # déterministe pour l'infra
            num_predict=2048,
        )
        self._executor = self._build_executor()
        self._history: list = []

    def _build_executor(self) -> AgentExecutor:
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])

        agent = create_react_agent(
            llm=self._llm,
            tools=ALL_TOOLS,
            prompt=prompt,
        )

        return AgentExecutor(
            agent=agent,
            tools=ALL_TOOLS,
            verbose=True,
            max_iterations=6,
            handle_parsing_errors=True,
            return_intermediate_steps=True,
        )

    async def chat(self, message: str) -> dict:
        """Traitement synchrone — retourne réponse + étapes intermédiaires."""
        try:
            result = await self._executor.ainvoke({
                "input":        message,
                "chat_history": self._history,
                "region":       "eu-west-1",
                "environment":  "production",
            })

            answer = result.get("output", "Je n'ai pas pu obtenir de réponse.")
            steps  = [
                {"tool": s[0].tool, "input": s[0].tool_input, "output": str(s[1])[:500]}
                for s in result.get("intermediate_steps", [])
            ]

            # Mettre à jour l'historique (garder les 10 derniers échanges)
            self._history.append(HumanMessage(content=message))
            self._history.append(AIMessage(content=answer))
            if len(self._history) > 20:
                self._history = self._history[-20:]

            return {"answer": answer, "steps": steps, "error": None}

        except Exception as e:
            log.exception("Agent error: %s", e)
            return {
                "answer": f"Une erreur s'est produite : {e}\nVérifie qu'Ollama est démarré (`ollama serve`).",
                "steps":  [],
                "error":  str(e),
            }

    def reset(self) -> None:
        """Réinitialise l'historique de la session."""
        self._history.clear()


# ── Pool d'agents par session ─────────────────────────────────────────

_sessions: dict[str, ObsAgent] = {}


def get_agent(session_id: str) -> ObsAgent:
    if session_id not in _sessions:
        _sessions[session_id] = ObsAgent()
        log.info("New agent session: %s", session_id)
    return _sessions[session_id]


def delete_session(session_id: str) -> None:
    _sessions.pop(session_id, None)
