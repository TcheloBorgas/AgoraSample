# app/

## Português (Brasil)
### Visão geral
Esta pasta contém todo o backend FastAPI.

### Subpastas e responsabilidades
- `core/`: configurações (`Settings`), logging JSON, métricas e conexão MongoDB.
- `models/`: modelos de domínio (`ConversationState`, `ToolExecution`).
- `schemas/`: contratos da API (`AssistantResponse`, requests, trace).
- `adapters/`: integrações externas (Agora, Google Calendar, Ollama, MCP tools).
- `repositories/`: acesso persistente ao MongoDB por coleção.
- `services/`: regras de negócio e orquestração conversacional.
- `routers/`: endpoints HTTP (`/api/conversation`, `/api/system`, `/api/cae`).
- `main.py`: bootstrap da API e mount do frontend estático.

### Requisitos do desafio cobertos aqui
- Voice agent: **Sim**
- CAE + MCP: **Sim**
- Appointment scheduling: **Sim**

---

## English
This folder contains the full FastAPI backend: routes, services, repositories, adapters, and app bootstrap.

---

## Español
Esta carpeta contiene todo el backend FastAPI: rutas, servicios, repositorios, adaptadores y arranque de la app.
