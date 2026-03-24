from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.adapters.mcp_tools import CalendarMcpTools
from app.core.config import settings
from app.services.cae_service import CAEService
from app.services.container import (
    get_cae_service,
    get_conversation_service,
    get_local_llm_client,
    get_memory_service,
    get_mcp_tools,
)
from app.services.conversation_service import ConversationService
from app.services.memory_service import MemoryService
from app.adapters.local_llm_client import LocalLlmClient

router = APIRouter(prefix="/api/cae", tags=["cae"])
logger = logging.getLogger(__name__)
_LOG_THROTTLE_SEC = 4.0
_last_log_by_key: dict[str, float] = {}
_last_reply_by_session: dict[str, dict[str, Any]] = {}
_cae_llm_locks: dict[str, asyncio.Lock] = {}
# ASR do CAE pode enviar dezenas de milhares de caracteres (ruído + histórico); o LLM só precisa do fim do turno.
CAE_USER_TEXT_MAX_CHARS = 4000

_FAILURE_SNIPPETS_PT = (
    "não consegui obter resposta",
    "nao consegui obter resposta",
    "tente de novo",
)
_FAILURE_SNIPPETS_EN = ("couldn't get a response", "try again")


def _json_for_log(obj: Any, max_len: int = 6000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = repr(obj)
    if len(s) > max_len:
        return f"{s[:max_len]}... [truncado len_total={len(s)}]"
    return s


def _looks_like_cae_failure_tts(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in _FAILURE_SNIPPETS_PT) or any(x in t for x in _FAILURE_SNIPPETS_EN)


def _should_emit_log(key: str, window_sec: float = _LOG_THROTTLE_SEC) -> bool:
    now = time.monotonic()
    last = _last_log_by_key.get(key, 0.0)
    if (now - last) >= window_sec:
        _last_log_by_key[key] = now
        return True
    return False


def _wants_streaming_llm(payload: dict[str, Any]) -> bool:
    """Agora CAE envia stream=true; sem SSE estilo OpenAI o motor marca llm failure e fala failure_message."""
    return bool(payload.get("stream"))


def _payload_turn_id(payload: dict[str, Any]) -> int | None:
    val = payload.get("turn_id")
    try:
        return int(val) if val is not None else None
    except Exception:
        return None


def _get_cae_llm_lock(session_id: str) -> asyncio.Lock:
    if session_id not in _cae_llm_locks:
        _cae_llm_locks[session_id] = asyncio.Lock()
    return _cae_llm_locks[session_id]


def _truncate_cae_user_text(user_text: str) -> str:
    raw = (user_text or "").strip()
    if len(raw) <= CAE_USER_TEXT_MAX_CHARS:
        return raw
    out = raw[-CAE_USER_TEXT_MAX_CHARS:]
    if _should_emit_log("cae_user_text_truncated", window_sec=30.0):
        logger.warning(
            "CAE_LLM user_text truncado: len_original=%s -> len_usada=%s (mantido sufixo; ASR acumulou demasiado texto).",
            len(raw),
            len(out),
        )
    return out


def _should_reuse_cached_turn_reply(session_id: str, turn_id: int | None) -> bool:
    """
    O Agora pode chamar o callback várias vezes para o mesmo turn_id (texto ASR a crescer).
    Reutiliza a primeira resposta já gerada para esse turno para evitar repetir frases e flood no backend.
    """
    if turn_id is None:
        return False
    prev = _last_reply_by_session.get(session_id)
    if not prev:
        return False
    if prev.get("turn_id") != turn_id:
        return False
    return bool((prev.get("out_text") or "").strip())


def _remember_turn_reply(session_id: str, turn_id: int | None, user_text: str, out_text: str) -> None:
    _last_reply_by_session[session_id] = {
        "turn_id": turn_id,
        "user_text": user_text or "",
        "out_text": out_text or "",
        "ts": time.monotonic(),
    }


async def _openai_chat_completion_sse(
    content: str,
    model: str = "local-scheduler-agent",
    include_usage: bool = False,
):
    """Gera linhas data: ... no formato chat.completion.chunk (OpenAI)."""
    cid = f"chatcmpl-{int(time.time())}"
    created = int(time.time())
    base: dict[str, Any] = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}
    chunks: list[dict[str, Any]] = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]},
    ]
    final: dict[str, Any] = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
    if include_usage:
        final["usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    chunks.append(final)
    for ch in chunks:
        line = f"data: {json.dumps(ch, ensure_ascii=False)}\n\n"
        yield line.encode("utf-8")
    yield b"data: [DONE]\n\n"


class CAEStartRequest(BaseModel):
    session_id: str
    channel: str
    token: str
    remote_uid: str = "0"
    language: str = "pt-BR"
    user_id: str = "local-user"


@router.post("/agent/start")
async def start_cae_agent(
    payload: CAEStartRequest,
    service: CAEService = Depends(get_cae_service),
    memory: MemoryService = Depends(get_memory_service),
):
    if not settings.agora_cae_enabled:
        return {
            "started": False,
            "reason": "cae_disabled",
            "message": "Erro: CAE desativado (AGORA_CAE_ENABLED=false). O agente conversacional Agora não será iniciado.",
        }
    try:
        started = await service.start_agent_for_session(
            session_id=payload.session_id,
            channel=payload.channel,
            token=payload.token,
            remote_uid=payload.remote_uid,
            language=payload.language,
        )
        memory.sync_conversation_language_from_ui_locale(
            payload.session_id,
            payload.user_id,
            payload.language,
        )
        tts_public = service.describe_tts_public(payload.language)
        logger.info(
            "Resposta /api/cae/agent/start: CAE ativo; TTS no motor Agora. tts_public=%s | vendor=%r "
            "el_key=%s oa_tts_key=%s",
            tts_public,
            settings.agora_cae_tts_vendor,
            "sim" if (settings.agora_cae_tts_elevenlabs_key or "").strip() else "nao",
            "sim" if (settings.agora_cae_tts_openai_key or "").strip() else "nao",
        )
        return {
            "started": True,
            "agent_id": started.agent_id,
            "status": started.status,
            "session_id": started.session_id,
            "agent_rtc_uid": int(settings.agora_cae_agent_uid),
            "cae_tts": tts_public,
        }
    except Exception as exc:  # noqa: BLE001
        detail = str(exc) if str(exc).strip() else repr(exc)
        logger.exception("Falha ao iniciar agente CAE")
        raise HTTPException(status_code=500, detail=detail) from exc


@router.get("/local-llm/health")
async def local_llm_health(local_llm: LocalLlmClient = Depends(get_local_llm_client)):
    return await local_llm.health()


@router.post("/agent/stop/{session_id}")
async def stop_cae_agent(
    session_id: str,
    service: CAEService = Depends(get_cae_service),
):
    try:
        return await service.stop_agent_for_session(session_id)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc) if str(exc).strip() else repr(exc)
        logger.exception("Falha ao parar agente CAE")
        raise HTTPException(status_code=500, detail=detail) from exc


