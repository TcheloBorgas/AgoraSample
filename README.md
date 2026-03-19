# Agora Voice Scheduling Agent

## Português (Brasil)
### Objetivo
Este projeto implementa um agente de voz de agendamento com **Agora Conversational AI Engine (CAE)**, **Agora RTC**, **MCP**, **FastAPI**, **MongoDB** e **Google Calendar**.

### Tecnologias
- Backend: `Python 3.11`, `FastAPI`, `Uvicorn`, `Pydantic`, `httpx`
- Dados: `MongoDB` (`pymongo`)
- Agenda: `Google Calendar API`
- Voz/IA: `Agora RTC`, `Agora CAE` (ASR/LLM/TTS), `SpeechRecognition` (fallback)
- Frontend: `HTML`, `Tailwind`, `JavaScript` com streaming SSE

### Requisitos do desafio (status)
- Construir um voice agent: **Cumprido**
- Usar Agora Conversational AI Engine: **Cumprido** (precisa chave TTS válida no `.env`)
- Caso de uso aberto (appointment scheduling): **Cumprido**
- Orquestração com MCP: **Cumprido**

### Como rodar
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
Abra `http://127.0.0.1:8000`.

### Estrutura
- `app/`: backend completo
- `web/`: interface de voz/chat
- `scripts/`: scripts de teste/simulação
- `docs/`: documentação técnica
- `data/`: dados locais (tokens)

---

## English
### Goal
This project delivers a scheduling voice agent using **Agora CAE**, **Agora RTC**, **MCP**, **FastAPI**, **MongoDB**, and **Google Calendar**.

### Challenge checklist
- Build a voice agent: **Done**
- Use Agora Conversational AI Engine: **Done** (requires valid TTS key in `.env`)
- Open-ended use case (appointment scheduling): **Done**
- MCP orchestration: **Done**

### Run
```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

---

## Español
### Objetivo
Este proyecto implementa un agente de voz para agenda usando **Agora CAE**, **Agora RTC**, **MCP**, **FastAPI**, **MongoDB** y **Google Calendar**.

### Estado de requisitos
- Agente de voz: **Cumplido**
- Uso de Agora CAE: **Cumplido** (requiere clave TTS válida)
- Caso de uso libre (agenda): **Cumplido**
- Orquestación MCP: **Cumplido**
