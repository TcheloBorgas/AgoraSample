from dataclasses import dataclass

from app.core.config import settings


@dataclass
class AgoraSession:
    app_id: str
    channel: str
    token: str
    uid: int


class AgoraClient:
    def build_session(self, session_id: str) -> AgoraSession:
        if not settings.agora_app_id:
            raise RuntimeError("AGORA_APP_ID nao configurado")

        channel = settings.agora_fixed_channel or f"{settings.agora_channel_prefix}-{session_id}"
        uid = settings.agora_uid
        if uid <= 0:
            # Evita UID dinamico (0), que pode gerar remote_rtc_uid invalido no CAE.
            uid = 10001
        if uid > 2_147_483_647:
            uid = uid % 2_147_483_647

        if not settings.agora_temp_token:
            raise RuntimeError(
                "AGORA_TEMP_TOKEN nao configurado. Para o MVP, gere um token temporario no console da Agora."
            )

        return AgoraSession(
            app_id=settings.agora_app_id,
            channel=channel,
            token=settings.agora_temp_token,
            uid=uid,
        )
