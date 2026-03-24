import re


class LanguageService:
    EN_HINTS = (
        "schedule",
        "meeting",
        "cancel",
        "reschedule",
        "tomorrow",
        "today",
        "with",
        "appointment",
        "calendar",
        "book",
        "available",
        "next week",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "am",
        "pm",
        "at ",
    )
    PT_HINTS = ("agende", "reuniao", "marque", "reagende", "amanha", "hoje", "compromisso", "manha", "horario", "horário")
    ES_HINTS = ("agenda", "reunion", "cancela", "reagenda", "manana", "mañana", "compromiso", "viernes", "tengo")

    def detect(self, text: str, fallback: str = "pt") -> str:
        lowered = text.lower()
        en_score = sum(1 for w in self.EN_HINTS if w in lowered)
        pt_score = sum(1 for w in self.PT_HINTS if w in lowered)
        es_score = sum(1 for w in self.ES_HINTS if w in lowered)

        if re.search(r"[ãõç]", lowered):
            pt_score += 2
        if re.search(r"[ñ¿¡]", lowered):
            es_score += 2
        # «é», «as 10» etc. são comuns em PT; não empurrar para ES só por vogal aguda.
        if re.search(r"[áéíóú]", lowered) and not re.search(r"[ãõç]", lowered):
            if not re.search(r"\b(as|às)\s+\d", lowered):
                es_score += 1

        best = max(en_score, pt_score, es_score)
        if best == 0:
            return fallback
        if es_score == best and es_score > en_score and es_score > pt_score:
            return "es"
        if en_score > pt_score:
            return "en"
        if pt_score > en_score:
            return "pt"
        return fallback

    def in_language(self, pt_text: str, en_text: str, language: str, es_text: str | None = None) -> str:
        if language == "es":
            return es_text or en_text
        return pt_text if language == "pt" else en_text
