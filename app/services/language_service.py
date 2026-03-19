import re


class LanguageService:
    EN_HINTS = ("schedule", "meeting", "cancel", "reschedule", "tomorrow", "today", "with")
    PT_HINTS = ("agende", "reuniao", "marque", "cancel", "reagende", "amanha", "hoje", "com")

    def detect(self, text: str, fallback: str = "pt") -> str:
        lowered = text.lower()
        en_score = sum(1 for w in self.EN_HINTS if w in lowered)
        pt_score = sum(1 for w in self.PT_HINTS if w in lowered)

        if re.search(r"[ãõçáéíóúâêô]", lowered):
            pt_score += 2

        if en_score > pt_score:
            return "en"
        if pt_score > en_score:
            return "pt"
        return fallback

    def in_language(self, pt_text: str, en_text: str, language: str) -> str:
        return pt_text if language == "pt" else en_text
