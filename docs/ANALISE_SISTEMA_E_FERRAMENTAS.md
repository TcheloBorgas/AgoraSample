# Analise do Sistema e Ferramentas Utilizadas

## 1) Visao geral

Este projeto implementa um **assistente virtual de voz para agendamento de reunioes** com foco em MVP funcional local.  
O sistema integra:

- interface web local para conversa por voz e chat;
- backend Python com orquestracao conversacional;
- operacoes reais no Google Calendar;
- persistencia de memoria e historico em MongoDB;
- voz em tempo real com Agora RTC e suporte opcional ao Agora Conversational AI Engine (CAE).

## 2) O que o sistema faz hoje

### Fluxo principal de conversa

- recebe mensagem por texto ou por voz (audio WAV enviado do navegador);
- detecta idioma (PT/EN), intencao e entidades de agenda (data/hora, duracao, participantes, recorrencia);
- aplica fallback quando falta contexto (perguntas de clarificacao);
- exige confirmacao antes de acoes criticas (criar, reagendar, cancelar);
- executa a acao no Google Calendar apos confirmacao;
- responde em texto no chat e com TTS no navegador.

### Intencoes suportadas

- `create_meeting` (criar reuniao);
- `list_meetings` (consultar compromissos);
- `reschedule_meeting` (reagendar);
- `cancel_meeting` (cancelar);
- `repeat_last_meeting` (repetir padrao da ultima);
- `set_language` (trocar idioma);
- `confirm_yes` / `confirm_no` (confirmacoes).

### Recursos funcionais implementados

- criacao de evento com horario e duracao;
- convites por e-mail via `attendees` no Google Calendar;
- consulta de agenda por periodo/alvo;
- reagendamento de evento existente;
- cancelamento de evento;
- recorrencia basica semanal e mensal (`RRULE`);
- sugestoes de horarios em caso de conflito;
- memoria curta por sessao + memoria persistente por usuario;
- priorizacao de horarios com base em historico;
- logs estruturados e metricas basicas.

## 3) Arquitetura e organizacao

Estrutura modular (separacao por responsabilidade):

- `app/routers`: endpoints HTTP (`conversation`, `system`, `cae`);
- `app/services`: regras de negocio e orquestracao de dialogo;
- `app/adapters`: integracoes externas (Agora, Google Calendar, LLM local HTTP);
- `app/repositories`: persistencia em MongoDB;
- `app/core`: config, logging, metricas e conexao DB;
- `app/models` e `app/schemas`: modelos de dominio e contratos de API;
- `web/`: frontend local (`index.html` + `app.js`);
- `scripts/`: simulacoes locais (ex.: multi-sessao).

## 4) Camadas e comportamento tecnico

### Input layer

- **Web UI**: captura texto e audio;
- **STT local**: frontend grava audio e envia para `/api/system/stt/transcribe`.

### Processing layer

- `LanguageService`: deteccao de idioma;
- `IntentService`: deteccao de intencao + extracao de entidades;
- ajustes de periodo do dia (ex.: "3:30 da tarde" -> 15:30);
- reconhecimento de confirmacoes naturais (ex.: "pode confirmar").

### Orchestration layer

- `ConversationService`:
  - controla estado da sessao;
  - gerencia confirmacao pendente;
  - aplica fallback/clarificacao;
  - registra historico e logs de acao.

### Service layer (agenda)

- `SchedulerService`:
  - cria/lista/reagenda/cancela;
  - detecta conflitos;
  - gera sugestoes de slots;
  - aplica recorrencia semanal/mensal.

### Persistence layer

MongoDB com colecoes:

- `sessions`
- `conversation_history`
- `user_preferences`
- `meeting_patterns`
- `action_logs`

### Integration layer

- Google Calendar API (OAuth local);
- Agora RTC (audio real-time);
- Agora CAE (quando habilitado);
- LLM local HTTP (fallback de resposta para unknown intent, quando `LOCAL_LLM_ENABLED=true`).

### Output layer

- resposta textual no chat;
- resposta falada no navegador (Web Speech TTS);
- contexto operacional na UI (intencao, confirmacao, acao executada).

## 5) Endpoints principais

### Conversa

- `POST /api/conversation/{session_id}/message`

### Sistema

