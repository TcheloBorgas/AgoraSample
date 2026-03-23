# web/

## Português (Brasil)
Frontend da aplicação:
- `index.html`: layout principal (hero, chat, painéis de contexto/trace, status RTC).
- `app.js`: lógica de UI, i18n (PT/EN/ES), conexão Agora RTC, start CAE, fallback STT, SSE streaming, TTS do navegador.

Fluxo importante:
1. Buscar sessão Agora em `/api/system/agora/session/{session_id}`
2. Entrar no canal RTC e publicar microfone
3. Iniciar agente CAE (`/api/cae/agent/start`)
4. Enviar mensagens via `/api/conversation/{session_id}/message/stream`

**Nota sobre voz e chat:** o ASR do CAE roda na Agora e **não** é enviado automaticamente para o FastAPI nem aparece como bolha no chat. Para ver transcrição no chat, o botão de voz usa **captura local +** `/api/system/stt/transcribe` (mesmo com CAE ativo).

---
## English
Client-side UI and interaction logic for RTC, CAE startup, chat, voice fallback, and streaming responses.

---
## Español
Interfaz web y lógica cliente para RTC, arranque CAE, chat, fallback de voz y respuestas en streaming.
