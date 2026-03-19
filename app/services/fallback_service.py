# -*- coding: utf-8 -*-
class FallbackService:
    def clarify_missing(self, intent: str, missing_fields: list[str], language: str) -> str:
        if language == "pt":
            if "organizer_name" in missing_fields:
                return "Para agendar com segurança, qual é o seu nome completo?"
            if "organizer_email" in missing_fields:
                return "Qual é o seu e-mail para o convite da reunião?"
            if "title" in missing_fields:
                return "Qual é o assunto desta reunião? Esse texto será o nome do evento no calendário (por exemplo: Alinhamento comercial, Revisão de sprint)."
            if "start" in missing_fields:
                return "Em qual data e horário você quer a reunião? Por exemplo: amanhã às 15h ou 19/03 14:30."
            if "target_meeting" in missing_fields:
                return "Pode me dizer qual reunião você quer usar? Se puder, cite horário ou participantes."
            if "new_start" in missing_fields:
                return "Certo. Para qual novo horário você deseja reagendar?"
            return "Pode me explicar um pouco melhor o que você deseja fazer com essa reunião?"

        if language == "es":
            if "organizer_name" in missing_fields:
                return "Para agendar con claridad, ¿cuál es tu nombre completo?"
            if "organizer_email" in missing_fields:
                return "¿Cuál es tu correo para la invitación?"
            if "title" in missing_fields:
                return "¿Cuál es el asunto o título de esta reunión?"
            if "start" in missing_fields:
                return "¿En qué fecha y hora quieres la reunión? Por ejemplo: mañana a las 15 o 19/03 14:30."
            if "target_meeting" in missing_fields:
                return "¿Puedes decirme cuál reunión quieres usar? Si puedes, menciona horario o participantes."
            if "new_start" in missing_fields:
                return "Entendido. ¿Para qué nuevo horario deseas reagendar?"
            return "¿Puedes explicarme un poco mejor lo que deseas hacer con esta reunión?"

        if "organizer_name" in missing_fields:
            return "To schedule this properly, what is your full name?"
        if "organizer_email" in missing_fields:
            return "What email should I use for the calendar invite?"
        if "title" in missing_fields:
            return "What is the subject or title of this meeting? It will appear as the event name in the calendar."
        if "start" in missing_fields:
            return "What date and time should the meeting be? For example: tomorrow at 3 PM or 2026-03-19 19:00."
        if "target_meeting" in missing_fields:
            return "Which meeting should I use? Please mention time or participants."
        if "new_start" in missing_fields:
            return "What is the new time for the reschedule?"
        return "Could you clarify your meeting request?"

    def misplaced_confirm_yes_during_booking(self, missing_fields: list[str], language: str) -> str:
        """User said 'yes' but there is no pending_calendar confirmation — only missing slot fields."""
        next_q = self.clarify_missing("create_meeting", missing_fields, language)
        if language == "pt":
            hint = (
                "Ainda não há confirmação final da reunião no calendário — primeiro preciso dos dados acima. "
                "Quando eu mostrar o resumo completo e perguntar se pode confirmar, use sim ou não."
            )
        elif language == "es":
            hint = (
                "Todavía no hay confirmación final en el calendario: primero necesito esos datos. "
                "Cuando muestre el resumen y pregunte si confirmas, entonces di sí o no."
            )
        else:
            hint = (
                "There is no final calendar confirmation yet — I still need the details above first. "
                "When I show the full summary and ask you to confirm, then say yes or no."
            )
        return f"{next_q}\n\n{hint}"

    def unknown_intent(self, language: str) -> str:
        if language == "pt":
            return "Não entendi completamente. Você quer criar, consultar, reagendar ou cancelar uma reunião?"
        if language == "es":
            return "No entendí completamente. ¿Quieres crear, consultar, reagendar o cancelar una reunión?"
        return "I did not fully understand. Do you want to create, list, reschedule, or cancel a meeting?"
