# -*- coding: utf-8 -*-
"""
Pedidos em falta de dados: tom conversacional (pedir o que falta).
Erros explícitos: unknown_intent, falhas de LLM, etc.
"""


def _first_missing_slot(fields: list[str], intent: str) -> str:
    """Escolhe o próximo campo a pedir (ordem fixa), mesmo que `missing_fields` venha noutra ordem."""
    if not fields:
        return ""
    if intent == "create_meeting":
        order = (
            "organizer_name",
            "organizer_email",
            "title",
            "start",
            "duration_minutes",
            "participants",
        )
    elif intent in {"reschedule_meeting", "cancel_meeting"}:
        order = ("target_meeting", "new_start")
    else:
        return fields[0]
    want = set(fields)
    for key in order:
        if key in want:
            return key
    return fields[0]


def _step_by_step_prefix(language: str) -> str:
    if language == "es":
        return "Vamos paso a paso — una sola respuesta por turno funciona mejor con voz. "
    if language == "en":
        return "Let's go one question at a time — that works better for voice. "
    return "Vamos passo a passo — uma resposta de cada vez funciona melhor por voz. "


class FallbackService:
    def clarify_missing(self, intent: str, missing_fields: list[str], language: str) -> str:
        fields = [f for f in (missing_fields or []) if f]
        if not fields:
            if language == "es":
                return "¿Puedes concretar un poco más lo que necesitas con esta reunión?"
            if language == "en":
                return "Could you clarify what you would like to do with this meeting?"
            return "Pode detalhar um pouco mais o que deseja fazer com esta reunião?"

        f0 = _first_missing_slot(fields, intent)
        prefix = _step_by_step_prefix(language) if len(fields) > 1 else ""
        if language == "es":
            if f0 == "organizer_name":
                return prefix + "Para agendar con claridad, ¿cuál es tu nombre completo?"
            if f0 == "organizer_email":
                return prefix + "¿Cuál es tu correo para la invitación al calendario?"
            if f0 == "title":
                return prefix + "¿Cuál es el asunto o título de esta reunión?"
            if f0 == "start":
                return prefix + "¿En qué fecha y hora quieres la reunión? Por ejemplo: mañana a las 15 o 19/03 14:30."
            if f0 == "duration_minutes":
                return prefix + "¿Cuántos minutos debe durar la reunión? (por ejemplo: 30 o 60.)"
            if f0 == "participants":
                return prefix + "¿Quieres invitar a alguien por correo? Di los correos o di «ninguno»."
            if f0 == "target_meeting":
                return prefix + "¿Puedes decirme cuál reunión quieres usar? Si puedes, menciona horario o participantes."
            if f0 == "new_start":
                return prefix + "Entendido. ¿Para qué nuevo horario deseas reagendar?"
            return prefix + "¿Puedes explicarme un poco mejor lo que deseas hacer con esta reunión?"

        if language == "en":
            if f0 == "organizer_name":
                return prefix + "To schedule this properly, what is your full name?"
            if f0 == "organizer_email":
                return prefix + "What email should I use for the calendar invite?"
            if f0 == "title":
                return prefix + "What is the subject or title of this meeting? It will appear as the event name in the calendar."
            if f0 == "start":
                return prefix + "What date and time should the meeting be? For example: tomorrow at 3 PM or 2026-03-19 19:00."
            if f0 == "duration_minutes":
                return prefix + "How long should the meeting be, in minutes? (e.g. 30 or 60.)"
            if f0 == "participants":
                return prefix + "Should I invite anyone by email? Share their addresses, or say none."
            if f0 == "target_meeting":
                return prefix + "Which meeting should I use? Please mention time or participants."
            if f0 == "new_start":
                return prefix + "What is the new time for the reschedule?"
            return prefix + "Could you clarify your meeting request?"

        if f0 == "organizer_name":
            return prefix + "Para agendar com segurança, qual é o seu nome completo?"
        if f0 == "organizer_email":
            return prefix + "Qual é o seu e-mail para o convite da reunião?"
        if f0 == "title":
            return prefix + "Qual é o assunto desta reunião? Esse texto será o nome do evento no calendário (por exemplo: Alinhamento comercial, Revisão de sprint)."
        if f0 == "start":
            return prefix + "Em qual data e horário você quer a reunião? Por exemplo: amanhã às 15h ou 19/03 14:30."
        if f0 == "duration_minutes":
            return prefix + "Quantos minutos deve durar a reunião? (por exemplo: 30 ou 60.)"
        if f0 == "participants":
            return prefix + "Quer convidar alguém por e-mail? Diga os e-mails ou diga «ninguém»."
        if f0 == "target_meeting":
            return prefix + "Pode me dizer qual reunião você quer usar? Se puder, cite horário ou participantes."
        if f0 == "new_start":
            return prefix + "Certo. Para qual novo horário você deseja reagendar?"
        return prefix + "Pode me explicar um pouco melhor o que você deseja fazer com essa reunião?"

    def misplaced_confirm_yes_during_booking(self, missing_fields: list[str], language: str) -> str:
        """Utilizador disse 'sim' mas ainda faltam dados do rascunho — pedir o que falta, sem tratar como erro grosseiro."""
        next_q = self.clarify_missing("create_meeting", missing_fields, language)
        if language == "es":
            hint = (
                "Aún no hay confirmación en el calendario: primero terminemos los datos, uno por uno. "
                "Cuando muestre el resumen y pregunte si confirmas, entonces di sí o no."
            )
        elif language == "en":
            hint = (
                "The meeting is not booked yet — let's finish the details one question at a time first. "
                "When I show the full summary and ask you to confirm, then say yes or no."
            )
        else:
            hint = (
                "A reunião ainda não está confirmada no calendário — primeiro vamos completar os dados, um de cada vez. "
                "Quando eu mostrar o resumo completo e perguntar se pode confirmar, use sim ou não."
            )
        return f"{next_q}\n\n{hint}"

    def unknown_intent(self, language: str) -> str:
        if language == "es":
            return (
                "Error: el clasificador de intenciones no reconoció un pedido válido (intención «unknown»). "
                "Reformule en crear reunión, listar, reagendar o cancelar."
            )
        if language == "en":
            return (
                "Error: the intent classifier did not recognize a valid request (intent «unknown»). "
                "Rephrase as create, list, reschedule, or cancel a meeting."
            )
        return (
            "Erro: o classificador de intenções não reconheceu um pedido válido (intenção «unknown»). "
            "Reformule como criar, listar, reagendar ou cancelar uma reunião."
        )

    def llm_empty_response_error(self, language: str) -> str:
        if language == "es":
            return "Error: el servicio de modelo devolvió una respuesta vacía."
        if language == "en":
            return "Error: the model service returned an empty response."
        return "Erro: o serviço de modelo devolveu uma resposta vazia."

    def llm_call_failed_error(self, language: str, exc: BaseException | None = None) -> str:
        tail = ""
        if exc is not None:
            msg = str(exc).strip().replace("\n", " ")[:160]
            if msg:
                tail = f" Causa: {type(exc).__name__}: {msg}"
        if language == "es":
            return f"Error: falló la llamada al servicio de modelo.{tail}"
        if language == "en":
            return f"Error: call to the model service failed.{tail}"
        return f"Erro: falhou a chamada ao serviço de modelo.{tail}"
