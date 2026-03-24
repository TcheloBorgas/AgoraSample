# -*- coding: utf-8 -*-
"""
Pedidos em falta de dados: tom conversacional (pedir o que falta).
Erros explícitos: unknown_intent, falhas de LLM, etc.
"""


def _missing_phrases_pt(fields: list[str]) -> list[str]:
    order = (
        "organizer_name",
        "organizer_email",
        "title",
        "start",
        "duration_minutes",
        "participants",
        "target_meeting",
        "new_start",
    )
    labels = {
        "organizer_name": "o seu nome completo",
        "organizer_email": "o seu e-mail (para o convite)",
        "title": "o assunto da reunião (nome do evento no calendário)",
        "start": "a data e o horário",
        "duration_minutes": "a duração em minutos",
        "participants": "os participantes por e-mail (se houver)",
        "target_meeting": "qual reunião (título, horário ou participantes)",
        "new_start": "o novo horário para reagendar",
    }
    seen = set()
    out: list[str] = []
    for key in order:
        if key in fields and key not in seen:
            seen.add(key)
            out.append(labels.get(key, key))
    for f in fields:
        if f not in seen:
            out.append(labels.get(f, f))
    return out


def _missing_phrases_es(fields: list[str]) -> list[str]:
    order = (
        "organizer_name",
        "organizer_email",
        "title",
        "start",
        "duration_minutes",
        "participants",
        "target_meeting",
        "new_start",
    )
    labels = {
        "organizer_name": "tu nombre completo",
        "organizer_email": "tu correo electrónico (para la invitación)",
        "title": "el asunto o título de la reunión",
        "start": "la fecha y la hora",
        "duration_minutes": "la duración en minutos",
        "participants": "los participantes por correo (si los hay)",
        "target_meeting": "qué reunión (título, hora o participantes)",
        "new_start": "la nueva hora para reagendar",
    }
    seen = set()
    out: list[str] = []
    for key in order:
        if key in fields and key not in seen:
            seen.add(key)
            out.append(labels.get(key, key))
    for f in fields:
        if f not in seen:
            out.append(labels.get(f, f))
    return out


def _missing_phrases_en(fields: list[str]) -> list[str]:
    order = (
        "organizer_name",
        "organizer_email",
        "title",
        "start",
        "duration_minutes",
        "participants",
        "target_meeting",
        "new_start",
    )
    labels = {
        "organizer_name": "your full name",
        "organizer_email": "your email (for the invite)",
        "title": "the meeting subject/title (event name in the calendar)",
        "start": "the date and time",
        "duration_minutes": "the duration in minutes",
        "participants": "participant emails (if any)",
        "target_meeting": "which meeting (title, time, or participants)",
        "new_start": "the new time for the reschedule",
    }
    seen = set()
    out: list[str] = []
    for key in order:
        if key in fields and key not in seen:
            seen.add(key)
            out.append(labels.get(key, key))
    for f in fields:
        if f not in seen:
            out.append(labels.get(f, f))
    return out


def _join_need_list(phrases: list[str], language: str) -> str:
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    if language == "en":
        if len(phrases) == 2:
            return f"{phrases[0]} and {phrases[1]}"
        return ", ".join(phrases[:-1]) + f", and {phrases[-1]}"
    # pt / es — usar «e» / «y»
    if len(phrases) == 2:
        conj = " e " if language == "pt" else " y "
        return f"{phrases[0]}{conj}{phrases[1]}"
    conj = ", " if language == "pt" else ", "
    last = " e " if language == "pt" else " y "
    return conj.join(phrases[:-1]) + last + phrases[-1]


