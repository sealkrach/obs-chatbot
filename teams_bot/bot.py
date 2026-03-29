"""Bot Microsoft Teams — Bot Framework adapter."""
from __future__ import annotations

import logging

from botbuilder.core import ActivityHandler, TurnContext, MessageFactory
from botbuilder.schema import Activity, ActivityTypes

from backend.agents.obs_agent import get_agent
from backend.config import get_settings

log = logging.getLogger(__name__)
cfg = get_settings()


class ObsTeamsBot(ActivityHandler):
    """Bot Teams qui route les messages vers l'ObsAgent."""

    async def on_message_activity(self, turn_context: TurnContext) -> None:
        user_id = turn_context.activity.from_property.id or "teams-user"
        text    = (turn_context.activity.text or "").strip()

        if not text:
            return

        # Indicateur "en train de taper"
        await turn_context.send_activity(Activity(type=ActivityTypes.typing))

        agent  = get_agent(f"teams-{user_id}")
        result = await agent.chat(text)

        # Construire la réponse avec les étapes si verbose
        answer = result["answer"]
        steps  = result.get("steps", [])

        if steps:
            tool_lines = "\n".join(
                f"🔧 `{s['tool']}` → {s['output'][:150]}…"
                for s in steps[:3]
            )
            full_reply = f"{tool_lines}\n\n---\n{answer}"
        else:
            full_reply = answer

        # Teams supporte Markdown dans les messages
        await turn_context.send_activity(
            MessageFactory.text(full_reply)
        )

    async def on_members_added_activity(self, members_added, turn_context: TurnContext) -> None:
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    MessageFactory.text(
                        "👋 Bonjour ! Je suis l'assistant d'observabilité.\n\n"
                        "Je peux :\n"
                        "- 🔴 Lister les alertes actives\n"
                        "- 📊 Interroger les métriques (CPU, mémoire, disque…)\n"
                        "- 📈 Donner des prédictions de capacité\n"
                        "- ✅ Acquitter une alerte\n"
                        "- 📋 Générer un rapport\n\n"
                        "Exemples : *\"Quelles alertes critiques ?\"*, "
                        "*\"CPU de api-gateway\"*, *\"Rapport du jour\"*"
                    )
                )


async def handle_teams_message(body: dict) -> dict:
    """Point d'entrée appelé depuis FastAPI."""
    from botbuilder.integration.aiohttp import CloudAdapter, ConfigurationBotFrameworkAuthentication
    from botbuilder.core.integration import aiohttp_error_middleware
    from botframework.connector.auth import AuthenticationConfiguration

    # En développement sans credentials : mode passthrough
    if not cfg.teams_app_id or not cfg.teams_app_password:
        log.warning("Teams credentials not configured — running in dev mode")
        text = body.get("text", "") or body.get("activity", {}).get("text", "")
        user = body.get("from", {}).get("id", "dev-user")
        if text:
            agent  = get_agent(f"teams-dev-{user}")
            result = await agent.chat(text)
            return {"type": "message", "text": result["answer"]}
        return {"type": "message", "text": "Message vide."}

    # Adapter Bot Framework complet
    bot = ObsTeamsBot()
    activity = Activity().deserialize(body)

    class BotConfig:
        APP_ID       = cfg.teams_app_id
        APP_PASSWORD = cfg.teams_app_password

    adapter = CloudAdapter(
        ConfigurationBotFrameworkAuthentication(BotConfig())
    )

    async def callback(tc: TurnContext):
        await bot.on_turn(tc)

    await adapter.process_activity(activity, "", callback)
    return {}
