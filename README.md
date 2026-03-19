# Voice Scheduling Agent — Agora Conversational AI Engine

Real-time voice agent for meeting scheduling, built on **Agora RTC** and **Agora Conversational AI Engine (CAE)** with tool orchestration via **MCP**.

## What it does

Speak naturally to create, query, reschedule, or cancel meetings on Google Calendar — with confirmation flow, memory, conflict detection, and proactive suggestions.

### Key capabilities

- **Agora RTC** — real-time audio channel between user and agent
- **Agora CAE** — end-to-end voice agent lifecycle (ASR → LLM → TTS) managed by Agora's API
- **MCP tools** — structured tool layer exposing calendar operations to the CAE agent
- **Google Calendar** — real CRUD operations with conflict detection, recurrence, and attendees
- **MongoDB** — session memory, action logs, meeting patterns, user preferences
- **Multi-language** — PT-BR / EN / ES interface and conversation
- **Streaming SSE** — incremental response delivery
- **Operational trace** — per-turn agent trace with steps and context

## 1) Prerequisites

- Python 3.11+
- MongoDB running locally
- Agora project (App ID + temp token from [Agora Console](https://console.agora.io))
- Google Calendar OAuth credentials (`credentials.json`)
- At least one TTS provider key (OpenAI, Azure, or ElevenLabs)
- Public URL for LLM callback (e.g. `ngrok http 8000`)

## 2) Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` with your credentials (see below).

## 3) Configure Agora CAE

### Required credentials

| Variable | Source |
|---|---|
| `AGORA_APP_ID` | Agora Console → Project |
| `AGORA_TEMP_TOKEN` | Agora Console → Temp Token (match channel name) |
| `AGORA_CAE_CUSTOMER_ID` | Agora Console → RESTful API credentials |
| `AGORA_CAE_CUSTOMER_SECRET` | Agora Console → RESTful API credentials |

### LLM callback (expose local backend)

```bash
ngrok http 8000
```

Then set in `.env`:

```
AGORA_CAE_PUBLIC_BASE_URL=https://<your-ngrok-url>
AGORA_CAE_MCP_ENDPOINT=https://<your-ngrok-url>/api/cae/mcp
```

### TTS provider (choose one)

Set `AGORA_CAE_TTS_VENDOR` to `openai`, `microsoft`, or `elevenlabs`, then fill the matching keys:

**OpenAI** (recommended — most accessible):
```
AGORA_CAE_TTS_VENDOR=openai
AGORA_CAE_TTS_OPENAI_KEY=sk-...
```

**Microsoft Azure**:
```
AGORA_CAE_TTS_VENDOR=microsoft
AGORA_CAE_TTS_AZURE_KEY=...
AGORA_CAE_TTS_AZURE_REGION=eastus
```

**ElevenLabs**:
```
AGORA_CAE_TTS_VENDOR=elevenlabs
AGORA_CAE_TTS_ELEVENLABS_KEY=...
```

## 4) Run

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000):

1. Click **Conectar Agora** — joins the RTC channel and publishes microphone.
2. When CAE is active, speak naturally — the agent listens, processes, and replies in real time.
3. When CAE is unavailable, use **Start voice** / **Stop capture** for local STT fallback.
4. Text chat is always available as an alternative input.

## 5) Conversation flows

- Create: "Marque uma reuniao amanha as 15h com joao@empresa.com"
- Query: "Tenho algum compromisso na quarta?"
- Reschedule: "Reagende minha reuniao de hoje para 18h"
- Cancel: "Cancele minha reuniao com o time"
- Repeat pattern: "Repita o padrao da ultima reuniao"
- Recurrence: "Crie uma reuniao recorrente toda semana"

Critical actions require explicit confirmation (`sim`/`nao` or `yes`/`no`).

## 6) Architecture

```
User (browser)
  ├── Agora RTC SDK ──► Agora RTC Channel
  │                         ▼
  │                   Agora CAE Agent
  │                   ├── ASR (ares)
  │                   ├── LLM callback ──► FastAPI backend
  │                   │                     ├── IntentService
  │                   │                     ├── ConversationService
  │                   │                     └── MemoryService
  │                   ├── MCP tools ──────► CalendarMcpTools
  │                   │                     └── SchedulerService
  │                   │                          └── Google Calendar API
  │                   └── TTS (openai/azure/elevenlabs)
  │
  └── Chat / Voice UI ──► REST API
                           ├── /api/conversation/{id}/message/stream
                           ├── /api/cae/agent/start|stop|status
                           ├── /api/cae/llm (CAE LLM callback)
                           ├── /api/cae/mcp (MCP tool gateway)
                           └── /api/system/health|metrics|stt
```

## 7) Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/conversation/{id}/message` | Send message (sync) |
| POST | `/api/conversation/{id}/message/stream` | Send message (SSE stream) |
| GET | `/api/conversation/{id}/trace` | Operational trace |
| GET | `/api/conversation/{id}/proactive` | Proactive suggestions |
| GET/POST | `/api/conversation/{id}/voice/*` | Voice turn state |
| POST | `/api/cae/agent/start` | Start CAE agent |
| POST | `/api/cae/agent/stop/{id}` | Stop CAE agent |
| GET | `/api/cae/agent/status/{id}` | Agent status |
| POST | `/api/cae/llm` | LLM callback (OpenAI style) |
| POST | `/api/cae/mcp` | MCP tool gateway |
| GET | `/api/system/health` | Health check |
| GET | `/api/system/metrics` | Runtime metrics |
| POST | `/api/system/stt/transcribe` | STT fallback |

## 8) Project structure

```
app/
  adapters/          # Agora RTC, Agora CAE, Google Calendar, Ollama
  adapters/mcp_tools # MCP tool layer for calendar operations
  core/              # config, logging, metrics, database
  models/            # domain models
  repositories/      # MongoDB persistence
  routers/           # HTTP routes (conversation, system, cae)
  schemas/           # API contracts
  services/          # conversation orchestration, intent, memory, scheduling
web/
  index.html         # Voice + chat UI with Agora RTC SDK
  app.js             # Frontend logic
scripts/
  simulate_sessions.py  # Local multi-session simulation
docs/
  ANALISE_SISTEMA_E_FERRAMENTAS.md
  EVOLUCAO_CAE_MCP.md
```

## 9) Local simulation (no Agora needed)

```bash
python scripts/simulate_sessions.py
```

Exercises multiple intents, confirmations, memory, and fallback across sessions.
