let agoraClient = null;
let localTrack = null;
let isConnectingAgora = false;
let isRtcConnected = false;
let caeActive = false;
let localRtcUid = null;
/** UID RTC do agente CAE (vem de /api/cae/agent/start) — para diagnóstico de áudio remoto */
let expectedCaeAgentUid = null;
let caeAgentAudioReceived = false;
let caeRemoteAudioWatchdogTimer = null;

/** Tracks de áudio remoto (agente CAE) para retomar play após bloqueio de autoplay */
let remoteAudioTracks = [];
/** Último RemoteAudioTrack por uid — ao republicar áudio, parar o anterior evita sobreposição / som «travado». */
let lastRemoteAudioTrackByUid = new Map();
/** Evita `play()` duplicado se o SDK repetir `user-published` para a mesma instância de track (referência). */
let agoraAutoplayHooked = false;

/**
 * CAE/TTS dispara user-published em rajada; trailing debounce sozinho nunca «descansa» se o intervalo
 * entre eventos for < DEBOUNCE_MS. MAX_WAIT_MS força pelo menos uma aplicação periódica.
 * Não cancelar o timer em user-unpublished — senão o áudio nunca chega a tocar.
 */
/** Rajadas do CAE: um pouco mais de espera reduz subscribe/play em loop e cortes audíveis. */
const REMOTE_AUDIO_PUBLISH_DEBOUNCE_MS = 100;
const REMOTE_AUDIO_PUBLISH_MAX_WAIT_MS = 220;
let remoteAudioPublishDebounceTimers = new Map();
/** Primeiro user-published do burst (por uid), para max-wait. */
let remoteAudioPublishBurstStartTs = new Map();
/** Evita subscribe/play em rajada para o mesmo uid. */
let remoteAudioSubscribeInFlightByUid = new Map();
let remoteAudioLastSubscribeAtByUid = new Map();
let remoteAudioLastPlayAtByUid = new Map();
const REMOTE_AUDIO_MIN_SUBSCRIBE_INTERVAL_MS = 700;
const REMOTE_AUDIO_MIN_REPLAY_INTERVAL_MS = 5000;
const RTC_EVENT_LOG_THROTTLE_MS = 1500;
const rtcAudioEventStatsByUid = new Map();

function clearRemoteAudioPublishDebouncers() {
  for (const tid of remoteAudioPublishDebounceTimers.values()) {
    clearTimeout(tid);
  }
  remoteAudioPublishDebounceTimers.clear();
  remoteAudioPublishBurstStartTs.clear();
  remoteAudioSubscribeInFlightByUid.clear();
  remoteAudioLastSubscribeAtByUid.clear();
  remoteAudioLastPlayAtByUid.clear();
  rtcAudioEventStatsByUid.clear();
}

function cancelRemoteAudioPublishDebounce(uidStr) {
  const tid = remoteAudioPublishDebounceTimers.get(uidStr);
  if (tid) {
    clearTimeout(tid);
    remoteAudioPublishDebounceTimers.delete(uidStr);
  }
}

function logRtcAudioEvent(uid, kind) {
  const uidStr = String(uid);
  const now = Date.now();
  const stat = rtcAudioEventStatsByUid.get(uidStr) || {
    published: 0,
    unpublished: 0,
    muteInfo: 0,
    unmuteInfo: 0,
    lastLogAt: 0,
  };
  if (kind === "published") stat.published += 1;
  else if (kind === "unpublished") stat.unpublished += 1;
  else if (kind === "mute-info") stat.muteInfo += 1;
  else if (kind === "unmute-info") stat.unmuteInfo += 1;

  if (now - stat.lastLogAt >= RTC_EVENT_LOG_THROTTLE_MS) {
    const summary = [];
    if (stat.published) summary.push(`published=${stat.published}`);
    if (stat.unpublished) summary.push(`unpublished=${stat.unpublished}`);
    if (stat.muteInfo || stat.unmuteInfo) summary.push(`info(mute=${stat.muteInfo}, unmute=${stat.unmuteInfo})`);
    if (summary.length) {
      log(`RTC uid=${uidStr} eventos (janela): ${summary.join(" ")}`);
    }
    stat.published = 0;
    stat.unpublished = 0;
    stat.muteInfo = 0;
    stat.unmuteInfo = 0;
    stat.lastLogAt = now;
  }
  rtcAudioEventStatsByUid.set(uidStr, stat);
}

function scheduleApplyRemoteUserAudio(uidStr) {
  const now = Date.now();
  if (!remoteAudioPublishBurstStartTs.has(uidStr)) {
    remoteAudioPublishBurstStartTs.set(uidStr, now);
  }
  const burstStart = remoteAudioPublishBurstStartTs.get(uidStr);
  const maxWaitElapsed = now - burstStart >= REMOTE_AUDIO_PUBLISH_MAX_WAIT_MS;

  const run = () => {
    remoteAudioPublishDebounceTimers.delete(uidStr);
    remoteAudioPublishBurstStartTs.delete(uidStr);
    applyRemoteUserAudioPublished(uidStr).catch((err) => {
      log(`RTC áudio remoto (debounce): ${err?.message || err}`);
    });
  };

  if (maxWaitElapsed) {
    cancelRemoteAudioPublishDebounce(uidStr);
    run();
    return;
  }

  cancelRemoteAudioPublishDebounce(uidStr);
  const timerId = setTimeout(run, REMOTE_AUDIO_PUBLISH_DEBOUNCE_MS);
  remoteAudioPublishDebounceTimers.set(uidStr, timerId);
}

function stopRemoteAudioTrackIfAny(track) {
  if (!track) return;
  try {
    if (typeof track.stop === "function") {
      track.stop();
    }
  } catch (_e) {
    /* track já libertado */
  }
}

function isSameTrackReplayTooSoon(uidStr, track) {
  const prevTrack = lastRemoteAudioTrackByUid.get(uidStr);
  if (!prevTrack || prevTrack !== track) return false;
  const lastPlayAt = remoteAudioLastPlayAtByUid.get(uidStr) || 0;
  return Date.now() - lastPlayAt < REMOTE_AUDIO_MIN_REPLAY_INTERVAL_MS;
}

function pruneRemoteAudioTracksFromClient() {
  if (!agoraClient) return;
  const live = new Set();
  for (const u of agoraClient.remoteUsers || []) {
    if (u.audioTrack) live.add(u.audioTrack);
  }
  remoteAudioTracks = remoteAudioTracks.filter((t) => live.has(t));
}

let recordingContext = null;
let recordingStream = null;
let recordingSource = null;
let recordingNode = null;
let recordingChunks = [];
let isRecording = false;

let uiLocale = "pt-BR";
let currentLanguage = "pt-BR";
let voiceUiState = "idle";

/** Base do FastAPI: vazio = mesmo host (quando a UI é servida pelo uvicorn). Para file:// ou outro host, defina antes de carregar este script: window.__SCHEDULER_API_BASE__ = 'http://127.0.0.1:8000' */
function apiUrl(path) {
  const base = String(typeof window !== "undefined" && window.__SCHEDULER_API_BASE__ ? window.__SCHEDULER_API_BASE__ : "")
    .trim()
    .replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
}

/** Evita UI presa em «a carregar» se o backend ou a API Agora não responderem. */
async function fetchWithTimeout(url, options, timeoutMs) {
  const controller = new AbortController();
  const timerId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timerId);
  }
}

const logEl = document.getElementById("log");
const sessionIdEl = document.getElementById("sessionId");
const userIdEl = document.getElementById("userId");
const connectAgoraBtnEl = document.getElementById("connectAgoraBtn");
const voiceToggleBtnEl = document.getElementById("voiceToggleBtn");
const interruptAgentBtnEl = document.getElementById("interruptAgentBtn");
const chatMessagesEl = document.getElementById("chatMessages");
const chatInputEl = document.getElementById("chatInput");
const sendChatBtnEl = document.getElementById("sendChatBtn");
const languageSelectEl = document.getElementById("languageSelect");

