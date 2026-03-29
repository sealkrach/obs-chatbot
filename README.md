# obs-chatbot — Assistant d'Observabilité

Chatbot connecté à obs-platform via tool-calling LLM (Ollama / llama3).  
Interfaces : web React + bot Microsoft Teams.

## Ce que le chatbot sait faire

- **Métriques & alertes** : "Quelles alertes sont actives en ce moment ?" · "Montre-moi le CPU de api-gateway"
- **Forecasts** : "Dans combien de temps le disque va saturer ?" · "Quel est le taux de croissance du RPS ?"
- **Acquittement** : "Acquitte l'alerte CPU sur api-gateway" · "Silence l'alerte #abc pendant 2h"
- **Rapports** : "Génère un résumé de la journée" · "Rapport hebdo de l'infra eu-west-1"

## Architecture

```
User (Web ou Teams)
    └── ChatRouter (FastAPI WebSocket / Teams Bot Framework)
            └── ObsAgent (LangChain AgentExecutor)
                    ├── LLM : Ollama (llama3.1 / mistral)
                    └── Tools
                            ├── get_active_alerts      → obs-platform API
                            ├── get_metrics            → VictoriaMetrics PromQL
                            ├── get_forecast           → obs-platform API
                            ├── acknowledge_alert      → obs-platform API
                            └── generate_report        → LLM synthesis
```

## Démarrage rapide

```bash
# Prérequis : obs-platform en cours d'exécution
# + Ollama installé : https://ollama.com

ollama pull llama3.1       # ou mistral, gemma2, etc.

cd obs-chatbot
cp .env.example .env
pip install -e ".[dev]"

# Backend
uvicorn backend.main:app --reload --port 8001

# Frontend (autre terminal)
cd frontend && npm install && npm run dev
# → http://localhost:5173
```

## Variables d'environnement

Voir `.env.example`. Les principales :
- `OBS_API_URL` : URL de l'API obs-platform (défaut: http://localhost:8000)
- `OLLAMA_BASE_URL` : URL Ollama (défaut: http://localhost:11434)
- `OLLAMA_MODEL` : modèle à utiliser (défaut: llama3.1)
- `TEAMS_APP_ID` / `TEAMS_APP_PASSWORD` : pour le bot Teams

## Structure

```
obs-chatbot/
├── backend/
│   ├── main.py          — FastAPI + WebSocket
│   ├── agents/          — ObsAgent LangChain
│   ├── tools/           — Outils LLM (métriques, alertes, ack, rapport)
│   └── routers/         — REST + WebSocket + Teams webhook
├── frontend/
│   └── src/
│       ├── components/  — ChatWindow, MessageBubble, AlertCard
│       └── hooks/       — useChat (WebSocket)
└── teams-bot/
    └── bot.py           — Bot Framework adapter
```
