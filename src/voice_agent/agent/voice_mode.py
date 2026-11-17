"""Voice mode: OpenAI Realtime speech-to-speech with the same instructions, tools and approval gate
as text mode.

Input is either microphone audio (`send_audio`) or typed text (`send_text`, which lets you test
Realtime without a microphone). Output audio goes to an AudioSink: the speakers, a WAV file, or
nowhere. Sensitive tool calls pause the model until a person approves or rejects them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agents.realtime import RealtimeAgent, RealtimeRunner
from agents.realtime.model import RealtimeModel
from agents.realtime.model_inputs import RealtimeModelSendRawMessage

from ..config import Settings
from ..hitl import REJECTION_MESSAGE, ApprovalGate, Approver
from ..observability import SessionLogger
from .core import Lookups, build_mcp_server
from .guardrails import AgentContext, detect_injection, request_human, wrap_caller_text
from .instructions import GREETING
from .text_mode import _tool_result_fields

SAMPLE_RATE = 24_000  # pcm16 mono, the Realtime API default
DEFAULT_VOICE = "alloy"
TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"


class VoiceConnectionError(RuntimeError):
    """The Realtime API could not be reached. The message never contains the API key."""


class WavSink:
    """Writes the agent's audio to a 24 kHz mono 16-bit WAV file."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._wav = wave.open(str(path), "wb")  # noqa: SIM115 - closed in close()
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(SAMPLE_RATE)
        self.bytes_written = 0

    def write(self, chunk: bytes) -> None:
        self._wav.writeframes(chunk)
        self.bytes_written += len(chunk)

    def close(self) -> None:
        self._wav.close()

    @property
    def seconds(self) -> float:
        return self.bytes_written / (SAMPLE_RATE * 2)