const rtcStatusDotEl = document.getElementById("rtcStatusDot");
const rtcStatusTextEl = document.getElementById("rtcStatusText");
const agentStateLabelEl = document.getElementById("agentStateLabel");
const agentStateHintEl = document.getElementById("agentStateHint");
const agentStatePulseEl = document.getElementById("agentStatePulse");

const ctxSessionEl = document.getElementById("ctxSession");
const ctxIntentEl = document.getElementById("ctxIntent");
const ctxConfirmationEl = document.getElementById("ctxConfirmation");
const ctxExecutedEl = document.getElementById("ctxExecuted");
const proactiveSuggestionsEl = document.getElementById("proactiveSuggestions");
const agentTraceEl = document.getElementById("agentTrace");
const audioUnlockBarEl = document.getElementById("audioUnlockBar");
const audioUnlockBtnEl = document.getElementById("audioUnlockBtn");
const audioUnlockTextEl = document.getElementById("audioUnlockText");

const UI_TEXTS = {
  "pt-BR": {
    brandText: "Voice Scheduling System",
    portfolioTopLink: "Ver meu portfolio",
    heroEyebrow: "Real-time Conversational Agent",
    heroTitleMain: "Converse naturalmente.",
    heroTitleGrad: "Agende com confiança.",
    heroCopy: "Interface de produto para voz + chat com streaming, contexto operacional e inteligência de agenda.",
    portfolioInfoTitle: "Mais informações",
    portfolioInfoDesc: "Explore projetos, trajetória e publicações em um portfólio completo.",
    portfolioBullet1: "Projetos de IA aplicada e engenharia",
    portfolioBullet2: "Experiência profissional e stack",
    portfolioBullet3: "Contato para parcerias e oportunidades",
    portfolioHeroLink: "Portfolio",
    consoleTitle: "Conversation Workspace",
    sessionLabel: "Session ID",
    userLabel: "User ID",
    chatPlaceholder: "Descreva o que você quer agendar...",
    connectAgoraBtn: "Conectar Agora",
    voiceToggleIdle: "Iniciar voz",
    voiceToggleRecording: "Parar captura",
    voiceToggleCaeLive: "CAE ativo (fale agora)",
    sendChatBtn: "Enviar",
    interruptAgentBtn: "Interromper resposta do agente",
    ctxSessionLabel: "Sessão",
    ctxIntentLabel: "Última intenção",
    ctxConfirmationLabel: "Confirmação",
    ctxExecutedLabel: "Execução",
    proactiveTitle: "Sugestões proativas",
    traceTitle: "Operational Trace",
    debugSummary: "Diagnóstico técnico",
    proactiveEmpty: "Sem sugestões no momento.",
    traceEmpty: "Sem etapas registradas ainda.",
    roleUser: "Você",
    roleAssistant: "Assistente",
    statusWaiting: "Aguardando conexão",
    statusConnected: "Conectado",
    statusFailed: "Falha de conexão",
    stateIdle: "Pronto",
    stateIdleHint: "Aguardando nova interação.",
    stateListening: "Ouvindo",
    stateListeningHint: "Capturando sua fala em tempo real.",
    stateThinking: "Processando",
    stateThinkingHint: "Analisando contexto e preparando resposta.",
    stateSpeaking: "Respondendo",
    stateSpeakingHint: "Agente falando em tempo real.",
    stateInterrupted: "Interrompido",
    stateInterruptedHint: "Interrupção detectada. Ajustando resposta.",
    stateError: "Erro",
    stateErrorHint: "Não foi possível completar esta etapa.",
    contextPending: "Pendente",
    contextNoPending: "Não pendente",
    contextYes: "Sim",
    contextNo: "Não",
    welcomeAssistant:
      "Olá! Para agendar, vou pedir seu nome, o assunto da reunião (esse texto vira o nome do evento no calendário), seu e-mail e data/hora. Também posso listar, reagendar ou cancelar. Links não são lidos em voz.",
    logConnecting: "Conexão com Agora em andamento.",
    logAlreadyConnected: "Já conectado no canal Agora.",
    logAgoraStepSession: "1/4 A pedir token ao backend…",
    logAgoraStepJoin: "2/4 A entrar no canal RTC…",
    logAgoraStepMic: "3/4 A abrir o microfone…",
    logAgoraStepPublish: "4/4 A publicar áudio…",
    logAgoraJoinHint:
      "Se falhar aqui: token inválido ou expirado. No backend defina AGORA_APP_CERTIFICATE (Console Agora) em vez de só AGORA_TEMP_TOKEN.",
    logConnected: "Agora conectada no canal",
    logRemoteUserJoined: "RTC: participante remoto entrou — uid=%s (esperado: agente CAE).",
    logRemoteAudio: "Áudio remoto ativo",
    logCaeTtsPlaying:
      "TTS CAE (Agora): áudio remoto do agente — voz sintetizada pelo Conversational AI no canal RTC.",
    logCaeActive: "CAE ativo. Fale normalmente sem usar captura local.",
    logCaeSpeakHint:
      "Voz CAE no RTC: fale no microfone (áudio já publicado). O chat/STT só atualiza texto no FastAPI — não manda TTS pelo Agora. Aguarde user-published de áudio após o agente responder.",
    logCaeLocalRecord:
      "CAE ativo: a transcrição no chat usa captura local (STT). O agente CAE também pode ouvir pelo canal RTC.",
    logCaeFallback: "CAE indisponível. Mantendo fluxo local com voz + chat.",
    logCaeRemoteAudioOk:
      "RTC: primeiro áudio publicado pelo agente CAE (uid=%s) — o browser deve reproduzir (ou pedir «Ativar áudio»).",
    logCaeNoRemoteAudioDiagnostic:
      "RTC diagnóstico: após %TIME% s ainda não houve user-published de áudio do agente (uid esperado %UID%). " +
      "Isto indica que o CAE não está a enviar TTS no canal (ou ainda não processou a sua fala no RTC). " +
      "Fale no microfone; confira no Render logs do CAE, chaves TTS e consola Agora.",
    logAutoplayBlocked:
      "Autoplay bloqueado: o áudio do agente CAE chegou ao browser, mas o Chrome/Safari exigem um clique para tocar. Use «Ativar áudio do agente».",
    logAudioPlayFailed: "Falha ao iniciar reprodução do áudio remoto",
    audioUnlockText:
      "O navegador pode bloquear o áudio remoto (autoplay). Toque no botão para ouvir o agente CAE no canal RTC.",
    audioUnlockBtn: "Ativar áudio do agente",
    logAudioResumed: "Áudio remoto retomado após o clique (política de autoplay).",
    logMicError: "Falha de microfone",
    logVoiceError: "Falha na captura de voz",
    logBackendError: "Falha no backend",
    logTypeMessage: "Digite uma mensagem para enviar.",
    errorPopupTitle: "Erro",
    errorPopupUnknown: "Ocorreu um erro sem mensagem detalhada.",
    errorPopupClose: "Fechar",
    errHtmlInsteadOfApi:
      "O servidor devolveu uma página HTML (como «Page not found» do Netlify) em vez da API JSON.\n\n" +
      "• Netlify: em Site → Environment variables crie SCHEDULER_API_BASE com a URL do FastAPI (ex.: https://seu-app.railway.app), sem barra no fim, e faça um deploy novo.\n" +
      "• Teste local: use a mesma origem do uvicorn ou defina window.__SCHEDULER_API_BASE__ = 'http://127.0.0.1:8000' antes de carregar app.js.",
  },
  "en-US": {
    brandText: "Voice Scheduling System",
    portfolioTopLink: "View my portfolio",
    heroEyebrow: "Real-time Conversational Agent",
    heroTitleMain: "Converse naturally.",
    heroTitleGrad: "Schedule confidently.",
    heroCopy: "Product-grade interface for voice + chat with streaming, operational context and scheduling intelligence.",
    portfolioInfoTitle: "More information",
    portfolioInfoDesc: "Explore projects, trajectory and publications in a complete portfolio.",
    portfolioBullet1: "Applied AI and engineering projects",
    portfolioBullet2: "Professional experience and stack",
    portfolioBullet3: "Direct contact for partnerships",
    portfolioHeroLink: "Portfolio",
    consoleTitle: "Conversation Workspace",
    sessionLabel: "Session ID",
    userLabel: "User ID",
    chatPlaceholder: "Describe what you want to schedule...",
    connectAgoraBtn: "Connect Agora",
    voiceToggleIdle: "Start voice",
    voiceToggleRecording: "Stop capture",
    voiceToggleCaeLive: "CAE live (speak now)",
    sendChatBtn: "Send",
    interruptAgentBtn: "Interrupt agent response",
    ctxSessionLabel: "Session",
    ctxIntentLabel: "Last intent",
    ctxConfirmationLabel: "Confirmation",
    ctxExecutedLabel: "Execution",
    proactiveTitle: "Proactive suggestions",
    traceTitle: "Operational Trace",
    debugSummary: "Technical diagnostics",
    proactiveEmpty: "No suggestions at this time.",
    traceEmpty: "No trace steps yet.",
    roleUser: "You",
    roleAssistant: "Assistant",
    statusWaiting: "Waiting for connection",
    statusConnected: "Connected",
    statusFailed: "Connection failed",
    stateIdle: "Ready",
    stateIdleHint: "Waiting for the next turn.",
    stateListening: "Listening",
    stateListeningHint: "Capturing your voice in real time.",
    stateThinking: "Thinking",
    stateThinkingHint: "Analyzing context and preparing response.",
    stateSpeaking: "Speaking",
    stateSpeakingHint: "Agent is responding in real time.",
    stateInterrupted: "Interrupted",
    stateInterruptedHint: "Interruption detected. Revising response.",
    stateError: "Error",
    stateErrorHint: "Could not complete this step.",
    contextPending: "Pending",
    contextNoPending: "Not pending",
    contextYes: "Yes",
    contextNo: "No",
    welcomeAssistant:
      "Hello! To schedule, I'll ask your name, meeting subject, email, and date and time. I can also list, reschedule, or cancel. Calendar links are not read aloud.",
    logConnecting: "Connecting to Agora...",
    logAlreadyConnected: "Already connected to Agora channel.",
    logConnected: "Agora connected on channel",
    logRemoteUserJoined: "RTC: remote participant joined — uid=%s (expected: CAE agent).",
    logRemoteAudio: "Remote audio active",
    logCaeTtsPlaying:
      "CAE TTS (Agora): remote agent audio — synthesized by Conversational AI on the RTC channel.",
    logCaeActive: "CAE active. Speak normally without local capture.",
    logCaeSpeakHint:
      "CAE voice on RTC: speak into the mic (audio is published). Chat/STT only updates the FastAPI text — it does not send Agora TTS. Wait for remote audio after the agent replies.",
    logCaeLocalRecord:
      "CAE active: chat transcription uses local capture (STT). The CAE agent may also listen via RTC.",
    logCaeFallback: "CAE unavailable. Keeping local voice + chat flow.",
    logCaeRemoteAudioOk:
      "RTC: first remote audio published by CAE agent (uid=%s) — browser should play (or use «Enable agent audio»).",
    logCaeNoRemoteAudioDiagnostic:
      "RTC diagnostic: after %TIME% s still no user-published audio from agent (expected uid %UID%). " +
      "The CAE is not sending TTS on the channel yet (or has not processed your RTC speech). " +
      "Speak into the mic; check Render CAE logs, TTS keys, and Agora console.",
    logAutoplayBlocked:
      "Autoplay blocked: CAE agent audio arrived but the browser requires a click to play. Use «Enable agent audio».",
    logAudioPlayFailed: "Failed to start remote audio playback",
    audioUnlockText:
      "The browser may block remote audio (autoplay policy). Click the button to hear the CAE agent on the RTC channel.",
    audioUnlockBtn: "Enable agent audio",
    logAudioResumed: "Remote audio resumed after click (autoplay policy).",
    logMicError: "Microphone failure",
    logVoiceError: "Voice capture failure",
    logBackendError: "Backend failure",
    logTypeMessage: "Type a message before sending.",
    errorPopupTitle: "Error",
    errorPopupUnknown: "An error occurred without a detailed message.",
    errorPopupClose: "Close",
    errHtmlInsteadOfApi:
      "The server returned an HTML page (e.g. Netlify «Page not found») instead of JSON.\n\n" +
      "• Netlify: Site → Environment variables → set SCHEDULER_API_BASE to your FastAPI public URL (no trailing slash), then redeploy.\n" +
      "• Local: serve from uvicorn or set window.__SCHEDULER_API_BASE__ = 'http://127.0.0.1:8000' before app.js.",
  },
  "es-419": {
    brandText: "Voice Scheduling System",
    portfolioTopLink: "Ver mi portafolio",
    heroEyebrow: "Agente conversacional en tiempo real",
    heroTitleMain: "Conversa naturalmente.",
    heroTitleGrad: "Agenda con confianza.",
    heroCopy: "Interfaz de producto para voz + chat con streaming, contexto operativo e inteligencia de agenda.",
    portfolioInfoTitle: "Más información",
    portfolioInfoDesc: "Explora proyectos, trayectoria y publicaciones en un portafolio completo.",
    portfolioBullet1: "Proyectos de IA aplicada e ingeniería",
    portfolioBullet2: "Experiencia profesional y stack",
    portfolioBullet3: "Contacto para colaboraciones",
    portfolioHeroLink: "Portafolio",
    consoleTitle: "Conversation Workspace",
    sessionLabel: "Session ID",
    userLabel: "User ID",
    chatPlaceholder: "Describe lo que quieres agendar...",
    connectAgoraBtn: "Conectar Agora",
    voiceToggleIdle: "Iniciar voz",
    voiceToggleRecording: "Detener captura",
    voiceToggleCaeLive: "CAE activo (habla ahora)",
    sendChatBtn: "Enviar",
    interruptAgentBtn: "Interrumpir respuesta del agente",
    ctxSessionLabel: "Sesión",
    ctxIntentLabel: "Última intención",
    ctxConfirmationLabel: "Confirmación",
    ctxExecutedLabel: "Ejecución",
    proactiveTitle: "Sugerencias proactivas",
    traceTitle: "Operational Trace",
    debugSummary: "Diagnóstico técnico",
    proactiveEmpty: "Sin sugerencias por ahora.",
    traceEmpty: "Sin pasos registrados todavía.",
    roleUser: "Tú",
    roleAssistant: "Asistente",
    statusWaiting: "Esperando conexión",
    statusConnected: "Conectado",
    statusFailed: "Fallo de conexión",
    stateIdle: "Listo",
    stateIdleHint: "Esperando la próxima interacción.",
    stateListening: "Escuchando",
    stateListeningHint: "Capturando tu voz en tiempo real.",
    stateThinking: "Procesando",
    stateThinkingHint: "Analizando contexto y preparando respuesta.",
    stateSpeaking: "Respondiendo",
    stateSpeakingHint: "El agente está respondiendo en tiempo real.",
    stateInterrupted: "Interrumpido",
    stateInterruptedHint: "Interrupción detectada. Ajustando respuesta.",
    stateError: "Error",
    stateErrorHint: "No se pudo completar este paso.",
    contextPending: "Pendiente",
    contextNoPending: "No pendiente",
    contextYes: "Sí",
    contextNo: "No",
    welcomeAssistant:
      "¡Hola! Para agendar pediré tu nombre, el asunto, tu correo y la fecha/hora. También puedo listar, reagendar o cancelar. No leo enlaces del calendario en voz alta.",
    logConnecting: "Conectando con Agora...",
    logAlreadyConnected: "Ya conectado al canal de Agora.",
    logConnected: "Agora conectada en el canal",
    logRemoteUserJoined: "RTC: participante remoto entró — uid=%s (esperado: agente CAE).",
    logRemoteAudio: "Audio remoto activo",
    logCaeTtsPlaying:
      "TTS CAE (Agora): audio remoto del agente — voz sintetizada por Conversational AI en el canal RTC.",
    logCaeActive: "CAE activo. Habla normalmente sin captura local.",
    logCaeSpeakHint:
      "Voz CAE en RTC: habla al micrófono. El chat/STT solo actualiza texto en el servidor — no envía TTS por Agora. Espera user-published cuando el agente hable.",
    logCaeLocalRecord:
      "CAE activo: la transcripción en el chat usa captura local (STT). El agente CAE también puede oír por RTC.",
    logCaeFallback: "CAE no disponible. Manteniendo flujo local de voz + chat.",
    logCaeRemoteAudioOk:
      "RTC: primer audio publicado por el agente CAE (uid=%s).",
    logCaeNoRemoteAudioDiagnostic:
      "RTC diagnóstico: tras %TIME% s no hubo user-published de audio del agente (uid esperado %UID%). " +
      "El CAE aún no envía TTS o no procesó tu voz en RTC. Habla al micrófono; revisa logs TTS y Agora.",
    logAutoplayBlocked:
      "Autoplay bloqueado: el audio del agente CAE llegó, pero el navegador exige un clic. Usa «Activar audio del agente».",
    logAudioPlayFailed: "Error al reproducir audio remoto",
    audioUnlockText:
      "El navegador puede bloquear el audio remoto (autoplay). Toca el botón para oír al agente CAE en RTC.",
    audioUnlockBtn: "Activar audio del agente",
    logAudioResumed: "Audio remoto reanudado tras el clic (política de autoplay).",
    logMicError: "Fallo de micrófono",
    logVoiceError: "Fallo en captura de voz",
    logBackendError: "Fallo del backend",
    logTypeMessage: "Escribe un mensaje antes de enviar.",
    errorPopupTitle: "Error",
    errorPopupUnknown: "Ocurrió un error sin mensaje detallado.",
    errorPopupClose: "Cerrar",
    errHtmlInsteadOfApi:
      "El servidor devolvió HTML (p. ej. «Page not found» de Netlify) en lugar de la API JSON.\n\n" +
      "• Netlify: Site → Environment variables → SCHEDULER_API_BASE = URL pública del FastAPI (sin barra final) y nuevo deploy.\n" +
      "• Local: mismo origen que uvicorn o window.__SCHEDULER_API_BASE__ = 'http://127.0.0.1:8000' antes de app.js.",
  },
};

