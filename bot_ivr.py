import datetime
import io
import os
import wave
from typing import Optional

import aiofiles
import aiohttp
from dotenv import load_dotenv
from loguru import logger
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.processors.aggregators.dtmf_aggregator import DTMFAggregator
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.groq.stt import GroqSTTService
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.utils.tracing.setup import setup_tracing
from pipecat_flows import FlowManager
from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService
from pipecat.services.elevenlabs import ElevenLabsTTSService
from flows.nodes import create_greeting_node
from pipecat.services.openrouter import OpenRouterLLMService

load_dotenv(override=True)

IS_TRACING_ENABLED = os.getenv("ENABLE_TRACING", "").lower() == "true"

if IS_TRACING_ENABLED:
    setup_tracing(
        service_name="virtual-assistant",
        exporter=OTLPSpanExporter(),
        console_export=bool(os.getenv("OTEL_CONSOLE_EXPORT")),
    )


async def get_call_info(call_sid: str) -> dict:
    """Fetch call information from Twilio REST API using aiohttp.

    Args:
        call_sid: The Twilio call SID

    Returns:
        Dictionary containing call information including from_number, to_number, status, etc.
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token:
        logger.warning("Missing Twilio credentials, cannot fetch call info")
        return {}

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls/{call_sid}.json"

    try:
        auth = aiohttp.BasicAuth(account_sid, auth_token)

        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=auth) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Twilio API error ({response.status}): {error_text}")
                    return {}

                data = await response.json()

                call_info = {
                    "from_number": data.get("from"),
                    "to_number": data.get("to"),
                }

                return call_info

    except Exception as e:
        logger.error(f"Error fetching call info from Twilio: {e}")
        return {}


async def save_audio(audio: bytes, sample_rate: int, num_channels: int):
    if len(audio) > 0:
        filename = f"recording_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.wav"
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wf:
                wf.setsampwidth(2)
                wf.setnchannels(num_channels)
                wf.setframerate(sample_rate)
                wf.writeframes(audio)
            async with aiofiles.open(filename, "wb") as file:
                await file.write(buffer.getvalue())
        logger.info(f"Merged audio saved to {filename}")
    else:
        logger.info("No audio data to save")


async def run_bot(
    transport: BaseTransport,
    handle_sigint: bool,
    testing: bool,
    conversation_id: Optional[str] = None,
):
    # LLM — no system_instruction here; persona is injected per-node via role_message
    # by FlowManager using LLMUpdateSettingsFrame.
    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
    )

    # llm = OpenRouterLLMService(
    #     api_key=os.getenv("OPENROUTER_API_KEY"),
    #     model="google/gemini-3.1-flash-lite-preview",
    # )

    # qwen/qwen3.5-27b
    # google/gemma-4-31b-it
    # mistralai/mistral-small-2603
    # meta-llama/llama-3.3-70b-instruct
    # anthropic/claude-sonnet-4.5
    # google/gemini-3.1-flash-lite-preview
    # OpenAI gpt-4.1

    # llm = OLLamaLLMService(
    #     base_url="http://18.153.196.239:11434/v1",
    #     model="llama3.3:70b",
    # )

    stt = GroqSTTService(
        api_key=os.getenv("GROQ_API_KEY"),
        settings=GroqSTTService.Settings(
            language=Language.PL,
            prompt="Jan, Kowalski, Bank Demo, konto osobiste, lokata, przelew, saldo, BankApp, złoty, PLN.",
        ),
    )

    tts = OpenAITTSService(
        api_key=os.getenv("OPENAI_API_KEY"),
        settings=OpenAITTSService.Settings(
            voice="cedar",
            model="gpt-4o-mini-tts",
            instructions="Speak in a warm, friendly tone with moderate pacing.",
            speed=1.1,
        ),
        push_silence_after_stop=testing,
    )

    # tts = ElevenLabsHttpTTSService(
    #     api_key=os.getenv("ELEVENLABS_API_KEY"),
    #     aiohttp_session=aiohttp.ClientSession(),
    #     settings=ElevenLabsHttpTTSService.Settings(
    #         voice="N0GCuK2B0qwWozQNTS8F",
    #         model="eleven_flash_v2_5",
    #         language=Language.PL,
    #     ),
    # )

    # tts = ElevenLabsTTSService(
    #     api_key=os.getenv("ELEVENLABS_API_KEY"),
    #     settings=ElevenLabsTTSService.Settings(
    #         # voice="N0GCuK2B0qwWozQNTS8F", Magdalena
    #         # Adam
    #         voice="B9cNwbQXN3s6l3nU6fqz",
    #         model="eleven_multilingual_v2",
    #         language=Language.PL,
    #         stability=0.7,
    #         similarity_boost=0.8,
    #         speed=1.1,
    #     ),
    # )

    # tts = ElevenLabsTTSService(
    #     api_key=os.getenv("ELEVENLABS_API_KEY"),
    #     settings=ElevenLabsTTSService.Settings(
    #         voice="V5GZ9rfeV9jjKZE5NkT7",             # Adam
    #         model="eleven_flash_v2_5",
    #         language=Language.PL,
    #     ),
    # )

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )
    user_aggregator, assistant_aggregator = context_aggregator

    # NOTE: Watch out! This will save all the conversation in memory. You can
    # pass `buffer_size` to get periodic callbacks.
    audiobuffer = AudioBufferProcessor()

    dtmf_aggregator = DTMFAggregator(
        timeout=2.0,
        termination_digit=KeypadEntry.POUND,
        prefix="DTMF: ",
    )

    pipeline = Pipeline(
        [
            transport.input(),  # Websocket input from client
            dtmf_aggregator,  # DTMF keypad input → TranscriptionFrame
            stt,  # Speech-To-Text
            user_aggregator,
            llm,  # LLM
            tts,  # Text-To-Speech
            transport.output(),  # Websocket output to client
            audiobuffer,  # Used to buffer the audio in the pipeline
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=8000,
            # audio_out_sample_rate=8000, zmiana pod openai
            audio_out_sample_rate=24000,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        enable_tracing=IS_TRACING_ENABLED,
        conversation_id=conversation_id,
    )

    # FlowManager is created after task so we can pass task to it.
    # It uses context_aggregator (the LLMContextAggregatorPair) to manage
    # context updates across node transitions.
    flow_manager = FlowManager(
        task=task,
        llm=llm,
        context_aggregator=context_aggregator,
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        # Start recording.
        await audiobuffer.start_recording()
        # Initialize flow at the greeting node — FlowManager sends role_message
        # and task_messages to the LLM and triggers the first LLM turn.
        await flow_manager.initialize(create_greeting_node())

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await task.cancel()

    @audiobuffer.event_handler("on_audio_data")
    async def on_audio_data(buffer, audio, sample_rate, num_channels):
        await save_audio(audio, sample_rate, num_channels)

    # We use `handle_sigint=False` because `uvicorn` is controlling keyboard
    # interruptions. We use `force_gc=True` to force garbage collection after
    # the runner finishes running a task which could be useful for long running
    # applications with multiple clients connecting.
    runner = PipelineRunner(handle_sigint=handle_sigint, force_gc=True)

    await runner.run(task)


async def bot(runner_args: RunnerArguments, testing: Optional[bool] = False):
    """Main bot entry point compatible with Pipecat Cloud."""

    _, call_data = await parse_telephony_websocket(runner_args.websocket)

    # Fetch call information from Twilio REST API
    # With the call information, you can make a request to your API to get the user's information
    # and inject that information into your bot's configuration.
    call_info = await get_call_info(call_data["call_id"])
    if call_info:
        logger.info(f"Call from: {call_info.get('from_number')} to: {call_info.get('to_number')}")

    serializer = TwilioFrameSerializer(
        stream_sid=call_data["stream_id"],
        call_sid=call_data["call_id"],
        account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
    )

    transport = FastAPIWebsocketTransport(
        websocket=runner_args.websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    await run_bot(
        transport, runner_args.handle_sigint, testing, conversation_id=call_data["call_id"]
    )


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()
