"""Chat bot entry point for Scenario 2 (web chat).

FastAPI app with:
  GET  /        → web/index.html
  WS   /ws      → chat pipeline (no STT/TTS/audio)
  GET  /healthz → liveness probe

Pipeline shape:
    transport.input() → ChatTurnAdapter → user_aggregator
    → llm → ChatMessageInjector → transport.output() → assistant_aggregator

ChatTurnAdapter wraps each TranscriptionFrame with UserStartedSpeakingFrame /
UserStoppedSpeakingFrame so the LLMUserAggregator (using ExternalUserTurnStrategies)
knows when a text turn begins and ends.

ChatMessageInjector converts LLM text frames to OutputTransportMessageUrgentFrame
so the WebSocket output transport actually delivers them to the client.
(LLMTextFrame is a DataFrame — BaseOutputTransport routes it to _handle_frame where
it is dropped for lack of a media sender. Only SystemFrame subclasses like
OutputTransportMessageUrgentFrame are forwarded through send_message → _write_frame
→ serializer.serialize.)

After the closure_chat node the bot pushes EndFrame to close the WS gracefully.
"""

import os
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies
from pipecat.utils.tracing.setup import setup_tracing
from pipecat_flows import FlowManager

from flows.nodes import create_greeting_chat_node
from serializers.chat_json import ChatJSONSerializer

load_dotenv(override=True)

IS_TRACING_ENABLED = os.getenv("ENABLE_TRACING", "").lower() == "true"

if IS_TRACING_ENABLED:
    setup_tracing(
        service_name="virtual-assistant-chat",
        exporter=OTLPSpanExporter(),
        console_export=bool(os.getenv("OTEL_CONSOLE_EXPORT")),
    )

app = FastAPI(title="Virtual Assistant — Chat S2")

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
app.mount("/static", StaticFiles(directory=_WEB_DIR), name="static")


@app.get("/")
async def index():
    return FileResponse(os.path.join(_WEB_DIR, "index.html"))


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


class ChatTurnAdapter(FrameProcessor):
    """Wraps each incoming TranscriptionFrame with speaking start/stop signals.

    ExternalUserTurnStrategies requires explicit UserStartedSpeakingFrame and
    UserStoppedSpeakingFrame to bracket each user turn. The WS serializer
    returns only TranscriptionFrame; this processor injects the brackets so the
    LLMUserAggregator closes the turn and triggers the LLM.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            await self.push_frame(UserStartedSpeakingFrame())
            await self.push_frame(frame)
            await self.push_frame(UserStoppedSpeakingFrame())
        else:
            await self.push_frame(frame, direction)


class ChatMessageInjector(FrameProcessor):
    """Converts LLM text frames to OutputTransportMessageUrgentFrame for WS delivery.

    LLMTextFrame is a DataFrame; BaseOutputTransport routes it to _handle_frame
    where it is silently dropped (no media sender registered). Only
    OutputTransportMessageUrgentFrame goes through send_message → _write_frame
    → serializer.serialize → WebSocket send.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            await self.push_frame(
                OutputTransportMessageUrgentFrame(message={"type": "assistant_start"})
            )
            await self.push_frame(frame, direction)
        elif isinstance(frame, LLMTextFrame):
            await self.push_frame(
                OutputTransportMessageUrgentFrame(
                    message={"type": "assistant_token", "text": frame.text}
                )
            )
        elif isinstance(frame, LLMFullResponseEndFrame):
            await self.push_frame(
                OutputTransportMessageUrgentFrame(message={"type": "assistant_end"})
            )
            await self.push_frame(frame, direction)
        elif isinstance(frame, EndFrame):
            await self.push_frame(
                OutputTransportMessageUrgentFrame(message={"type": "session_closing"})
            )
            await self.push_frame(frame, direction)
        else:
            await self.push_frame(frame, direction)


async def run_chat_bot(transport: FastAPIWebsocketTransport, conversation_id: str):
    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
    )

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=None,
            user_turn_strategies=ExternalUserTurnStrategies(),
        ),
    )
    user_aggregator, assistant_aggregator = context_aggregator

    chat_turn_adapter = ChatTurnAdapter()
    chat_message_injector = ChatMessageInjector()

    pipeline = Pipeline(
        [
            transport.input(),
            chat_turn_adapter,
            user_aggregator,
            llm,
            chat_message_injector,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_enabled=False,
            audio_out_enabled=False,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        enable_tracing=IS_TRACING_ENABLED,
        conversation_id=conversation_id,
    )

    flow_manager = FlowManager(
        task=task,
        llm=llm,
        context_aggregator=context_aggregator,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        flow_manager.state["channel"] = "chat"
        # Pre-authenticated via web session (SSO/BankApp); no identity step needed.
        flow_manager.state["customer_id"] = "CUST-000001"
        await flow_manager.initialize(create_greeting_chat_node())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await task.cancel()

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn_stopped(aggregator, message):
        if flow_manager.state.get("__last_node") == "closure_chat":
            logger.info("chat: farewell complete — pushing EndFrame")
            await task.queue_frame(EndFrame())

    runner = PipelineRunner(handle_sigint=False, force_gc=True)
    await runner.run(task)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    serializer = ChatJSONSerializer()
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=False,
            audio_out_enabled=False,
            add_wav_header=False,
            serializer=serializer,
        ),
    )
    await run_chat_bot(transport, conversation_id=str(uuid4()))
