import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from dateparser.search import search_dates
from dateutil import parser as date_parser

from app.adapters.intent_llm_classifier import classify_intent_sync, intent_classification_configured
from app.core.config import settings
from app.models.domain import MeetingDraft

logger = logging.getLogger(__name__)


def _fold_ascii_lower(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (s or "").strip()) if unicodedata.category(c) != "Mn"
    ).lower()


_TEMPORAL_SUBJECT_WORDS = frozenset({
    "amanha",
    "hoje",
    "ontem",
    "tarde",
    "noite",
    "manha",
    "depois",
    "logo",
    "agora",
    "tomorrow",
    "today",
    "yesterday",
    "morning",
    "afternoon",
    "evening",
    "tonight",
    "later",
})


def meeting_subject_is_invalid(title: str | None) -> bool:
    """True se o texto nao serve como assunto/titulo real (generico ou so temporal)."""
    if title is None or not str(title).strip():
        return True
    raw = str(title).strip()
    tl = raw.lower()
    if len(tl) < 2:
        return True
    if tl in {"reuniao", "reunião", "meeting", "reunion", "reunión", "cita"}:
        return True
    folded = _fold_ascii_lower(raw)
    if folded in _TEMPORAL_SUBJECT_WORDS:
        return True
    words = folded.split()
    if words and all(w in _TEMPORAL_SUBJECT_WORDS for w in words):
        return True
    return False


@dataclass
class IntentResult:
    intent: str
    entities: dict[str, Any]
    missing_fields: list[str]


