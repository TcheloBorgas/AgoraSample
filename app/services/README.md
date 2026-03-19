# app/services/

## Português (Brasil)
Serviços de negócio e orquestração:
- `conversation_service.py`: núcleo da conversa (idioma, intenção, confirmação, execução, resposta).
- `intent_service.py`: detecção de intenção e extração de entidades (PT/EN/ES).
- `scheduler_service.py`: regras de agenda, conflito e recorrência.
- `memory_service.py`: memória curta + persistência em repositórios.
- `cae_service.py`: lifecycle do agente CAE (start/stop/status + payload join).
- `response_streaming_service.py`: streaming SSE por chunks.
- `agent_trace_service.py`: trace operacional.
- `voice_turn_coordinator.py`: estado de turnos de voz.
- `fallback_service.py`, `language_service.py`, `prioritization_service.py`, `proactive_suggestion_service.py`, `stt_service.py`.
- `container.py`: injeção de dependência com `@lru_cache`.

### Requisitos do desafio atendidos por esta pasta
- agente de voz (lógica conversacional): **sim**
- integração CAE/MCP: **sim**
- domínio de scheduling: **sim**

---
## English
Business and orchestration layer: intent detection, memory, scheduling, CAE lifecycle, SSE streaming, trace, and voice-turn state.

---
## Español
Capa de negocio y orquestación: intents, memoria, agenda, ciclo de vida CAE, streaming SSE, trazas y estado de turnos de voz.
