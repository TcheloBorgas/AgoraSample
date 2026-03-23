from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Agora Voice Scheduling Assistant"
    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    timezone: str = "America/Sao_Paulo"

    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "voice_assistant_mvp"
    # true só depois de reativar pymongo em app/core/database.py
    use_mongo: bool = Field(default=False, validation_alias="USE_MONGO")


    # Ficheiro local (nome padrão alinhado com o Secret File típico). Em produção use GOOGLE_CLIENT_SECRET_JSON.
    google_client_secret_file: str = "google-oauth.json"
    # JSON OAuth: texto JSON (uma linha, começa com "{") OU caminho para ficheiro (ex.: /etc/secrets/google-oauth.json).
    google_client_secret_json: str = ""
    google_token_file: str = "data/google_token.json"
    # Token OAuth já autorizado (conteúdo de google_token.json), para servidores sem browser.
    google_token_json: str = ""
    google_calendar_id: str = "primary"

    agora_app_id: str = ""
    agora_app_certificate: str = Field(default="", validation_alias="AGORA_APP_CERTIFICATE")
    agora_temp_token: str = ""
    agora_channel_prefix: str = "assistant-voice"
    agora_fixed_channel: str = ""
    agora_uid: int = 0
    agora_cae_customer_id: str = Field(default="", validation_alias="AGORA_CAE_CUSTOMER_ID")
    agora_cae_customer_secret: str = Field(default="", validation_alias="AGORA_CAE_CUSTOMER_SECRET")
    # Evitar colisao com AGORA_UID por defeito (10001): agente e utilizador nao podem partilhar o mesmo UID no RTC.
    agora_cae_agent_uid: int = Field(default=20001, validation_alias="AGORA_CAE_AGENT_UID")
    agora_cae_agent_name_prefix: str = Field(default="assistant-cae", validation_alias="AGORA_CAE_AGENT_NAME_PREFIX")
    agora_cae_enable_tools: bool = Field(default=True, validation_alias="AGORA_CAE_ENABLE_TOOLS")
    agora_cae_public_base_url: str = Field(default="", validation_alias="AGORA_CAE_PUBLIC_BASE_URL")
    agora_cae_external_llm_url: str = Field(default="", validation_alias="AGORA_CAE_EXTERNAL_LLM_URL")
    agora_cae_external_llm_api_key: str = Field(default="", validation_alias="AGORA_CAE_EXTERNAL_LLM_API_KEY")
    agora_cae_external_llm_model: str = Field(default="", validation_alias="AGORA_CAE_EXTERNAL_LLM_MODEL")
    agora_cae_mcp_endpoint: str = Field(default="", validation_alias="AGORA_CAE_MCP_ENDPOINT")
    agora_cae_tts_vendor: str = Field(default="elevenlabs", validation_alias="AGORA_CAE_TTS_VENDOR")
    agora_cae_tts_azure_key: str = Field(default="", validation_alias="AGORA_CAE_TTS_AZURE_KEY")
    agora_cae_tts_azure_region: str = Field(default="", validation_alias="AGORA_CAE_TTS_AZURE_REGION")
    agora_cae_tts_openai_key: str = Field(default="", validation_alias="AGORA_CAE_TTS_OPENAI_KEY")
    agora_cae_tts_openai_model: str = Field(default="gpt-4o-mini-tts", validation_alias="AGORA_CAE_TTS_OPENAI_MODEL")
    agora_cae_tts_openai_voice: str = Field(default="coral", validation_alias="AGORA_CAE_TTS_OPENAI_VOICE")
    agora_cae_tts_elevenlabs_key: str = Field(default="", validation_alias="AGORA_CAE_TTS_ELEVENLABS_KEY")
    agora_cae_tts_elevenlabs_voice_id: str = Field(default="pNInz6obpgDQGcFmaJgB", validation_alias="AGORA_CAE_TTS_ELEVENLABS_VOICE_ID")
    agora_cae_tts_elevenlabs_model_id: str = Field(default="eleven_flash_v2_5", validation_alias="AGORA_CAE_TTS_ELEVENLABS_MODEL_ID")
    agora_cae_enabled: bool = Field(default=True, validation_alias="AGORA_CAE_ENABLED")
    ollama_enabled: bool = Field(default=False, validation_alias="OLLAMA_ENABLED")
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", validation_alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="mistral", validation_alias="OLLAMA_MODEL")

    # API estilo OpenAI (Groq tier grátis, OpenRouter, Gemini compat, etc.) — usada no fallback de intenção unknown
    llm_openai_compat_base_url: str = Field(default="", validation_alias="LLM_OPENAI_COMPAT_BASE_URL")
    llm_openai_compat_api_key: str = Field(default="", validation_alias="LLM_OPENAI_COMPAT_API_KEY")
    llm_openai_compat_model: str = Field(default="", validation_alias="LLM_OPENAI_COMPAT_MODEL")
    llm_openai_compat_timeout_seconds: int = Field(default=60, validation_alias="LLM_OPENAI_COMPAT_TIMEOUT")

    # Google AI Studio (grátis): uma chave ativa LLM OpenAI-compat sem Groq/Ollama
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", validation_alias="GEMINI_MODEL")

    short_term_memory_limit: int = 20

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