@router.get("/agent/status/{session_id}")
def get_cae_status(
    session_id: str,
    service: CAEService = Depends(get_cae_service),
):
    return service.get_session_status(session_id)


@router.get("/agent/voice/source")
def get_cae_voice_source(
    language: str = Query("pt-BR"),
    service: CAEService = Depends(get_cae_service),
):
    """
    Diagnóstico rápido para confirmar a voz efetiva do pipeline CAE (vendor/model/voice).
    """
    tts_public = service.describe_tts_public(language)
    logger.info(
        "GET /api/cae/agent/voice/source language=%r vendor_env=%r cae_tts=%s el_key=%s oa_tts_key=%s",
        language,
        settings.agora_cae_tts_vendor,
        tts_public,
        "sim" if (settings.agora_cae_tts_elevenlabs_key or "").strip() else "nao",
        "sim" if (settings.agora_cae_tts_openai_key or "").strip() else "nao",
    )
    return {
        "language": language,
        "configured_vendor_env": settings.agora_cae_tts_vendor,
        "cae_tts": tts_public,
    }


@router.post("/llm")
async def cae_llm_callback(
    request: Request,
    session_id: str = Query("cae-default"),
    user_id: str = Query("local-user"),
    conversation: ConversationService = Depends(get_conversation_service),
):
    """
    Callback em estilo OpenAI para o CAE em modo llm.vendor=custom/style=openai.
    """
    t0 = time.perf_counter()
    client_host = getattr(request.client, "host", None)
    xff = request.headers.get("x-forwarded-for")
    xri = request.headers.get("x-request-id")
    ua = request.headers.get("user-agent", "")[:200]
    if _should_emit_log(f"cae_llm_start:{session_id}", window_sec=1.5):
        logger.info(
            "CAE_LLM POST inicio session_id=%r user_id=%r client=%s x_forwarded_for=%s "
            "x_request_id=%s user_agent=%r",
            session_id,
            user_id,
            client_host,
            xff,
            xri,
            ua,
        )
    try:
        raw_body = await request.body()
        body_len = len(raw_body)
        try:
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except json.JSONDecodeError as je:
            logger.error(
                "CAE_LLM corpo JSON invalido len=%s erro=%s raw_preview=%r",
                body_len,
                je,
                (raw_body[:500] if raw_body else b""),
            )
            raise HTTPException(status_code=400, detail="Invalid JSON body") from je

        if _should_emit_log(f"cae_llm_payload:{session_id}", window_sec=30.0):
            logger.info(
                "CAE_LLM payload keys=%s body_len=%s turn_id=%s stream=%s",
                list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
                body_len,
                payload.get("turn_id") if isinstance(payload, dict) else None,
                payload.get("stream") if isinstance(payload, dict) else None,
            )

        async with _get_cae_llm_lock(session_id):
            turn_id = _payload_turn_id(payload)
            raw_user = _extract_user_text(payload)
            user_text = _truncate_cae_user_text(raw_user)

            if _should_reuse_cached_turn_reply(session_id, turn_id):
                prev_text = (_last_reply_by_session.get(session_id) or {}).get("out_text") or ""
                logger.debug(
                    "CAE_LLM mesmo turn_id=%s — reutilizando resposta (evita repetir audio/LLM). session_id=%s len_user_text=%s",
                    turn_id,
                    session_id,
                    len(user_text or ""),
                )
                stream_opts = payload.get("stream_options") if isinstance(payload.get("stream_options"), dict) else {}
                include_usage = bool(stream_opts.get("include_usage"))
                if _wants_streaming_llm(payload):
                    return StreamingResponse(
                        _openai_chat_completion_sse(prev_text, include_usage=include_usage),
                        media_type="text/event-stream",
                        headers={
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                            "X-Accel-Buffering": "no",
                        },
                    )
                return {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": "local-scheduler-agent",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": prev_text},
                            "finish_reason": "stop",
                        }
                    ],
                }
            if not (user_text or "").strip():
                # ASR vazio: não inventar frase que o classificador interpreta como mudança de idioma (ex.: "português" → set_language).
                out_empty = (
                    "Erro: o texto do utilizador chegou vazio ao callback do LLM (ASR sem transcrição ou payload sem mensagem). "
                    "Repita a frase ou verifique o microfone/canal de áudio."
                )
                if _should_emit_log(f"cae_llm_empty_asr:{session_id}", window_sec=15.0):
                    logger.warning("CAE_LLM texto de user vazio (ASR); resposta de erro sem handle_message.")
                stream_opts = payload.get("stream_options") if isinstance(payload.get("stream_options"), dict) else {}
                include_usage = bool(stream_opts.get("include_usage"))
                if _wants_streaming_llm(payload):
                    return StreamingResponse(
                        _openai_chat_completion_sse(out_empty, include_usage=include_usage),
                        media_type="text/event-stream",
                        headers={
                            "Cache-Control": "no-cache",
                            "Connection": "keep-alive",
                            "X-Accel-Buffering": "no",
                        },
                    )
                return {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": "local-scheduler-agent",
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": out_empty},
                            "finish_reason": "stop",
                        }
                    ],
                }

            if _should_emit_log(f"cae_llm_user_text:{session_id}", window_sec=12.0):
                logger.info(
                    "CAE_LLM user_text len=%s preview=%r",
                    len(user_text),
                    user_text[:400] + ("…" if len(user_text) > 400 else ""),
                )

            result = conversation.handle_message(
                session_id=session_id,
                user_id=user_id,
                message=user_text,
                use_cloud_fallback_for_unknown=False,
                request_source="cae_llm",
            )
            out_text = (result.response_text or "").strip()
            if not out_text:
                logger.error(
                    "CAE_LLM response_text VAZIO apos handle_message intent=%s — Agora pode falhar ou falar mensagem de erro.",
                    result.intent,
                )
                out_text = (
                    "Erro: o assistente devolveu `response_text` vazio após processar a mensagem "
                    f"(intent={result.intent}). O fluxo no servidor não produziu texto para o TTS."
                )

            if _looks_like_cae_failure_tts(out_text):
                logger.warning(
                    "CAE_LLM ATENCAO: response_text parece a mensagem de falha do CAE ou similar — "
                    "verifique se nao e eco do failure_message. preview=%r",
                    out_text[:300],
                )

            elapsed_ms = (time.perf_counter() - t0) * 1000
            stream_opts = payload.get("stream_options") if isinstance(payload.get("stream_options"), dict) else {}
            include_usage = bool(stream_opts.get("include_usage"))

            if _wants_streaming_llm(payload):
                _remember_turn_reply(session_id, turn_id, user_text, out_text)
                if _should_emit_log(f"cae_llm_stream_ok:{session_id}", window_sec=12.0):
                    logger.info(
                        "CAE_LLM STREAM ok session_id=%s intent=%s response_len=%s elapsed_ms=%.2f",
                        session_id,
                        result.intent,
                        len(out_text),
                        elapsed_ms,
                    )
                if _should_emit_log(f"cae_llm_tts_pipeline:{session_id}", window_sec=6.0):
                    _v = (settings.agora_cae_tts_vendor or "").lower().strip()
                    if _v == "openai":
                        logger.info(
                            "CAE_LLM -> TTS: texto para o CAE; vendor=openai voice=%r model=%r (join).",
                            settings.agora_cae_tts_openai_voice,
                            settings.agora_cae_tts_openai_model,
                        )
                    elif _v == "elevenlabs":
                        logger.info(
                            "CAE_LLM -> TTS: texto para o CAE; vendor=elevenlabs voice_id=%r model_id=%r (join).",
                            settings.agora_cae_tts_elevenlabs_voice_id,
                            settings.agora_cae_tts_elevenlabs_model_id,
                        )
                    else:
                        logger.info(
                            "CAE_LLM -> TTS: texto para o CAE; vendor=%r (join).",
                            _v,
                        )
                return StreamingResponse(
                    _openai_chat_completion_sse(out_text, include_usage=include_usage),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )

            body_out = {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "local-scheduler-agent",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": out_text},
                        "finish_reason": "stop",
                    }
                ],
            }
            _remember_turn_reply(session_id, turn_id, user_text, out_text)
            if _should_emit_log(f"cae_llm_json_ok:{session_id}", window_sec=12.0):
                logger.info(
                    "CAE_LLM JSON ok session_id=%s intent=%s response_len=%s elapsed_ms=%.2f",
                    session_id,
                    result.intent,
                    len(out_text),
                    elapsed_ms,
                )
            if _should_emit_log(f"cae_llm_tts_pipeline_json:{session_id}", window_sec=6.0):
                _v = (settings.agora_cae_tts_vendor or "").lower().strip()
                if _v == "openai":
                    logger.info(
                        "CAE_LLM -> TTS (JSON): vendor=openai voice=%r model=%r.",
                        settings.agora_cae_tts_openai_voice,
                        settings.agora_cae_tts_openai_model,
                    )
                elif _v == "elevenlabs":
                    logger.info(
                        "CAE_LLM -> TTS (JSON): vendor=elevenlabs voice_id=%r model_id=%r.",
                        settings.agora_cae_tts_elevenlabs_voice_id,
                        settings.agora_cae_tts_elevenlabs_model_id,
                    )
                else:
                    logger.info("CAE_LLM -> TTS (JSON): vendor=%r.", _v)
            return body_out
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "CAE_LLM POST EXCECAO session_id=%r user_id=%r tipo=%s msg=%r\n%s",
            session_id,
            user_id,
            type(exc).__name__,
            str(exc),
            traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"CAE LLM callback failed: {exc!s}") from exc


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Any = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


