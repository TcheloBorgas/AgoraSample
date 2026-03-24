import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.api import AssistantResponse, StreamMessageRequest, UserMessageRequest
from app.services.container import (
    get_conversation_service,
    get_response_streaming_service,
    get_trace_service,
    get_voice_turn_coordinator,
)
from app.services.conversation_service import ConversationService
from app.services.response_streaming_service import ResponseStreamingService
from app.services.agent_trace_service import AgentTraceService
from app.services.voice_turn_coordinator import VoiceTurnCoordinator

router = APIRouter(prefix="/api/conversation", tags=["conversation"])
logger = logging.getLogger(__name__)


@router.post("/{session_id}/message", response_model=AssistantResponse)
def send_message(
    session_id: str,
    request: UserMessageRequest,
    service: ConversationService = Depends(get_conversation_service),
):
    try:
        return service.handle_message(session_id=session_id, user_id=request.user_id, message=request.message)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{session_id}/message/stream")
async def stream_message(
    session_id: str,
    request: StreamMessageRequest,
    conversation: ConversationService = Depends(get_conversation_service),
    streaming: ResponseStreamingService = Depends(get_response_streaming_service),
):
    try:
        response = conversation.handle_message(session_id=session_id, user_id=request.user_id, message=request.message)
        return StreamingResponse(streaming.stream_response(response), media_type="text/event-stream")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{session_id}/trace")
def get_recent_trace(
    session_id: str,
    limit: int = 10,
    traces: AgentTraceService = Depends(get_trace_service),
):
    return {"session_id": session_id, "traces": [item.model_dump(mode="json") for item in traces.get_recent_traces(session_id, limit=limit)]}


@router.get("/{session_id}/proactive")
def get_proactive_suggestions(
    session_id: str,
    user_id: str = "local-user",
    trigger: str = "manual",
    conversation: ConversationService = Depends(get_conversation_service),
):
    return {
        "session_id": session_id,
        "user_id": user_id,
        "trigger": trigger,
        "suggestions": conversation.get_proactive_suggestions(session_id=session_id, user_id=user_id, trigger=trigger),
    }


@router.get("/{session_id}/voice/state")
def get_voice_state(
    session_id: str,
    turns: VoiceTurnCoordinator = Depends(get_voice_turn_coordinator),
):
    state = turns.get_state(session_id)
    return {
        "session_id": session_id,
        "agent_speaking": state.agent_speaking,
        "user_interrupting": state.user_interrupting,
        "pending_revision": state.pending_revision,
        "updated_at": state.updated_at.isoformat(),
    }


@router.post("/{session_id}/voice/interrupt")
def interrupt_voice_turn(
    session_id: str,
    turns: VoiceTurnCoordinator = Depends(get_voice_turn_coordinator),
):
    state = turns.register_user_interrupt(session_id)
    logger.info(
        "POST /voice/interrupt session_id=%s agent_speaking=%s user_interrupting=%s",
        session_id,
        state.agent_speaking,
        state.user_interrupting,
    )
    return {
        "session_id": session_id,
        "agent_speaking": state.agent_speaking,
        "user_interrupting": state.user_interrupting,
        "pending_revision": state.pending_revision,
        "updated_at": state.updated_at.isoformat(),
    }


@router.post("/{session_id}/voice/agent-speaking/{speaking}")
def set_agent_speaking(
    session_id: str,
    speaking: bool,
    turns: VoiceTurnCoordinator = Depends(get_voice_turn_coordinator),
):
    logger.info("POST /voice/agent-speaking session_id=%s speaking=%s", session_id, speaking)
    state = turns.set_agent_speaking(session_id=session_id, speaking=speaking)
    if not speaking:
        turns.mark_revision_applied(session_id)
    return {
        "session_id": session_id,
        "agent_speaking": state.agent_speaking,
        "user_interrupting": state.user_interrupting,
        "pending_revision": state.pending_revision,
        "updated_at": state.updated_at.isoformat(),
    }
