import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from dateparser.search import search_dates

from app.core.config import settings


@dataclass
class IntentResult:
    intent: str
    entities: dict[str, Any]
    missing_fields: list[str]


class IntentService:
    def detect_intent_and_entities(self, text: str, language: str) -> IntentResult:
        lowered = text.lower().strip()
        if self._is_confirm_yes(lowered):
            return IntentResult(intent="confirm_yes", entities={}, missing_fields=[])
        if self._is_confirm_no(lowered):
            return IntentResult(intent="confirm_no", entities={}, missing_fields=[])

        intent = self._infer_intent(lowered)
        entities = self._extract_entities(text, language, intent)
        missing_fields = self._required_fields(intent, entities)
        return IntentResult(intent=intent, entities=entities, missing_fields=missing_fields)

    def _infer_intent(self, lowered: str) -> str:
        has_time_hint = bool(re.search(r"\b\d{1,2}(:\d{2})?\b", lowered)) or any(
            token in lowered
            for token in [
                "manha", "manhã", "tarde", "noite", "tomorrow", "today", "amanha", "amanhã",
                "manana", "mañana", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
            ]
        )
        has_meeting_noun = any(token in lowered for token in ["reuniao", "reunião", "meeting", "reunion", "reunión", "cita"])

        if any(k in lowered for k in ["criar", "crie", "create", "book", "agende", "marque", "agenda una", "crea una", "programa"]):
            return "create_meeting"
        if has_meeting_noun and has_time_hint and not any(k in lowered for k in ["reagend", "resched", "cancel", "cancele", "cancela"]):
            return "create_meeting"
        if any(k in lowered for k in ["reagend", "resched", "reprograma", "cambia la hora"]):
            return "reschedule_meeting"
        if any(k in lowered for k in ["cancel", "cancele", "cancela", "delete", "remove", "elimina"]):
            return "cancel_meeting"
        if any(k in lowered for k in [
            "tenho", "compromisso", "what do i have", "list", "show", "consultar", "consulta",
            "tengo", "compromiso", "que tengo", "algún compromiso", "algun compromiso", "mis reuniones",
        ]):
            return "list_meetings"
        if any(k in lowered for k in ["repita", "same as last", "last meeting", "ultima", "última", "repite"]):
            return "repeat_last_meeting"
        if any(k in lowered for k in ["english", "portugues", "português", "español", "espanol", "idioma", "language"]):
            return "set_language"
        return "unknown"

    def _extract_entities(self, text: str, language: str, intent: str) -> dict[str, Any]:
        now = datetime.now()
        lang_map = {"pt": ["pt", "en"], "en": ["en", "pt"], "es": ["es", "en"]}
        languages = lang_map.get(language, [language, "en"])
        date_hits = search_dates(
            text,
            languages=languages,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": False,
                "TIMEZONE": settings.timezone,
            },
        )
        start = date_hits[0][1] if date_hits else None

        if start and "amanh" in text.lower() and start.date() == now.date():
            start = start + timedelta(days=1)

        start = self._apply_day_period_adjustment(text, start)

        duration = self._extract_duration_minutes(text)
        end = start + timedelta(minutes=duration) if start else None
        participants = self._extract_participants(text)
        recurrence = self._extract_recurrence(text)
        language_change = self._extract_language_change(text)
        target_hint = self._extract_target_hint(text)

        title_map = {"en": "Meeting", "es": "Reunion", "pt": "Reuniao"}
        title = title_map.get(language, "Reuniao")
        if participants:
            prep = {"en": "with", "es": "con", "pt": "com"}.get(language, "com")
            title = f"{title} {prep} {', '.join(participants)}"

        return {
            "start": start,
            "end": end,
            "duration_minutes": duration,
            "participants": participants,
            "recurrence": recurrence,
            "language": language_change,
            "title": title,
            "target_hint": target_hint,
        }

    def _extract_duration_minutes(self, text: str) -> int:
        match = re.search(r"(\d{1,3})\s*(min|minute|minuto)", text.lower())
        if not match:
            return 30
        return max(15, int(match.group(1)))

    def _extract_participants(self, text: str) -> list[str]:
        emails = re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", text)
        names = []
        match = re.search(r"\bcom\s+([a-zA-ZÀ-ú,\seEand]+)", text, re.IGNORECASE)
        if match:
            raw = match.group(1).strip()
            separators = re.split(r",| e | and ", raw, flags=re.IGNORECASE)
            for part in separators:
                clean = part.strip(" .")
                if clean and len(clean) > 1:
                    names.append(clean.title())
        all_participants = []
        for value in names + emails:
            if value not in all_participants:
                all_participants.append(value)
        return all_participants[:10]

    def _extract_recurrence(self, text: str) -> str | None:
        lowered = text.lower()
        if any(k in lowered for k in ["toda semana", "every week", "semanal", "cada semana"]):
            return "weekly"
        if any(k in lowered for k in ["todo mes", "todo mês", "every month", "mensal", "cada mes"]):
            return "monthly"
        return None

    def _extract_language_change(self, text: str) -> str | None:
        lowered = text.lower()
        if "english" in lowered:
            return "en"
        if "portugues" in lowered or "português" in lowered:
            return "pt"
        if "español" in lowered or "espanol" in lowered:
            return "es"
        return None

    def _extract_target_hint(self, text: str) -> str | None:
        match = re.search(r"(?:reuniao|reunion|reunión)\s+(?:com|con|with)\s+([a-zA-ZÀ-ú\s]+)", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _apply_day_period_adjustment(self, text: str, start: datetime | None) -> datetime | None:
        if start is None:
            return None
        lowered = text.lower()
        hour = start.hour
        if any(token in lowered for token in ["tarde", "da tarde", "à tarde", "pm"]) and hour < 12:
            return start.replace(hour=hour + 12)
        if any(token in lowered for token in ["noite", "da noite"]) and hour < 12:
            return start.replace(hour=min(hour + 12, 23))
        if any(token in lowered for token in ["manhã", "manha", "de manhã"]) and hour == 12:
            return start.replace(hour=0)
        return start

    def _is_confirm_yes(self, lowered: str) -> bool:
        yes_exact = {
            "sim", "yes", "ok", "okay",
            "claro", "confirmo", "confirmar", "confirm",
            "pode", "pode sim", "pode ser", "isso", "isso mesmo",
            "si", "sí", "dale", "por supuesto", "confirmar", "adelante",
        }
        if lowered in yes_exact:
            return True
        yes_patterns = [
            r"\bpode confirmar\b",
            r"\bconfirma(r)?\b",
            r"\bsim[, ]+pode\b",
            r"\byes[, ]+please\b",
            r"\bgo ahead\b",
            r"\bprosseguir\b",
        ]
        return any(re.search(pattern, lowered) for pattern in yes_patterns)

    def _is_confirm_no(self, lowered: str) -> bool:
        no_exact = {"nao", "não", "no", "cancelar", "stop", "negativo", "nao confirmar", "não confirmar", "no gracias", "mejor no"}
        if lowered in no_exact:
            return True
        has_meeting_context = any(w in lowered for w in ["reuniao", "reunion", "meeting", "compromiso", "mi ", "minha "])
        if has_meeting_context:
            return False
        no_patterns = [
            r"^\s*nao[, ]+confirm(ar)?\s*$",
            r"^\s*não[, ]+confirm(ar)?\s*$",
            r"^\s*cancel(a|ar|e)\s*$",
            r"\bdeixa pra la\b",
            r"^\s*pare\s*$",
        ]
        return any(re.search(pattern, lowered) for pattern in no_patterns)

    def _required_fields(self, intent: str, entities: dict[str, Any]) -> list[str]:
        if intent == "create_meeting":
            missing = []
            if not entities.get("start"):
                missing.append("start")
            return missing
        if intent in {"reschedule_meeting", "cancel_meeting"}:
            missing = []
            if not entities.get("start") and not entities.get("target_hint"):
                missing.append("target_meeting")
            if intent == "reschedule_meeting" and not entities.get("start"):
                missing.append("new_start")
            return missing
        return []