@router.post("/mcp")
def mcp_tools_gateway(
    body: MCPRequest,
    tools: CalendarMcpTools = Depends(get_mcp_tools),
):
    """
    MCP simplificado (streamable_http) para tools de agenda.
    """
    try:
        if body.method == "initialize":
            return _mcp_ok(
                body.id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "local-scheduler-mcp", "version": "1.0.0"},
                },
            )

        if body.method == "tools/list":
            return _mcp_ok(body.id, {"tools": _tool_definitions()})

        if body.method == "tools/call":
            name = body.params.get("name")
            args = body.params.get("arguments", {})
            output = _call_tool(name, args, tools)
            return _mcp_ok(body.id, {"content": [{"type": "text", "text": str(output)}], "tool_execution": output})

        return _mcp_err(body.id, code=-32601, message=f"Method not found: {body.method}")
    except Exception as exc:  # noqa: BLE001
        return _mcp_err(body.id, code=-32000, message=str(exc))


def _extract_user_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages", [])
    payload_turn_id = _payload_turn_id(payload)

    # Primeiro tenta extrair o conteúdo do mesmo turn_id enviado no payload.
    if payload_turn_id is not None:
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            try:
                msg_turn_id = int(message.get("turn_id")) if message.get("turn_id") is not None else None
            except Exception:
                msg_turn_id = None
            if msg_turn_id != payload_turn_id:
                continue
            content = message.get("content")
            if isinstance(content, str):
                if content.strip():
                    return content
                continue
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        txt = block.get("text", "")
                        if isinstance(txt, str) and txt.strip():
                            return txt

    # Último texto de utilizador não vazio (sem turn_id coincidente).
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            if content.strip():
                return content
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "text":
                    txt = block.get("text", "")
                    if isinstance(txt, str) and txt.strip():
                        return txt
    return ""


