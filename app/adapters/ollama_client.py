from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings


class OllamaClient:
    def health_sync(self) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=6) as client:
                response = client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
                return {"ok": response.status_code < 300, "status_code": response.status_code}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                response = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
                return {"ok": response.status_code < 300, "status_code": response.status_code}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def chat_reply_sync(self, user_text: str, language: str = "pt") -> str:
        prompt = self._build_prompt(user_text, language)
        body = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        with httpx.Client(timeout=45) as client:
            response = client.post(f"{settings.ollama_base_url.rstrip('/')}/api/generate", json=body)
            if response.status_code >= 300:
                raise RuntimeError(f"Ollama retornou {response.status_code}: {response.text}")
            payload = response.json()
            return (payload.get("response") or "").strip()

    async def chat_reply(self, user_text: str, language: str = "pt") -> str:
        prompt = self._build_prompt(user_text, language)
        body = {
            "model": settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(f"{settings.ollama_base_url.rstrip('/')}/api/generate", json=body)
            if response.status_code >= 300:
                raise RuntimeError(f"Ollama retornou {response.status_code}: {response.text}")
            payload = response.json()
            return (payload.get("response") or "").strip()

    def _build_prompt(self, user_text: str, language: str) -> str:
        if language == "pt":
            return (
                "Você é um assistente de agenda. Responda em português, de forma curta e humana.\n"
                "Se o pedido estiver ambíguo, faça uma única pergunta objetiva para clarificar.\n"
                f"Pedido do usuário: {user_text}\nResposta:"
            )
        return (
            "You are a scheduling assistant. Reply in concise, natural English.\n"
            "If the request is ambiguous, ask one objective clarification question.\n"
            f"User request: {user_text}\nReply:"
        )