- `GET /api/system/health`
- `GET /api/system/metrics`
- `GET /api/system/sessions/{session_id}/history`
- `GET /api/system/agora/session/{session_id}`
- `GET /api/system/agora/debug`
- `POST /api/system/stt/transcribe`

### CAE / Integracoes de agente

- `POST /api/cae/agent/start`
- `POST /api/cae/agent/stop/{session_id}`
- `GET /api/cae/agent/status/{session_id}`
- `GET /api/cae/local-llm/health`
- `POST /api/cae/llm` (callback estilo OpenAI para CAE custom LLM)
- `POST /api/cae/mcp` (gateway MCP simplificado para tools de agenda)

## 6) Ferramentas e tecnologias utilizadas

## Backend e API

- Python 3.11+
- FastAPI
- Uvicorn
- Pydantic / pydantic-settings
- python-dotenv

## Persistencia e dados

- MongoDB local
- PyMongo

## Voz e tempo real

- Agora Web SDK (`AgoraRTC_N.js`) no frontend
- Agora RTC (entrada/saida de audio no canal)
- Agora Conversational AI Engine (opcional, via API REST)
- SpeechRecognition (biblioteca Python) para STT backend
- Web Speech API (TTS no navegador)

## Agenda e calendario

- Google Calendar API (`google-api-python-client`)
- OAuth local com `google-auth-oauthlib` e `google-auth-httplib2`

## NLP e suporte conversacional

- dateparser (parse de datas/horarios naturais)
- python-dateutil (parse ISO/datas)
- fallback com modelo local HTTP (`LOCAL_LLM_*`, ex. `mistral`) quando habilitado

## HTTP e integracoes

- httpx (clientes sincrono/assincrono para APIs externas)

## Observabilidade

- logging estruturado em JSON (`logging_config.py`)
- metricas em memoria (`metrics.py`) com contadores e medias de tempo

## Frontend

- HTML + CSS + JavaScript vanilla
- chat custom, captura de audio, encoder WAV e envio para backend

## 7) Variaveis de ambiente mais relevantes

- Agora RTC:
  - `AGORA_APP_ID`
  - `AGORA_TEMP_TOKEN`
  - `AGORA_FIXED_CHANNEL`
  - `AGORA_UID`
- Agora CAE:
  - `AGORA_CAE_ENABLED`
  - `AGORA_CAE_CUSTOMER_ID`
  - `AGORA_CAE_CUSTOMER_SECRET`
  - `AGORA_CAE_PUBLIC_BASE_URL`
  - `AGORA_CAE_MCP_ENDPOINT`
  - `AGORA_CAE_AGENT_UID`
- Google:
  - `GOOGLE_CLIENT_SECRET_FILE`
  - `GOOGLE_TOKEN_FILE`
  - `GOOGLE_CALENDAR_ID`
- Mongo:
  - `MONGO_URI`
  - `MONGO_DB_NAME`
- LLM local:
  - `LOCAL_LLM_ENABLED`
  - `LOCAL_LLM_BASE_URL`
  - `LOCAL_LLM_MODEL`

## 8) Como o sistema opera no dia a dia

1. Usuario conecta na Agora pela UI.
2. Usuario envia comando por voz ou texto.
3. Backend interpreta intencao e verifica contexto.
4. Se acao critica, solicita confirmacao.
5. Apos confirmacao, executa no Google Calendar.
6. Persiste memoria/historico/acao no MongoDB.
7. Retorna resposta humanizada + atualiza contexto no chat.

## 9) Limitacoes atuais (MVP)

- STT backend usa provedor do `speech_recognition` (pode variar por rede/qualidade de audio);
- matching de evento alvo ainda e heuristico (titulo/horario/query);
- chat textual ainda e custom local (nao e Agora Chat/RTM nativo);
- metricas estao em memoria local (nao persistidas em plataforma externa);
- foco em 1 dominio (agendamento de reunioes), sem modulos multi-dominio.

## 10) Conclusao

O sistema ja entrega um MVP funcional ponta a ponta para agendamento por voz, com integracoes reais, memoria persistente e arquitetura modular.  
As ferramentas escolhidas sao coerentes com evolucao para producao: separacao em camadas, adaptadores externos isolados, repositorios para dados e observabilidade minima ativa.

