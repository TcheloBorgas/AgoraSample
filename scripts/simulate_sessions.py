import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AGORA_APP_ID", "dummy-app-id")
os.environ.setdefault("AGORA_TEMP_TOKEN", "dummy-token")

from app.services.container import get_conversation_service  # noqa: E402


def run() -> None:
    service = get_conversation_service()
    scenarios = {
        "sessao-a": [
            "Marque uma reunião amanhã às 15h com joao@empresa.com por 30 minutos",
            "sim",
            "Tenho algum compromisso amanhã?",
            "Marque com a mesma duração da última reunião amanhã às 17h",
            "sim",
        ],
        "session-b": [
            "Schedule a meeting tomorrow at 11am with maria@company.com",
            "yes",
            "Reschedule my meeting today to 6pm",
            "yes",
            "Cancel my meeting with maria",
            "no",
        ],
    }

    for session_id, messages in scenarios.items():
        print(f"\n=== Session {session_id} ===")
        for msg in messages:
            response = service.handle_message(session_id=session_id, user_id="local-user", message=msg)
            print(f"USER: {msg}")
            print(f"BOT: {response.response_text}")


if __name__ == "__main__":
    run()
