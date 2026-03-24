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
/** Só true quando o track local está publicado no canal (PTT: CAE/ASR só recebe áudio neste período). */
let localRtcAudioPublishedToChannel = false;

/** Tracks de áudio remoto (agente CAE) para retomar play após bloqueio de autoplay */
let remoteAudioTracks = [];
/** Último RemoteAudioTrack por uid — ao republicar áudio, parar o anterior evita sobreposição / som «travado». */
let lastRemoteAudioTrackByUid = new Map();
/** Evita `play()` duplicado se o SDK repetir `user-published` para a mesma instância de track (referência). */
let agoraAutoplayHooked = false;

/** Evita subscribe/play em rajada para o mesmo uid. */
let remoteAudioSubscribeInFlightByUid = new Map();
let remoteAudioLastSubscribeAtByUid = new Map();
let remoteAudioLastPlayAtByUid = new Map();
/** Após INVALID_REMOTE_USER / «not published», não martelar o SDK durante este período. */
let remoteAudioSubscribeBackoffUntilByUid = new Map();
const REMOTE_AUDIO_INVALID_SUBSCRIBE_BACKOFF_MS = 280;
let remoteAudioLastInvalidSubscribeLogAtByUid = new Map();
const REMOTE_AUDIO_INVALID_LOG_EVERY_MS = 4000;
/** Intervalo mínimo entre subscribes ao mesmo uid — baixo para reduzir latência perceptível do TTS CAE. */
const REMOTE_AUDIO_MIN_SUBSCRIBE_INTERVAL_MS = 180;
/** Evita play() duplicado no mesmo track; não bloquear respostas novas do agente. */
const REMOTE_AUDIO_MIN_REPLAY_INTERVAL_MS = 2200;
const RTC_EVENT_LOG_THROTTLE_MS = 1500;
const rtcAudioEventStatsByUid = new Map();