def _mcp_ok(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _mcp_err(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "check_availability",
            "description": "Checks availability for a given date/query window.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "query": {"type": "string"},
                },
            },
        },
        {
            "name": "create_calendar_event",
            "description": "Creates an event in Google Calendar through MCP tool orchestration.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "title": {"type": "string"},
                    "date": {"type": "string"},
                    "start": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "participants": {"type": "array", "items": {"type": "string"}},
                    "recurrence": {"type": "string"},
                },
                "required": ["user_id", "title", "start"],
            },
        },
        {
            "name": "list_events",
            "description": "Lists events by date/query. Use span=week for the full calendar week (Mon-Sun) containing date.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "query": {"type": "string"},
                    "span": {"type": "string", "description": "day (default) or week"},
                },
            },
        },
        {
            "name": "reschedule_event",
            "description": "Reschedules an existing event.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "event_id": {"type": "string"},
                    "new_start": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                },
                "required": ["user_id", "event_id", "new_start"],
            },
        },
        {
            "name": "cancel_event",
            "description": "Cancels an event by event_id.",
            "inputSchema": {
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
            },
        },
        {
            "name": "suggest_time_slots",
            "description": "Suggests conflict-free slots for a desired start time.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "start": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                },
                "required": ["user_id", "start"],
            },
        },
    ]


def _call_tool(name: str, args: dict[str, Any], tools: CalendarMcpTools) -> dict[str, Any]:
    execution = tools.call_tool(name, args)
    return execution.model_dump(mode="json")
