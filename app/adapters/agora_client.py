import re
import time
from dataclasses import dataclass

from app.core.config import settings

# Limite do nome de canal Agora (bytes/caracteres conservador)
_AGORA_CHANNEL_MAX_LEN = 64


def _sanitize_session_id_for_channel(session_id: str) -> str:
    raw = (session_id or "").strip() or "default"
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", raw)
    return safe.strip("-") or "default"


def build_rtc_channel_name(session_id: str) -> str:
    """
    Um canal RTC por sessão: evita colisão de agentes/uid 20001 entre utilizadores
    quando AGORA_FIXED_CHANNEL era um nome único (ex.: «Agora») para todos.
    Formato: {prefixo ou fixo}-{session_id_sanitizado}, truncado a 64 chars.
    """
    sid = _sanitize_session_id_for_channel(session_id)
    base = (settings.agora_fixed_channel or settings.agora_channel_prefix or "assistant-voice").strip()
    if not base:
        base = "assistant-voice"
    raw = f"{base}-{sid}"
    if len(raw) <= _AGORA_CHANNEL_MAX_LEN:
        return raw
    # Truncar mantendo sufixo (session) para unicidade
    suffix = f"-{sid}"
    max_base = _AGORA_CHANNEL_MAX_LEN - len(suffix)
    if max_base < 8:
        return raw[:_AGORA_CHANNEL_MAX_LEN]
    return f"{base[:max_base]}{suffix}"


@dataclass
class AgoraSession:
    app_id: str
    channel: str
    token: str
    uid: int


def build_rtc_token_for_uid(channel: str, uid: int, ttl_seconds: int = 86400) -> str:
    """
    Token RTC para um UID concreto no canal (ex.: agente CAE com AGORA_CAE_AGENT_UID).
    O token enviado ao utilizador no browser e sempre para AGORA_UID — nao serve para o agente.
    Requer AGORA_APP_CERTIFICATE (tokens por uid nao podem ser reutilizados entre UIDs).
    """
    if not settings.agora_app_id:
        raise RuntimeError("AGORA_APP_ID nao configurado")
    cert = (settings.agora_app_certificate or "").strip()
    if not cert:
        raise RuntimeError(
            "AGORA_APP_CERTIFICATE e obrigatorio para gerar o token RTC do agente CAE. "
            "O token do utilizador (browser) e valido apenas para AGORA_UID; o agente usa AGORA_CAE_AGENT_UID."
        )
    uid_int = int(uid)
    if uid_int <= 0:
        uid_int = 10001
    if uid_int > 2_147_483_647:
        uid_int = uid_int % 2_147_483_647
    return _build_rtc_token(settings.agora_app_id, cert, channel, uid_int, ttl_seconds)


def _build_rtc_token(app_id: str, certificate: str, channel: str, uid: int, ttl_seconds: int = 86400) -> str:
    from agora_token_builder import RtcTokenBuilder
    from agora_token_builder.RtcTokenBuilder import Role_Publisher

    expire_ts = int(time.time()) + ttl_seconds
    return RtcTokenBuilder.buildTokenWithUid(
        app_id,
        certificate.strip(),
        channel,
        uid,
        Role_Publisher,
        expire_ts,
    )


class AgoraClient:
    def build_session(self, session_id: str) -> AgoraSession:
        if not settings.agora_app_id:
            raise RuntimeError("AGORA_APP_ID nao configurado")

        channel = build_rtc_channel_name(session_id)
        uid = settings.agora_uid
        if uid <= 0:
            uid = 10001
        if uid > 2_147_483_647:
            uid = uid % 2_147_483_647

        cert = (settings.agora_app_certificate or "").strip()
        if cert:
            try:
                token = _build_rtc_token(settings.agora_app_id, cert, channel, uid)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Falha ao gerar token RTC com AGORA_APP_CERTIFICATE: {exc}. "
                    "Confira o certificado no console Agora (mesmo projeto do App ID)."
                ) from exc
        elif settings.agora_temp_token:
            token = settings.agora_temp_token
        else:
            raise RuntimeError(
                "Defina AGORA_APP_CERTIFICATE (recomendado; token renovado a cada pedido) "
                "ou AGORA_TEMP_TOKEN (token do console Agora, expira rapido)."
            )

        return AgoraSession(
            app_id=settings.agora_app_id,
            channel=channel,
            token=token,
            uid=uid,
        )