class IntentService:
    @staticmethod
    def _has_strong_temporal_signal(text: str) -> bool:
        lowered = text.lower()
        if re.search(r"\b\d{1,2}\s*:\s*\d{2}\b", lowered):
            return True
        if re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)\b", lowered):
            return True
        if re.search(r"\b\d{1,2}\s*h\b", lowered):
            return True
        if re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", lowered):
            return True
        strong_tokens = (
            "amanh",
            "hoje",
            "tomorrow",
            "today",
            "depois de amanha",
            "depois de amanhã",
            "next week",
            "proxima semana",
            "próxima semana",
            "segunda",
            "terca",
            "terça",
            "quarta",
            "quinta",
            "sexta",
            "sabado",
            "sábado",
            "domingo",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
        return any(token in lowered for token in strong_tokens)

    def normalize_user_text(self, text: str) -> str:
        t = (text or "").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
        t = re.sub(r"https?://[^\s]+", " ", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def detect_intent_and_entities(self, text: str, language: str) -> IntentResult:
        text = self.normalize_user_text(text)
        lowered = text.lower().strip()
        if self._is_confirm_yes(lowered):
            return IntentResult(intent="confirm_yes", entities={}, missing_fields=[])
        if self._is_confirm_no(lowered):
            return IntentResult(intent="confirm_no", entities={}, missing_fields=[])

        if intent_classification_configured():
            llm_intent: str | None = None
            try:
                llm_intent = classify_intent_sync(text, language)
            except Exception as exc:  # noqa: BLE001
                logger.warning("intent LLM falhou, usando heuristica: %s", exc)
            intent = llm_intent if llm_intent else self._infer_intent(lowered)
        else:
            intent = self._infer_intent(lowered)
        entities = self._extract_entities(text, language, intent)
        missing_fields = self._required_fields(intent, entities)
        return IntentResult(intent=intent, entities=entities, missing_fields=missing_fields)

    def _infer_intent(self, lowered: str) -> str:
        has_time_hint = bool(re.search(r"\b\d{1,2}\s*:\s*\d{2}\b", lowered)) or bool(
            re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)\b", lowered)
        ) or bool(re.search(r"\b\d{1,2}h\b", lowered)) or bool(re.search(r"\b\d{1,2}(:\d{2})?\b", lowered)) or any(
            token in lowered
            for token in [
                "manha", "manhã", "tarde", "noite", "tomorrow", "today", "amanha", "amanhã",
                "manana", "mañana", "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo",
            ]
        )
        has_meeting_noun = any(token in lowered for token in ["reuniao", "reunião", "meeting", "reunion", "reunión", "cita"])
        has_preference_reply = any(
            token in lowered
            for token in [
                "i'd like", "i would like", "prefer", "i prefer",
                "prefiro", "gostaria", "quero", "pode ser",
                "me gustaría", "prefiero", "quisiera",
            ]
        )

        if any(
            k in lowered
            for k in [
            "criar",
            "crie",
            "cria",
            "criado",
            "criando",

            "create",
            "creates",
            "creating",
            "created",

            "book",
            "booking",
            "booked",

            "schedule",
            "schedules",
            "scheduled",
            "scheduling",

            "agendar",
            "agende",
            "agenda",
            "agendado",
            "agendando",
            "awgende",
            "agnda",
            "agendar um",
            "agendar uma",

            "marcar",
            "marque",
            "marca",
            "marcado",
            "marcando",
            "marcar um",
            "marcar uma",

            "programar",
            "programe",
            "programa",
            "programado",
            "programando",

            "reservar",
            "reserve",
            "reserva",
            "reservado",
            "reservando",

            "appointment",
            "set appointment",
            "make appointment",

            "crear",
            "crea",
            "cree",
            "creando",
            "creado",

            "agenda una",
            "agenda un",
            "agendar una",
            "agendar un",

            "programa una",
            "programa un",
            "programar una",
            "programar un",

            "reservar una",
            "reservar un",
            "reserva una",
            "reserva un",

            "cita",
            "agendar cita",
            "reservar cita",
            "programar cita"
        ]
        ):
            return "create_meeting"
        if has_time_hint and has_preference_reply:
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
        clock = self._extract_explicit_clock_time(text)
        lowered = text.lower()
        if not self._has_strong_temporal_signal(text):
            start = None

        if start is None and clock:
            base_date = now.date()
            if "depois de amanha" in lowered or "depois de amanhã" in lowered:
                base_date = (now + timedelta(days=2)).date()
            elif "amanh" in lowered:
                base_date = (now + timedelta(days=1)).date()
            h, mn = clock
            start = datetime(base_date.year, base_date.month, base_date.day, h, mn, 0, 0)

        if start and "amanh" in lowered and start.date() == now.date():
            start = start + timedelta(days=1)

        if start and clock:
            h, mn = clock
            start = start.replace(hour=h, minute=mn, second=0, microsecond=0)

        if (
            start
            and intent == "create_meeting"
            and start < now
            and "ontem" not in lowered
            and "yesterday" not in lowered
            and "hoje" not in lowered
            and "today" not in lowered
        ):
            start = start + timedelta(days=1)

        start = self._apply_day_period_adjustment(text, start)

        duration = self._extract_duration_minutes(text)
        end = start + timedelta(minutes=duration) if start else None
        participants = self._extract_participants(text)
        recurrence = self._extract_recurrence(text)
        language_change = self._extract_language_change(text)
        target_hint = self._extract_target_hint(text)

        organizer_name = self._extract_organizer_name(text)
        organizer_email = self._extract_explicit_contact_email(text)
        emails_in_text = re.findall(r"[\w.-]+@[\w.-]+\.\w+", text)
        if organizer_email is None and emails_in_text:
            organizer_email = emails_in_text[0].lower()
        explicit_title = self._extract_explicit_subject(text)
        list_span = self._extract_list_span(text)

        title: str | None
        if intent == "create_meeting":
            title = explicit_title
        else:
            title_map = {"en": "Meeting", "es": "Reunion", "pt": "Reuniao"}
            title = explicit_title or title_map.get(language, "Reuniao")
            if participants:
                prep = {"en": "with", "es": "con", "pt": "com"}.get(language, "com")
                title = f"{title_map.get(language, 'Reuniao')} {prep} {', '.join(participants)}"

        return {
            "start": start,
            "end": end,
            "duration_minutes": duration,
            "participants": participants,
            "recurrence": recurrence,
            "language": language_change,
            "title": title,
            "target_hint": target_hint,
            "organizer_name": organizer_name,
            "organizer_email": organizer_email,
            "list_span": list_span,
        }

    def _extract_list_span(self, text: str) -> str:
        """Intervalo para listar compromissos: semana calendário (seg–dom) que contém a data de referência."""
        lowered = text.lower()
        if any(
            p in lowered
            for p in (
                "essa semana",
                "esta semana",
                "dessa semana",
                "desta semana",
                "nessa semana",
                "nesta semana",
                "this week",
                "whole week",
                "semana atual",
                "durante a semana",
                "ao longo da semana",
                "encontros da semana",
                "compromissos da semana",
            )
        ):
            return "week"
        return "day"

    def _extract_explicit_clock_time(self, text: str) -> tuple[int, int] | None:
        """Hora explícita tipo «às 13», «as 13h», «at 2:30». dateparser costuma acertar o dia mas manter o relógio «agora»."""
        if re.search(r"\b\d{1,3}\s*(?:min|minute|minuto)", text.lower()):
            return None
        m = re.search(r"(?:às|as|at)\s*(\d{1,2})(?::(\d{2}))?(?:\s*h\b)?", text, re.IGNORECASE)
        if m:
            h, mn = int(m.group(1)), int(m.group(2) or 0)
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return h, mn
        m2 = re.search(r"\b(\d{1,2})\s*:\s*(\d{2})\b", text)
        if m2:
            h, mn = int(m2.group(1)), int(m2.group(2))
            if 0 <= h <= 23 and 0 <= mn <= 59:
                return h, mn
        m3 = re.search(r"\b(\d{1,2})\s*h\b", text, re.IGNORECASE)
        if m3 and not re.search(r"\bhoje\b", text.lower()):
            h = int(m3.group(1))
            if 0 <= h <= 23:
                return h, 0
        return None

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
        has_afternoon = bool(re.search(r"\btarde\b|da tarde|à tarde|\bpm\b", lowered))
        has_night = bool(re.search(r"\bnoite\b|da noite", lowered))
        has_morning = bool(re.search(r"\bmanh[ãa]\b|de manhã|de manha", lowered))
        if has_afternoon and hour < 12:
            return start.replace(hour=hour + 12)
        if has_night and hour < 12:
            return start.replace(hour=min(hour + 12, 23))
        if has_morning and hour == 12:
            return start.replace(hour=0)
        return start

    def _is_confirm_yes(self, lowered: str) -> bool:
        yes_exact = {
            "sim", "yes", "ok", "okay", "k",
            "claro", "confirmo", "confirmar", "confirm", "confirma", "confirme",
            "pode", "pode sim", "pode ser", "isso", "isso mesmo",
            "tudo bem", "perfeito", "feito", "certo", "correto",
            "si", "sí", "dale", "por supuesto", "adelante", "perfecto",
            "pode confirmar", "sim pode", "sim confirmar",
            "yes please", "go ahead", "prosseguir",
            "pode confirmar sim", "confirma por favor",
            "confirma sim", "sim confirma", "sim por favor",
            "claro que sim", "com certeza",
        }
        if lowered in yes_exact:
            return True
        yes_patterns = [
            r"\bpode confirmar\b",
            r"\bconfirm(a|e|o|ar)\b",
            r"\bsim[, ]+pode\b",
            r"\byes[, ]+please\b",
            r"\bgo ahead\b",
            r"\bprosseguir\b",
            r"\btudo (bem|certo)\b",
            r"\bcom certeza\b",
            r"\bpor favor\b.*\bconfirm",
        ]
        return any(re.search(pattern, lowered) for pattern in yes_patterns)

    def _is_confirm_no(self, lowered: str) -> bool:
        no_exact = {
            "nao", "não", "no", "cancelar", "stop", "negativo",
            "nao confirmar", "não confirmar", "no gracias", "mejor no",
            "deixa pra la", "deixa pra lá", "nao quero", "não quero",
        }
        if lowered in no_exact:
            return True
        has_meeting_context = any(
            w in lowered for w in [
                "reuniao", "reunião", "reunion", "reunión",
                "meeting", "compromiso", "compromisso",
                "mi ", "minha ", "essa ", "esta ", "este ",
            ]
        )
        if has_meeting_context:
            return False
        no_patterns = [
            r"^\s*nao[, ]+confirm(ar)?\s*$",
            r"^\s*não[, ]+confirm(ar)?\s*$",
            r"^\s*cancel(a|ar|e)\s*$",
            r"\bdeixa pra l[aá]\b",
            r"^\s*pare\s*$",
        ]
        return any(re.search(pattern, lowered) for pattern in no_patterns)

    def _is_generic_title(self, title: str | None) -> bool:
        return meeting_subject_is_invalid(title)

    _PLAIN_NAME_DENYLIST = frozenset({
        "sim",
        "não",
        "nao",
        "yes",
        "no",
        "ok",
        "list",
        "lista",
        "listar",
        "show",
        "cancelar",
        "cancel",
        "email",
        "mail",
        "e-mail",
        "assunto",
        "reuniao",
        "reunião",
        "meeting",
        "amanha",
        "amanhã",
        "hoje",
        "tomorrow",
        "today",
    })

    def _looks_like_plain_person_name(self, text: str) -> bool:
        t = text.strip()
        if len(t) < 2 or len(t) > 120:
            return False
        if "@" in t or "\n" in t:
            return False
        lowered = t.lower()
        if lowered in self._PLAIN_NAME_DENYLIST:
            return False
        words = t.split()
        if len(words) == 1:
            w = words[0].lower()
            if w in self._PLAIN_NAME_DENYLIST or len(w) < 3:
                return False
        for w in words:
            wl = w.lower().strip("'.-")
            if wl and wl in self._PLAIN_NAME_DENYLIST:
                return False
        if not re.match(r"^[a-zA-ZÀ-úà-üßñçÇÑ\s'.-]+$", t, re.UNICODE):
            return False
        if re.search(r"\d", t):
            return False
        return True

    def fill_first_missing_create_slot(self, normalized_text: str, language: str, merged: dict[str, Any]) -> dict[str, Any]:
        """Preenche o proximo campo obrigatorio quando o usuario responde so com nome/email/assunto (sem frases-chave)."""
        missing = self._required_fields("create_meeting", merged)
        if not missing:
            return merged
        first = missing[0]
        t = normalized_text.strip()
        if not t:
            return merged
        lowered = t.lower()
        out = dict(merged)
        if first == "organizer_name":
            if self._looks_like_plain_person_name(t):
                out["organizer_name"] = " ".join(w.strip("'.-") for w in t.split() if w.strip())[:120]
            return out
        if first == "organizer_email":
            m = re.search(r"[\w.-]+@[\w.-]+\.\w+", t)
            if m:
                out["organizer_email"] = m.group(0).lower()
            return out
        if first == "title":
            if "@" in t or len(t) < 3:
                return out
            if re.search(r"\b\d{1,2}\s*:\s*\d{2}\b", lowered):
                return out
            if re.search(r"\b\d{1,2}h\b", lowered):
                return out
            if re.search(r"\b(às|as|at)\s+\d{1,2}\b", lowered):
                return out
            if meeting_subject_is_invalid(t):
                return out
            out["title"] = t.strip()[:200]
            return out
        return out

    def merge_meeting_draft(self, draft: MeetingDraft | None, entities: dict[str, Any]) -> dict[str, Any]:
        base: dict[str, Any] = {}
        if draft is not None:
            base = draft.model_dump()
            if meeting_subject_is_invalid(base.get("title")):
                base["title"] = None
        out = {**base}
        for k, v in entities.items():
            if v is None:
                continue
            if k == "title" and meeting_subject_is_invalid(str(v)):
                continue
            if k == "participants" and isinstance(v, list) and len(v) == 0:
                continue
            if k == "organizer_name" and isinstance(v, str) and len(v.strip()) < 2:
                continue
            if k == "organizer_email" and isinstance(v, str) and "@" not in v:
                continue
            out[k] = v
        return out

    def try_revise_pending_create_payload(
        self, text: str, language: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Durante confirmação final: extrair novo horário/título/duração a partir de correções curtas."""
        if not payload or not payload.get("start"):
            return None
        normalized = self.normalize_user_text(text)
        lowered = normalized.lower()
        if not normalized:
            return None

        bail_phrases = (
            "cancela",
            "cancelar",
            "esquece",
            "nao quero mais",
            "não quero mais",
            "listar",
            "consultar",
            "reagend",
            "desmarca",
        )
        if any(p in lowered for p in bail_phrases):
            return None

        time_cues = (
            "horario",
            "horário",
            "hora",
            "às",
            " as ",
            "as ",
            "at ",
            "manhã",
            "manha",
            "tarde",
            "noite",
            "mudar",
            "mude",
            "alter",
            "troca",
            "corrig",
            "errado",
            "em vez",
            "na verdade",
        )
        has_digit_time = bool(
            re.search(r"\b\d{1,2}\s*:\s*\d{2}\b", lowered)
            or re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm|a\.m\.|p\.m\.)\b", lowered)
            or self._extract_explicit_clock_time(normalized) is not None
            or re.search(r"\b\d{1,2}\s*h\b", lowered)
        )
        has_time_signal = any(c in lowered for c in time_cues) or has_digit_time
        explicit_title = self._extract_explicit_subject(normalized)
        dur_explicit = bool(re.search(r"\b(\d{1,3})\s*(min|minute|minuto)", lowered))
        dur_m = self._extract_duration_minutes(normalized)

        if not has_time_signal and explicit_title is None and not dur_explicit:
            return None

        try:
            anchor_start = date_parser.isoparse(str(payload["start"]))
        except (ValueError, TypeError):
            return None
        if anchor_start.tzinfo is not None:
            anchor_start = anchor_start.replace(tzinfo=None)

        now = datetime.now()
        lang_map = {"pt": ["pt", "en"], "en": ["en", "pt"], "es": ["es", "en"]}
        languages = lang_map.get(language, [language, "en"])
        date_hits = search_dates(
            normalized,
            languages=languages,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": False,
                "TIMEZONE": settings.timezone,
            },
        )
        start = date_hits[0][1] if date_hits else None
        clock = self._extract_explicit_clock_time(normalized)

        if start is None and clock:
            base_date = anchor_start.date()
            if "depois de amanha" in lowered or "depois de amanhã" in lowered:
                base_date = (now + timedelta(days=2)).date()
            elif "amanh" in lowered:
                base_date = (now + timedelta(days=1)).date()
            h, mn = clock
            start = datetime(base_date.year, base_date.month, base_date.day, h, mn, 0, 0)

        if start and "amanh" in lowered and start.date() == now.date():
            start = start + timedelta(days=1)

        if start and clock:
            h, mn = clock
            start = start.replace(hour=h, minute=mn, second=0, microsecond=0)

        if (
            start
            and start < now
            and "ontem" not in lowered
            and "yesterday" not in lowered
            and "hoje" not in lowered
            and "today" not in lowered
        ):
            start = start + timedelta(days=1)

        start = self._apply_day_period_adjustment(normalized, start)

        updates: dict[str, Any] = {}
        if start is not None:
            if start.replace(second=0, microsecond=0) != anchor_start.replace(second=0, microsecond=0):
                updates["start"] = start

        if explicit_title and not meeting_subject_is_invalid(explicit_title):
            prev = (payload.get("title") or "").strip()
            if explicit_title.strip() != prev:
                updates["title"] = explicit_title.strip()[:200]

        if dur_explicit and dur_m != int(payload.get("duration_minutes") or 30):
            updates["duration_minutes"] = dur_m

        return updates if updates else None

    def try_resume_create_after_unknown(self, text: str, language: str, draft: MeetingDraft | None) -> IntentResult | None:
        if draft is None:
            return None
        normalized = self.normalize_user_text(text)
        lowered = normalized.lower().strip()
        if self._is_confirm_yes(lowered) or self._is_confirm_no(lowered):
            return None
        if lowered in {"list", "lista", "listar", "show", "mostrar"}:
            return None
        entities = self._extract_entities(normalized, language, "create_meeting")
        merged = self.merge_meeting_draft(draft, entities)
        merged = self.fill_first_missing_create_slot(normalized, language, merged)
        missing = self._required_fields("create_meeting", merged)
        return IntentResult(intent="create_meeting", entities=merged, missing_fields=missing)

    def _extract_explicit_subject(self, text: str) -> str | None:
        patterns = [
            r"\bassunto\s*[:\s]+\s*(.+?)(?:\.|,|\n|$|(?=\s+(?:às|as|at|para|for|com|with|on)\s))",
            r"\bsubject\s*[:\s]+\s*(.+?)(?:\.|,|\n|$)",
            r"\bt(?:ítulo|itulo)\s*[:\s]+\s*(.+?)(?:\.|,|\n|$)",
            r"\bsobre\s+([^.,\n]{2,100}?)(?=\s*(?:\.|,|\n|às|as|at|para)\s|$)",
            r"\babout\s+([^.,\n]{2,100}?)(?=\s*(?:\.|,|\n|at|for)\s|$)",
            r"\btitled\s+[\"']?([^\"'\n,]{2,100})",
            r"\breuni[aã]o\s+(?:de|para)\s+(?!(?:amanh[ãa]|hoje|ontem|depois)\b)([^.,\n]{2,100}?)(?=\s*(?:\.|,|\n|às|as|at)\s|$)",
            r"\bmeeting\s+(?:about|for)\s+([^.,\n]{2,100}?)(?=\s*(?:\.|,|\n|at)\s|$)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                subj = re.sub(r"\s+", " ", m.group(1).strip()).strip("'\"")
                if len(subj) >= 2 and not meeting_subject_is_invalid(subj):
                    return subj[:200]
        return None

    def _extract_organizer_name(self, text: str) -> str | None:
        patterns = [
            r"(?:meu\s+nome\s+[ée]\s+|my\s+name\s+is\s+|i\s+am\s+|i'm\s+|sou\s+(?:o\s+|a\s+)?)([A-Za-zÀ-ú](?:[A-Za-zÀ-ú\s'.-]{0,58}[A-Za-zÀ-ú])?)",
            r"\bnome\s*[:\s]+\s*([A-Za-zÀ-ú](?:[A-Za-zÀ-ú\s'.-]{0,58}[A-Za-zÀ-ú])?)",
            r"\bname\s*[:\s]+\s*([A-Za-zÀ-ú](?:[A-Za-zÀ-ú\s'.-]{0,58}[A-Za-zÀ-ú])?)",
            r"\bmi\s+nombre\s+es\s+([A-Za-zÀ-ú](?:[A-Za-zÀ-ú\s'.-]{0,58}[A-Za-zÀ-ú])?)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                name = re.sub(r"\s+", " ", m.group(1).strip(" .,'"))
                if name and len(name) >= 2 and "@" not in name:
                    return name[:120]
        return None

    def _extract_explicit_contact_email(self, text: str) -> str | None:
        m = re.search(
            r"(?:e-?mail|correo)\s*(?:é|eh|es|is|\:)?\s*([\w.-]+@[\w.-]+\.\w+)",
            text,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).lower()
        return None

    def _required_fields(self, intent: str, entities: dict[str, Any]) -> list[str]:
        if intent == "create_meeting":
            missing = []
            name = entities.get("organizer_name")
            if not name or len(str(name).strip()) < 2:
                missing.append("organizer_name")
            email = entities.get("organizer_email")
            if not email or "@" not in str(email):
                missing.append("organizer_email")
            if not entities.get("title") or meeting_subject_is_invalid(str(entities.get("title"))):
                missing.append("title")
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
