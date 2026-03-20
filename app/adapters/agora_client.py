import time
from dataclasses import dataclass

from app.core.config import settings


@dataclass
class AgoraSession:
    app_id: str
    channel: str
    token: str
    uid: int


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

        channel = settings.agora_fixed_channel or f"{settings.agora_channel_prefix}-{session_id}"
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
