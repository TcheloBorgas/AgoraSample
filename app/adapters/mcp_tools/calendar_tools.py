from __future__ import annotations

from datetime import datetime
from typing import Any

from dateutil import parser as date_parser

from app.models.tool_execution import ToolExecution
from app.services.scheduler_service import SchedulerService


class CalendarMcpTools:
    """Structured MCP tool layer for calendar operations."""

    def __init__(self, scheduler: SchedulerService) -> None:
        self.scheduler = scheduler

    def check_availability(self, date: str, query: str | None = None) -> ToolExecution:
        when = date_parser.isoparse(date)
        events = self.scheduler.list_meetings(when=when, query=query)
        return ToolExecution(
            tool_name="check_availability",
            success=True,
            summary=f"Found {len(events)} events in requested period.",
            input_payload={"date": date, "query": query},
            output_payload={"events": events},
        )

    def list_events(self, date: str, query: str | None = None, span: str = "day") -> ToolExecution:
        when = date_parser.isoparse(date)
        events = self.scheduler.list_meetings(when=when, query=query, span=span)
        return ToolExecution(
            tool_name="list_events",
            success=True,
            summary=f"Listed {len(events)} events.",
            input_payload={"date": date, "query": query, "span": span},
            output_payload={"events": events},
        )

    def create_calendar_event(
        self,
        user_id: str,
        title: str,
        start: str,
        duration_minutes: int = 30,
        participants: list[str] | None = None,
        recurrence: str | None = None,
        organizer_name: str | None = None,
        organizer_email: str | None = None,
    ) -> ToolExecution:
        start_dt = date_parser.isoparse(start)
        event, suggestions = self.scheduler.create_meeting(
            user_id=user_id,
            title=title,
            start=start_dt,
            duration_minutes=duration_minutes,
            participants=participants or [],
            recurrence=recurrence,
            organizer_name=organizer_name,
            organizer_email=organizer_email,
        )
        success = event is not None
        summary = "Calendar event created." if success else "Conflict detected, suggestions returned."
        return ToolExecution(
            tool_name="create_calendar_event",
            success=success,
            summary=summary,
            input_payload={
                "user_id": user_id,
                "title": title,
                "start": start,
                "duration_minutes": duration_minutes,
                "participants": participants or [],
                "recurrence": recurrence,
            },
            output_payload={"event": event, "suggestions": [s.isoformat() for s in suggestions]},
        )

    def reschedule_event(self, user_id: str, event_id: str, new_start: str, duration_minutes: int = 30) -> ToolExecution:
        start_dt = date_parser.isoparse(new_start)
        event, suggestions = self.scheduler.reschedule_meeting(
            user_id=user_id,
            event_id=event_id,
            new_start=start_dt,
            duration_minutes=duration_minutes,
        )
        success = event is not None
        summary = "Event rescheduled." if success else "Conflict detected while rescheduling."
        return ToolExecution(
            tool_name="reschedule_event",
            success=success,
            summary=summary,
            input_payload={
                "user_id": user_id,
                "event_id": event_id,
                "new_start": new_start,
                "duration_minutes": duration_minutes,
            },
            output_payload={"event": event, "suggestions": [s.isoformat() for s in suggestions]},
        )

    def cancel_event(self, event_id: str) -> ToolExecution:
        self.scheduler.cancel_meeting(event_id)
        return ToolExecution(
            tool_name="cancel_event",
            success=True,
            summary="Event canceled.",
            input_payload={"event_id": event_id},
            output_payload={"cancelled": True},
        )

    def suggest_time_slots(self, user_id: str, start: str, duration_minutes: int = 30) -> ToolExecution:
        start_dt = date_parser.isoparse(start)
        suggestions = self.scheduler.suggest_time_slots(user_id=user_id, start=start_dt, duration_minutes=duration_minutes)
        return ToolExecution(
            tool_name="suggest_time_slots",
            success=True,
            summary=f"Generated {len(suggestions)} suggestion slots.",
            input_payload={"user_id": user_id, "start": start, "duration_minutes": duration_minutes},
            output_payload={"suggestions": [slot.isoformat() for slot in suggestions]},
        )

    def call_tool(self, name: str, args: dict[str, Any]) -> ToolExecution:
        normalized = {
            "create_meeting": "create_calendar_event",
            "reschedule_meeting": "reschedule_event",
            "cancel_meeting": "cancel_event",
            "list_meetings": "list_events",
        }.get(name, name)
        if normalized == "check_availability":
            return self.check_availability(date=args.get("date", datetime.now().isoformat()), query=args.get("query"))
        if normalized == "create_calendar_event":
            return self.create_calendar_event(
                user_id=args["user_id"],
                title=args.get("title", "Meeting"),
                start=args["start"],
                duration_minutes=int(args.get("duration_minutes", 30)),
                participants=args.get("participants", []),
                recurrence=args.get("recurrence"),
                organizer_name=args.get("organizer_name"),
                organizer_email=args.get("organizer_email"),
            )
        if normalized == "list_events":
            return self.list_events(
                date=args.get("date", datetime.now().isoformat()),
                query=args.get("query"),
                span=str(args.get("span", "day")),
            )
        if normalized == "reschedule_event":
            return self.reschedule_event(
                user_id=args["user_id"],
                event_id=args["event_id"],
                new_start=args["new_start"],
                duration_minutes=int(args.get("duration_minutes", 30)),
            )
        if normalized == "cancel_event":
            return self.cancel_event(event_id=args["event_id"])
        if normalized == "suggest_time_slots":
            return self.suggest_time_slots(
                user_id=args["user_id"],
                start=args.get("start", datetime.now().isoformat()),
                duration_minutes=int(args.get("duration_minutes", 30)),
            )
        raise ValueError(f"Unknown MCP tool: {name}")

