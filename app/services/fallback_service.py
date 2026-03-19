class FallbackService:
    def clarify_missing(self, intent: str, missing_fields: list[str], language: str) -> str:
        if language == "pt":
            if "start" in missing_fields:
                return "Perfeito. Qual horario voce prefere para essa reuniao?"
            if "target_meeting" in missing_fields:
                return "Pode me dizer qual reuniao voce quer usar? Se puder, cite horario ou participantes."
            if "new_start" in missing_fields:
                return "Certo. Para qual novo horario voce deseja reagendar?"
            return "Pode me explicar um pouco melhor o que voce deseja fazer com essa reuniao?"

        if language == "es":
            if "start" in missing_fields:
                return "Perfecto. A que hora prefieres esta reunion?"
            if "target_meeting" in missing_fields:
                return "Puedes decirme cual reunion quieres usar? Si puedes, menciona horario o participantes."
            if "new_start" in missing_fields:
                return "Entendido. Para que nuevo horario deseas reagendar?"
            return "Puedes explicarme un poco mejor lo que deseas hacer con esta reunion?"

        if "start" in missing_fields:
            return "What time do you prefer for this meeting?"
        if "target_meeting" in missing_fields:
            return "Which meeting should I use? Please mention time or participants."
        if "new_start" in missing_fields:
            return "What is the new time for the reschedule?"
        return "Could you clarify your meeting request?"

    def unknown_intent(self, language: str) -> str:
        if language == "pt":
            return "Nao entendi completamente. Voce quer criar, consultar, reagendar ou cancelar uma reuniao?"
        if language == "es":
            return "No entendi completamente. Quieres crear, consultar, reagendar o cancelar una reunion?"
        return "I did not fully understand. Do you want to create, list, reschedule, or cancel a meeting?"
