# Relatorio Completo: Frontend e Backend

## 1) Objetivo deste relatorio

Este documento descreve de forma completa o que existe hoje no projeto, separando:

- tudo o que o **frontend** contem e faz;
- tudo o que o **backend** contem e faz;
- como ambas as camadas se conectam no fluxo operacional.

---

## 2) Frontend (camada `web/`)

Arquivos:

- `web/index.html`
- `web/app.js`

### 2.1 Estrutura visual e UX

A interface e orientada a demo de produto e contem:

- topo com branding do sistema;
- seletor de idioma da UI (`pt-BR`, `en-US`, `es-419`);
- link de portfolio;
- hero visual com identidade neon/dark e bloco “mais informacoes” do portfolio;
- console operacional de chat/voz;
- cards de contexto do turno;
- painel de sugestoes proativas;
- painel de trace operacional do agente;
- bloco colapsavel de diagnostico tecnico.

### 2.2 Elementos funcionais de interface

No HTML, os principais elementos de interacao sao:

- `connectAgoraBtn`: conecta no canal Agora (RTC) e publica microfone;
- `voiceToggleBtn`: inicia/para captura de voz local;
- `chatInput` + `sendChatBtn`: envio textual manual;
- `languageSelect`: troca idioma da interface;
- `chatMessages`: renderizacao das mensagens;
- `rtcStatusDot` + `rtcStatusText`: estado da sessao de voz;
- `ctxSession`, `ctxIntent`, `ctxConfirmation`, `ctxExecuted`: contexto operacional;
- `proactiveSuggestions`: sugestoes proativas renderizadas;
- `agentTrace`: etapas operacionais do agente.

### 2.3 Comportamento JavaScript principal (`web/app.js`)

#### Inicializacao e estado local

- Mantem estado de conexao RTC, gravacao, idioma, e estado de conversa.
- Inicializa contexto visual e mensagem de boas-vindas.

#### Internacionalizacao da UI

- Dicionario `UI_TEXTS` com tres idiomas:
  - `pt-BR`
  - `en-US`
  - `es-419`
- Traduz dinamicamente labels, botoes, placeholders, mensagens auxiliares e status.

#### Voz em tempo real e audio local

- Conecta Agora RTC via endpoint backend de sessao.
- Publica audio local no canal.
- Captura audio com `getUserMedia` + `AudioContext` + `ScriptProcessor`.
- Converte para WAV (`encodeWav`) e envia para STT backend.

#### Streaming de resposta

- Envia mensagens para `POST /api/conversation/{session_id}/message/stream`.
- Consome SSE (`text/event-stream`) com eventos:
  - `chunk` (incremental)
  - `final` (payload completo)
- Renderiza chunks no bubble de assistente e finaliza com resposta completa.

#### Interrupcao de fala

- Ao iniciar nova captura enquanto TTS esta falando:
  - cancela `speechSynthesis`;
  - aciona endpoint de interrupcao de voz no backend.
- Sincroniza estado de fala com backend (`agent-speaking true/false`).

#### Renderizacao de inteligencia operacional

- `renderProactiveSuggestions`: mostra sugestoes proativas em pills.
- `renderAgentTrace`: mostra steps de trace operacional (ok/warning/error).
- `setContextState`: atualiza estado curto do turno (intencao, confirmacao, etc.).

#### TTS no navegador

- Usa `SpeechSynthesisUtterance` para leitura da resposta.
- Ajusta `lang` conforme idioma.
- Envia estado `agent_speaking` para backend em `onstart/onend/onerror`.

### 2.4 Fluxo de uso no frontend

1. Usuario conecta na Agora.
2. Usuario fala ou escreve no chat.
3. Frontend envia mensagem (streaming endpoint).
4. Frontend recebe resposta incremental.
5. Frontend exibe:
   - resposta final,
   - contexto do turno,
   - trace operacional,
   - sugestoes proativas.
6. Frontend reproduz TTS e sincroniza estado de fala.

---

## 3) Backend (camada `app/`)

### 3.1 Aplicacao FastAPI e bootstrap

Arquivo principal:

- `app/main.py`

Responsabilidades:

- configura logging JSON;
- habilita CORS;
- registra routers:
  - `conversation_router`
  - `system_router`
  - `cae_router`
- monta frontend estatico em `/`.

### 3.2 Core

Arquivos:

- `app/core/config.py`
- `app/core/database.py`
- `app/core/logging_config.py`
- `app/core/metrics.py`

Responsabilidades:

- carregamento de variaveis de ambiente (`Settings`);
- conexao MongoDB;
- logging estruturado JSON;
- metricas em memoria (counters + timers).

### 3.3 Models e Schemas

#### Models (`app/models`)

- `domain.py`:
  - `IntentName`
  - `MeetingDraft`
  - `ConversationState`
- `tool_execution.py`:
  - modelo formal de execucao de ferramenta MCP.

#### Schemas (`app/schemas`)

- `api.py`:
  - `UserMessageRequest`
  - `StreamMessageRequest`
  - `AssistantResponse`
  - `AgoraSessionResponse`
- `agent_trace.py`:
  - `AgentTraceStep`
  - `AgentTrace`
