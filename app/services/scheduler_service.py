from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from dateutil import parser as date_parser

from app.adapters.google_calendar_client import GoogleCalendarClient
from app.core.config import settings
from app.services.prioritization_service import PrioritizationService


class SchedulerService:
    def __init__(self, calendar: GoogleCalendarClient, prioritization: PrioritizationService) -> None:
        self.calendar = calendar
        self.prioritization = prioritization

    def list_meetings(self, when: datetime | None = None, query: str | None = None) -> list[dict[str, Any]]:
        base = when or datetime.now()
        day_start = base.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        return self.calendar.list_events(day_start, day_end, query=query)

    def create_meeting(
        self,
        user_id: str,
        title: str,
        start: datetime,
        duration_minutes: int,
        participants: list[str],
        recurrence: str | None,
    ) -> tuple[dict[str, Any] | None, list[datetime]]:
        end = start + timedelta(minutes=duration_minutes)
        conflicts = self.calendar.find_conflicts(start, end)
        if conflicts:
            suggestions = self._suggest_slots(user_id, start, duration_minutes)
            return None, suggestions

        body = self._build_event_body(title, start, end, participants, recurrence)
        event = self.calendar.create_event(body)
        self.prioritization.update_with_meeting(user_id, start, participants)
        return event, []

    def reschedule_meeting(
        self,
        user_id: str,
        event_id: str,
        new_start: datetime,
        duration_minutes: int,
    ) -> tuple[dict[str, Any] | None, list[datetime]]:
        new_end = new_start + timedelta(minutes=duration_minutes)
        conflicts = self.calendar.find_conflicts(new_start, new_end)
        if any(ev.get("id") != event_id for ev in conflicts):
            suggestions = self._suggest_slots(user_id, new_start, duration_minutes)
            return None, suggestions

        payload = {
            "start": {"dateTime": new_start.isoformat(), "timeZone": settings.timezone},
            "end": {"dateTime": new_end.isoformat(), "timeZone": settings.timezone},
        }
        event = self.calendar.update_event(event_id, payload)
        self.prioritization.update_with_meeting(user_id, new_start, [])
        return event, []

    def cancel_meeting(self, event_id: str) -> None:
        self.calendar.delete_event(event_id)

    def find_target_event(self, target_hint: str | None = None, around: datetime | None = None) -> dict | None:
        when = around or datetime.now()
        start = when.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        events = self.calendar.list_events(start, end, query=target_hint)
        if events:
            return events[0]

        events = self.calendar.list_events(start - timedelta(days=1), end + timedelta(days=2), query=target_hint)
        return events[0] if events else None

    def _suggest_slots(self, user_id: str, start: datetime, duration_minutes: int) -> list[datetime]:
        preferred = self.prioritization.suggest_preferred_slots(user_id, start)
        suggestions: list[datetime] = []
        for candidate in preferred:
            if not self.calendar.find_conflicts(candidate, candidate + timedelta(minutes=duration_minutes)):
                suggestions.append(candidate)
            if len(suggestions) == 3:
                return suggestions

        offset = 1
        while len(suggestions) < 3 and offset <= 6:
            candidate = start + timedelta(hours=offset)
            if not self.calendar.find_conflicts(candidate, candidate + timedelta(minutes=duration_minutes)):
                suggestions.append(candidate)
            offset += 1
        return suggestions

    def suggest_time_slots(self, user_id: str, start: datetime, duration_minutes: int = 30) -> list[datetime]:
        return self._suggest_slots(user_id=user_id, start=start, duration_minutes=duration_minutes)

    def event_duration_minutes(self, event: dict) -> int:
        start_s = event.get("start", {}).get("dateTime")
        end_s = event.get("end", {}).get("dateTime")
        if not start_s or not end_s:
            return 30
        start = date_parser.isoparse(start_s)
        end = date_parser.isoparse(end_s)
        return max(15, int((end - start).total_seconds() // 60))

    def _build_event_body(
        self,
        title: str,
        start: datetime,
        end: datetime,
        participants: list[str],
        recurrence: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": settings.timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": settings.timezone},
            "attendees": [{"email": p} for p in participants if "@" in p],
        }
        if recurrence == "weekly":
            body["recurrence"] = ["RRULE:FREQ=WEEKLY"]
        if recurrence == "monthly":
            body["recurrence"] = ["RRULE:FREQ=MONTHLY"]
        return body
