# -*- coding: utf-8 -*-
"""Mensagens quando um ramo automático não consegue concluir — sempre como erro explícito."""


def _fields_list_pt(fields: list[str]) -> str:
    labels = {
        "organizer_name": "nome completo do organizador",
        "organizer_email": "e-mail do organizador",
        "title": "assunto/título da reunião",
        "start": "data e horário de início",
        "target_meeting": "qual reunião (título, horário ou participantes)",
        "new_start": "novo horário para reagendar",
        "duration_minutes": "duração em minutos",
        "participants": "participantes",
    }
    return ", ".join(labels.get(f, f) for f in fields)


def _fields_list_es(fields: list[str]) -> str:
    labels = {
        "organizer_name": "nombre completo del organizador",
        "organizer_email": "correo del organizador",
        "title": "asunto/título de la reunión",
        "start": "fecha y hora de inicio",
        "target_meeting": "qué reunión (título, hora o participantes)",
        "new_start": "nueva hora para reagendar",
        "duration_minutes": "duración en minutos",
        "participants": "participantes",
    }
    return ", ".join(labels.get(f, f) for f in fields)


def _fields_list_en(fields: list[str]) -> str:
    labels = {
        "organizer_name": "organizer full name",
        "organizer_email": "organizer email",
        "title": "meeting title/subject",
        "start": "start date and time",
        "target_meeting": "which meeting (title, time, or participants)",
        "new_start": "new time for reschedule",
        "duration_minutes": "duration in minutes",
        "participants": "participants",
    }
    return ", ".join(labels.get(f, f) for f in fields)


class FallbackService:
    def clarify_missing(self, intent: str, missing_fields: list[str], language: str) -> str:
        if language == "es":
            fl = _fields_list_es(missing_fields)
            return (
                f"Error: no se puede ejecutar la intención «{intent}»; faltan datos obligatorios: {fl}."
            )
        if language == "en":
            fl = _fields_list_en(missing_fields)
            return f"Error: cannot execute intent «{intent}»; missing required fields: {fl}."
        fl = _fields_list_pt(missing_fields)
        return f"Erro: não é possível executar a intenção «{intent}»; faltam dados obrigatórios: {fl}."

    def misplaced_confirm_yes_during_booking(self, missing_fields: list[str], language: str) -> str:
        """Utilizador disse «sim» sem confirmação pendente no calendário e com rascunho incompleto."""
        base = self.clarify_missing("create_meeting", missing_fields, language)
        if language == "es":
            extra = " Contexto: dijiste confirmación pero no hay reserva pendiente en el calendario y el borrador está incompleto."
        elif language == "en":
            extra = " Context: you sent a confirmation but there is no pending calendar confirmation and the draft is incomplete."
        else:
            extra = " Contexto: foi enviada uma confirmação, mas não há confirmação de calendário pendente e o rascunho está incompleto."
        return base + extra

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
