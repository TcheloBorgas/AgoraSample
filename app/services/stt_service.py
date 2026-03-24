from __future__ import annotations

import io

import speech_recognition as sr


class STTService:
    def __init__(self) -> None:
        self.recognizer = sr.Recognizer()
        # Sem dynamic_energy_threshold: com WAV curto do browser, o limiar dinâmico pode cortar fala válida.

    def transcribe_wav(self, wav_bytes: bytes, language_hint: str = "pt-BR") -> str:
        with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
            audio = self.recognizer.record(source)
        return self.recognizer.recognize_google(audio, language=language_hint)
