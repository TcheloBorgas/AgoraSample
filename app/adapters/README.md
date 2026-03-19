# app/adapters/

## Português (Brasil)
Adaptadores de integração com serviços externos:
- `agora_client.py`: dados de sessão RTC (app_id, token, channel, uid).
- `agora_cae_client.py`: cliente REST do Agora CAE (`/join` e `/leave`).
- `google_calendar_client.py`: CRUD de eventos no Google Calendar.
- `ollama_client.py`: fallback local de resposta com Ollama.
- `mcp_tools/`: tools expostas via MCP para o agente.

Tecnologias: `httpx`, `google-api-python-client`, `google-auth`.

---
## English
External service clients: Agora RTC/CAE, Google Calendar, Ollama, and MCP tools wrapper.

---
## Español
Clientes externos: Agora RTC/CAE, Google Calendar, Ollama y capa de tools MCP.
