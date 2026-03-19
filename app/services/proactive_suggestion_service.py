from __future__ import annotations

from datetime import datetime, timedelta

from app.repositories.action_log_repository import ActionLogRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.pattern_repository import MeetingPatternRepository
from app.repositories.preference_repository import PreferenceRepository
from app.schemas.proactive_suggestion import ProactiveSuggestion
from app.services.language_service import LanguageService
from app.services.scheduler_service import SchedulerService


class ProactiveSuggestionService:
    """Generates high-signal proactive suggestions based on persisted history."""

    def __init__(
        self,
        preferences: PreferenceRepository,
        patterns: MeetingPatternRepository,
        conversations: ConversationRepository,
        actions: ActionLogRepository,
        scheduler: SchedulerService,
        language: LanguageService,
    ) -> None:
        self.preferences = preferences
        self.patterns = patterns
        self.conversations = conversations
        self.actions = actions
        self.scheduler = scheduler
        self.language = language
        self._seen_keys_by_session: dict[str, set[str]] = {}

    def suggest(self, session_id: str, user_id: str, language: str, trigger: str) -> list[ProactiveSuggestion]:
        now = datetime.now()
        pref = self.preferences.get(user_id)
        pattern = self.patterns.get_last_meeting(user_id)
        recent_actions = self.actions.get_recent(user_id=user_id, limit=8)

        candidates: list[ProactiveSuggestion] = []
        preferred_slots = pref.get("preferred_slots", {})
        top_hour = self._top_preferred_hour(preferred_slots)

        if pattern and pattern.get("start"):
            pattern_dt = self._safe_parse(pattern["start"])
            if pattern_dt:
                score = 0.45
                if pattern_dt.weekday() == now.weekday():
                    score += 0.25
                if top_hour is not None and abs(pattern_dt.hour - top_hour) <= 1:
                    score += 0.2
                if self._recent_created_action(recent_actions):
                    score += 0.1
                if score >= 0.55:
                    title = pattern.get("title", "Reuniao")
                    suggestion_dt = now.replace(hour=pattern_dt.hour, minute=pattern_dt.minute, second=0, microsecond=0)
                    if suggestion_dt < now + timedelta(minutes=20):
                        suggestion_dt = suggestion_dt + timedelta(days=1)
                    key = f"repeat:{title}:{suggestion_dt.date().isoformat()}"
                    msg = self.language.in_language(
                        f"Voce costuma agendar '{title}' perto deste horario. Quer que eu crie para {suggestion_dt.strftime('%d/%m as %H:%M')}?",
                        f"You usually schedule '{title}' around this time. Want me to create it for {suggestion_dt.strftime('%Y-%m-%d %H:%M')}?",
                        language,
                    )
                    candidates.append(
                        ProactiveSuggestion(
                            key=key,
                            title="repeat_pattern",
                            message=msg,
                            score=min(score, 1.0),
                            reason="historical_pattern_match",
                            suggested_action="create_meeting",
                            payload={
                                "title": title,
                                "start": suggestion_dt.isoformat(),
                                "duration_minutes": int(pattern.get("duration_minutes", 30)),
                                "participants": pattern.get("participants", []),
                                "recurrence": pattern.get("recurrence"),
                            },
                        )
                    )

        if trigger in {"session_start", "after_list"} and top_hour is not None:
            today_events = self.scheduler.list_meetings(when=now)
            has_top_hour = any(self._event_is_near_hour(event, top_hour) for event in today_events)
            if not has_top_hour:
                key = f"slot:{now.date().isoformat()}:{top_hour}"
                msg = self.language.in_language(
                    f"Seu horario mais frequente e por volta de {top_hour:02d}h. Deseja que eu proponha um horario livre nesse periodo?",
                    f"Your most frequent slot is around {top_hour:02d}:00. Should I suggest an available time around that period?",
                    language,
                )
                candidates.append(
                    ProactiveSuggestion(
                        key=key,
                        title="preferred_slot_missing",
                        message=msg,
                        score=0.62,
                        reason="preferred_slot_without_event_today",
                        suggested_action="suggest_time_slots",
                        payload={"preferred_hour": top_hour},
                    )
                )

        seen = self._seen_keys_by_session.setdefault(session_id, set())
        filtered = [item for item in sorted(candidates, key=lambda s: s.score, reverse=True) if item.key not in seen]
        for item in filtered[:2]:
            seen.add(item.key)
        return filtered[:2]

    @staticmethod
    def _safe_parse(value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _top_preferred_hour(preferred_slots: dict) -> int | None:
        if not preferred_slots:
            return None
        try:
            hour_str = max(preferred_slots.items(), key=lambda kv: kv[1])[0]
            return int(hour_str)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _event_is_near_hour(event: dict, hour: int) -> bool:
        start = event.get("start", {}).get("dateTime")
        if not start:
            return False
        try:
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            return abs(dt.hour - hour) <= 1
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _recent_created_action(actions: list[dict]) -> bool:
        return any(item.get("intent") == "create_meeting" and item.get("success") for item in actions)

