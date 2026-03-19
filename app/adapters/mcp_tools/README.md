# app/adapters/mcp_tools/

## Português (Brasil)
`calendar_tools.py` implementa tools MCP de calendário:
- `check_availability`
- `list_events`
- `create_calendar_event`
- `reschedule_event`
- `cancel_event`
- `suggest_time_slots`

Essas tools são chamadas pelo gateway `/api/cae/mcp` e podem ser usadas diretamente pelo CAE quando `enable_tools=true`.

---
## English
MCP tool implementations for scheduling operations exposed to CAE.

---
## Español
Implementación de tools MCP para operaciones de agenda usadas por el agente CAE.
