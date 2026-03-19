from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


class GoogleCalendarClient:
    def __init__(self) -> None:
        self._service = None

    def _ensure_service(self):
        if self._service is not None:
            return self._service

        token_path = Path(settings.google_token_file)
        token_path.parent.mkdir(parents=True, exist_ok=True)

        creds = None
        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(settings.google_client_secret_file):
                    raise FileNotFoundError(
                        f"Arquivo de credenciais Google nao encontrado: {settings.google_client_secret_file}"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(settings.google_client_secret_file, SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json(), encoding="utf-8")

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    def list_events(self, start: datetime, end: datetime, query: str | None = None) -> list[dict[str, Any]]:
        service = self._ensure_service()
        try:
            events_result = (
                service.events()
                .list(
                    calendarId=settings.google_calendar_id,
                    timeMin=start.astimezone(timezone.utc).isoformat(),
                    timeMax=end.astimezone(timezone.utc).isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    q=query,
                    maxResults=50,
                )
                .execute()
            )
            return events_result.get("items", [])
        except HttpError as exc:
            raise RuntimeError(f"Falha ao listar eventos no Google Calendar: {exc}") from exc

    def create_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        service = self._ensure_service()
        try:
            created = (
                service.events()
                .insert(
                    calendarId=settings.google_calendar_id,
                    body=payload,
                    sendUpdates="all",
                )
                .execute()
            )
            return created
        except HttpError as exc:
            raise RuntimeError(f"Falha ao criar evento no Google Calendar: {exc}") from exc

    def update_event(self, event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        service = self._ensure_service()
        try:
            updated = (
                service.events()
                .patch(
                    calendarId=settings.google_calendar_id,
                    eventId=event_id,
                    body=payload,
                    sendUpdates="all",
                )
                .execute()
            )
            return updated
        except HttpError as exc:
            raise RuntimeError(f"Falha ao atualizar evento no Google Calendar: {exc}") from exc

    def delete_event(self, event_id: str) -> None:
        service = self._ensure_service()
        try:
            service.events().delete(
                calendarId=settings.google_calendar_id,
                eventId=event_id,
                sendUpdates="all",
            ).execute()
        except HttpError as exc:
            raise RuntimeError(f"Falha ao cancelar evento no Google Calendar: {exc}") from exc

    def find_conflicts(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self.list_events(start=start - timedelta(minutes=1), end=end + timedelta(minutes=1))
