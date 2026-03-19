from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncGenerator

from app.schemas.api import AssistantResponse


class ResponseStreamingService:
    """Best-effort streaming for text responses via SSE."""

    def split_chunks(self, text: str) -> list[str]:
        parts = [part.strip() for part in re.split(r"(?<=[\.\!\?\n])\s+", text) if part.strip()]
        if not parts:
            return [text]
        return parts

    async def stream_response(self, response: AssistantResponse, chunk_delay_ms: int = 130) -> AsyncGenerator[str, None]:
        chunks = self.split_chunks(response.response_text)
        for idx, chunk in enumerate(chunks):
            payload = {
                "type": "chunk",
                "index": idx,
                "text": chunk,
                "is_final_chunk": idx == len(chunks) - 1,
            }
            yield f"data: {json.dumps(payload, ensure_ascii=True)}\n\n"
            await asyncio.sleep(chunk_delay_ms / 1000)

        final_payload = {
            "type": "final",
            "response": response.model_dump(mode="json"),
        }
        yield f"data: {json.dumps(final_payload, ensure_ascii=True)}\n\n"

