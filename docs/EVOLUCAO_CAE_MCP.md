# Evolucao: Real-time Conversational Scheduling Agent

## 1) Descricao tecnica atualizada

O sistema evoluiu de MVP para uma demonstracao de arquitetura orientada ao ecossistema Agora:

- **Agora RTC** segue como base da experiencia de voz em tempo real na interface web.
- **Agora CAE** permanece no centro da narrativa do agente de voz (com lifecycle dedicado e integracao de tools via MCP).
- **MCP** agora esta estruturado como camada de ferramentas de calendario com contratos mais claros (`check_availability`, `create_calendar_event`, `list_events`, `reschedule_event`, `cancel_event`, `suggest_time_slots`).
- **Conversation orchestration** ganhou:
  - trace operacional por turno (`AgentTraceService`);
  - sugestoes proativas baseadas em historico persistido (`ProactiveSuggestionService`);
  - coordenacao de turnos de voz com interrupcao (`VoiceTurnCoordinator`);
  - streaming de resposta via SSE (`ResponseStreamingService`).

Fluxo resumido por turno:

1. Detecta idioma/intencao/entidades.
2. Emite trace operacional (steps formais).
3. Aplica validacao de contexto e confirmacao quando necessario.
4. Executa ferramentas de calendario via camada MCP tools.
5. Anexa resultado + trace + sugestoes proativas no payload.
6. Entrega resposta incremental no endpoint de streaming.

## 2) Por que agora evidencia melhor Agora RTC, CAE e MCP

### Agora RTC

- UI mostra estado de voz e conversa em fluxo continuo.
- Streaming de resposta deixa a experiencia mais proxima de tempo real.
- Coordenacao de turnos permite sinalizar interrupcao de usuario durante resposta do agente.

### Agora CAE

- Rotas e servicos de CAE seguem dedicados e conectados ao fluxo de agente.
- Configuracao de `allowed_tools` foi alinhada aos novos contratos MCP.
- A narrativa tecnica posiciona CAE como engine principal com fallback explicito.

### MCP

- Ferramentas de calendario agora possuem contrato semantico explicito.
- A camada `app/adapters/mcp_tools` separa intencao/orquestracao da execucao.
- Trace exibe etapa de execucao de ferramenta e resultado resumido.

## 3) Features implementadas nesta evolucao

- `ProactiveSuggestionService` com score basico e anti-repeticao por sessao.
- Sugestoes proativas integradas ao fluxo principal de conversa.
- `AgentTraceService` com steps formais por turno.
- Trace retornado no payload de resposta (`trace`).
- Endpoint de streaming (`POST /api/conversation/{session_id}/message/stream`).
- Endpoint de consulta de trace (`GET /api/conversation/{session_id}/trace`).
- Endpoints de estado/interrupcao de voz:
  - `GET /api/conversation/{session_id}/voice/state`
  - `POST /api/conversation/{session_id}/voice/interrupt`
  - `POST /api/conversation/{session_id}/voice/agent-speaking/{speaking}`
- Endpoint de sugestoes proativas:
  - `GET /api/conversation/{session_id}/proactive`
- Camada MCP tools estruturada em `app/adapters/mcp_tools/calendar_tools.py`.
- Gateway MCP atualizado para tool contracts mais claros.
- Frontend atualizado com:
  - painel de sugestoes proativas;
  - painel de trace operacional;
  - consumo de streaming incremental;
  - sincronizacao de estado de fala/interrupcao.

## 4) Limitacoes remanescentes (honestas)

- O streaming atual e **best-effort via SSE** no backend textual (incremental por chunks), nao token streaming nativo de um LLM em todos os cenarios.
- A interrupcao de voz e coordenada por estado de sessao + eventos de UI; em ambiente de rede/latencia real, pode haver pequenas defasagens.
- Algumas operacoes de agenda ainda dependem de heuristicas de identificacao de evento alvo.
- O fallback local (STT/TTS browser + backend) ainda existe por robustez operacional quando CAE externo nao esta disponivel.
- O suporte de linguagem no backend continua focado em PT/EN para intencao; a camada de UI agora suporta tambem es-LATAM.

