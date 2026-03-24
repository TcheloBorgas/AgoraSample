from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


class LocalLlmClient:
    """Cliente HTTP para um LLM em localhost (API /api/chat e /api/generate)."""

    def health_sync(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=6) as client:
                response = client.get(f"{settings.local_llm_base_url.rstrip('/')}/api/tags")
                return {"ok": response.status_code < 300, "status_code": response.status_code}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                response = await client.get(f"{settings.local_llm_base_url.rstrip('/')}/api/tags")
                return {"ok": response.status_code < 300, "status_code": response.status_code}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def chat_reply_sync(self, user_text: str, language: str = "pt") -> str:
        base = f"{settings.local_llm_base_url.rstrip('/')}"
        model = settings.local_llm_model
        opts = {"temperature": 0.2}
        with httpx.Client(timeout=120) as client:
            chat_body: dict[str, Any] = {
                "model": model,
                "messages": [
                    {"role": "system", "content": self._system_prompt(language)},
                    {"role": "user", "content": (user_text or "Usuario nao especificou claramente o pedido.").strip()},
                ],
                "stream": False,
                "options": opts,
            }
            try:
                r = client.post(f"{base}/api/chat", json=chat_body)
                if r.status_code < 300:
                    text = self._text_from_chat_payload(r.json())
                    if text:
                        return text
            except (httpx.RequestError, ValueError):
                pass

            prompt = self._build_generate_prompt(user_text, language)
            gen_body = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": opts,
            }
            response = client.post(f"{base}/api/generate", json=gen_body)
            if response.status_code >= 300:
                raise RuntimeError(f"LLM local HTTP {response.status_code}: {response.text}")
            payload = response.json()
            err = payload.get("error")
            if err:
                raise RuntimeError(str(err))
            return (payload.get("response") or "").strip()

    async def chat_reply(self, user_text: str, language: str = "pt") -> str:
        base = f"{settings.local_llm_base_url.rstrip('/')}"
        model = settings.local_llm_model
        opts = {"temperature": 0.2}
        chat_body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": self._system_prompt(language)},
                {"role": "user", "content": (user_text or "Usuario nao especificou claramente o pedido.").strip()},
            ],
            "stream": False,
            "options": opts,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                r = await client.post(f"{base}/api/chat", json=chat_body)
                if r.status_code < 300:
                    text = self._text_from_chat_payload(r.json())
                    if text:
                        return text
            except (httpx.RequestError, ValueError):
                pass

            prompt = self._build_generate_prompt(user_text, language)
            gen_body = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": opts,
            }
            response = await client.post(f"{base}/api/generate", json=gen_body)
            if response.status_code >= 300:
                raise RuntimeError(f"LLM local HTTP {response.status_code}: {response.text}")
            payload = response.json()
            err = payload.get("error")
            if err:
                raise RuntimeError(str(err))
            return (payload.get("response") or "").strip()

    @staticmethod
    def _text_from_chat_payload(payload: dict[str, Any]) -> str:
        if payload.get("error"):
            return ""
        msg = payload.get("message")
        if isinstance(msg, dict):
            return LocalLlmClient._normalize_content(msg.get("content")).strip()
        return (payload.get("response") or "").strip()

    @staticmethod
    def _normalize_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text" and isinstance(block.get("text"), str):
                        parts.append(block["text"])
                    elif isinstance(block.get("content"), str):
                        parts.append(block["content"])
            return "".join(parts)
        return ""

    def _system_prompt(self, language: str) -> str:
        if language == "es":
            return (
                "Eres un asistente de agenda. Responde en español, de forma breve y natural.\n"
                "Si la solicitud es ambigua, haz una sola pregunta clara para aclarar."
            )
        if language == "pt":
            return (
                "Você é um assistente de agenda. Responda em português, de forma curta e humana.\n"
                "Se o pedido estiver ambíguo, faça uma única pergunta objetiva para clarificar."
            )
        return (
            "You are a scheduling assistant. Reply in concise, natural English.\n"
            "If the request is ambiguous, ask one objective clarification question."
        )

    def _build_generate_prompt(self, user_text: str, language: str) -> str:
        ut = (user_text or "Usuario nao especificou claramente o pedido.").strip()
        if language == "es":
            return (
                "Eres un asistente de agenda. Responde en español, de forma breve y natural.\n"
                "Si la solicitud es ambigua, haz una sola pregunta clara.\n"
                f"Pedido del usuario: {ut}\nRespuesta:"
            )
        if language == "pt":
            return (
                "Você é um assistente de agenda. Responda em português, de forma curta e humana.\n"
                "Se o pedido estiver ambíguo, faça uma única pergunta objetiva para clarificar.\n"
                f"Pedido do usuário: {ut}\nResposta:"
            )
        return (
            "You are a scheduling assistant. Reply in concise, natural English.\n"
            "If the request is ambiguous, ask one objective clarification question.\n"
            f"User request: {ut}\nReply:"
        )
