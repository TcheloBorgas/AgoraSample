let agoraClient = null;
let localTrack = null;
let isConnectingAgora = false;
let isRtcConnected = false;
let caeActive = false;
let localRtcUid = null;

let recordingContext = null;
let recordingStream = null;
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
    logRemoteAudio: "Áudio remoto ativo",
    logCaeActive: "CAE ativo. Fale normalmente sem usar captura local.",
    logCaeFallback: "CAE indisponível. Mantendo fluxo local com voz + chat.",
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
    logRemoteAudio: "Remote audio active",
    logCaeActive: "CAE active. Speak normally without local capture.",
    logCaeFallback: "CAE unavailable. Keeping local voice + chat flow.",
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
    logRemoteAudio: "Audio remoto activo",
    logCaeActive: "CAE activo. Habla normalmente sin captura local.",
    logCaeFallback: "CAE no disponible. Manteniendo flujo local de voz + chat.",
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
  if (!logEl) return;
  const time = new Date().toLocaleTimeString();
  logEl.textContent += `[${time}] ${message}\n`;
  logEl.scrollTop = logEl.scrollHeight;
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
  };
  Object.entries(map).forEach(([id, key]) => {
    const el = document.getElementById(id);
    if (el) el.textContent = t(key);
  });
  chatInputEl.placeholder = t("chatPlaceholder");
  if (!isRecording) {
    voiceToggleBtnEl.textContent = t("voiceToggleIdle");
  }
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

async function setAgentSpeakingOnServer(speaking) {
  const sessionId = sessionIdEl.value.trim();
  if (!sessionId) return;
  try {
    await fetch(apiUrl(`/api/conversation/${sessionId}/voice/agent-speaking/${speaking}`), { method: "POST" });
  } catch (_err) {}
}

async function signalInterrupt() {
  const sessionId = sessionIdEl.value.trim();
  if (!sessionId) return;
  try {
    await fetch(apiUrl(`/api/conversation/${sessionId}/voice/interrupt`), { method: "POST" });
  } catch (_err) {}
}

async function getAgoraSession(sessionId) {
  const response = await fetch(apiUrl(`/api/system/agora/session/${sessionId}`));
  const text = await response.text();
  if (!response.ok) throw new Error(parseHttpErrorBody(text, response.status));
  return parseJsonResponse(text, "Sessão Agora");
}

async function startCaeAgent(sessionId, channel, token, remoteUid) {
  const response = await fetch(apiUrl("/api/cae/agent/start"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      channel,
      token,
      remote_uid: String(remoteUid),
      language: getBackendLangFromUi(),
    }),
  });
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

  isConnectingAgora = true;
  connectAgoraBtnEl.disabled = true;
  const sessionId = sessionIdEl.value.trim();
  try {
    log(t("logAgoraStepSession"));
    const data = await getAgoraSession(sessionId);
    agoraClient = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" });
    agoraClient.on("user-published", async (user, mediaType) => {
      await agoraClient.subscribe(user, mediaType);
      if (mediaType === "audio") {
        user.audioTrack.play();
        log(`${t("logRemoteAudio")} (uid=${user.uid}).`);
      }
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
    isRtcConnected = true;
    setRtcStatus(true, `uid=${localRtcUid}`);
    log(`${t("logConnected")} ${data.channel}.`);
    try {
      const cae = await startCaeAgent(sessionId, data.channel, data.token, localRtcUid);
      caeActive = cae?.started !== false;
      if (caeActive) {
        log(t("logCaeActive"));
      } else {
        log(t("logCaeFallback"));
      }
    } catch (caeErr) {
      caeActive = false;
      log(`${t("logCaeFallback")} — ${caeErr?.message || caeErr || ""}`);
    }
  } finally {
    isConnectingAgora = false;
    connectAgoraBtnEl.disabled = false;
  }
}

function speak(text, backendLanguage) {
  const utterance = new SpeechSynthesisUtterance(text);
  if (backendLanguage === "en") utterance.lang = "en-US";
  else if (backendLanguage === "es") utterance.lang = "es-ES";
  else utterance.lang = getSpeechLocaleFromUi();

  utterance.onstart = () => {
    setVoiceUiState("speaking");
    setAgentSpeakingOnServer(true);
  };
  utterance.onend = () => {
    setAgentSpeakingOnServer(false);
    if (!isRecording) setVoiceUiState("idle");
  };
  utterance.onerror = (ev) => {
    setAgentSpeakingOnServer(false);
    const detail = ev?.error || "speech-synthesis";
    log(`TTS (${detail}): leia a resposta no chat; o agente já respondeu.`);
    if (!isRecording) setVoiceUiState("idle");
  };
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(utterance);
}

async function sendMessage(message) {
  const sessionId = sessionIdEl.value.trim();
  const userId = userIdEl.value.trim();
  setVoiceUiState("thinking");

  const response = await fetch(apiUrl(`/api/conversation/${sessionId}/message/stream`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, user_id: userId, stream: true }),
  });
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
  if (!isRecording) setVoiceUiState("idle");
  speak(finalPayload.response_text, finalPayload.language);
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
  try {
    const permission = await navigator.mediaDevices.getUserMedia({ audio: true });
    permission.getTracks().forEach((track) => track.stop());
  } catch (err) {
    throw new Error(`${t("logMicError")}: ${err.message}`);
  }
  recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recordingContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
  const source = recordingContext.createMediaStreamSource(recordingStream);
  recordingNode = recordingContext.createScriptProcessor(4096, 1, 1);
  recordingChunks = [];
  recordingNode.onaudioprocess = (event) => {
    recordingChunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
  };
  source.connect(recordingNode);
  recordingNode.connect(recordingContext.destination);
  isRecording = true;
  setVoiceUiState("listening");
  voiceToggleBtnEl.textContent = t("voiceToggleRecording");
}

async function stopRecordingAndSend() {
  if (!isRecording) return;
  isRecording = false;
  recordingNode.disconnect();
  recordingStream.getTracks().forEach((track) => track.stop());
  await recordingContext.close();
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
  window.speechSynthesis.cancel();
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
    if (caeActive) {
      log(t("logCaeActive"));
      return;
    }
    if (!isRecording) {
      if (window.speechSynthesis.speaking) {
        await interruptAgent();
      }
      await startRecording();
      return;
    }
    await stopRecordingAndSend();
    if (!window.speechSynthesis.speaking) setVoiceUiState("idle");
    voiceToggleBtnEl.textContent = t("voiceToggleIdle");
  } catch (err) {
    const detail = err?.message || String(err);
    setVoiceUiState("error");
    voiceToggleBtnEl.textContent = t("voiceToggleIdle");
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
