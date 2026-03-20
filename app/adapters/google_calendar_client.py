from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _load_oauth_client_config_from_env_value(raw: str) -> dict[str, Any]:
    """GOOGLE_CLIENT_SECRET_JSON: JSON inline (começa com `{`) ou caminho para um ficheiro .json."""
    s = (raw or "").strip()
    if not s:
        raise ValueError("GOOGLE_CLIENT_SECRET_JSON esta vazia.")
    if s.startswith("{"):
        try:
            return cast(dict[str, Any], json.loads(s))
        except json.JSONDecodeError as exc:
            raise ValueError("GOOGLE_CLIENT_SECRET_JSON nao e JSON valido (inline).") from exc

    path = Path(s)
    candidates = [path, Path("/etc/secrets") / path.name, Path("/opt/render/project/src") / path.name, Path.cwd() / path.name]
    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            try:
                return cast(dict[str, Any], json.loads(p.read_text(encoding="utf-8")))
            except json.JSONDecodeError as exc:
                raise ValueError(f"OAuth client secret em {p} nao e JSON valido.") from exc

    raise FileNotFoundError(
        f"GOOGLE_CLIENT_SECRET_JSON aponta para um ficheiro que nao existe: {s}. "
        "Monte o Secret File no Render ou cola o JSON completo na env (texto que começa com {{)."
    )


def _resolve_google_client_secret_path() -> str | None:
    """Caminhos usuais no Render: Python nativo por vezes expõe secrets na raiz do projeto, não só em /etc/secrets."""
    raw = (settings.google_client_secret_file or "").strip()
    base = os.path.basename(raw) if raw else ""
    candidates: list[str] = []
    if raw:
        candidates.append(raw)
    if base:
        candidates.extend(
            [
                f"/etc/secrets/{base}",
                str(Path("/opt/render/project/src") / base),
                str(Path.cwd() / base),
            ]
        )
    for extra in ("google-oauth.json", "credentials.json"):
        p = f"/etc/secrets/{extra}"
        if p not in candidates:
            candidates.append(p)
        p2 = str(Path("/opt/render/project/src") / extra)
        if p2 not in candidates:
            candidates.append(p2)
        p3 = str(Path.cwd() / extra)
        if p3 not in candidates:
            candidates.append(p3)
    seen: set[str] = set()
    for p in candidates:
        if not p or p in seen:
            continue
        seen.add(p)
        if os.path.isfile(p):
            return p
    return None


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
                secret_json = (settings.google_client_secret_json or "").strip()
                if secret_json:
                    client_cfg = _load_oauth_client_config_from_env_value(secret_json)
                    flow = InstalledAppFlow.from_client_config(client_cfg, SCOPES)
                else:
                    path = _resolve_google_client_secret_path()
                    if not path:
                        raise FileNotFoundError(
                            "Arquivo de credenciais Google nao encontrado. "
                            "Defina GOOGLE_CLIENT_SECRET_JSON (JSON numa linha) ou coloque o ficheiro "
                            f"({settings.google_client_secret_file}) num dos paths tentados."
                        )
                    flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
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
