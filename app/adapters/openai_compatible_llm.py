"""LLM via API estilo OpenAI (chat/completions): OpenAI oficial, Groq, OpenRouter, etc."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings

_OPENAI_API_V1 = "https://api.openai.com/v1"


def _scheduling_system_prompt(language: str) -> str:
    if language == "es":
        return (
            "Eres un asistente de agenda. Responde en español, de forma breve y natural.\n"
            "Si la solicitud es ambigua, haz una sola pregunta clara para aclarar.\n"
            "No mezcles inglés ni portugués: toda la respuesta debe estar solo en español."
        )
    if language == "pt":
        return (
            "Você é um assistente de agenda. Responda em português, de forma curta e humana.\n"
            "Se o pedido estiver ambíguo, faça uma única pergunta objetiva para clarificar.\n"
            "Não use inglês nem espanhol na resposta: apenas português, do primeiro ao último caractere."
        )
    return (
        "You are a scheduling assistant. Reply in concise, natural English.\n"
        "If the request is ambiguous, ask one objective clarification question.\n"
        "Do not use Portuguese or Spanish in your reply — English only, from start to finish."
    )


def _openai_official_chat_model() -> str:
    return (settings.openai_chat_model or "gpt-4o-mini").strip() or "gpt-4o-mini"


def resolve_openai_compat_llm() -> tuple[str, str, str] | None:
    """Retorna (base_url_sem_barra_final, api_key, model_id) ou None. Apenas APIs no formato OpenAI."""
    b = (settings.llm_openai_compat_base_url or "").strip().rstrip("/")
    k = (settings.llm_openai_compat_api_key or "").strip()
    m = (settings.llm_openai_compat_model or "").strip()
    if b and k and m:
        return b, k, m
    tts_key = (settings.agora_cae_tts_openai_key or "").strip()
    if tts_key:
        return _OPENAI_API_V1, tts_key, _openai_official_chat_model()
    return None


def resolve_intent_classification_llm() -> tuple[str, str, str] | None:
    """
    Credenciais só para classificar intenções (1 chamada extra por mensagem).

    1) LLM_OPENAI_COMPAT_* completo
    2) AGORA_CAE_TTS_OPENAI_KEY → chat na API OpenAI (modelo OPENAI_CHAT_MODEL, por defeito gpt-4o-mini)
    """
    b = (settings.llm_openai_compat_base_url or "").strip().rstrip("/")
    k = (settings.llm_openai_compat_api_key or "").strip()
    m = (settings.llm_openai_compat_model or "").strip()
    if b and k and m:
        return b, k, m
    tts_key = (settings.agora_cae_tts_openai_key or "").strip()
    if tts_key:
        return _OPENAI_API_V1, tts_key, _openai_official_chat_model()
    return None


class OpenAICompatibleLlmClient:
    """POST {base}/chat/completions com Bearer."""

    @staticmethod
    def is_configured() -> bool:
        return resolve_openai_compat_llm() is not None

    def chat_reply_sync(self, user_text: str, language: str = "pt") -> str:
        resolved = resolve_openai_compat_llm()
        if not resolved:
            raise RuntimeError("LLM OpenAI-compat não configurado")
        base, api_key, model = resolved
        url = f"{base}/chat/completions"
        ut = (user_text or "Usuario nao especificou claramente o pedido.").strip()
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": _scheduling_system_prompt(language)},
                {"role": "user", "content": ut},
            ],
            "temperature": 0.2,
            "max_tokens": 512,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        timeout = max(5, int(settings.llm_openai_compat_timeout_seconds))
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, headers=headers, json=body)
            if r.status_code >= 300:
                raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
        err = data.get("error")
        if err:
            msg = err if isinstance(err, str) else (err.get("message") if isinstance(err, dict) else str(err))
            raise RuntimeError(msg or "LLM error")
        choices = data.get("choices") or []
        if not choices:
            return ""
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "".join(parts).strip()
        return ""