- `proactive_suggestion.py`:
  - `ProactiveSuggestion`

### 3.4 Repositories (MongoDB)

Arquivos:

- `session_repository.py`
- `conversation_repository.py`
- `preference_repository.py`
- `pattern_repository.py`
- `action_log_repository.py`

Colecoes utilizadas:

- `sessions`
- `conversation_history`
- `user_preferences`
- `meeting_patterns`
- `action_logs`

Responsabilidades:

- estado de sessao;
- historico de mensagens;
- preferencias (idioma, horarios, participantes);
- ultimo padrao de reuniao;
- logs de acao (sucesso/falha).

### 3.5 Adapters (integracoes)

#### Agora

- `agora_client.py`: monta sessao RTC (app_id, channel, token, uid).
- `agora_cae_client.py`: integra API REST do CAE (start/stop agent).

#### Google Calendar

- `google_calendar_client.py`:
  - OAuth local;
  - listar/criar/atualizar/remover eventos;
  - detectar conflitos.

#### Ollama

- `ollama_client.py`:
  - health check;
  - geracao de fallback textual local.

#### MCP tools

- `adapters/mcp_tools/calendar_tools.py`:
  - camada real de ferramentas:
    - `check_availability`
    - `create_calendar_event`
    - `list_events`
    - `reschedule_event`
    - `cancel_event`
    - `suggest_time_slots`

### 3.6 Services (regras e orquestracao)

#### Conversa e decisao

- `conversation_service.py`:
  - motor principal de turno conversacional;
  - detecta intencao e valida contexto;
  - controla confirmacoes;
  - aciona tools (via `CalendarMcpTools`);
  - gera trace operacional;
  - anexa sugestoes proativas;
  - atualiza estado de voz.

#### Linguagem / NLP

- `language_service.py`: detecta idioma.
- `intent_service.py`: detecta intencoes e extrai entidades.
- `fallback_service.py`: respostas de fallback/clarificacao.

#### Agenda e memoria

- `scheduler_service.py`: regra de negocio de agenda.
- `memory_service.py`: memoria curta e persistente.
- `prioritization_service.py`: preferencias de horarios.

#### Voz, trace, streaming e proatividade

- `stt_service.py`: transcricao de WAV para texto.
- `voice_turn_coordinator.py`: estado `agent_speaking/user_interrupting/pending_revision`.
- `response_streaming_service.py`: chunking e SSE.
- `agent_trace_service.py`: emissao e armazenamento de trace por sessao.
- `proactive_suggestion_service.py`: sugestoes baseadas em historico com score.

#### CAE

- `cae_service.py`:
  - monta payload de join do CAE;
  - define llm/asr/tts;
  - conecta MCP endpoint e `allowed_tools`;
  - gerencia sessao ativa de agente.

#### DI container

- `container.py`: provedor central singleton/cacheado dos componentes.

### 3.7 Routers e endpoints

#### Conversation router (`/api/conversation`)

- `POST /{session_id}/message`
- `POST /{session_id}/message/stream`
- `GET /{session_id}/trace`
- `GET /{session_id}/proactive`
- `GET /{session_id}/voice/state`
- `POST /{session_id}/voice/interrupt`
- `POST /{session_id}/voice/agent-speaking/{speaking}`

#### System router (`/api/system`)

- `GET /health`
- `GET /metrics`
- `GET /sessions/{session_id}/history`
- `GET /agora/session/{session_id}`
- `GET /agora/debug`
- `POST /stt/transcribe`

#### CAE router (`/api/cae`)

- `POST /agent/start`
- `POST /agent/stop/{session_id}`
- `GET /agent/status/{session_id}`
- `GET /ollama/health`
- `POST /llm` (callback estilo OpenAI)
- `POST /mcp` (gateway MCP JSON-RPC simplificado)

---

## 4) Integracao frontend/backend (visao ponta a ponta)

1. UI pede sessao Agora ao backend.
2. UI conecta RTC e publica microfone.
3. Usuario envia texto/voz.
4. Backend processa turno com `ConversationService`.
5. Backend executa tools de calendario via MCP tools.
6. Backend retorna resposta com:
   - texto
   - trace
   - sugestoes proativas
   - estado de voz
7. UI renderiza em tempo real + TTS + paineis de inteligencia operacional.

---

## 5) Resumo funcional final

### O que o frontend faz

- oferece experiencia de produto para demo;
- permite conversa por voz e texto;
- suporta UI multilanguage;
- mostra contexto operacional, trace e proatividade;
- suporta resposta incremental e interrupcao de fala.

### O que o backend faz

- interpreta linguagem natural;
- gerencia memoria persistente;
- executa agenda real no Google Calendar;
- orquestra ferramentas via camada MCP;
- coordena estados de turnos de voz;
- gera observabilidade operacional estruturada.

---

## 6) Observacao de estado atual

O sistema esta organizado para demonstrar claramente:

- valor de voz em tempo real (Agora RTC),
- papel central de agente (CAE),
- orquestracao de ferramentas (MCP),
- inteligencia operacional visivel (trace + proatividade),

mantendo os fluxos essenciais do dominio de agendamento.

