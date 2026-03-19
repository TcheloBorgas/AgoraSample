from datetime import datetime, timedelta

from app.repositories.preference_repository import PreferenceRepository


class PrioritizationService:
    def __init__(self, preferences: PreferenceRepository) -> None:
        self.preferences = preferences

    def update_with_meeting(self, user_id: str, start: datetime, participants: list[str]) -> None:
        self.preferences.touch_slot(user_id, start.hour)
        self.preferences.add_participants(user_id, participants)

    def suggest_preferred_slots(self, user_id: str, base_date: datetime) -> list[datetime]:
        pref = self.preferences.get(user_id)
        slots = pref.get("preferred_slots", {})
        if not slots:
            return []

        sorted_hours = sorted(slots.items(), key=lambda item: item[1], reverse=True)
        suggestions = []
        for hour, _count in sorted_hours[:3]:
            candidate = base_date.replace(hour=int(hour), minute=0, second=0, microsecond=0)
            if candidate < datetime.now():
                candidate += timedelta(days=1)
            suggestions.append(candidate)
        return suggestions