function t(key) {
  return UI_TEXTS[uiLocale]?.[key] ?? UI_TEXTS["pt-BR"][key] ?? key;
}

function refreshVoiceToggleButton() {
  if (isRecording) {
    voiceToggleBtnEl.textContent = t("voiceToggleRecording");
    return;
  }
  if (caeActive) {
    voiceToggleBtnEl.textContent = t("voiceToggleCaeLive");
    return;
  }
  voiceToggleBtnEl.textContent = t("voiceToggleIdle");
}

function looksLikeHtmlPayload(text) {
  const raw = (text || "").trimStart();
  const head = raw.slice(0, 96).toLowerCase();
  if (head.startsWith("<!doctype") || head.startsWith("<html")) return true;
  if (/page not found/i.test(raw) && /netlify/i.test(raw)) return true;
  return false;
}

function parseHttpErrorBody(text, status) {
  if (!text?.trim()) return status ? `HTTP ${status}` : t("errorPopupUnknown");
  if (looksLikeHtmlPayload(text)) return t("errHtmlInsteadOfApi");
  try {
    const j = JSON.parse(text);
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return j.detail.map((x) => (typeof x === "object" && x.msg) || JSON.stringify(x)).join("; ");
    if (j.detail != null) return String(j.detail);
    if (j.message) return String(j.message);
  } catch (_e) {}
  const snippet = text.length > 400 ? `${text.slice(0, 400)}…` : text;
  return snippet;
}

