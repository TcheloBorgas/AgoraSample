from __future__ import annotations

from app.services.container import get_proactive_suggestion_service


def main() -> None:
    service = get_proactive_suggestion_service()
    suggestions = service.suggest(
        session_id="test-session-proactive",
        user_id="local-user",
        language="pt",
        trigger="session_start",
    )
    print(f"proactive_suggestions_count={len(suggestions)}")
    for item in suggestions:
        print(f"- key={item.key} score={item.score} reason={item.reason}")


if __name__ == "__main__":
    main()