function clearRemoteAudioPublishDebouncers() {
  remoteAudioSubscribeInFlightByUid.clear();
  remoteAudioLastSubscribeAtByUid.clear();
  remoteAudioLastPlayAtByUid.clear();
  remoteAudioSubscribeBackoffUntilByUid.clear();
  remoteAudioLastInvalidSubscribeLogAtByUid.clear();
  rtcAudioEventStatsByUid.clear();
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

let uiLocale = "en-US";
let currentLanguage = "en-US";
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
    voiceToggleIdle: "Iniciar voz",
    voiceToggleRecording: "Parar captura",
    voiceToggleCaeLive: "CAE ativo (fale agora)",
    sendChatBtn: "Enviar",
    interruptAgentBtn: "Interromper resposta do agente",
    ctxSessionLabel: "Sessão",
    ctxIntentLabel: "Última intenção",
    ctxConfirmationLabel: "Confirmação",
    ctxExecutedLabel: "Execução",
    traceTitle: "Operational Trace",
    debugSummary: "Diagnóstico técnico",
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
      "Olá! Para agendar, faço uma pergunta de cada vez (nome, e-mail, assunto da reunião, data/hora) — assim funciona melhor por voz. Também posso listar, reagendar ou cancelar. Links não são lidos em voz.",
    logConnecting: "Conexão com Agora em andamento.",
    logAlreadyConnected: "Já conectado no canal Agora.",
    logAgoraStepSession: "1/3 A pedir token ao backend…",
    logAgoraStepJoin: "2/3 A entrar no canal RTC…",
    logAgoraStepMic: "3/3 A preparar o microfone (só envia áudio ao CAE ao premir o botão de voz)…",
    logAgoraJoinHint:
      "Se falhar aqui: token inválido ou expirado. No backend defina AGORA_APP_CERTIFICATE (Console Agora) em vez de só AGORA_TEMP_TOKEN.",
    logConnected: "Agora conectada no canal",
    logRemoteUserJoined: "RTC: participante remoto entrou — uid=%s (esperado: agente CAE).",
    logRemoteAudio: "Áudio remoto ativo",
    logCaeTtsPlaying:
      "TTS CAE (Agora): áudio remoto do agente — voz sintetizada pelo Conversational AI no canal RTC.",
    logCaeActive: "CAE ativo. Prima o botão de voz para o microfone entrar no canal (push-to-talk).",
    logCaeSpeakHint:
      "Voz CAE: sem premir o botão, o teu áudio não é publicado no RTC — o agente não ouve. Com o botão ativo, fala; o TTS do agente vem do CAE (ex. ElevenLabs). Chat/STT local só atualiza texto no servidor.",
    logCaeLocalRecord:
      "CAE ativo: captura local para STT no chat; o CAE ouve só enquanto o botão de voz está ligado (áudio RTC publicado).",
    logCaeFallback:
      "O agente de voz CAE não entrou no canal (falha no join na Agora). Se os logs do servidor mostram HTTP 429 ou «vendor capacity», é fila/capacidade do TTS — recarregue a página mais tarde ou mude AGORA_CAE_TTS_VENDOR. O chat por texto continua a funcionar.",
    logCaeRemoteAudioOk:
      "RTC: primeiro áudio publicado pelo agente CAE (uid=%s) — o browser deve reproduzir (ou pedir «Ativar áudio»).",
    logCaeNoRemoteAudioDiagnostic:
      "Erro (áudio RTC): após %TIME% s não houve «user-published» de áudio do agente CAE (uid esperado %UID%). " +
      "Causas prováveis: CAE/TTS inativo, microfone não publicado no canal, ou falha Agora/ElevenLabs. Verifique logs do servidor e consola.",
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
    sttTooShort: "Gravação muito curta. Fale um pouco mais antes de soltar o botão de voz, ou escreva no chat.",
    errHtmlInsteadOfApi:
      "O servidor devolveu uma página HTML (como «Page not found» do Netlify) em vez da API JSON.\n\n" +
      "• Netlify: em Site → Environment variables crie SCHEDULER_API_BASE com a URL do FastAPI (ex.: https://seu-app.railway.app), sem barra no fim, e faça um deploy novo.\n" +
      "• Teste local: use a mesma origem do uvicorn ou defina window.__SCHEDULER_API_BASE__ = 'http://127.0.0.1:8000' antes de carregar app.js.",
  },
  "en-US": {
    brandText: "Voice Scheduling System",
    portfolioTopLink: "View my portfolio",
    heroEyebrow: "Real-time Conversational Agent",
    heroTitleMain: "Talk naturally.",
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
    voiceToggleIdle: "Start voice",
    voiceToggleRecording: "Stop capture",
    voiceToggleCaeLive: "CAE live (speak now)",
    sendChatBtn: "Send",
    interruptAgentBtn: "Interrupt agent response",
    ctxSessionLabel: "Session",
    ctxIntentLabel: "Last intent",
    ctxConfirmationLabel: "Confirmation",
    ctxExecutedLabel: "Execution",
    traceTitle: "Operational Trace",
    debugSummary: "Technical diagnostics",
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
      "Hello! To schedule, I'll ask one thing at a time (your name, email, meeting subject, then date and time) — that works better for voice. I can also list, reschedule, or cancel. Calendar links are not read aloud.",
    logConnecting: "Connecting to Agora...",
    logAlreadyConnected: "Already connected to Agora channel.",
    logAgoraStepSession: "1/3 Requesting token from backend…",
    logAgoraStepJoin: "2/3 Joining RTC channel…",
    logAgoraStepMic: "3/3 Preparing mic (audio published only while voice button is on)…",
    logConnected: "Agora connected on channel",
    logRemoteUserJoined: "RTC: remote participant joined — uid=%s (expected: CAE agent).",
    logRemoteAudio: "Remote audio active",
    logCaeTtsPlaying:
      "CAE TTS (Agora): remote agent audio — synthesized by Conversational AI on the RTC channel.",
    logCaeActive: "CAE active. Press the voice button to publish your mic (push-to-talk).",
    logCaeSpeakHint:
      "CAE: without the voice button, your audio is not on the channel. When on, speak; agent TTS comes from CAE (e.g. ElevenLabs). Local chat/STT only updates server text.",
    logCaeLocalRecord:
      "CAE active: local capture for chat STT; CAE listens only while the voice button is on.",
    logCaeFallback:
      "Voice agent CAE did not join the channel (Agora join failed). If server logs show HTTP 429 or «vendor capacity», the TTS queue is saturated — reload the page later or change AGORA_CAE_TTS_VENDOR. Text chat still works.",
    logCaeRemoteAudioOk:
      "RTC: first remote audio published by CAE agent (uid=%s) — browser should play (or use «Enable agent audio»).",
    logCaeNoRemoteAudioDiagnostic:
      "Error (RTC audio): after %TIME% s there was no «user-published» audio from the CAE agent (expected uid %UID%). " +
      "Likely causes: CAE/TTS inactive, mic not published to channel, or Agora/ElevenLabs failure. Check server logs and browser console.",
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
    sttTooShort: "Recording too short. Hold the voice button a bit longer, or type in the chat.",
    errHtmlInsteadOfApi:
      "The server returned an HTML page (e.g. Netlify «Page not found») instead of JSON.\n\n" +
      "• Netlify: Site → Environment variables → set SCHEDULER_API_BASE to your FastAPI public URL (no trailing slash), then redeploy.\n" +
      "• Local: serve from uvicorn or set window.__SCHEDULER_API_BASE__ = 'http://127.0.0.1:8000' before app.js.",
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
    if (j.detail != null && typeof j.detail === "object" && typeof j.detail.message === "string") {
      return j.detail.message;
    }
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
  return uiLocale;
}