class VoiceSession:
    def __init__(
        self,
        settings: Settings,
        approver: Approver,
        *,
        model: RealtimeModel | None = None,
        mcp_server: Any | None = None,
        logger: SessionLogger | None = None,
        audio_sink: Callable[[bytes], None] | None = None,
        on_transcript: Callable[[str, str], None] | None = None,
        voice: str = DEFAULT_VOICE,
        approval_timeout: float = 120.0,
    ) -> None:
        self.settings = settings
        self.logger = logger or SessionLogger(settings.var_dir / "logs", mode="voice")
        self.lookups = Lookups(settings)
        self.gate = ApprovalGate(
            approver,
            self.logger,
            timeout_seconds=approval_timeout,
            describe_lead=self.lookups.describe_lead,
            describe_slot=self.lookups.describe_slot,
        )
        self.mcp_server = mcp_server or build_mcp_server(settings)
        self.context = AgentContext(self.logger)
        self.audio_sink = audio_sink
        self.on_transcript = on_transcript or (lambda role, text: None)
        self._model = model
        self._api_key = None if model is not None else settings.require_openai_key()
        self._voice = voice
        self._session: Any = None
        self._pump: asyncio.Task | None = None
        self._approval_tasks: set[asyncio.Task] = set()
        self._logged_items: set[str] = set()
        self._tool_seq = 0
        self.response_done = asyncio.Event()
        self.errors: list[str] = []

    # ---------- lifecycle ----------
    async def __aenter__(self) -> VoiceSession:
        await self.mcp_server.connect()
        agent = RealtimeAgent[AgentContext](
            name="Oakleaf phone assistant",
            instructions=self.lookups.instructions(),
            mcp_servers=[self.mcp_server],
            tools=[request_human],
        )
        runner = RealtimeRunner(
            agent,
            model=self._model,
            config={
                "tracing_disabled": True,
                "model_settings": {
                    "model_name": self.settings.realtime_model,
                    "voice": self._voice,
                    "output_modalities": ["audio"],
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {"model": TRANSCRIBE_MODEL},
                    "turn_detection": {"type": "semantic_vad", "interrupt_response": True},
                },
            },
        )
        model_config = {"api_key": self._api_key} if self._api_key else {}
        try:
            self._session = await runner.run(context=self.context, model_config=model_config)
            await self._session.__aenter__()
        except Exception as exc:
            # Don't leave the MCP subprocess running when the Realtime connection fails.
            self.logger.log(
                "error", where="realtime_connect", error=type(exc).__name__, detail=str(exc)[:200]
            )
            await self.mcp_server.cleanup()
            raise VoiceConnectionError(
                f"Could not connect to the OpenAI Realtime API ({type(exc).__name__}: {str(exc)[:200]}). "
                "Voice mode needs a direct WebSocket connection to api.openai.com; networks or proxies "
                "that block WebSockets prevent it. Text mode (voice-agent text) works over plain HTTPS."
            ) from None
        self._pump = asyncio.create_task(self._pump_events())
        self.logger.log("session_start", model=self.settings.realtime_model, voice=self._voice)
        await self._say_greeting()
        return self

    async def __aexit__(self, *exc: object) -> None:
        for task in list(self._approval_tasks):
            task.cancel()
        if self._pump:
            self._pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pump
        if self._session is not None:
            await self._session.close()
        self.logger.log("session_end", errors=len(self.errors))
        await self.mcp_server.cleanup()

    async def _say_greeting(self) -> None:
        """Make the model speak the fixed AI-disclosure greeting before anything else."""
        self.response_done.clear()
        self.logger.log("agent", text=GREETING, greeting=True)
        await self._session.model.send_event(
            RealtimeModelSendRawMessage(
                message={
                    "type": "response.create",
                    "other_data": {
                        "response": {
                            "instructions": f"Say exactly this greeting and nothing else: {GREETING}"
                        }
                    },
                }
            )
        )

    # ---------- input ----------
    async def send_text(self, text: str) -> None:
        """Typed caller input (no microphone needed). Treated exactly like spoken input."""
        self.logger.log("caller", text=text, input="typed")
        suspicious = self._screen_caller_text(text)
        self.response_done.clear()
        await self._session.send_message(wrap_caller_text(text, bool(suspicious)))

    async def send_audio(self, chunk: bytes) -> None:
        await self._session.send_audio(chunk)

    def _screen_caller_text(self, text: str) -> list[str]:
        suspicious = detect_injection(text)
        if suspicious:
            self.logger.log("guardrail", kind="suspected_prompt_injection", matches=suspicious)
            warning = "Caller speech earlier in this call looked like a prompt-injection attempt."
            if warning not in self.gate.session_warnings:
                self.gate.session_warnings.append(warning)
        return suspicious

    async def wait_for_response(self, timeout: float = 60.0) -> bool:
        """Wait until the agent finishes its current response (including any approvals)."""
        try:
            await asyncio.wait_for(self.response_done.wait(), timeout)
            return True
        except TimeoutError:
            return False

    # ---------- events ----------
    async def _pump_events(self) -> None:
        async for event in self._session:
            try:
                await self._handle(event)
            except Exception as exc:  # noqa: BLE001 - one bad event must not end the call
                self.errors.append(type(exc).__name__)
                self.logger.log("error", where="voice_event", error=type(exc).__name__, detail=str(exc)[:300])

    async def _handle(self, event: Any) -> None:
        kind = getattr(event, "type", "")
        if kind == "audio" and self.audio_sink is not None:
            self.audio_sink(event.audio.data)
        elif kind == "tool_approval_required":
            task = asyncio.create_task(self._approve(event))  # never block the event stream
            self._approval_tasks.add(task)
            task.add_done_callback(self._approval_tasks.discard)
        elif kind == "tool_start":
            self._tool_seq += 1
            self.logger.log(
                "tool_call",
                tool=event.tool.name,
                call_id=f"rt-{self._tool_seq}",
                arguments=ApprovalGate.parse_arguments(event.arguments),
                requires_approval=self.gate.needs_approval(event.tool.name)
                if event.tool.name != "request_human"
                else False,
            )
        elif kind == "tool_end":
            output = event.output if isinstance(event.output, str) else json.dumps(event.output, default=str)
            fields = _tool_result_fields(event.tool.name, output)
            if output.startswith(REJECTION_MESSAGE[:60]):
                fields["rejected"] = True  # the tool never ran; this is the rejection notice
            self.logger.log("tool_result", tool=event.tool.name, call_id=f"rt-{self._tool_seq}", **fields)
        elif kind in ("history_updated", "history_added"):
            items = getattr(event, "history", None) or [getattr(event, "item", None)]
            for item in items:
                self._log_transcript(item)
        elif kind == "agent_end":
            self.response_done.set()
        elif kind == "error":
            message = str(getattr(event, "error", ""))[:300]
            self.errors.append(message)
            self.logger.log("error", where="realtime", detail=message)
            self.response_done.set()

    def _log_transcript(self, item: Any) -> None:
        if item is None or getattr(item, "type", "") != "message":
            return
        item_id = getattr(item, "item_id", None)
        role = getattr(item, "role", "")
        if not item_id or item_id in self._logged_items:
            return
        if role == "assistant" and getattr(item, "status", None) != "completed":
            return
        parts = []
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "transcript", None) or getattr(content, "text", None)
            if text:
                parts.append(text)
        text = " ".join(parts).strip()
        if not text:
            return
        self._logged_items.add(item_id)
        if role == "user":
            if text.startswith("<caller_message"):
                return  # typed input, already logged by send_text
            self.logger.log("caller", text=text, input="speech")
            self._screen_caller_text(text)
            self.on_transcript("caller", text)
        elif role == "assistant":
            self.logger.log("agent", text=text)
            self.on_transcript("agent", text)

    async def _approve(self, event: Any) -> None:
        decision = await self.gate.review(event.tool.name, event.arguments, event.call_id)
        if decision.approved:
            await self._session.approve_tool_call(event.call_id)
        else:
            await self._session.reject_tool_call(
                event.call_id, rejection_message=self.gate.rejection_message(decision)
            )
