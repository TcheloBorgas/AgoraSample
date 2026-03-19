from __future__ import annotations

import logging
from datetime import datetime
from time import perf_counter
from typing import Any

from dateutil import parser as date_parser

from app.adapters.mcp_tools import CalendarMcpTools
from app.adapters.ollama_client import OllamaClient
from app.core.config import settings
from app.core.metrics import metrics
from app.models.domain import ConversationState
from app.schemas.api import AssistantResponse
from app.services.agent_trace_service import AgentTraceService, TraceContext
from app.services.fallback_service import FallbackService
from app.services.intent_service import IntentService
from app.services.language_service import LanguageService
from app.services.memory_service import MemoryService
from app.services.proactive_suggestion_service import ProactiveSuggestionService
from app.services.scheduler_service import SchedulerService
from app.services.voice_turn_coordinator import VoiceTurnCoordinator
from app.repositories.action_log_repository import ActionLogRepository
from app.repositories.preference_repository import PreferenceRepository

logger = logging.getLogger(__name__)


class ConversationService:
    def __init__(
        self,
        memory: MemoryService,
        language: LanguageService,
        intents: IntentService,
        scheduler: SchedulerService,
        fallback: FallbackService,
        actions: ActionLogRepository,
        preferences: PreferenceRepository,
        mcp_tools: CalendarMcpTools,
        trace_service: AgentTraceService,
        proactive: ProactiveSuggestionService,
        turns: VoiceTurnCoordinator,
        ollama: OllamaClient | None = None,
    ) -> None:
        self.memory = memory
        self.language = language
        self.intents = intents
        self.scheduler = scheduler
        self.fallback = fallback
        self.actions = actions
        self.preferences = preferences
        self.mcp_tools = mcp_tools
        self.trace_service = trace_service
        self.proactive = proactive
        self.turns = turns
        self.ollama = ollama

    def get_proactive_suggestions(self, session_id: str, user_id: str, trigger: str = "manual") -> list[dict]:
        state = self.memory.get_session(session_id, user_id)
        suggestions = self.proactive.suggest(session_id=session_id, user_id=user_id, language=state.language, trigger=trigger)
        return [item.model_dump(mode="json") for item in suggestions]

    def handle_message(self, session_id: str, user_id: str, message: str) -> AssistantResponse:
        start_ts = perf_counter()
        state = self.memory.get_session(session_id, user_id)
        trace = self.trace_service.start_turn(session_id=session_id, user_id=user_id, language=state.language)

        detected_language = self.language.detect(message, fallback=state.language)
        state.language = detected_language
        self.preferences.set_language(user_id, state.language)
        self.trace_service.step(trace, "detect_language", "Language identified for current turn.", data={"language": detected_language})

        intent_result = self.intents.detect_intent_and_entities(message, state.language)
        self.memory.append_user_message(state, message, intent_result.intent)
        metrics.inc("messages_total")
        self.trace_service.step(
            trace,
            "detect_intent",
            "Intent and entities extracted.",
            data={
                "intent": intent_result.intent,
                "entities": self._serialize_entities(intent_result.entities),
                "missing_fields": intent_result.missing_fields,
            },
        )

        current_voice_state = self.turns.get_state(session_id)
        if current_voice_state.agent_speaking:
            self.turns.register_user_interrupt(session_id)
            self.trace_service.step(
                trace,
                "user_interrupting",
                "User interrupted while the agent was speaking.",
                status="warning",
            )
            self.turns.mark_revision_applied(session_id)

        if state.pending_confirmation and intent_result.intent not in {"confirm_yes", "confirm_no"}:
            state.pending_confirmation = None
            response = self._handle_intent(
                state, user_id, intent_result.intent, intent_result.entities, intent_result.missing_fields, message, trace
            )
        elif state.pending_confirmation:
            response = self._handle_confirmation(state, user_id, intent_result.intent, message, trace)
        elif intent_result.intent in {"confirm_yes", "confirm_no"}:
            response = self._reparse_as_new_intent(state, user_id, message, trace)
        else:
            response = self._handle_intent(
                state, user_id, intent_result.intent, intent_result.entities, intent_result.missing_fields, message, trace
            )

        trigger = "session_start" if len(state.short_memory) <= 2 else "after_list" if response.intent == "list_meetings" else "generic"
        proactive_suggestions = self.proactive.suggest(
            session_id=state.session_id,
            user_id=user_id,
            language=state.language,
            trigger=trigger,
        )
        if proactive_suggestions:
            self.trace_service.step(
                trace,
                "proactive_suggestion",
                "Generated proactive suggestions from persisted history.",
                data={"suggestions_count": len(proactive_suggestions), "reasons": [s.reason for s in proactive_suggestions]},
            )
            if not response.needs_confirmation:
                response.response_text = response.response_text + "\n\n" + proactive_suggestions[0].message

        response.proactive_suggestions = proactive_suggestions
        response.trace = self.trace_service.finalize(trace)
        voice_state = self.turns.set_agent_speaking(session_id, True)
        response.voice_turn_state = {
            "agent_speaking": voice_state.agent_speaking,
            "user_interrupting": voice_state.user_interrupting,
            "pending_revision": voice_state.pending_revision,
            "updated_at": voice_state.updated_at.isoformat(),
        }

        duration_ms = (perf_counter() - start_ts) * 1000
        metrics.observe("response_time_ms", duration_ms)
        logger.info(
            "Processed message",
            extra={
                "session_id": session_id,
                "intent": response.intent,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response

    def _handle_intent(
        self,
        state: ConversationState,
        user_id: str,
        intent: str,
        entities: dict[str, Any],
        missing_fields: list[str],
        raw_message: str,
        trace: TraceContext,
    ) -> AssistantResponse:
        if intent == "unknown":
            text = self._smart_unknown_reply(state.language, raw_message)
            self.trace_service.step(trace, "fallback_unknown", "Unknown intent handled by fallback/LLM.", status="warning")
            return self._build_response(state, intent, text, False, False)

        if intent == "set_language":
            lang = entities.get("language") or state.language
            state.language = lang
            self.preferences.set_language(user_id, lang)
            text = self.language.in_language(
                "Perfeito, a partir de agora vou responder em portugues.",
                "Great, I will reply in English from now on.",
                lang,
            )
            self.trace_service.step(trace, "set_language", "Updated preferred language.", data={"language": lang})
            return self._build_response(state, "set_language", text, False, True)

        if missing_fields:
            text = self.fallback.clarify_missing(intent, missing_fields, state.language)
            self.trace_service.step(trace, "validate_context", "Missing required fields for action.", status="warning", data={"missing_fields": missing_fields})
            return self._build_response(state, intent, text, False, False)

        try:
            if intent == "list_meetings":
                exec_result = self.mcp_tools.call_tool(
                    "list_events",
                    {"date": (entities.get("start") or datetime.now()).isoformat(), "query": entities.get("target_hint")},
                )
                events = exec_result.output_payload.get("events", [])
                self.trace_service.step(trace, "execute_tool", exec_result.summary, data={"tool": exec_result.tool_name, "success": exec_result.success})
                text = self._format_events(events, state.language)
                return self._build_response(state, intent, text, False, True, {"events": events, "tool_execution": exec_result.model_dump(mode="json")})

            if intent == "repeat_last_meeting":
                last = self.memory.get_last_meeting_pattern(user_id)
                if not last:
                    text = self.language.in_language(
                        "Ainda nao encontrei uma reuniao anterior para repetir. Se quiser, eu posso criar uma nova do zero.",
                        "I could not find a previous meeting to repeat yet. If you want, I can create a new one from scratch.",
                        state.language,
                    )
                    self.trace_service.step(trace, "validate_context", "No meeting pattern available to repeat.", status="warning")
                    return self._build_response(state, intent, text, False, False)

                state.pending_confirmation = {
                    "action": "create",
                    "payload": last,
                }
                start_label = self._format_dt(last["start"], state.language)
                text = self.language.in_language(
                    f"Posso repetir sua ultima reuniao para {start_label}, com duracao de {last['duration_minutes']} minutos?",
                    f"Should I repeat your last meeting at {start_label}, for {last['duration_minutes']} minutes?",
                    state.language,
                )
                self.trace_service.step(trace, "propose_action", "Prepared repeat-last-meeting confirmation.", data={"action": "create"})
                return self._build_response(state, intent, text, True, False, {"draft": last})

            if intent == "create_meeting":
                payload = {
                    "title": entities["title"],
                    "start": entities["start"].isoformat(),
                    "duration_minutes": entities["duration_minutes"],
                    "participants": entities["participants"],
                    "recurrence": entities["recurrence"],
                }
                state.pending_confirmation = {"action": "create", "payload": payload}
                text = self.language.in_language(
                    self._pt_create_confirm(payload),
                    self._en_create_confirm(payload),
                    state.language,
                )
                self.trace_service.step(trace, "propose_action", "Prepared create meeting confirmation.", data={"action": "create", "payload": payload})
                return self._build_response(state, intent, text, True, False, {"draft": payload})

            if intent == "reschedule_meeting":
                target = self.scheduler.find_target_event(entities.get("target_hint"), around=entities.get("start"))
                if not target:
                    text = self.language.in_language(
                        "Nao encontrei qual reuniao voce quer reagendar. Pode me dizer o titulo, horario ou participantes?",
                        "I could not identify which meeting you want to reschedule. Please tell me the title, time, or participants.",
                        state.language,
                    )
                    self.trace_service.step(trace, "validate_context", "Could not identify target meeting for reschedule.", status="warning")
                    return self._build_response(state, intent, text, False, False)
                payload = {
                    "event_id": target["id"],
                    "new_start": entities["start"].isoformat(),
                    "duration_minutes": self.scheduler.event_duration_minutes(target),
                    "summary": target.get("summary", "Reuniao"),
                }
                state.pending_confirmation = {"action": "reschedule", "payload": payload}
                new_start_label = self._format_dt(payload["new_start"], state.language)
                text = self.language.in_language(
                    f"Perfeito. Posso reagendar '{payload['summary']}' para {new_start_label}?",
                    f"Can I reschedule '{payload['summary']}' to {new_start_label}?",
                    state.language,
                )
                self.trace_service.step(trace, "propose_action", "Prepared reschedule confirmation.", data={"action": "reschedule", "payload": payload})
                return self._build_response(state, intent, text, True, False, {"draft": payload})

            if intent == "cancel_meeting":
                target = self.scheduler.find_target_event(entities.get("target_hint"), around=entities.get("start"))
                if not target:
                    text = self.language.in_language(
                        "Nao encontrei qual reuniao voce quer cancelar. Pode citar horario, titulo ou participantes?",
                        "I could not identify which meeting you want to cancel. Please mention time, title, or participants.",
                        state.language,
                    )
                    self.trace_service.step(trace, "validate_context", "Could not identify target meeting for cancellation.", status="warning")
                    return self._build_response(state, intent, text, False, False)
                payload = {
                    "event_id": target["id"],
                    "summary": target.get("summary", "Reuniao"),
                    "start": target.get("start", {}).get("dateTime"),
                }
                state.pending_confirmation = {"action": "cancel", "payload": payload}
                start_label = self._format_dt(payload.get("start"), state.language)
                text = self.language.in_language(
                    f"So para confirmar: deseja cancelar '{payload['summary']}' em {start_label}?",
                    f"Do you really want to cancel '{payload['summary']}' at {start_label}?",
                    state.language,
                )
                self.trace_service.step(trace, "propose_action", "Prepared cancel confirmation.", data={"action": "cancel", "payload": payload})
                return self._build_response(state, intent, text, True, False, {"draft": payload})
        except Exception as exc:  # noqa: BLE001
            metrics.inc("errors_total")
            self.actions.log(state.session_id, user_id, intent, "pre_action", entities, False, str(exc))
            self.trace_service.step(trace, "execute_tool", "Failed while preparing action.", status="error", data={"error": str(exc)})
            text = self.language.in_language(
                f"Tive uma falha ao preparar essa acao: {self._humanize_error(exc, state.language)}",
                f"I hit an integration issue while preparing this action: {self._humanize_error(exc, state.language)}",
                state.language,
            )
            return self._build_response(state, intent, text, False, False)

        text = self.fallback.unknown_intent(state.language)
        return self._build_response(state, intent, text, False, False)

    def _smart_unknown_reply(self, language: str, raw_message: str) -> str:
        if settings.ollama_enabled and self.ollama is not None:
            try:
                prompt = raw_message or "Usuario nao especificou claramente o pedido."
                result = self.ollama.chat_reply_sync(prompt, language=language)
                if result:
                    return result
            except Exception:  # noqa: BLE001
                pass
        return self.fallback.unknown_intent(language)

    def _reparse_as_new_intent(
        self,
        state: ConversationState,
        user_id: str,
        raw_message: str,
        trace: TraceContext,
    ) -> AssistantResponse:
        """User said something like 'confirm' but there's no pending action.
        Re-parse the raw text as a regular actionable command so the agent
        doesn't reply with 'I didn't understand'."""
        self.trace_service.step(
            trace,
            "reparse_confirmation",
            "No pending confirmation found; re-interpreting message as a new intent.",
            status="warning",
        )
        fallback_intent = self.intents._infer_intent(raw_message.lower().strip())
        if fallback_intent != "unknown":
            entities = self.intents._extract_entities(raw_message, state.language, fallback_intent)
            missing = self.intents._required_fields(fallback_intent, entities)
            return self._handle_intent(state, user_id, fallback_intent, entities, missing, raw_message, trace)

        text = self.language.in_language(
            "Nao ha nenhuma operacao pendente para confirmar. Me diga o que deseja: criar, consultar, reagendar ou cancelar uma reuniao.",
            "There is no pending operation to confirm. Tell me what you'd like to do: create, list, reschedule or cancel a meeting.",
            state.language,
            es_text="No hay ninguna operacion pendiente para confirmar. Dime que deseas: crear, consultar, reagendar o cancelar una reunion.",
        )
        return self._build_response(state, "unknown", text, False, False)

    def _handle_confirmation(
        self,
        state: ConversationState,
        user_id: str,
        detected_intent: str,
        raw_message: str,
        trace: TraceContext,
    ) -> AssistantResponse:
        if detected_intent == "confirm_no":
            state.pending_confirmation = None
            text = self.language.in_language(
                "Sem problemas, operacao cancelada.",
                "No problem, operation canceled.",
                state.language,
            )
            self.trace_service.step(trace, "confirm_action", "User denied confirmation.", data={"intent": detected_intent})
            return self._build_response(state, "confirm_no", text, False, False)

        if detected_intent != "confirm_yes":
            text = self.language.in_language(
                "Para seguir com seguranca, me confirme com 'sim' ou 'nao'.",
                "To proceed safely, please confirm with 'yes' or 'no'.",
                state.language,
            )
            self.trace_service.step(trace, "confirm_action", "User response was not a valid confirmation.", status="warning")
            return self._build_response(state, detected_intent, text, True, False)

        pending = state.pending_confirmation or {}
        action = pending.get("action")
        payload = pending.get("payload", {})
        state.pending_confirmation = None
        self.trace_service.step(trace, "confirm_action", "User approved pending action.", data={"action": action})

        try:
            if action == "create":
                exec_result = self.mcp_tools.call_tool(
                    "create_calendar_event",
                    {
                        "user_id": user_id,
                        "title": payload["title"],
                        "start": payload["start"],
                        "duration_minutes": payload["duration_minutes"],
                        "participants": payload.get("participants", []),
                        "recurrence": payload.get("recurrence"),
                    },
                )
                self.trace_service.step(
                    trace,
                    "execute_tool",
                    exec_result.summary,
                    status="ok" if exec_result.success else "warning",
                    data={"tool": exec_result.tool_name},
                )
                event = exec_result.output_payload.get("event")
                suggestions = [
                    date_parser.isoparse(item) for item in exec_result.output_payload.get("suggestions", []) if isinstance(item, str)
                ]
                if not exec_result.success:
                    sug = self._format_suggestions(suggestions, state.language)
                    text = self.language.in_language(
                        f"Encontrei conflito nesse horario. Posso usar uma destas sugestoes: {sug}",
                        f"There is a scheduling conflict at that time. I can suggest: {sug}",
                        state.language,
                    )
                    self.actions.log(state.session_id, user_id, "create_meeting", "create", payload, False, "conflict")
                    return self._build_response(state, "create_meeting", text, False, False, {"suggestions": sug})

                self.memory.remember_meeting_pattern(
                    user_id,
                    {
                        "title": payload["title"],
                        "start": payload["start"],
                        "duration_minutes": payload["duration_minutes"],
                        "participants": payload.get("participants", []),
                        "recurrence": payload.get("recurrence"),
                    },
                )
                text = self.language.in_language(
                    self._pt_create_done(event),
                    f"Done! Meeting created successfully. Link: {event.get('htmlLink')}",
                    state.language,
                )
                self.actions.log(state.session_id, user_id, "create_meeting", "create", payload, True)
                return self._build_response(
                    state,
                    "create_meeting",
                    text,
                    False,
                    True,
                    {"event": event, "tool_execution": exec_result.model_dump(mode="json")},
                )

            if action == "reschedule":
                exec_result = self.mcp_tools.call_tool(
                    "reschedule_event",
                    {
                        "user_id": user_id,
                        "event_id": payload["event_id"],
                        "new_start": payload["new_start"],
                        "duration_minutes": payload["duration_minutes"],
                    },
                )
                self.trace_service.step(
                    trace,
                    "execute_tool",
                    exec_result.summary,
                    status="ok" if exec_result.success else "warning",
                    data={"tool": exec_result.tool_name},
                )
                event = exec_result.output_payload.get("event")
                suggestions = [
                    date_parser.isoparse(item) for item in exec_result.output_payload.get("suggestions", []) if isinstance(item, str)
                ]
                if not exec_result.success:
                    sug = self._format_suggestions(suggestions, state.language)
                    text = self.language.in_language(
                        f"Esse novo horario tambem conflita. Sugestoes disponiveis: {sug}",
                        f"The new time also conflicts. Available suggestions: {sug}",
                        state.language,
                    )
                    self.actions.log(state.session_id, user_id, "reschedule_meeting", "reschedule", payload, False, "conflict")
                    return self._build_response(state, "reschedule_meeting", text, False, False, {"suggestions": sug})
                text = self.language.in_language(
                    self._pt_reschedule_done(event),
                    f"Great, your meeting has been rescheduled. Updated link: {event.get('htmlLink')}",
                    state.language,
                )
                self.actions.log(state.session_id, user_id, "reschedule_meeting", "reschedule", payload, True)
                return self._build_response(
                    state,
                    "reschedule_meeting",
                    text,
                    False,
                    True,
                    {"event": event, "tool_execution": exec_result.model_dump(mode="json")},
                )

            if action == "cancel":
                exec_result = self.mcp_tools.call_tool("cancel_event", {"event_id": payload["event_id"]})
                self.trace_service.step(trace, "execute_tool", exec_result.summary, data={"tool": exec_result.tool_name})
                text = self.language.in_language(
                    "Tudo certo, ja cancelei essa reuniao para voce.",
                    "All set, the meeting was canceled successfully.",
                    state.language,
                )
                self.actions.log(state.session_id, user_id, "cancel_meeting", "cancel", payload, True)
                return self._build_response(
                    state,
                    "cancel_meeting",
                    text,
                    False,
                    True,
                    {"tool_execution": exec_result.model_dump(mode="json")},
                )

            text = self.language.in_language(
                "Nao encontrei nenhuma acao pendente para confirmar.",
                "I could not find any pending action to confirm.",
                state.language,
            )
            return self._build_response(state, detected_intent, text, False, False)
        except Exception as exc:  # noqa: BLE001
            metrics.inc("errors_total")
            self.actions.log(state.session_id, user_id, detected_intent, action or "unknown", payload, False, str(exc))
            self.trace_service.step(trace, "execute_tool", "Tool execution failed.", status="error", data={"error": str(exc)})
            text = self.language.in_language(
                f"Eu nao consegui concluir essa acao agora: {self._humanize_error(exc, state.language)}",
                f"I could not complete this action right now: {self._humanize_error(exc, state.language)}",
                state.language,
            )
            return self._build_response(state, detected_intent, text, False, False)

    def _build_response(
        self,
        state: ConversationState,
        intent: str,
        text: str,
        needs_confirmation: bool,
        action_executed: bool,
        payload: dict | None = None,
    ) -> AssistantResponse:
        state.last_intent = intent
        self.memory.append_assistant_message(state, text, intent, payload or {})
        return AssistantResponse(
            session_id=state.session_id,
            language=state.language,
            intent=intent,  # type: ignore[arg-type]
            response_text=text,
            needs_confirmation=needs_confirmation,
            action_executed=action_executed,
            payload=payload or {},
        )

    def _format_events(self, events: list[dict], language: str) -> str:
        if not events:
            return self.language.in_language(
                "Nao encontrei compromissos nesse periodo.",
                "I could not find meetings for that period.",
                language,
            )
        rows = []
        for event in events[:6]:
            start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
            summary = event.get("summary", "Sem titulo")
            start_label = self._format_dt(start, language)
            rows.append(f"- {summary} ({start_label})")
        header = "Encontrei estes compromissos:" if language == "pt" else "I found these meetings:"
        return header + "\n" + "\n".join(rows)

    def _pt_create_confirm(self, payload: dict[str, Any]) -> str:
        participants = ", ".join(payload.get("participants", []))
        recurrence = payload.get("recurrence")
        recurrence_part = ""
        if recurrence == "weekly":
            recurrence_part = " com recorrencia semanal"
        if recurrence == "monthly":
            recurrence_part = " com recorrencia mensal"
        participants_part = f" com {participants}" if participants else ""
        start_label = self._format_dt(payload["start"], "pt")
        return (
            f"Perfeito, ja vou organizar isso. Confirmo a criacao da reuniao para {start_label}, "
            f"com duracao de {payload['duration_minutes']} minutos{participants_part}{recurrence_part}?"
        )

    def _en_create_confirm(self, payload: dict[str, Any]) -> str:
        participants = ", ".join(payload.get("participants", [])) or "no participants"
        recurrence = payload.get("recurrence")
        recurrence_part = ""
        if recurrence == "weekly":
            recurrence_part = " weekly recurring"
        if recurrence == "monthly":
            recurrence_part = " monthly recurring"
        start_label = self._format_dt(payload["start"], "en")
        return (
            f"Do you confirm creating the meeting at {start_label} for {payload['duration_minutes']} minutes "
            f"with {participants}{recurrence_part}?"
        )

    def _pt_create_done(self, event: dict[str, Any]) -> str:
        summary = event.get("summary") or "Reuniao"
        raw_start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date"))
        when = self._format_dt(raw_start, "pt")
        link = event.get("htmlLink")
        if link:
            return f"Perfeito! '{summary}' ficou agendada para {when}. Aqui esta o link: {link}"
        return f"Perfeito! '{summary}' ficou agendada para {when}."

    def _pt_reschedule_done(self, event: dict[str, Any]) -> str:
        summary = event.get("summary") or "Reuniao"
        raw_start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date"))
        when = self._format_dt(raw_start, "pt")
        link = event.get("htmlLink")
        if link:
            return f"Feito! Reagendei '{summary}' para {when}. Link atualizado: {link}"
        return f"Feito! Reagendei '{summary}' para {when}."

    def _humanize_error(self, exc: Exception, language: str) -> str:
        raw = str(exc)
        lowered = raw.lower()
        if "access_denied" in lowered:
            return self.language.in_language(
                "O Google bloqueou o acesso OAuth. No Google Cloud, abra OAuth consent screen e adicione seu e-mail em Test users.",
                "Google blocked OAuth access. In Google Cloud, open OAuth consent screen and add your email under Test users.",
                language,
            )
        if "credentials" in lowered and "google" in lowered:
            return self.language.in_language(
                "Nao encontrei as credenciais do Google Calendar. Verifique GOOGLE_CLIENT_SECRET_FILE no .env.",
                "Google Calendar credentials were not found. Check GOOGLE_CLIENT_SECRET_FILE in .env.",
                language,
            )
        if "network" in lowered:
            return self.language.in_language(
                "Houve falha de rede. Tente novamente em alguns segundos.",
                "There was a network failure. Please retry in a few seconds.",
                language,
            )
        if "missing time zone definition" in lowered:
            return self.language.in_language(
                "A criacao falhou por configuracao de fuso horario. Ajustei isso no sistema; tente novamente.",
                "Creation failed because of a timezone configuration issue. I fixed this in the system; please retry.",
                language,
            )
        return raw

    def _format_dt(self, value: Any, language: str) -> str:
        if not value:
            return "-"
        try:
            dt = date_parser.isoparse(value) if isinstance(value, str) else value
            if language == "pt":
                return dt.strftime("%d/%m/%Y às %H:%M")
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:  # noqa: BLE001
            return str(value)

    def _format_suggestions(self, suggestions: list[datetime], language: str) -> str:
        if not suggestions:
            return "-"
        return ", ".join(self._format_dt(s.isoformat(), language) for s in suggestions)

    @staticmethod
    def _serialize_entities(entities: dict[str, Any]) -> dict[str, Any]:
        serialized: dict[str, Any] = {}
        for key, value in entities.items():
            if isinstance(value, datetime):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = value
        return serialized
