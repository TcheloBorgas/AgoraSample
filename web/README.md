# web/

## Português (Brasil)
Frontend da aplicação:
- `index.html`: layout principal (hero, chat, painéis de contexto/trace, status RTC).
- `app.js`: lógica de UI, i18n (PT/EN), conexão Agora RTC, start CAE, fallback STT, SSE streaming. Voz sintetizada só via **TTS do CAE** (áudio remoto no RTC); respostas do chat são só texto.

Fluxo importante:
1. Buscar sessão Agora em `/api/system/agora/session/{session_id}`
2. Entrar no canal RTC e publicar microfone
3. Iniciar agente CAE (`/api/cae/agent/start`)
4. Enviar mensagens via `/api/conversation/{session_id}/message/stream`

**Nota sobre voz e chat:** o ASR do CAE roda na Agora e **não** é enviado automaticamente para o FastAPI nem aparece como bolha no chat. Para ver transcrição no chat, o botão de voz usa **captura local +** `/api/system/stt/transcribe` (mesmo com CAE ativo).

**Áudio no browser:** Chrome/Safari podem bloquear **autoplay** do áudio remoto (o evento `user-published` não conta como gesto do utilizador). O `app.js` regista `AgoraRTC.onAutoplayFailed` e mostra o botão **«Ativar áudio do agente»** para retomar o `play()` dos tracks remotos.

---
## English
Client-side UI for RTC, CAE startup, chat, STT fallback, and streaming responses. Synthesized voice is **CAE TTS only** (remote RTC audio); chat replies are text-only.
