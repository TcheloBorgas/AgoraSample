"""Classificação de intenção via API estilo OpenAI (chat/completions), com fallback nas heurísticas."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.adapters.openai_compatible_llm import resolve_intent_classification_llm
from app.core.config import settings

logger = logging.getLogger(__name__)

_ALLOWED_INTENTS = frozenset(
    {
        "create_meeting",
        "list_meetings",
        "reschedule_meeting",
        "cancel_meeting",
        "repeat_last_meeting",
        "set_language",
        "unknown",
    }
)


def _intent_system_prompt(language: str) -> str:
    if language == "es":
        lang_hint = "El usuario puede hablar en español u otros idiomas."
    elif language == "en":
        lang_hint = (
            "The user speaks conversational English (including casual phrasing). "
            "Map scheduling/calendar wording to the closest intent (e.g. «book a call», «what's on my calendar», «move my 3pm»)."
        )
    else:
        lang_hint = "O usuário pode falar português ou outros idiomas."

    return (
        "You classify a single user utterance for a meeting/calendar voice assistant.\n"
        f"{lang_hint}\n"
        "Return ONLY JSON: {\"intent\": \"<one_of_the_list>\"} with no extra text.\n"
        "Allowed intent values (exact strings):\n"
        "- create_meeting: schedule new meeting / appointment, add to calendar, book a slot\n"
        "- list_meetings: what meetings do I have, show my commitments, list my calendar\n"
        "- reschedule_meeting: change time/date of an existing meeting\n"
        "- cancel_meeting: cancel/delete an existing meeting\n"
        "- repeat_last_meeting: repeat last meeting pattern, same as before\n"
        "- set_language: switch UI language (pt/en/es)\n"
        "- unknown: greetings, thanks, filler, unrelated, or unclear intent\n"
    )


def intent_classification_configured() -> bool:
    """True se houver chave/modelo para classificar intenção (sem variável de ambiente extra)."""
    return resolve_intent_classification_llm() is not None


def classify_intent_sync(user_text: str, language: str) -> str | None:
    """
    Chama LLM OpenAI-compat para obter uma intenção.
    Retorna None se não configurado, erro HTTP, ou JSON inválido.
    """
    resolved = resolve_intent_classification_llm()
    if not resolved:
        return None
    base, api_key, model = resolved
    url = f"{base}/chat/completions"
    ut = (user_text or "").strip()
    if not ut:
        return None
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": _intent_system_prompt(language)},
            {"role": "user", "content": ut},
        ],
        "temperature": 0,
        "max_tokens": 64,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    timeout = min(20, max(5, int(settings.llm_openai_compat_timeout_seconds)))
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, headers=headers, json=body)
            if r.status_code >= 300:
                logger.warning(
                    "intent_llm HTTP %s: %s",
                    r.status_code,
                    (r.text or "")[:400],
                )
                return None
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("intent_llm request failed: %s", exc)
        return None

    err = data.get("error")
    if err:
        msg = err if isinstance(err, str) else (err.get("message") if isinstance(err, dict) else str(err))
        logger.warning("intent_llm API error: %s", msg)
        return None

    choices = data.get("choices") or []
    if not choices:
        return None
    msg0 = choices[0].get("message") or {}
    content = msg0.get("content")
    raw = ""
    if isinstance(content, str):
        raw = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        raw = "".join(parts).strip()
    if not raw:
        return None

    intent: str | None = None
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and isinstance(obj.get("intent"), str):
            intent = obj["intent"].strip()
    except json.JSONDecodeError:
        m = re.search(r'"intent"\s*:\s*"([^"]+)"', raw)
        if m:
            intent = m.group(1).strip()

    if not intent:
        return None
    if intent not in _ALLOWED_INTENTS:
        logger.warning("intent_llm valor fora da lista: %r", intent)
        return None
    logger.info("intent_llm classificou intent=%s", intent)
    return intent
