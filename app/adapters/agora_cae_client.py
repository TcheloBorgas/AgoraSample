from __future__ import annotations

import asyncio
import base64
import logging
import random
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 429 «allocate failed / vendor capacity» na Agora: várias tentativas com teto de espera (somatório ~3–4 min).
_CAE_JOIN_MAX_ATTEMPTS_RATE_LIMIT = 12
_CAE_JOIN_MAX_BACKOFF_SEC = 42.0
_CAE_JOIN_BASE_BACKOFF_429 = 2.4
_CAE_JOIN_BACKOFF_MULT_429 = 1.55


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        sec = float(raw)
        if sec >= 0:
            return sec
    except ValueError:
        pass
    return None


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

        max_attempts = _CAE_JOIN_MAX_ATTEMPTS_RATE_LIMIT
        last_error: Exception | None = None

        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    code = response.status_code

                    if code in (429, 503):
                        body = self._response_text(response)
                        if attempt < max_attempts - 1:
                            ra = _retry_after_seconds(response)
                            if ra is not None:
                                delay = min(
                                    _CAE_JOIN_MAX_BACKOFF_SEC,
                                    max(1.5, ra) + random.uniform(0, 0.6),
                                )
                            else:
                                delay = min(
                                    _CAE_JOIN_MAX_BACKOFF_SEC,
                                    _CAE_JOIN_BASE_BACKOFF_429
                                    * (_CAE_JOIN_BACKOFF_MULT_429**attempt)
                                    + random.uniform(0, 1.0),
                                )
                            logger.warning(
                                "CAE join HTTP %s, nova tentativa em %.1fs (%s/%s): %s",
                                code,
                                delay,
                                attempt + 1,
                                max_attempts,
                                body[:240],
                            )
                            await asyncio.sleep(delay)
                            continue
                        raise RuntimeError(
                            f"Falha ao iniciar CAE ({code}) após {max_attempts} tentativas: {body}. "
                            "Isto costuma ser capacidade temporária na Agora/fornecedor TTS (ex. ElevenLabs); "
                            "tente «Conectar Agora» de novo dentro de alguns minutos ou altere AGORA_CAE_TTS_VENDOR no .env."
                        )

                    if code >= 300:
                        body = self._response_text(response)
                        raise RuntimeError(f"Falha ao iniciar CAE ({code}): {body}")

                    return response.json()

            except httpx.ReadTimeout as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    delay = min(12.0, 1.0 * (2**attempt) + random.uniform(0, 0.3))
                    logger.warning(
                        "CAE join read timeout, nova tentativa em %.1fs (%s/%s)",
                        delay,
                        attempt + 1,
                        max_attempts,
                    )
                    await asyncio.sleep(delay)
                    continue
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    delay = min(12.0, 1.0 * (2**attempt) + random.uniform(0, 0.3))
                    logger.warning(
                        "CAE join timeout, nova tentativa em %.1fs (%s/%s)",
                        delay,
                        attempt + 1,
                        max_attempts,
                    )
                    await asyncio.sleep(delay)
                    continue
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    delay = min(8.0, 0.8 * (2**attempt))
                    logger.warning(
                        "CAE join rede: %s; nova tentativa em %.1fs (%s/%s)",
                        exc,
                        delay,
                        attempt + 1,
                        max_attempts,
                    )
                    await asyncio.sleep(delay)
                    continue

        if isinstance(last_error, (httpx.ReadTimeout, httpx.TimeoutException)):
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