class FallbackService:
    def clarify_missing(self, intent: str, missing_fields: list[str], language: str) -> str:
        fields = [f for f in (missing_fields or []) if f]
        if not fields:
            if language == "es":
                return "¿Puedes concretar un poco más lo que necesitas con esta reunión?"
            if language == "en":
                return "Could you clarify what you would like to do with this meeting?"
            return "Pode detalhar um pouco mais o que deseja fazer com esta reunião?"

        # Vários campos: um único pedido claro (ex.: horário já dito + falta nome/e-mail/assunto).
        if len(fields) > 1:
            if language == "es":
                need = _join_need_list(_missing_phrases_es(fields), "es")
                return f"Para seguir con la intención «{intent}», aún necesito: {need}."
            if language == "en":
                need = _join_need_list(_missing_phrases_en(fields), "en")
                return f"To continue with «{intent}», I still need: {need}."
            need = _join_need_list(_missing_phrases_pt(fields), "pt")
            return f"Para continuar com o pedido («{intent}»), ainda preciso de: {need}."

        # Um campo: pergunta direcionada (melhor fluxo passo a passo).
        f0 = fields[0]
        if language == "es":
            if f0 == "organizer_name":
                return "Para agendar con claridad, ¿cuál es tu nombre completo?"
            if f0 == "organizer_email":
                return "¿Cuál es tu correo para la invitación al calendario?"
            if f0 == "title":
                return "¿Cuál es el asunto o título de esta reunión?"
            if f0 == "start":
                return "¿En qué fecha y hora quieres la reunión? Por ejemplo: mañana a las 15 o 19/03 14:30."
            if f0 == "target_meeting":
                return "¿Puedes decirme cuál reunión quieres usar? Si puedes, menciona horario o participantes."
            if f0 == "new_start":
                return "Entendido. ¿Para qué nuevo horario deseas reagendar?"
            return "¿Puedes explicarme un poco mejor lo que deseas hacer con esta reunión?"

        if language == "en":
            if f0 == "organizer_name":
                return "To schedule this properly, what is your full name?"
            if f0 == "organizer_email":
                return "What email should I use for the calendar invite?"
            if f0 == "title":
                return "What is the subject or title of this meeting? It will appear as the event name in the calendar."
            if f0 == "start":
                return "What date and time should the meeting be? For example: tomorrow at 3 PM or 2026-03-19 19:00."
            if f0 == "target_meeting":
                return "Which meeting should I use? Please mention time or participants."
            if f0 == "new_start":
                return "What is the new time for the reschedule?"
            return "Could you clarify your meeting request?"

        if f0 == "organizer_name":
            return "Para agendar com segurança, qual é o seu nome completo?"
        if f0 == "organizer_email":
            return "Qual é o seu e-mail para o convite da reunião?"
        if f0 == "title":
            return "Qual é o assunto desta reunião? Esse texto será o nome do evento no calendário (por exemplo: Alinhamento comercial, Revisão de sprint)."
        if f0 == "start":
            return "Em qual data e horário você quer a reunião? Por exemplo: amanhã às 15h ou 19/03 14:30."
        if f0 == "target_meeting":
            return "Pode me dizer qual reunião você quer usar? Se puder, cite horário ou participantes."
        if f0 == "new_start":
            return "Certo. Para qual novo horário você deseja reagendar?"
        return "Pode me explicar um pouco melhor o que você deseja fazer com essa reunião?"

    def misplaced_confirm_yes_during_booking(self, missing_fields: list[str], language: str) -> str:
        """Utilizador disse 'sim' mas ainda faltam dados do rascunho — pedir o que falta, sem tratar como erro grosseiro."""
        next_q = self.clarify_missing("create_meeting", missing_fields, language)
        if language == "es":
            hint = (
                "Aún no hay confirmación final en el calendario: primero necesito esos datos. "
                "Cuando muestre el resumen y pregunte si confirmas, entonces di sí o no."
            )
        elif language == "en":
            hint = (
                "There is no final calendar confirmation yet — I still need the details above first. "
                "When I show the full summary and ask you to confirm, then say yes or no."
            )
        else:
            hint = (
                "Ainda não há confirmação final da reunião no calendário — primeiro preciso dos dados acima. "
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

    def llm_empty_response_error(self, language: str, provider: str) -> str:
        if language == "es":
            return f"Error: el servicio LLM ({provider}) devolvió una respuesta vacía."
        if language == "en":
            return f"Error: the LLM service ({provider}) returned an empty response."
        return f"Erro: o serviço LLM ({provider}) devolveu uma resposta vazia."

    def llm_call_failed_error(self, language: str, provider: str, exc: BaseException | None = None) -> str:
        tail = ""
        if exc is not None:
            msg = str(exc).strip().replace("\n", " ")[:160]
            if msg:
                tail = f" Causa: {type(exc).__name__}: {msg}"
        if language == "es":
            return f"Error: falló la llamada al servicio LLM ({provider}).{tail}"
        if language == "en":
            return f"Error: call to LLM service ({provider}) failed.{tail}"
        return f"Erro: falhou a chamada ao serviço LLM ({provider}).{tail}"
