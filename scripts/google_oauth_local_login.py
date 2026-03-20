"""
Login Google Calendar no PC (abre o browser). Gera o ficheiro configurado em GOOGLE_TOKEN_FILE
(por defeito data/google_token.json). Copie o conteúdo desse ficheiro para GOOGLE_TOKEN_JSON no Render.

Uso (na raiz do repositório):
  python scripts/google_oauth_local_login.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402

from app.adapters.google_calendar_client import (  # noqa: E402
    _load_oauth_client_config_from_env_value,
    _resolve_google_client_secret_path,
)
from app.core.config import settings  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _load_installed_client_config() -> dict:
    raw = (settings.google_client_secret_json or "").strip()
    if raw:
        loaded = _load_oauth_client_config_from_env_value(raw)
        if "installed" not in loaded and "web" not in loaded:
            raise SystemExit("O JSON em GOOGLE_CLIENT_SECRET_JSON deve ter a chave 'installed' (cliente Desktop).")
        return loaded
    path = _resolve_google_client_secret_path()
    if not path:
        raise SystemExit(
            "Não encontrei credenciais OAuth. No .env defina GOOGLE_CLIENT_SECRET_JSON=... "
            f"ou coloque o ficheiro em {settings.google_client_secret_file} na raiz do projeto."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    cfg = _load_installed_client_config()
    print("A abrir o browser para autorizar o Google Calendar…")
    flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
    creds = flow.run_local_server(port=0)
    out = Path(settings.google_token_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(creds.to_json(), encoding="utf-8")
    print()
    print("Pronto.")
    print(f"  Token guardado em: {out.resolve()}")
    print()
    print("No Render: crie GOOGLE_TOKEN_JSON e cole o conteúdo inteiro desse ficheiro (uma linha).")
    print("Mantenha GOOGLE_CLIENT_SECRET_JSON igual ao que usou aqui.")


if __name__ == "__main__":
    main()