function getBackendLangFromUi() {
  return uiLocale;
}

/** Idioma da conversa no backend (pt/en/es), alinhado ao seletor da interface. */
function getConversationLangFromUi() {
  if (uiLocale.startsWith("en")) return "en";
  return "pt";
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

/** Diagnóstico de áudio / RTC (painel #log + consola). */
function logAudioDiag(phase, detail, extra) {
  const rel =
    typeof performance !== "undefined" && performance.now
      ? `+${performance.now().toFixed(0)}ms`
      : "";
  const tail = extra != null ? ` ${typeof extra === "string" ? extra : JSON.stringify(extra)}` : "";
  log(`[audio] ${rel} ${phase}: ${detail}${tail}`);
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
    const qLang = encodeURIComponent(language || "en-US");
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
    logAudioDiag("RTC mic", `setEnabled(${enabled ? "on" : "off"})`, { published: localRtcAudioPublishedToChannel });
  } catch (err) {
    log(`RTC mic setEnabled(${enabled ? "on" : "off"}): ${err?.message || err}`);
  }
}

/**
 * Publica ou retira o microfone RTC do canal. Enquanto não publicado, o CAE não recebe áudio do utilizador (push-to-talk).
 */
async function setLocalRtcAudioUpstream(publish) {
  if (!agoraClient || !localTrack || !isRtcConnected) return;
  try {
    if (publish) {
      if (localRtcAudioPublishedToChannel) return;
      // O Web SDK recusa publish com track desligado (TRACK_IS_DISABLED).
      if (typeof localTrack.setEnabled === "function" && !localTrack.enabled) {
        await localTrack.setEnabled(true);
      }
      await agoraClient.publish([localTrack]);
      localRtcAudioPublishedToChannel = true;
      logAudioDiag("RTC upstream", "publish — microfone no canal (CAE/ASR pode ouvir)");
    } else {
      if (!localRtcAudioPublishedToChannel) return;
      await agoraClient.unpublish([localTrack]);
      localRtcAudioPublishedToChannel = false;
      logAudioDiag("RTC upstream", "unpublish — sem áudio do utilizador no canal até novo PTT");
    }
  } catch (err) {
    log(`RTC publish/unpublish: ${err?.message || err}`);
    logAudioDiag("RTC upstream", "erro publish/unpublish", String(err?.message || err));
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
  logAudioDiag("cae_agent", "primeiro user-published áudio do agente", { uid: String(uid) });
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
  const u = remoteUsers.find((x) => String(x.uid) === uidStr);
  if (!u) return;
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
  const backoffUntil = remoteAudioSubscribeBackoffUntilByUid.get(uidStr) || 0;
  if (Date.now() < backoffUntil) {
    return;
  }
  const inFlight = remoteAudioSubscribeInFlightByUid.get(uidStr);
  if (inFlight) {
    await inFlight;
    return;
  }
  const run = (async () => {
  logAudioDiag("remote_audio", "applyRemoteUserAudioPublished início", { uid: uidStr });
  const users = agoraClient.remoteUsers || [];
  const user = users.find((u) => String(u.uid) === uidStr);
  if (!user) {
    logAudioDiag("remote_audio", "skip sem remote user", { uid: uidStr });
    return;
  }
  // Não exigir hasAudio: no user-published o SDK por vezes ainda não actualizou o flag e o subscribe falhava a toda a sessão.
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
    logAudioDiag("remote_audio", "subscribe(audio)…", { uid: uidStr });
    await agoraClient.subscribe(user, "audio");
    remoteAudioLastSubscribeAtByUid.set(uidStr, Date.now());
    logAudioDiag("remote_audio", "subscribe(audio) OK", { uid: uidStr });
  } catch (subErr) {
    const msg = String(subErr?.message || subErr);
    const notPublished =
      msg.includes("INVALID_REMOTE_USER") ||
      msg.includes("not published") ||
      msg.includes("NOT_PUBLISHED");
    if (notPublished) {
      remoteAudioSubscribeBackoffUntilByUid.set(uidStr, Date.now() + REMOTE_AUDIO_INVALID_SUBSCRIBE_BACKOFF_MS);
      const lastInv = remoteAudioLastInvalidSubscribeLogAtByUid.get(uidStr) || 0;
      if (Date.now() - lastInv >= REMOTE_AUDIO_INVALID_LOG_EVERY_MS) {
        remoteAudioLastInvalidSubscribeLogAtByUid.set(uidStr, Date.now());
        logAudioDiag("remote_audio", "subscribe adiado (remoto sem áudio publicado neste instante)", {
          uid: uidStr,
          err: msg,
        });
      }
      return;
    }
    log(`RTC subscribe áudio: ${msg}`);
    logAudioDiag("remote_audio", "subscribe FALHOU", { uid: uidStr, err: msg });
    return;
  }
  const pickUser = () => (agoraClient.remoteUsers || []).find((u) => String(u.uid) === uidStr);
  const delaysMs = [0, 4, 12, 28, 55];
  let remote = pickUser();
  let track = remote?.audioTrack ?? user.audioTrack;
  for (let i = 0; !track && i < delaysMs.length; i += 1) {
    await new Promise((r) => setTimeout(r, delaysMs[i]));
    remote = pickUser();
    track = remote?.audioTrack ?? user.audioTrack;
  }
  if (!track) {
    log(`RTC: subscribe OK mas audioTrack ainda ausente (uid=${uidStr}).`);
    logAudioDiag("remote_audio", "audioTrack ausente após subscribe", { uid: uidStr });
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
  logAudioDiag("remote_audio", "play() remoto…", { uid: String(uidForPlay) });
  const playedOk = await playRemoteAudioTrack(track, uidForPlay);
  logAudioDiag("remote_audio", playedOk ? "play() OK" : "play() falhou", { uid: String(uidForPlay) });
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
    sendChatBtn: "sendChatBtn",
    interruptAgentBtn: "interruptAgentBtn",
    ctxSessionLabel: "ctxSessionLabel",
    ctxIntentLabel: "ctxIntentLabel",
    ctxConfirmationLabel: "ctxConfirmationLabel",
    ctxExecutedLabel: "ctxExecutedLabel",
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
        user_id: (userIdEl && userIdEl.value ? userIdEl.value.trim() : "") || "local-user",
      }),
    },
    240000,
  );
  const text = await response.text();
  if (!response.ok) throw new Error(parseHttpErrorBody(text, response.status));
  return parseJsonResponse(text, "CAE");
}

