import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.routers.cae_router import router as cae_router
from app.routers.conversation_router import router as conversation_router
from app.routers.system_router import router as system_router

configure_logging()

_log = logging.getLogger(__name__)
_log.info(
    "CAE TTS resolvido: AGORA_CAE_TTS_VENDOR=%r | elevenlabs_key=%s openai_tts_key=%s azure_tts=%s",
    settings.agora_cae_tts_vendor,
    "sim" if (settings.agora_cae_tts_elevenlabs_key or "").strip() else "nao",
    "sim" if (settings.agora_cae_tts_openai_key or "").strip() else "nao",
    "sim"
    if (settings.agora_cae_tts_azure_key or "").strip() and (settings.agora_cae_tts_azure_region or "").strip()
    else "nao",
)

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def ensure_utf8_charset(request, call_next):
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if ct.startswith("application/json") and "charset" not in ct.lower():
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversation_router)
app.include_router(system_router)
app.include_router(cae_router)

web_dir = Path(__file__).resolve().parents[1] / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
# up