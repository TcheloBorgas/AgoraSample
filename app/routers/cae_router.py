from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.adapters.mcp_tools import CalendarMcpTools
from app.core.config import settings
from app.services.cae_service import CAEService
from app.services.container import get_cae_service, get_conversation_service, get_mcp_tools, get_ollama_client
from app.services.conversation_service import ConversationService
from app.adapters.ollama_client import OllamaClient

router = APIRouter(prefix="/api/cae", tags=["cae"])
logger = logging.getLogger(__name__)


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
        return {
            "started": True,
            "agent_id": started.agent_id,
            "status": started.status,
            "session_id": started.session_id,
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
    payload = await request.json()
    user_text = _extract_user_text(payload)
    if not user_text:
        user_text = "Continue em portugues com uma resposta curta."

    result = conversation.handle_message(session_id=session_id, user_id=user_id, message=user_text)
    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "local-scheduler-agent",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.response_text},
                "finish_reason": "stop",
            }
        ],
    }


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
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if block.get("type") == "text":
                    return block.get("text", "")
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
            "description": "Lists events by date/query.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "query": {"type": "string"},
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
