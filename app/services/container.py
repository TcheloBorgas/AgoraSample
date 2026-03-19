from functools import lru_cache

from app.adapters.agora_cae_client import AgoraConversationalAIClient
from app.adapters.agora_client import AgoraClient
from app.adapters.google_calendar_client import GoogleCalendarClient
from app.adapters.ollama_client import OllamaClient
from app.adapters.mcp_tools import CalendarMcpTools
from app.repositories.action_log_repository import ActionLogRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.pattern_repository import MeetingPatternRepository
from app.repositories.preference_repository import PreferenceRepository
from app.repositories.session_repository import SessionRepository
from app.services.agent_trace_service import AgentTraceService
from app.services.conversation_service import ConversationService
from app.services.cae_service import CAEService
from app.services.fallback_service import FallbackService
from app.services.intent_service import IntentService
from app.services.language_service import LanguageService
from app.services.memory_service import MemoryService
from app.services.proactive_suggestion_service import ProactiveSuggestionService
from app.services.prioritization_service import PrioritizationService
from app.services.response_streaming_service import ResponseStreamingService
from app.services.scheduler_service import SchedulerService
from app.services.stt_service import STTService
from app.services.voice_turn_coordinator import VoiceTurnCoordinator


@lru_cache
def get_session_repository() -> SessionRepository:
    return SessionRepository()


@lru_cache
def get_conversation_repository() -> ConversationRepository:
    return ConversationRepository()


@lru_cache
def get_preference_repository() -> PreferenceRepository:
    return PreferenceRepository()


@lru_cache
def get_pattern_repository() -> MeetingPatternRepository:
    return MeetingPatternRepository()


@lru_cache
def get_action_log_repository() -> ActionLogRepository:
    return ActionLogRepository()


@lru_cache
def get_memory_service() -> MemoryService:
    return MemoryService(
        sessions=get_session_repository(),
        conversations=get_conversation_repository(),
        preferences=get_preference_repository(),
        patterns=get_pattern_repository(),
    )


@lru_cache
def get_language_service() -> LanguageService:
    return LanguageService()


@lru_cache
def get_intent_service() -> IntentService:
    return IntentService()


@lru_cache
def get_google_calendar_client() -> GoogleCalendarClient:
    return GoogleCalendarClient()


@lru_cache
def get_prioritization_service() -> PrioritizationService:
    return PrioritizationService(get_preference_repository())


@lru_cache
def get_scheduler_service() -> SchedulerService:
    return SchedulerService(get_google_calendar_client(), get_prioritization_service())


@lru_cache
def get_mcp_tools() -> CalendarMcpTools:
    return CalendarMcpTools(get_scheduler_service())


@lru_cache
def get_fallback_service() -> FallbackService:
    return FallbackService()


@lru_cache
def get_trace_service() -> AgentTraceService:
    return AgentTraceService()


@lru_cache
def get_voice_turn_coordinator() -> VoiceTurnCoordinator:
    return VoiceTurnCoordinator()


@lru_cache
def get_response_streaming_service() -> ResponseStreamingService:
    return ResponseStreamingService()


@lru_cache
def get_proactive_suggestion_service() -> ProactiveSuggestionService:
    return ProactiveSuggestionService(
        preferences=get_preference_repository(),
        patterns=get_pattern_repository(),
        conversations=get_conversation_repository(),
        actions=get_action_log_repository(),
        scheduler=get_scheduler_service(),
        language=get_language_service(),
    )


@lru_cache
def get_conversation_service() -> ConversationService:
    return ConversationService(
        memory=get_memory_service(),
        language=get_language_service(),
        intents=get_intent_service(),
        scheduler=get_scheduler_service(),
        fallback=get_fallback_service(),
        actions=get_action_log_repository(),
        preferences=get_preference_repository(),
        ollama=get_ollama_client(),
        mcp_tools=get_mcp_tools(),
        trace_service=get_trace_service(),
        proactive=get_proactive_suggestion_service(),
        turns=get_voice_turn_coordinator(),
    )


@lru_cache
def get_agora_client() -> AgoraClient:
    return AgoraClient()


@lru_cache
def get_agora_cae_client() -> AgoraConversationalAIClient:
    return AgoraConversationalAIClient()


@lru_cache
def get_cae_service() -> CAEService:
    return CAEService(get_agora_cae_client())


@lru_cache
def get_ollama_client() -> OllamaClient:
    return OllamaClient()


@lru_cache
def get_stt_service() -> STTService:
    return STTService()
