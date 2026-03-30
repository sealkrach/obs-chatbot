"""ObsAgent — LangChain agent avec Ollama ou OpenAI et tools d'observabilité."""
from __future__ import annotations

import logging

from langchain.agents import AgentExecutor, create_tool_calling_agent, create_structured_chat_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_ollama import ChatOllama

from backend.config import get_settings
from backend.tools.obs_tools import ALL_TOOLS
from backend.collector.mcp_tools import MCP_TOOLS

log = logging.getLogger(__name__)
cfg = get_settings()


COMBINED_TOOLS = ALL_TOOLS + MCP_TOOLS

SYSTEM_MSG = """Tu es un assistant expert en observabilité infra, connecté à une plateforme de monitoring en temps réel ET à un collecteur de métriques macOS local (OpenTelemetry).

Tu as deux types d'outils :
- **Outils plateforme** : get_active_alerts, get_metrics, get_forecast, acknowledge_alert, generate_report — pour la plateforme d'observabilité distante
- **Outils locaux (MCP/OTLP)** : get_local_metrics, get_system_summary, list_collected_metrics — pour les métriques du Mac local collectées via OpenTelemetry

Règles :
1. Utilise toujours un outil pour obtenir des données réelles — ne jamais inventer des valeurs
2. Pour les métriques du système local (CPU, RAM, disque du Mac), utilise get_system_summary ou get_local_metrics
3. Pour les alertes et métriques de la plateforme distante, utilise get_active_alerts, get_metrics, etc.
4. Réponds en français, de manière concise et structurée avec du Markdown
5. Si une métrique dépasse 80%, signale-le clairement"""


def _build_llm():
    """Build the LLM based on current runtime config."""
    from backend.llm_config import get_llm_config
    llm_cfg = get_llm_config()

    if llm_cfg["provider"] == "openai" and llm_cfg["openai_api_key"]:
        from langchain_openai import ChatOpenAI
        log.info("Using OpenAI: model=%s base_url=%s", llm_cfg["openai_model"], llm_cfg["openai_base_url"])
        return "openai", ChatOpenAI(
            api_key=llm_cfg["openai_api_key"],
            model=llm_cfg["openai_model"],
            base_url=llm_cfg["openai_base_url"],
            temperature=0.1,
            max_tokens=2048,
        )
    else:
        log.info("Using Ollama: model=%s", llm_cfg["ollama_model"])
        return "ollama", ChatOllama(
            base_url=cfg.ollama_base_url,
            model=llm_cfg["ollama_model"],
            temperature=0.1,
            num_predict=2048,
        )


def _build_executor(provider: str, llm) -> AgentExecutor:
    """Build agent executor — tool_calling for OpenAI, structured_chat for Ollama."""

    if provider == "openai":
        # OpenAI supports native tool calling
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_MSG),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])
        agent = create_tool_calling_agent(llm=llm, tools=COMBINED_TOOLS, prompt=prompt)
    else:
        # Ollama: use structured chat with JSON action format
        system_with_tools = SYSTEM_MSG + """

Tu as accès aux outils suivants :

{tools}

Pour utiliser un outil, réponds UNIQUEMENT avec un bloc JSON markdown :

```json
{{{{
  "action": "<nom de l'outil>",
  "action_input": {{{{<paramètres>}}}}
}}}}
```

Quand tu as la réponse finale :

```json
{{{{
  "action": "Final Answer",
  "action_input": "<ta réponse>"
}}}}
```

Outils disponibles : {tool_names}"""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_with_tools),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            ("ai", "{agent_scratchpad}"),
        ])
        agent = create_structured_chat_agent(llm=llm, tools=COMBINED_TOOLS, prompt=prompt)

    return AgentExecutor(
        agent=agent,
        tools=COMBINED_TOOLS,
        verbose=True,
        max_iterations=6,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


class ObsAgent:
    """Agent principal — instancié une fois par session WebSocket."""

    def __init__(self) -> None:
        provider, llm = _build_llm()
        self._executor = _build_executor(provider, llm)
        self._history: list = []

    async def chat(self, message: str) -> dict:
        try:
            from langchain_core.messages import HumanMessage, AIMessage
            result = await self._executor.ainvoke({
                "input": message,
                "chat_history": self._history,
            })
            answer = result.get("output", "Je n'ai pas pu obtenir de réponse.")
            steps = [
                {"tool": s[0].tool, "input": s[0].tool_input, "output": str(s[1])[:500]}
                for s in result.get("intermediate_steps", [])
            ]
            self._history.append(HumanMessage(content=message))
            self._history.append(AIMessage(content=answer))
            if len(self._history) > 20:
                self._history = self._history[-20:]
            return {"answer": answer, "steps": steps, "error": None}
        except Exception as e:
            log.exception("Agent error: %s", e)
            return {
                "answer": f"Une erreur s'est produite : {e}",
                "steps": [],
                "error": str(e),
            }

    def reset(self) -> None:
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


def clear_all_sessions() -> None:
    _sessions.clear()
    log.info("All agent sessions cleared (LLM config changed)")
