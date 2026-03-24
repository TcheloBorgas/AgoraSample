import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
import speech_recognition as sr

from app.adapters.agora_client import AgoraClient
from app.core.config import settings
from app.core.metrics import metrics
from app.schemas.api import AgoraSessionResponse
from app.services.container import get_agora_client, get_memory_service, get_stt_service
from app.services.memory_service import MemoryService
from app.services.stt_service import STTService

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def healthcheck():
    return {"status": "ok"}


@router.get("/metrics")
def get_metrics():
    return metrics.snapshot()


@router.get("/sessions/{session_id}/history")
def get_history(session_id: str, memory: MemoryService = Depends(get_memory_service)):
    state = memory.get_session(session_id=session_id, user_id="local-user")
    return {"session_id": session_id, "short_memory": state.short_memory}


@router.get("/agora/session/{session_id}", response_model=AgoraSessionResponse)
def get_agora_session(session_id: str, agora: AgoraClient = Depends(get_agora_client)):
    try:
        result = agora.build_session(session_id)
        return AgoraSessionResponse(
            app_id=result.app_id,
            channel=result.channel,
            token=result.token,
            uid=result.uid,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/stt/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = Form("pt-BR"),
    stt: STTService = Depends(get_stt_service),
):
    try:
        data = await file.read()
        text = stt.transcribe_wav(data, language_hint=language)
        return {"text": text, "language": language}
    except sr.UnknownValueError:
        return {
            "text": "Erro: o serviço de reconhecimento de voz não conseguiu extrair texto do áudio (sinal ilegível ou demasiado curto).",
            "language": language,
            "reason": "unintelligible",
        }
    except sr.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Falha no provedor STT: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/agora/debug")
def get_agora_debug(agora: AgoraClient = Depends(get_agora_client)):
    """
    Endpoint de consistencia para validar se configuracao local parece correta
    antes de tentar conectar via browser SDK.
    """
    try:
        session = agora.build_session("debug-session")
        app_id_ok = bool(re.fullmatch(r"[a-fA-F0-9]{32}", session.app_id))
        channel_ok = bool(session.channel and len(session.channel) <= 64)
        uid_ok = isinstance(session.uid, int) and session.uid >= 0
        token_ok = bool(session.token and len(session.token) > 40)

        warnings: list[str] = []
        if not app_id_ok:
            warnings.append("AGORA_APP_ID deve ter 32 caracteres hexadecimais.")
        if not channel_ok:
            warnings.append("Canal invalido (vazio ou acima de 64 caracteres).")
        if not uid_ok:
            warnings.append("UID invalido, use inteiro >= 0.")
        if not token_ok:
            warnings.append("Token vazio/curto; defina AGORA_APP_CERTIFICATE ou AGORA_TEMP_TOKEN.")
        fixed = (settings.agora_fixed_channel or "").strip()
        if fixed and not (session.channel == fixed or session.channel.startswith(f"{fixed}-")):
            warnings.append(
                f"Canal efetivo {session.channel!r} deveria usar o prefixo fixo {fixed!r} "
                "(formato esperado: {fixo}-{session_id})."
            )

        return {
            "ok": app_id_ok and channel_ok and uid_ok and token_ok,
            "checks": {
                "app_id_format": app_id_ok,
                "channel_format": channel_ok,
                "uid_format": uid_ok,
                "token_format": token_ok,
            },
            "effective": {
                "app_id": session.app_id,
                "channel": session.channel,
                "uid": session.uid,
                "token_prefix": session.token[:12],
                "token_length": len(session.token),
            },
            "env": {
                "agora_fixed_channel": settings.agora_fixed_channel,
                "agora_channel_prefix": settings.agora_channel_prefix,
                "agora_uid": settings.agora_uid,
            },
            "warnings": warnings,
            "hint": (
                "Preferir AGORA_APP_CERTIFICATE (Console Agora, mesmo projeto do App ID) para tokens que renovam a cada pedido. "
                "AGORA_TEMP_TOKEN expira em minutos. Netlify: defina SCHEDULER_API_BASE para o backend que tem estas variáveis."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
