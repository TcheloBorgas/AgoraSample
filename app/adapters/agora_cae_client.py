from __future__ import annotations

import base64
from typing import Any

import httpx

from app.core.config import settings


class AgoraConversationalAIClient:
    def __init__(self) -> None:
        self.base_url = "https://api.agora.io/api/conversational-ai-agent/v2"

    def _auth_header(self) -> dict[str, str]:
        if not settings.agora_cae_customer_id or not settings.agora_cae_customer_secret:
            raise RuntimeError(
                "AGORA_CAE_CUSTOMER_ID/AGORA_CAE_CUSTOMER_SECRET nao configurados. "
                "Crie credenciais REST no Agora Console para iniciar o Conversational AI Engine."
            )
        raw = f"{settings.agora_cae_customer_id}:{settings.agora_cae_customer_secret}".encode("utf-8")
        token = base64.b64encode(raw).decode("utf-8")
        return {"Authorization": f"Basic {token}"}

    async def start_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/projects/{settings.agora_app_id}/join"
        headers = {"Content-Type": "application/json", **self._auth_header()}
        timeout = httpx.Timeout(connect=15.0, read=60.0, write=30.0, pool=30.0)

        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    if response.status_code >= 300:
                        body = self._response_text(response)
                        raise RuntimeError(f"Falha ao iniciar CAE ({response.status_code}): {body}")
                    return response.json()
            except httpx.ReadTimeout as exc:
                last_error = exc
            except httpx.TimeoutException as exc:
                last_error = exc
            except httpx.RequestError as exc:
                last_error = exc

        if isinstance(last_error, httpx.ReadTimeout | httpx.TimeoutException):
            raise RuntimeError(
                "Timeout ao iniciar CAE na API da Agora. Verifique conectividade externa e tente novamente."
            ) from last_error
        if last_error:
            raise RuntimeError(f"Falha de rede ao iniciar CAE: {last_error}") from last_error
        raise RuntimeError("Falha desconhecida ao iniciar CAE.")

    async def stop_agent(self, agent_id: str) -> None:
        url = f"{self.base_url}/projects/{settings.agora_app_id}/agents/{agent_id}/leave"
        headers = {"Content-Type": "application/json", **self._auth_header()}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=headers)
            if response.status_code >= 300:
                body = self._response_text(response)
                raise RuntimeError(f"Falha ao parar CAE ({response.status_code}): {body}")

    @staticmethod
    def _response_text(response: httpx.Response) -> str:
        text = (response.text or "").strip()
        if text:
            return text
        try:
            return str(response.json())
        except Exception:  # noqa: BLE001
            return response.reason_phrase or "sem detalhe retornado pela API"
