from __future__ import annotations

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
from app.services.container import get_cae_service, get_conversation_service, get_mcp_tools, get_ollama_client
from app.services.conversation_service import ConversationService
from app.adapters.ollama_client import OllamaClient

router = APIRouter(prefix="/api/cae", tags=["cae"])
logger = logging.getLogger(__name__)
_LOG_THROTTLE_SEC = 2.0
_last_log_by_key: dict[str, float] = {}
_last_reply_by_session: dict[str, dict[str, Any]] = {}

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


def _is_duplicate_turn(session_id: str, turn_id: int | None, user_text: str) -> bool:
    if turn_id is None:
        return False
    prev = _last_reply_by_session.get(session_id)
    if not prev:
        return False
    return prev.get("turn_id") == turn_id and (prev.get("user_text") or "") == (user_text or "")


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


@router.post("/agent/start")
async def start_cae_agent(
    payload: CAEStartRequest,
    service: CAEService = Depends(get_cae_service),
):
    if not settings.agora_cae_enabled:
        return {"started": False, "reason": "cae_disabled", "message": "CAE desabilitado no .env. Usando fluxo local com Ollama."}
    try:
        started = await service.start_agent_for_session(
            session_id=payload.session_id,
            channel=payload.channel,
            token=payload.token,
            remote_uid=payload.remote_uid,
            language=payload.language,
        )
        tts_public = service.describe_tts_public(payload.language)
        logger.info(
            "Resposta /api/cae/agent/start: CAE ativo; voce deve ouvir a voz do agente via track de audio remoto RTC "
            "(TTS do pipeline CAE / Agora). tts=%s",
            tts_public,
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


@router.get("/ollama/health")
async def ollama_health(ollama: OllamaClient = Depends(get_ollama_client)):
    return await ollama.health()


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

        if _should_emit_log(f"cae_llm_payload:{session_id}", window_sec=2.0):
            logger.info(
                "CAE_LLM payload keys=%s body_len=%s payload_json=%s",
                list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
                body_len,
                _json_for_log(payload, max_len=3000),
            )

        turn_id = _payload_turn_id(payload)
        user_text = _extract_user_text(payload)
        if _is_duplicate_turn(session_id, turn_id, user_text):
            prev_text = (_last_reply_by_session.get(session_id) or {}).get("out_text") or ""
            logger.info(
                "CAE_LLM turn duplicado ignorado session_id=%s turn_id=%s len_user_text=%s",
                session_id,
                turn_id,
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
            out_empty = "Não ouvi bem desta vez. Pode repetir em uma frase?"
            logger.warning("CAE_LLM texto de user vazio (ASR); resposta fixa sem handle_message.")
            stream_opts = payload.get("stream_options") if isinstance(payload.get("stream_options"), dict) else {}
            include_usage = bool(stream_opts.get("include_usage"))
            if _wants_streaming_llm(payload):
                _remember_turn_reply(session_id, turn_id, user_text, out_empty)
                return StreamingResponse(
                    _openai_chat_completion_sse(out_empty, include_usage=include_usage),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    },
                )
            _remember_turn_reply(session_id, turn_id, user_text, out_empty)
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

        if _should_emit_log(f"cae_llm_user_text:{session_id}", window_sec=2.0):
            logger.info(
                "CAE_LLM user_text len=%s preview=%r",
                len(user_text),
                user_text[:500] + ("…" if len(user_text) > 500 else ""),
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
                "Desculpe, não consegui gerar uma resposta agora. Pode repetir em uma frase o que deseja?"
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
            logger.info(
                "CAE_LLM resposta modo STREAM (chat.completion.chunk + SSE); Agora enviou stream=true. "
                "session_id=%s intent=%s response_len=%s include_usage=%s elapsed_ms=%.2f",
                session_id,
                result.intent,
                len(out_text),
                include_usage,
                elapsed_ms,
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
        logger.info(
            "CAE_LLM POST sucesso (JSON nao-stream) session_id=%s intent=%s needs_confirmation=%s response_len=%s "
            "elapsed_ms=%.2f body_out=%s",
            session_id,
            result.intent,
            result.needs_confirmation,
            len(out_text),
            elapsed_ms,
            _json_for_log(body_out, max_len=4000),
        )
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

    # Fallback: último texto de usuário não-vazio.
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