function parseJsonResponse(text, context) {
  if (looksLikeHtmlPayload(text)) {
    throw new Error(parseHttpErrorBody(text, 0));
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    if ((text || "").trimStart().startsWith("<")) {
      throw new Error(parseHttpErrorBody(text, 0));
    }
    const hint = context ? `${context}: ` : "";
    throw new Error(`${hint}${e instanceof Error ? e.message : String(e)}`);
  }
}

function getSpeechLocaleFromUi() {
  if (uiLocale === "es-419") return "es-ES";
  return uiLocale;
}

function getBackendLangFromUi() {
  if (uiLocale === "es-419") return "es-ES";
  return uiLocale;
}

let __lastErrorPopupMsg = "";
let __lastErrorPopupAt = 0;

function showErrorPopup(message, title) {
  const modal = document.getElementById("errorModal");
  const bodyEl = document.getElementById("errorModalBody");
  const titleEl = document.getElementById("errorModalTitle");
  const msg = String(message || "").trim() || String(t("errorPopupUnknown"));
  const now = Date.now();
  if (msg === __lastErrorPopupMsg && now - __lastErrorPopupAt < 900) return;
  __lastErrorPopupMsg = msg;
  __lastErrorPopupAt = now;
  if (!modal || !bodyEl || !titleEl) {
    window.alert(msg);
    return;
  }
  titleEl.textContent = title || t("errorPopupTitle");
  bodyEl.textContent = msg;
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  modal.setAttribute("aria-hidden", "false");
}