/**
 * Se o 1.º ciclo de retries do backend esgotar numa fila Agora (429), uma pausa + 2.º pedido
 * muitas vezes acerta quando a capacidade abre (não substitui quota/plano Agora).
 */
async function startCaeAgentWithBackoffRetry(sessionId, channel, token, remoteUid) {
  try {
    return await startCaeAgent(sessionId, channel, token, remoteUid);
  } catch (e) {
    const msg = String(e?.message || e || "");
    const looksLikeCapacity =
      /429|capacidade|vendor|allocate failed|Too Many Requests|Falha ao iniciar CAE|503|500/i.test(msg);
    if (!looksLikeCapacity) throw e;
    log("CAE: primeira série de tentativas falhou (fila/capacidade). Pausa de 22s e nova série no servidor…");
    await new Promise((r) => setTimeout(r, 22000));
    return await startCaeAgent(sessionId, channel, token, remoteUid);
  }
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
  localRtcAudioPublishedToChannel = false;

  isConnectingAgora = true;
  const sessionId = sessionIdEl.value.trim();
  const connectT0 = typeof performance !== "undefined" && performance.now ? performance.now() : 0;
  try {
    try {
      if (window.AgoraRTC && typeof AgoraRTC.setLogLevel === "function") {
        // SDK Web (ex. AgoraRTC_N): LOG_LEVEL.DEBUG=0 … NONE=4. Fallback 0 = máximo ruído no console.
        const LL = AgoraRTC.LOG_LEVEL;
        let lv = 4;
        if (typeof LL === "object" && LL !== null) {
          if (LL.NONE !== undefined) lv = LL.NONE;
          else if (LL.ERROR !== undefined) lv = LL.ERROR;
        }
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
    logAudioDiag("connect", "sessão/token backend OK", { ms: Math.round(performance.now() - connectT0) });
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
      remoteAudioSubscribeBackoffUntilByUid.delete(uidStr);
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
      // Subscribe no mesmo tick do user-published (com hasAudio); debounce atrasava e batia em «not published».
      void applyRemoteUserAudioPublished(String(user.uid)).catch((err) => {
        log(`RTC áudio remoto (user-published): ${err?.message || err}`);
      });
    });
    log(t("logAgoraStepJoin"));
    try {
      localRtcUid = await agoraClient.join(data.app_id, data.channel, data.token, data.uid);
    } catch (joinErr) {
      const code = joinErr && typeof joinErr.code === "number" ? ` código Agora ${joinErr.code}` : "";
      log(`${t("logAgoraJoinHint")} ${joinErr?.message || joinErr}${code}`);
      throw joinErr;
    }
    logAudioDiag("connect", "join RTC OK", { ms: Math.round(performance.now() - connectT0) });
    log(t("logAgoraStepMic"));
    const tMic = performance.now();
    localTrack = await AgoraRTC.createMicrophoneAudioTrack();
    localRtcAudioPublishedToChannel = false;
    logAudioDiag("connect", "track microfone criado (sem publish até PTT)", {
      ms: Math.round(performance.now() - tMic),
      acum_ms: Math.round(performance.now() - connectT0),
    });
    await setRtcMicCaptureEnabled(false);
    isRtcConnected = true;
    setRtcStatus(true, `uid=${localRtcUid}`);
    log(`${t("logConnected")} ${data.channel}.`);
    try {
      let cae;
      try {
        cae = await startCaeAgentWithBackoffRetry(sessionId, data.channel, data.token, localRtcUid);
      } catch (e) {
        if (e && e.name === "AbortError") {
          throw new Error(
            "CAE: tempo limite (4 min) ao iniciar o agente — a API Agora pode estar com fila (429/capacidade). Recarregue a página e tente de novo.",
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
        void fetchAndLogCaeVoiceSource(getBackendLangFromUi()).catch(() => {});
        scheduleCaeRemoteAudioWatchdog();
        const uidForSync = expectedCaeAgentUid;
        setTimeout(() => trySyncSubscribeCaeAgentAudio(uidForSync), 0);
        setTimeout(() => trySyncSubscribeCaeAgentAudio(uidForSync), 380);
        setTimeout(() => trySyncSubscribeCaeAgentAudio(uidForSync), 1100);
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
    logAudioDiag("connect", "fluxo de conexão Agora concluído", { ms: Math.round(performance.now() - connectT0) });
  } finally {
    isConnectingAgora = false;
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
          body: JSON.stringify({
            message,
            user_id: userId,
            stream: true,
            ui_language: getConversationLangFromUi(),
          }),
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

    currentLanguage = finalPayload.language === "en" ? "en-US" : "pt-BR";
    streamBubble.set(finalPayload.response_text);
    setContextState({
      sessionId: finalPayload.session_id || sessionId,
      intent: finalPayload.intent,
      needsConfirmation: finalPayload.needs_confirmation,
      actionExecuted: finalPayload.action_executed,
    });
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
  if (isRtcConnected && agoraClient && localTrack) {
    await setRtcMicCaptureEnabled(true);
    await setLocalRtcAudioUpstream(true);
  }
  try {
    await setRtcMicCaptureEnabled(true);
    try {
      const permission = await navigator.mediaDevices.getUserMedia({ audio: true });
      permission.getTracks().forEach((track) => track.stop());
    } catch (err) {
      throw new Error(`${t("logMicError")}: ${err.message}`);
    }
    recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    // Não forçar 16 kHz: muitos browsers ignoram e usam ~48 kHz; o WAV tem de declarar a taxa real dos samples.
    recordingContext = new (window.AudioContext || window.webkitAudioContext)();
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
  } catch (err) {
    await setLocalRtcAudioUpstream(false);
    await setRtcMicCaptureEnabled(false);
    throw err;
  }
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
  let recordedSampleRate = 48000;
  if (recordingContext) {
    try {
      recordedSampleRate = recordingContext.sampleRate || 48000;
      await recordingContext.close();
    } catch (_e) {}
  }
  recordingNode = null;
  recordingSource = null;
  recordingStream = null;
  recordingContext = null;
  await setLocalRtcAudioUpstream(false);
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
  if (totalLength < (recordedSampleRate || 48000) * 0.35) {
    setVoiceUiState("idle");
    showErrorPopup(t("sttTooShort"), t("errorPopupTitle"));
    return;
  }
  const wavBlob = encodeWav(pcm, recordedSampleRate);
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
  if (!sessionId || !isRtcConnected) return;
  try {
    const response = await fetch(apiUrl(`/api/conversation/${sessionId}/voice/state`));
    if (!response.ok) return;
    const state = await response.json();
    if (state.user_interrupting) {
      setVoiceUiState("interrupted");
    }
  } catch (_err) {}
}

function waitForAgoraSdk(maxMs = 45000) {
  return new Promise((resolve, reject) => {
    const t0 = Date.now();
    const id = setInterval(() => {
      if (window.AgoraRTC) {
        clearInterval(id);
        resolve();
      } else if (Date.now() - t0 > maxMs) {
        clearInterval(id);
        reject(new Error("Agora SDK não carregou a tempo."));
      }
    }, 50);
  });
}

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
  if (event.shiftKey) return;
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
renderAgentTrace(null);
setVoiceUiState("idle");
applyUiTranslations();
addChatMessage("assistant", t("welcomeAssistant"));

(async () => {
  try {
    await waitForAgoraSdk();
    await connectAgora();
  } catch (err) {
    const detail = err?.message || String(err);
    setRtcStatus(false, t("statusFailed"));
    setVoiceUiState("error");
    log(detail);
    showErrorPopup(detail);
  }
})();

setInterval(() => {
  pollVoiceState();
}, 5000);

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
