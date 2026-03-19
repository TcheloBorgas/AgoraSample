# app/routers/

## Português (Brasil)
Camada HTTP da API:
- `conversation_router.py` (`/api/conversation`): mensagem síncrona, streaming, trace, proactive, voice state.
- `system_router.py` (`/api/system`): health, metrics, sessão Agora, STT, debug.
- `cae_router.py` (`/api/cae`): start/stop/status do agente, callback LLM e gateway MCP.

Tecnologia: `FastAPI`.

---
## English
HTTP route layer: conversation endpoints, system endpoints, and CAE/MCP endpoints.

---
## Español
Capa de rutas HTTP: endpoints de conversación, sistema y CAE/MCP.