function hideErrorPopup() {
  const modal = document.getElementById("errorModal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.classList.remove("flex");
  modal.setAttribute("aria-hidden", "true");
}

function log(message) {
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  if (typeof console !== "undefined" && console.log) {
    console.log(line);
  }
  if (!logEl) return;
  logEl.textContent += `${line}\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

function showAudioUnlockBar() {
  if (!audioUnlockBarEl) return;
  audioUnlockBarEl.classList.remove("hidden");
}

function hideAudioUnlockBar() {
  if (!audioUnlockBarEl) return;
  audioUnlockBarEl.classList.add("hidden");
}

function logCaeVoiceSource(caePayload) {
  const tts = caePayload?.cae_tts || {};
  const vendor = tts.vendor || "unknown";
  const details = [];
  if (tts.voice) details.push(`voice=${tts.voice}`);
  if (tts.voice_id) details.push(`voice_id=${tts.voice_id}`);
  if (tts.model) details.push(`model=${tts.model}`);
  if (tts.model_id) details.push(`model_id=${tts.model_id}`);
  if (tts.region) details.push(`region=${tts.region}`);
  log(`Fonte da voz CAE no RTC: vendor=${vendor}${details.length ? ` (${details.join(", ")})` : ""}.`);
}

async function fetchAndLogCaeVoiceSource(language) {
  try {
    const qLang = encodeURIComponent(language || "pt-BR");
    const response = await fetchWithTimeout(apiUrl(`/api/cae/agent/voice/source?language=${qLang}`), {}, 10000);
    const text = await response.text();
    if (!response.ok) {
      log(`Diagnóstico de voz CAE falhou (${response.status}).`);
      return;
    }
    const data = parseJsonResponse(text, "CAE voice source");
    const tts = data?.cae_tts || {};
    const vendor = String(tts.vendor || "unknown").toLowerCase();
    const details = [];
    if (tts.voice) details.push(`voice=${tts.voice}`);
    if (tts.voice_id) details.push(`voice_id=${tts.voice_id}`);
    if (tts.model) details.push(`model=${tts.model}`);
    if (tts.model_id) details.push(`model_id=${tts.model_id}`);
    if (tts.region) details.push(`region=${tts.region}`);
    log(`Diagnóstico backend TTS: vendor=${vendor}${details.length ? ` (${details.join(", ")})` : ""}.`);
    if (vendor !== "elevenlabs") {
      log("ALERTA: vendor de voz ativo não é ElevenLabs.");
    }
  } catch (err) {
    log(`Diagnóstico de voz CAE indisponível: ${err?.message || err}`);
  }
}

async function setRtcMicCaptureEnabled(enabled) {
  if (!localTrack || typeof localTrack.setEnabled !== "function") return;
  try {
    await localTrack.setEnabled(Boolean(enabled));
  } catch (err) {
    log(`RTC mic setEnabled(${enabled ? "on" : "off"}): ${err?.message || err}`);
  }
}

function setupAgoraAutoplayHook() {
  if (agoraAutoplayHooked || !window.AgoraRTC) return;
  agoraAutoplayHooked = true;
  try {
    AgoraRTC.onAutoplayFailed = () => {
      log(t("logAutoplayBlocked"));
      showAudioUnlockBar();
    };
  } catch (_e) {
    /* SDK antigo sem onAutoplayFailed */
  }
}

/** Segundos sem `user-published` de áudio do agente antes de log de diagnóstico (consola + #log). */
const CAE_REMOTE_AUDIO_WATCHDOG_SEC = 45;

function clearCaeRemoteAudioWatchdog() {
  if (caeRemoteAudioWatchdogTimer) {
    clearTimeout(caeRemoteAudioWatchdogTimer);
    caeRemoteAudioWatchdogTimer = null;
  }
}

function resetCaeRemoteAudioState() {
  expectedCaeAgentUid = null;
  caeAgentAudioReceived = false;
  clearCaeRemoteAudioWatchdog();
}

function scheduleCaeRemoteAudioWatchdog() {
  clearCaeRemoteAudioWatchdog();
  const sec = CAE_REMOTE_AUDIO_WATCHDOG_SEC;
  caeRemoteAudioWatchdogTimer = setTimeout(() => {
    caeRemoteAudioWatchdogTimer = null;
    if (caeAgentAudioReceived || !caeActive) return;
    const uidStr = expectedCaeAgentUid != null ? String(expectedCaeAgentUid) : "?";
    log(
      t("logCaeNoRemoteAudioDiagnostic").replace("%TIME%", String(sec)).replace("%UID%", uidStr),
    );
  }, sec * 1000);
}

/** Chamado quando há `user-published` de áudio remoto; confirma se é o UID do agente CAE. */
function markCaeAgentAudioPublished(uid) {
  if (expectedCaeAgentUid != null && String(uid) !== String(expectedCaeAgentUid)) {
    log(`RTC: áudio publicado por uid=${uid} (agente esperado uid=${expectedCaeAgentUid}).`);
    return;
  }
  if (caeAgentAudioReceived) return;
  caeAgentAudioReceived = true;
  clearCaeRemoteAudioWatchdog();
  log(t("logCaeRemoteAudioOk").replace("%s", String(uid)));
}

/**
 * Se o agente já publicou áudio antes do cliente tratar `user-published`, ou o evento falhou,
 * tenta subscrever com base em `remoteUsers` (Web SDK 4.x).
 */
async function trySyncSubscribeCaeAgentAudio(agentUid) {
  if (!agoraClient || agentUid == null) return;
  const uidStr = String(agentUid);
  const remoteUsers = agoraClient.remoteUsers || [];
  const hasPublished = remoteUsers.some((u) => String(u.uid) === uidStr && u.hasAudio);
  if (!hasPublished) return;
  try {
    await applyRemoteUserAudioPublished(uidStr);
    log(`RTC: sync subscribe áudio do agente uid=${agentUid}`);
  } catch (err) {
    log(`RTC: sync subscribe: ${err?.message || err}`);
  }
}

/** @returns {Promise<boolean>} */
async function playRemoteAudioTrack(track, uid) {
  if (!track) return false;
  try {
    try {
      if (typeof track.setVolume === "function") {
        track.setVolume(100);
      }
    } catch (_v) {
      /* volume opcional */
    }
    const ret = track.play();
    if (ret && typeof ret.then === "function") {
      await ret;
    }
    log(`${t("logRemoteAudio")} (uid=${uid}).`);
    log(t("logCaeTtsPlaying"));
    hideAudioUnlockBar();
    return true;
  } catch (err) {
    log(`${t("logAudioPlayFailed")}: ${err?.message || err}`);
    showAudioUnlockBar();
    return false;
  }
}

/**
 * Aplica subscribe + play uma vez (Web SDK 4.x: `audioTrack` só existe de forma fiável **depois** de `subscribe`).
 * Independente do TTS do CAE (ElevenLabs / OpenAI / Azure) — o browser só recebe áudio remoto RTC.
 * Debounce externo suaviza rajadas de `user-published`.
 */
async function applyRemoteUserAudioPublished(uidStr) {
  if (!agoraClient) return;
  const inFlight = remoteAudioSubscribeInFlightByUid.get(uidStr);
  if (inFlight) {
    await inFlight;
    return;
  }
  const run = (async () => {
  const users = agoraClient.remoteUsers || [];
  const user = users.find((u) => String(u.uid) === uidStr);
  if (!user || !user.hasAudio) return;
  const currentTrack = user.audioTrack;
  const prevTrack = lastRemoteAudioTrackByUid.get(uidStr);
  const now = Date.now();
  const lastSubAt = remoteAudioLastSubscribeAtByUid.get(uidStr) || 0;
  const tooSoon = now - lastSubAt < REMOTE_AUDIO_MIN_SUBSCRIBE_INTERVAL_MS;
  if (currentTrack && prevTrack === currentTrack && tooSoon) {
    return;
  }
  if (currentTrack && isSameTrackReplayTooSoon(uidStr, currentTrack)) {
    return;
  }
  try {
    await agoraClient.subscribe(user, "audio");
    remoteAudioLastSubscribeAtByUid.set(uidStr, Date.now());
  } catch (subErr) {
    log(`RTC subscribe áudio: ${subErr?.message || subErr}`);
    return;
  }
  const pickUser = () => (agoraClient.remoteUsers || []).find((u) => String(u.uid) === uidStr);
  const delaysMs = [0, 16, 48];
  let remote = pickUser();
  let track = remote?.audioTrack ?? user.audioTrack;
  for (let i = 0; !track && i < delaysMs.length; i += 1) {
    await new Promise((r) => setTimeout(r, delaysMs[i]));
    remote = pickUser();
    track = remote?.audioTrack ?? user.audioTrack;
  }
  if (!track) {
    log(`RTC: subscribe OK mas audioTrack ainda ausente (uid=${uidStr}).`);
    return;
  }
  const uidForPlay = remote?.uid ?? user.uid;
  if (isSameTrackReplayTooSoon(uidStr, track)) {
    return;
  }
  markCaeAgentAudioPublished(uidForPlay);
  const prev = lastRemoteAudioTrackByUid.get(uidStr);
  if (prev && prev !== track) {
    stopRemoteAudioTrackIfAny(prev);
  }
  lastRemoteAudioTrackByUid.set(uidStr, track);
  if (!remoteAudioTracks.some((tr) => tr === track)) {
    remoteAudioTracks.push(track);
  }
  const playedOk = await playRemoteAudioTrack(track, uidForPlay);
  if (!playedOk) {
    lastRemoteAudioTrackByUid.delete(uidStr);
    remoteAudioLastPlayAtByUid.delete(uidStr);
  } else {
    remoteAudioLastPlayAtByUid.set(uidStr, Date.now());
  }
  })();
  remoteAudioSubscribeInFlightByUid.set(uidStr, run);
  try {
    await run;
  } finally {
    remoteAudioSubscribeInFlightByUid.delete(uidStr);
  }
}

async function resumeAllRemoteAudio() {
  for (let i = 0; i < remoteAudioTracks.length; i += 1) {
    const tr = remoteAudioTracks[i];
    try {
      if (typeof tr.setVolume === "function") tr.setVolume(100);
      const ret = tr.play();
      if (ret && typeof ret.then === "function") {
        await ret;
      }
    } catch (e) {
      log(String(e?.message || e));
    }
  }
  hideAudioUnlockBar();
  log(t("logAudioResumed"));
}

function applyUiTranslations() {
  document.documentElement.lang = uiLocale;
  const map = {
    brandText: "brandText",
    portfolioTopLink: "portfolioTopLink",
    heroEyebrow: "heroEyebrow",
    heroTitleMain: "heroTitleMain",
    heroTitleGrad: "heroTitleGrad",
    heroCopy: "heroCopy",
    portfolioInfoTitle: "portfolioInfoTitle",
    portfolioInfoDesc: "portfolioInfoDesc",
    portfolioBullet1: "portfolioBullet1",
    portfolioBullet2: "portfolioBullet2",
    portfolioBullet3: "portfolioBullet3",
    portfolioHeroLink: "portfolioHeroLink",
    consoleTitle: "consoleTitle",
    sessionLabel: "sessionLabel",
    userLabel: "userLabel",
    connectAgoraBtn: "connectAgoraBtn",
    sendChatBtn: "sendChatBtn",
    interruptAgentBtn: "interruptAgentBtn",
    ctxSessionLabel: "ctxSessionLabel",
    ctxIntentLabel: "ctxIntentLabel",
    ctxConfirmationLabel: "ctxConfirmationLabel",
    ctxExecutedLabel: "ctxExecutedLabel",
    proactiveTitle: "proactiveTitle",
    traceTitle: "traceTitle",
    debugSummary: "debugSummary",
    errorModalClose: "errorPopupClose",
    audioUnlockText: "audioUnlockText",
    audioUnlockBtn: "audioUnlockBtn",
  };
  Object.entries(map).forEach(([id, key]) => {
    const el = document.getElementById(id);
    if (el) el.textContent = t(key);
  });
  chatInputEl.placeholder = t("chatPlaceholder");
  refreshVoiceToggleButton();
  setContextState({});
  setRtcStatus(isRtcConnected, isRtcConnected ? `uid=${localRtcUid}` : t("statusWaiting"));
  setVoiceUiState(voiceUiState);
}

function setRtcStatus(connected, detail = "") {
  if (!rtcStatusDotEl || !rtcStatusTextEl) return;
  rtcStatusDotEl.className = connected
    ? "h-2 w-2 rounded-full bg-state-success shadow-[0_0_8px_rgba(34,197,94,0.7)]"
    : "h-2 w-2 rounded-full bg-text-muted";
  rtcStatusTextEl.textContent = connected
    ? `${t("statusConnected")}${detail ? ` (${detail})` : ""}`
    : detail || t("statusWaiting");
}

function setVoiceUiState(state) {
  voiceUiState = state;
  if (!agentStateLabelEl || !agentStateHintEl || !agentStatePulseEl) return;
  const stateMap = {
    idle: ["stateIdle", "stateIdleHint", "bg-text-muted", false],
    listening: ["stateListening", "stateListeningHint", "bg-accent-primary animate-pulse-soft", false],
    thinking: ["stateThinking", "stateThinkingHint", "bg-state-warning animate-pulse-soft", false],
    speaking: ["stateSpeaking", "stateSpeakingHint", "bg-state-success animate-pulse-soft", true],
    interrupted: ["stateInterrupted", "stateInterruptedHint", "bg-state-warning", false],
    error: ["stateError", "stateErrorHint", "bg-state-error", false],
  };
  const [labelKey, hintKey, dotClasses, showInterrupt] = stateMap[state] || stateMap.idle;
  agentStateLabelEl.textContent = t(labelKey);
  agentStateHintEl.textContent = t(hintKey);
  agentStatePulseEl.className = `h-3 w-3 rounded-full ${dotClasses}`;
  interruptAgentBtnEl.classList.toggle("hidden", !showInterrupt);
}

function setContextState({ sessionId = null, intent = null, needsConfirmation = null, actionExecuted = null } = {}) {
  if (sessionId !== null && ctxSessionEl) ctxSessionEl.textContent = sessionId || "-";
  if (intent !== null && ctxIntentEl) ctxIntentEl.textContent = intent || "-";
  if (needsConfirmation !== null && ctxConfirmationEl) ctxConfirmationEl.textContent = needsConfirmation ? t("contextPending") : t("contextNoPending");
  if (actionExecuted !== null && ctxExecutedEl) ctxExecutedEl.textContent = actionExecuted ? t("contextYes") : t("contextNo");
}

function renderProactiveSuggestions(items = []) {
  proactiveSuggestionsEl.innerHTML = "";
  if (!items.length) {
    const span = document.createElement("span");
    span.className = "text-xs text-text-muted";
    span.textContent = t("proactiveEmpty");
    proactiveSuggestionsEl.appendChild(span);
    return;
  }
  items.slice(0, 2).forEach((item) => {
    const pill = document.createElement("span");
    pill.className = "rounded-full border border-border-subtle bg-bg-primary px-2 py-1 text-xs text-text-secondary";
    pill.textContent = item.message || item.title || "Suggestion";
    proactiveSuggestionsEl.appendChild(pill);
  });
}

function renderAgentTrace(trace) {
  if (!agentTraceEl) return;
  agentTraceEl.innerHTML = "";
  const steps = trace?.steps || [];
  if (!steps.length) {
    const span = document.createElement("span");
    span.className = "text-xs text-text-muted";
    span.textContent = t("traceEmpty");
    agentTraceEl.appendChild(span);
    return;
  }
  steps.forEach((step) => {
    const statusColor = step.status === "error" ? "border-state-error/50" : step.status === "warning" ? "border-state-warning/50" : "border-border-subtle";
    const div = document.createElement("div");
    div.className = `rounded-lg border ${statusColor} bg-bg-primary p-2 text-xs text-text-muted`;
    const dataText = step.data && Object.keys(step.data).length ? ` · ${JSON.stringify(step.data)}` : "";
    div.innerHTML = `<div class="font-medium text-text-secondary">${step.name}</div><div class="mt-1">${step.message || ""}${dataText}</div>`;
    agentTraceEl.appendChild(div);
  });
}

function createMessageBubble(role) {
  const wrapper = document.createElement("div");
  wrapper.className = `mb-2.5 max-w-[86%] rounded-2xl border p-3 shadow-soft animate-fade-in-up ${
    role === "user"
      ? "ml-auto border-accent-primary/40 bg-gradient-to-br from-accent-primary/15 to-accent-secondary/10"
      : "mr-auto border-border-subtle bg-bg-elevated/95"
  }`;
  const head = document.createElement("div");
  head.className = "mb-1.5 flex items-center justify-between text-[11px] text-text-muted";
  const roleEl = document.createElement("span");
  roleEl.className = "font-medium";
  roleEl.textContent = role === "user" ? t("roleUser") : t("roleAssistant");
  const timeEl = document.createElement("span");
  timeEl.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const body = document.createElement("div");
  body.className =
    "text-sm leading-6 text-text-primary whitespace-pre-line break-words";
  head.appendChild(roleEl);
  head.appendChild(timeEl);
  wrapper.appendChild(head);
  wrapper.appendChild(body);
  chatMessagesEl.appendChild(wrapper);
  chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
  return body;
}

function addChatMessage(role, text) {
  const body = createMessageBubble(role);
  body.textContent = text;
}

function createStreamingAssistantMessage() {
  const body = createMessageBubble("assistant");
  return {
    append(chunk) {
      body.textContent = body.textContent ? `${body.textContent} ${chunk}` : chunk;
      chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    },
    set(text) {
      body.textContent = text;
      chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
    },
  };
}

async function signalInterrupt() {
  const sessionId = sessionIdEl.value.trim();
  if (!sessionId) return;
  try {
    await fetch(apiUrl(`/api/conversation/${sessionId}/voice/interrupt`), { method: "POST" });
  } catch (_err) {}
}

async function getAgoraSession(sessionId) {
  const response = await fetchWithTimeout(apiUrl(`/api/system/agora/session/${sessionId}`), {}, 30000);
  const text = await response.text();
  if (!response.ok) throw new Error(parseHttpErrorBody(text, response.status));
  return parseJsonResponse(text, "Sessão Agora");
}

async function startCaeAgent(sessionId, channel, token, remoteUid) {
  const response = await fetchWithTimeout(
    apiUrl("/api/cae/agent/start"),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        channel,
        token,
        remote_uid: String(remoteUid),
        language: getBackendLangFromUi(),
      }),
    },
    90000,
  );
  const text = await response.text();
  if (!response.ok) throw new Error(parseHttpErrorBody(text, response.status));
  return parseJsonResponse(text, "CAE");
}

async function connectAgora() {
  if (!window.AgoraRTC) throw new Error("Agora SDK not loaded.");
  if (isConnectingAgora) {
    log(t("logConnecting"));
    return;
  }
  if (isRtcConnected) {
    log(t("logAlreadyConnected"));
    return;
  }

  setupAgoraAutoplayHook();
  remoteAudioTracks = [];
  lastRemoteAudioTrackByUid.clear();
  clearRemoteAudioPublishDebouncers();
  resetCaeRemoteAudioState();

  isConnectingAgora = true;
  connectAgoraBtnEl.disabled = true;
  const sessionId = sessionIdEl.value.trim();
  try {
    try {
      if (window.AgoraRTC && typeof AgoraRTC.setLogLevel === "function") {
        // 0 = NONE no SDK Web — corta o flood de Agora-SDK [DEBUG]/[INFO] no console.
        const lv =
          typeof AgoraRTC.LOG_LEVEL === "object" && AgoraRTC.LOG_LEVEL.NONE !== undefined
            ? AgoraRTC.LOG_LEVEL.NONE
            : 0;
        AgoraRTC.setLogLevel(lv);
      }
    } catch (_e) {
      /* noop */
    }
    log(t("logAgoraStepSession"));
    let data;
    try {
      data = await getAgoraSession(sessionId);
    } catch (e) {
      if (e && e.name === "AbortError") {
        throw new Error("Sessão Agora: tempo limite (30s). O backend não respondeu a tempo.");
      }
      throw e;
    }
    agoraClient = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
    let lastVolumeLogTs = 0;
    try {
      if (typeof agoraClient.enableAudioVolumeIndicator === "function") {
        agoraClient.enableAudioVolumeIndicator();
        agoraClient.on("volume-indicator", (volumes) => {
          const now = Date.now();
          for (const v of volumes) {
            if (v.level > 5 && now - lastVolumeLogTs > 2000) {
              lastVolumeLogTs = now;
              log(`RTC volume-indicator uid=${v.uid} level=${v.level}`);
            }
          }
        });
      }
    } catch (_e) {
      /* ignore */
    }
    agoraClient.on("user-info-update", (uid, msg) => {
      if (msg === "mute-audio") {
        logRtcAudioEvent(uid, "mute-info");
        return;
      }
      if (msg === "unmute-audio") {
        logRtcAudioEvent(uid, "unmute-info");
        return;
      }
      log(`RTC user-info-update uid=${uid} msg=${msg}`);
    });
    agoraClient.on("user-joined", (user) => {
      log(t("logRemoteUserJoined").replace("%s", String(user.uid)));
    });
    agoraClient.on("user-unpublished", (user, mediaType) => {
      if (mediaType !== "audio") return;
      const uidStr = String(user.uid);
      remoteAudioPublishBurstStartTs.delete(uidStr);
      logRtcAudioEvent(user.uid, "unpublished");
      lastRemoteAudioTrackByUid.delete(uidStr);
      remoteAudioLastSubscribeAtByUid.delete(uidStr);
      remoteAudioSubscribeInFlightByUid.delete(uidStr);
      pruneRemoteAudioTracksFromClient();
    });
    agoraClient.on("user-published", (user, mediaType) => {
      if (mediaType !== "audio") {
        agoraClient.subscribe(user, mediaType).catch((err) => {
          log(`RTC subscribe ${mediaType}: ${err?.message || err}`);
        });
        return;
      }
      logRtcAudioEvent(user.uid, "published");
      scheduleApplyRemoteUserAudio(String(user.uid));
    });
    log(t("logAgoraStepJoin"));
    try {
      localRtcUid = await agoraClient.join(data.app_id, data.channel, data.token, data.uid);
    } catch (joinErr) {
      const code = joinErr && typeof joinErr.code === "number" ? ` código Agora ${joinErr.code}` : "";
      log(`${t("logAgoraJoinHint")} ${joinErr?.message || joinErr}${code}`);
      throw joinErr;
    }
    log(t("logAgoraStepMic"));
    localTrack = await AgoraRTC.createMicrophoneAudioTrack();
    log(t("logAgoraStepPublish"));
    await agoraClient.publish([localTrack]);
    // Mantém o microfone RTC fechado até o usuário iniciar captura explicitamente.
    await setRtcMicCaptureEnabled(false);
    isRtcConnected = true;
    setRtcStatus(true, `uid=${localRtcUid}`);
    log(`${t("logConnected")} ${data.channel}.`);
    try {
      let cae;
      try {
        cae = await startCaeAgent(sessionId, data.channel, data.token, localRtcUid);
      } catch (e) {
        if (e && e.name === "AbortError") {
          throw new Error(
            "CAE: tempo limite (90s) ao iniciar o agente. A API Agora ou o backend pode estar lenta; tente de novo.",
          );
        }
        throw e;
      }
      caeActive = cae?.started !== false;
      if (cae?.cae_tts) {
        log(`CAE TTS (backend): ${JSON.stringify(cae.cae_tts)}`);
      }
      logCaeVoiceSource(cae);
      if (cae?.agent_rtc_uid != null && cae?.agent_rtc_uid !== undefined) {
        expectedCaeAgentUid = cae.agent_rtc_uid;
        log(`CAE agent_rtc_uid (backend): ${expectedCaeAgentUid}`);
      }
      caeAgentAudioReceived = false;
      if (caeActive) {
        log(t("logCaeActive"));
        log(t("logCaeSpeakHint"));
        await fetchAndLogCaeVoiceSource(getBackendLangFromUi());
        scheduleCaeRemoteAudioWatchdog();
        const uidForSync = expectedCaeAgentUid;
        setTimeout(() => trySyncSubscribeCaeAgentAudio(uidForSync), 0);
        setTimeout(() => trySyncSubscribeCaeAgentAudio(uidForSync), 1500);
      } else {
        log(t("logCaeFallback"));
        clearCaeRemoteAudioWatchdog();
      }
      refreshVoiceToggleButton();
    } catch (caeErr) {
      caeActive = false;
      resetCaeRemoteAudioState();
      log(`${t("logCaeFallback")} — ${caeErr?.message || caeErr || ""}`);
      refreshVoiceToggleButton();
    }
  } finally {
    isConnectingAgora = false;
    connectAgoraBtnEl.disabled = false;
  }
}

async function sendMessage(message) {
  const sessionId = sessionIdEl.value.trim();
  const userId = userIdEl.value.trim();
  setVoiceUiState("thinking");

  try {
    let response;
    try {
      response = await fetchWithTimeout(
        apiUrl(`/api/conversation/${sessionId}/message/stream`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, user_id: userId, stream: true }),
        },
        120000,
      );
    } catch (err) {
      if (err && err.name === "AbortError") {
        throw new Error("Pedido excedeu o tempo limite (120s). Verifique o servidor e a rede.");
      }
      throw err;
    }
    if (!response.ok) {
      const errText = await response.text();
      throw new Error(parseHttpErrorBody(errText, response.status));
    }

    const streamBubble = createStreamingAssistantMessage();
    const reader = response.body?.getReader();
    if (!reader) throw new Error("Streaming body unavailable.");

    const decoder = new TextDecoder();
    let buffer = "";
    let finalPayload = null;

    const consumeSseBuffer = () => {
      if (buffer.length >= 32 && looksLikeHtmlPayload(buffer)) {
        throw new Error(parseHttpErrorBody(buffer, response.status));
      }
      const events = buffer.split("\n\n");
      buffer = events.pop() || "";
      for (const eventChunk of events) {
        const line = eventChunk.split("\n").find((part) => part.startsWith("data: "));
        if (!line) continue;
        let payload;
        try {
          payload = JSON.parse(line.slice(6).trimStart());
        } catch (_e) {
          continue;
        }
        if (payload.type === "chunk") {
          streamBubble.append(payload.text);
        } else if (payload.type === "final") {
          finalPayload = payload.response;
        }
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      consumeSseBuffer();
    }
    buffer += decoder.decode();
    consumeSseBuffer();
    if (!finalPayload && buffer.trim()) {
      const line = buffer.split("\n").find((part) => part.startsWith("data: "));
      if (line) {
        try {
          const payload = JSON.parse(line.replace(/^data:\s*/, ""));
          if (payload.type === "final") finalPayload = payload.response;
        } catch (_e) {}
      }
    }

    if (!finalPayload) {
      if (looksLikeHtmlPayload(buffer)) throw new Error(parseHttpErrorBody(buffer, response.status));
      throw new Error("Final payload missing.");
    }

    currentLanguage = finalPayload.language === "en" ? "en-US" : finalPayload.language === "es" ? "es-ES" : "pt-BR";
    streamBubble.set(finalPayload.response_text);
    setContextState({
      sessionId: finalPayload.session_id || sessionId,
      intent: finalPayload.intent,
      needsConfirmation: finalPayload.needs_confirmation,
      actionExecuted: finalPayload.action_executed,
    });
    renderProactiveSuggestions(finalPayload.proactive_suggestions || []);
    renderAgentTrace(finalPayload.trace || null);
  } catch (err) {
    if (!isRecording) setVoiceUiState("idle");
    throw err;
  }
  if (!isRecording) setVoiceUiState("idle");
}

function floatTo16BitPCM(input) {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i += 1) {
    const s = Math.max(-1, Math.min(1, input[i]));
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return output;
}

function encodeWav(samples, sampleRate = 16000) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, str) => {
    for (let i = 0; i < str.length; i += 1) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    view.setInt16(offset, samples[i], true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

async function transcribeRecordedAudio(wavBlob) {
  const formData = new FormData();
  formData.append("file", wavBlob, "record.wav");
  formData.append("language", getSpeechLocaleFromUi());
    const response = await fetch(apiUrl("/api/system/stt/transcribe"), { method: "POST", body: formData });
  const ttxt = await response.text();
  if (!response.ok) throw new Error(parseHttpErrorBody(ttxt, response.status));
  return parseJsonResponse(ttxt, "Transcrição");
}

async function startRecording() {
  if (isRecording) return;
  await setRtcMicCaptureEnabled(true);
  try {
    const permission = await navigator.mediaDevices.getUserMedia({ audio: true });
    permission.getTracks().forEach((track) => track.stop());
  } catch (err) {
    throw new Error(`${t("logMicError")}: ${err.message}`);
  }
  recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recordingContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
  recordingSource = recordingContext.createMediaStreamSource(recordingStream);
  recordingNode = recordingContext.createScriptProcessor(4096, 1, 1);
  recordingChunks = [];
  recordingNode.onaudioprocess = (event) => {
    recordingChunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
  };
  recordingSource.connect(recordingNode);
  recordingNode.connect(recordingContext.destination);
  isRecording = true;
  setVoiceUiState("listening");
  refreshVoiceToggleButton();
}

async function stopRecordingAndSend() {
  if (!isRecording) return;
  isRecording = false;
  if (recordingNode) {
    try {
      recordingNode.disconnect();
    } catch (_e) {}
  }
  if (recordingSource) {
    try {
      recordingSource.disconnect();
    } catch (_e) {}
  }
  if (recordingStream) {
    try {
      recordingStream.getTracks().forEach((track) => track.stop());
    } catch (_e) {}
  }
  if (recordingContext) {
    try {
      await recordingContext.close();
    } catch (_e) {}
  }
  recordingNode = null;
  recordingSource = null;
  recordingStream = null;
  recordingContext = null;
  await setRtcMicCaptureEnabled(false);
  setVoiceUiState("thinking");

  const totalLength = recordingChunks.reduce((acc, item) => acc + item.length, 0);
  const merged = new Float32Array(totalLength);
  let offset = 0;
  recordingChunks.forEach((chunk) => {
    merged.set(chunk, offset);
    offset += chunk.length;
  });

  const pcm = floatTo16BitPCM(merged);
  const wavBlob = encodeWav(pcm, 16000);
  const stt = await transcribeRecordedAudio(wavBlob);
  const text = (stt.text || "").trim();
  if (!text) {
    setVoiceUiState("idle");
    return;
  }
  addChatMessage("user", text);
  await sendMessage(text);
}

async function interruptAgent() {
  await signalInterrupt();
  setVoiceUiState("interrupted");
}

async function pollVoiceState() {
  const sessionId = sessionIdEl.value.trim();
  if (!sessionId) return;
  try {
    const response = await fetch(apiUrl(`/api/conversation/${sessionId}/voice/state`));
    if (!response.ok) return;
    const state = await response.json();
    if (state.user_interrupting) {
      setVoiceUiState("interrupted");
    }
  } catch (_err) {}
}

connectAgoraBtnEl.addEventListener("click", async () => {
  try {
    await connectAgora();
  } catch (err) {
    const detail = err?.message || String(err);
    setRtcStatus(false, t("statusFailed"));
    setVoiceUiState("error");
    log(detail);
    showErrorPopup(detail);
  }
});

voiceToggleBtnEl.addEventListener("click", async () => {
  try {
    if (!isRecording) {
      if (caeActive) {
        log(t("logCaeLocalRecord"));
      }
      await startRecording();
      return;
    }
    await signalInterrupt();
    await stopRecordingAndSend();
    setVoiceUiState("idle");
    refreshVoiceToggleButton();
  } catch (err) {
    const detail = err?.message || String(err);
    setVoiceUiState("error");
    refreshVoiceToggleButton();
    log(`${t("logVoiceError")}: ${detail}`);
    showErrorPopup(detail);
  }
});

interruptAgentBtnEl.addEventListener("click", async () => {
  await interruptAgent();
});

sendChatBtnEl.addEventListener("click", async () => {
  const text = (chatInputEl.value || "").trim();
  if (!text) {
    log(t("logTypeMessage"));
    return;
  }
  addChatMessage("user", text);
  chatInputEl.value = "";
  try {
    await sendMessage(text);
  } catch (err) {
    const detail = err?.message || String(err);
    setVoiceUiState("error");
    log(`${t("logBackendError")}: ${detail}`);
    showErrorPopup(detail);
  }
});

chatInputEl.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  sendChatBtnEl.click();
});

languageSelectEl.addEventListener("change", () => {
  uiLocale = languageSelectEl.value;
  currentLanguage = getSpeechLocaleFromUi();
  applyUiTranslations();
});

sessionIdEl.addEventListener("input", () => {
  setContextState({ sessionId: sessionIdEl.value.trim() || "-" });
});

if ((sessionIdEl.value || "").trim() === "sessao-demo-1") {
  sessionIdEl.value = `sessao-${Date.now()}`;
}

setRtcStatus(false, t("statusWaiting"));
setContextState({
  sessionId: sessionIdEl.value.trim(),
  intent: "-",
  needsConfirmation: false,
  actionExecuted: false,
});
renderProactiveSuggestions([]);
renderAgentTrace(null);
setVoiceUiState("idle");
applyUiTranslations();
addChatMessage("assistant", t("welcomeAssistant"));
setInterval(() => {
  pollVoiceState();
}, 2500);

audioUnlockBtnEl?.addEventListener("click", () => {
  resumeAllRemoteAudio();
});

window.addEventListener("beforeunload", () => {
  try {
    if (isRecording) {
      stopRecordingAndSend().catch(() => {});
    } else {
      setRtcMicCaptureEnabled(false).catch(() => {});
    }
    clearRemoteAudioPublishDebouncers();
    clearCaeRemoteAudioWatchdog();
  } catch (_e) {}
});

(function setupErrorModal() {
  const modal = document.getElementById("errorModal");
  const closeBtn = document.getElementById("errorModalClose");
  closeBtn?.addEventListener("click", () => hideErrorPopup());
  modal?.addEventListener("click", (e) => {
    if (e.target === modal) hideErrorPopup();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (modal && !modal.classList.contains("hidden")) hideErrorPopup();
  });
})();
