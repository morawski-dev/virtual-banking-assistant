"""JSON-over-WebSocket serializer for the chat (S2) pipeline.

Translates between JSON text frames (browser ↔ bot) and pipecat Frame objects.

Client → Server:
    {"type": "user_message", "text": "..."}

Server → Client (streaming, via OutputTransportMessageUrgentFrame):
    {"type": "assistant_start"}
    {"type": "assistant_token", "text": "..."}
    {"type": "assistant_end"}
    {"type": "session_closing"}

Note: LLMTextFrame is a DataFrame that BaseOutputTransport drops (no media sender).
ChatMessageInjector in bot_webchat.py converts LLM frames to OutputTransportMessageUrgentFrame
before they reach the transport, so this serializer only needs to handle that type.
"""

import json
import time

from pipecat.frames.frames import OutputTransportMessageUrgentFrame, TranscriptionFrame
from pipecat.serializers.base_serializer import FrameSerializer


class ChatJSONSerializer(FrameSerializer):
    async def serialize(self, frame) -> str | bytes | None:
        if self.should_ignore_frame(frame):
            return None
        if isinstance(frame, OutputTransportMessageUrgentFrame):
            msg = frame.message
            if isinstance(msg, dict):
                return json.dumps(msg, ensure_ascii=False)
        return None

    async def deserialize(self, data: str | bytes) -> TranscriptionFrame | None:
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        try:
            msg = json.loads(data)
        except Exception:
            return None
        if msg.get("type") == "user_message":
            text = msg.get("text", "").strip()
            if not text:
                return None
            return TranscriptionFrame(
                text=text,
                user_id="web",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            )
        return None
