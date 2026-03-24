from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.adapters.agora_cae_client import AgoraConversationalAIClient
from app.adapters.agora_client import build_rtc_token_for_uid
from app.adapters.openai_compatible_llm import resolve_openai_compat_llm
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class AgentSession:
    session_id: str
    agent_id: str
    status: str
    channel: str
    remote_uid: str
    started_at: datetime


class CAEService:
    def __init__(self, client: AgoraConversationalAIClient) -> None:
        self.client = client
        self._sessions: dict[str, AgentSession] = {}
        self._start_locks: dict[str, asyncio.Lock] = {}

    def _lock_for_session(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._start_locks:
            self._start_locks[session_id] = asyncio.Lock()
        return self._start_locks[session_id]

    async def start_agent_for_session(
        self,
        session_id: str,
        channel: str,
        token: str,
        remote_uid: str,
        language: str = "pt-BR",
    ) -> AgentSession:
        async with self._lock_for_session(session_id):
            if session_id in self._sessions and self._sessions[session_id].status in {
                "RUNNING",
                "STARTING",
                "IDLE",
            }:
                return self._sessions[session_id]

            payload = self._build_join_payload(session_id, channel, token, remote_uid, language)
            response = await self.client.start_agent(payload)
            session = AgentSession(
                session_id=session_id,
                agent_id=response["agent_id"],
                status=response.get("status", "STARTING"),
                channel=channel,
                remote_uid=remote_uid,
                started_at=datetime.utcnow(),
            )
            self._sessions[session_id] = session
            tts_pub = self.describe_tts_public(language)
            logger.info(
                "CAE agente iniciado: a voz do agente no canal RTC vem do TTS configurado no CAE (Agora Conversational AI), "
                "nao do backend FastAPI. session_id=%s agent_id=%s channel=%s remote_uid=%s agent_rtc_uid=%s tts=%s",
                session_id,
                session.agent_id,
                channel,
                remote_uid,
                settings.agora_cae_agent_uid,
                tts_pub,
            )
            return session

    async def stop_agent_for_session(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if not session:
            return {"stopped": False, "reason": "agent_not_found"}
        await self.client.stop_agent(session.agent_id)
        session.status = "STOPPED"
        return {"stopped": True, "agent_id": session.agent_id}

    def get_session_status(self, session_id: str) -> dict[str, Any]:
        session = self._sessions.get(session_id)
        if not session:
            return {"exists": False}
        return {
            "exists": True,
            "session_id": session.session_id,
            "agent_id": session.agent_id,
            "status": session.status,
            "channel": session.channel,
            "remote_uid": session.remote_uid,
            "started_at": session.started_at.isoformat(),
        }

    def _build_join_payload(
        self,
        session_id: str,
        channel: str,
        _token: str,
        remote_uid: str,
        language: str,
    ) -> dict[str, Any]:
        name = f"{settings.agora_cae_agent_name_prefix}-{session_id}-{int(time.time())}"
        llm_config = self._build_llm_config(session_id, language)

        # Token do browser e para AGORA_UID; o agente CAE entra com AGORA_CAE_AGENT_UID — precisa de token proprio.
        agent_token = build_rtc_token_for_uid(channel, int(settings.agora_cae_agent_uid))
        logger.info(
            "CAE join: token RTC gerado no servidor para agent_rtc_uid=%s canal=%s (token do cliente nao e reutilizado).",
            settings.agora_cae_agent_uid,
            channel,
        )

        tts_cfg = self._build_tts_config(language)
        tts_vendor = (tts_cfg.get("vendor") or "").lower()
        if tts_vendor == "openai":
            p = tts_cfg.get("params") or {}
            oa_ok = bool((p.get("api_key") or "").strip())
            logger.info(
                "CAE join OpenAI TTS: model=%s voice=%s key_configurada=%s (docs Agora: base_url + api_key no join).",
                p.get("model"),
                p.get("voice"),
                oa_ok,
            )
        elif tts_vendor == "elevenlabs":
            el_key_ok = bool((settings.agora_cae_tts_elevenlabs_key or "").strip())
            logger.info(
                "CAE join ElevenLabs: voice_id=%s model_id=%s sample_rate=24000 key_configurada=%s "
                "(sintese no motor Agora CAE; FastAPI só envia esta config no join).",
                (tts_cfg.get("params") or {}).get("voice_id"),
                (tts_cfg.get("params") or {}).get("model_id"),
                el_key_ok,
            )
        else:
            logger.info("CAE join TTS vendor=%s.", tts_vendor)
        logger.info(
            "CAE join properties.tts efectivo (sem segredos): %s",
            self._tts_config_to_public(tts_cfg),
        )

        idle_to = max(0, int(settings.agora_cae_idle_timeout_seconds))
        properties: dict[str, Any] = {
            "channel": channel,
            "token": agent_token,
            "agent_rtc_uid": str(settings.agora_cae_agent_uid),
            "remote_rtc_uids": [str(remote_uid)],
            "idle_timeout": idle_to,
            "llm": llm_config,
            "asr": {
                "language": language,
                "vendor": "ares",
                "params": {},
            },
            "tts": tts_cfg,
            "advanced_features": {
                "enable_rtm": False,
                "enable_tools": settings.agora_cae_enable_tools,
            },
        }

        if settings.agora_cae_enable_tools and settings.agora_cae_mcp_endpoint:
            properties["llm"]["mcp_servers"] = [
                {
                    "name": "scheduler",
                    "endpoint": settings.agora_cae_mcp_endpoint,
                    "transport": "streamable_http",
                    "allowed_tools": [
                        "check_availability",
                        "create_calendar_event",
                        "list_events",
                        "reschedule_event",
                        "cancel_event",
                        "suggest_time_slots",
                    ],
                    "timeout_ms": 12000,
                }
            ]

        llm_u = str(properties.get("llm", {}).get("url", ""))[:120]
        fail_msg = str(properties.get("llm", {}).get("failure_message", ""))[:160]
        greet_msg = str(properties.get("llm", {}).get("greeting_message", ""))[:120]
        logger.info(
            "CAE join audio/canal: idle_timeout=%s s (agente para após o utilizador sair do canal e este tempo; 0=só manual). "
            "remote_rtc_uids=%s",
            idle_to,
            properties.get("remote_rtc_uids"),
        )
        logger.info(
            "CAE join resumo LLM: url_prefix=%r output_modalities=%s failure_message_preview=%r "
            "greeting_preview=%r mcp_tools=%s",
            llm_u,
            properties.get("llm", {}).get("output_modalities"),
            fail_msg,
            greet_msg,
            bool(properties.get("llm", {}).get("mcp_servers")),
        )

        return {"name": name, "properties": properties}

    def _tts_config_to_public(self, tts_cfg: dict[str, Any]) -> dict[str, Any]:
        """Mesmos campos que vao no join ao CAE, sem api_key/key (segredo)."""
        vendor = (tts_cfg.get("vendor") or "").lower()
        p = tts_cfg.get("params") or {}
        out: dict[str, Any] = {"pipeline": "cae_tts", "vendor": vendor}
        if vendor == "openai":
            out["model"] = p.get("model")
            out["voice"] = p.get("voice")
        elif vendor == "elevenlabs":
            out["model_id"] = p.get("model_id")
            out["voice_id"] = p.get("voice_id")
        return out

    def describe_tts_public(self, language: str) -> dict[str, Any]:
        """
        Resumo seguro alinhado com o bloco real `properties.tts` enviado ao CAE.
        Resumo alinhado com o join: ElevenLabs (voice_id) ou OpenAI TTS (model/voice).
        """
        try:
            cfg = self._build_tts_config(language)
        except RuntimeError as exc:
            return {"pipeline": "cae_tts", "error": str(exc)}
        return self._tts_config_to_public(cfg)

    def _llm_voice_output_and_greeting(self, language: str) -> dict[str, Any]:
        """
        O CAE exige output_modalities explicito: ['text'] envia a resposta do LLM ao TTS e ao canal RTC.
        Sem isto, o motor pode assumir outro modo e nunca publicar audio (browser nao recebe user-published).
        """
        if language.startswith("es"):
            greet = "Hola, soy tu asistente de agenda. ¿En qué puedo ayudarte?"
            fail = "No pude obtener respuesta del asistente en este momento. Intenta de nuevo."
        elif language.startswith("pt"):
            greet = "Olá, sou o assistente de agenda. Em que posso ajudar?"
            fail = "Não consegui obter resposta do assistente agora. Tente de novo."
        else:
            greet = "Hi, I'm your scheduling assistant. How can I help?"
            fail = "I couldn't get a response from the assistant right now. Please try again."
        return {
            "output_modalities": ["text"],
            "greeting_configs": {"mode": "single_first"},
            "greeting_message": greet,
            "failure_message": fail,
        }

    def _build_llm_config(self, session_id: str, language: str) -> dict[str, Any]:
        sys_content = (
            "You are a bilingual scheduling assistant. Confirm critical actions before execution. "
            "Prefer concise, natural answers in user language."
        )
        voice = self._llm_voice_output_and_greeting(language)
        if settings.agora_cae_external_llm_url.strip():
            model = (settings.agora_cae_external_llm_model or "").strip() or "gpt-4o-mini"
            return {
                "vendor": "custom",
                "style": "openai",
                "url": settings.agora_cae_external_llm_url.strip().rstrip("/"),
                "api_key": settings.agora_cae_external_llm_api_key.strip(),
                "system_messages": [{"role": "system", "content": sys_content}],
                "params": {"model": model},
                **voice,
            }

        # Em producao (ex.: Render) use sempre o callback FastAPI: o mesmo ConversationService do chat.
        # Chamar Gemini diretamente a partir dos servidores Agora costuma falhar (payload/compat) e o CAE
        # reproduz failure_message em voz ("Nao consegui obter resposta...").
        pub = (settings.agora_cae_public_base_url or "").strip()
        if pub:
            callback_url = f"{pub.rstrip('/')}/api/cae/llm?session_id={session_id}"
            return {
                "vendor": "custom",
                "style": "openai",
                "url": callback_url,
                "api_key": "",
                "system_messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a voice meeting assistant connected to Google Calendar and session memory. "
                            "Always confirm create/reschedule/cancel actions."
                        ),
                    }
                ],
                "params": {"model": "local-scheduler-agent"},
                **voice,
            }

        resolved = resolve_openai_compat_llm()
        if resolved:
            base_url, api_key, model = resolved
            return {
                "vendor": "custom",
                "style": "openai",
                "url": base_url,
                "api_key": api_key,
                "system_messages": [{"role": "system", "content": sys_content}],
                "params": {"model": model},
                **voice,
            }

        raise RuntimeError(
            "Defina AGORA_CAE_PUBLIC_BASE_URL com a URL publica deste backend (ex.: Render) para o LLM do CAE, "
            "ou configure GEMINI_API_KEY / LLM_OPENAI_COMPAT_* para modo sem callback."
        )

    def _build_tts_config(self, language: str) -> dict[str, Any]:
        """
        TTS do agente CAE no join: `openai` ou `elevenlabs` (formato params conforme docs Agora Conversational AI).
        """
        vendor = settings.agora_cae_tts_vendor.lower().strip()

        if vendor == "openai":
            api_key = (settings.agora_cae_tts_openai_key or "").strip()
            if not api_key:
                raise RuntimeError(
                    "AGORA_CAE_TTS_OPENAI_KEY nao configurado. Necessario para AGORA_CAE_TTS_VENDOR=openai."
                )
            model = (settings.agora_cae_tts_openai_model or "").strip() or "gpt-4o-mini-tts"
            voice = (settings.agora_cae_tts_openai_voice or "").strip() or "coral"
            return {
                "vendor": "openai",
                "params": {
                    "base_url": "https://api.openai.com/v1",
                    "api_key": api_key,
                    "model": model,
                    "voice": voice,
                    "speed": 1,
                },
            }

        if vendor == "elevenlabs":
            el_key = (settings.agora_cae_tts_elevenlabs_key or "").strip()
            if not el_key:
                raise RuntimeError("AGORA_CAE_TTS_ELEVENLABS_KEY nao configurado.")
            return {
                "vendor": "elevenlabs",
                "params": {
                    "base_url": "wss://api.elevenlabs.io/v1",
                    "key": el_key,
                    "model_id": settings.agora_cae_tts_elevenlabs_model_id,
                    "voice_id": settings.agora_cae_tts_elevenlabs_voice_id,
                    "sample_rate": 24000,
                },
            }

        raise RuntimeError(
            "AGORA_CAE_TTS_VENDOR deve ser 'openai' ou 'elevenlabs'. "
            "OpenAI: AGORA_CAE_TTS_OPENAI_KEY (+ opcional MODEL/VOICE). "
            "ElevenLabs: AGORA_CAE_TTS_ELEVENLABS_KEY e AGORA_CAE_TTS_ELEVENLABS_VOICE_ID."
        )
