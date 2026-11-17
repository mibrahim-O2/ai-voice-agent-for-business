"""Interactive front-ends for `voice-agent text` and `voice-agent voice`.

Approvals are asked in the same terminal by default (ConsoleApprover). `--auto-reject` rejects
every sensitive action, which is a safe way to try the agent without changing any data.
There is deliberately no auto-approve option.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

from ..config import Settings
from ..hitl import Approver, ConsoleApprover, ScriptedApprover
from .text_mode import TextSession
from .voice_mode import SAMPLE_RATE, VoiceSession, WavSink

QUIT_WORDS = {"quit", "exit", "bye", "/quit"}


def make_approver(auto_reject: bool) -> Approver:
    if auto_reject:
        return ScriptedApprover(lambda _request: False, name="auto-reject")
    return ConsoleApprover()


def _print_summary(logger) -> None:
    counts: dict[str, int] = {}
    for event in logger.events:
        counts[event["type"]] = counts.get(event["type"], 0) + 1
    decisions = [e for e in logger.events if e["type"] == "approval_decision"]
    approved = sum(1 for e in decisions if e.get("approved"))
    rejected = len(decisions) - approved
    print(
        f"\n[session {logger.session_id}] {counts.get('caller', 0)} caller turns, "
        f"{counts.get('tool_call', 0)} tool calls, {approved} approved / {rejected} rejected, "
        f"log: {logger.path}",
        file=sys.stderr,
    )


async def run_text_chat(settings: Settings, approver: Approver) -> None:
    async with TextSession(settings, approver) as session:
        print(f"\nAgent: {session.greeting}\n(type 'quit' to hang up)\n")
        while True:
            try:
                line = await asyncio.to_thread(input, "You: ")
            except EOFError:
                break
            if line.strip().lower() in QUIT_WORDS:
                break
            if not line.strip():
                continue
            reply = await session.send(line)
            print(f"\nAgent: {reply}\n")
        _print_summary(session.logger)


async def run_voice_typed(settings: Settings, approver: Approver, wav_path: Path, voice: str) -> None:
    """Realtime speech-to-speech without a microphone: type what the caller says, hear/save audio."""
    sink = WavSink(wav_path)

    def show(role: str, text: str) -> None:
        print(f"\n{'Agent' if role == 'agent' else 'You'} (transcript): {text}\n")

    try:
        async with VoiceSession(
            settings, approver, audio_sink=sink.write, on_transcript=show, voice=voice
        ) as vs:
            await vs.wait_for_response(timeout=60)
            print("(type what the caller says; 'quit' to hang up)")
            while True:
                try:
                    line = await asyncio.to_thread(input, "You: ")
                except EOFError:
                    break
                if line.strip().lower() in QUIT_WORDS:
                    break
                if line.strip():
                    await vs.send_text(line)
                    if not await vs.wait_for_response(timeout=120):
                        print("(no response within 120 s)", file=sys.stderr)
            _print_summary(vs.logger)
    finally:
        sink.close()
        print(f"Agent audio saved: {sink.path} ({sink.seconds:.1f} s)", file=sys.stderr)


async def run_voice_microphone(settings: Settings, approver: Approver, voice: str) -> None:
    """Full speech-to-speech with the default microphone and speakers (needs `sounddevice`)."""
    try:
        import sounddevice as sd  # optional dependency: pip install -e ".[voice]"
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            'Microphone mode needs the optional audio packages: pip install -e ".[voice]" '
            "(and PortAudio on Linux: sudo apt install libportaudio2). "
            "Without a microphone, use: voice-agent voice --type"
        ) from exc

    loop = asyncio.get_running_loop()
    mic_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=200)
    speaker = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16")
    speaker.start()

    def enqueue(chunk: bytes) -> None:  # runs on the event loop
        with contextlib.suppress(asyncio.QueueFull):  # drop audio rather than block if we fall behind
            mic_queue.put_nowait(chunk)

    def on_mic(indata, _frames, _time, _status) -> None:  # runs on the audio thread
        loop.call_soon_threadsafe(enqueue, bytes(indata))

    def play(chunk: bytes) -> None:
        speaker.write(chunk)

    def show(role: str, text: str) -> None:
        print(f"{'Agent' if role == 'agent' else 'Caller'}: {text}")

    mic = sd.RawInputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=2400, callback=on_mic
    )
    async with VoiceSession(settings, approver, audio_sink=play, on_transcript=show, voice=voice) as vs:
        print("Listening. Speak after the greeting; press Ctrl+C to hang up.", file=sys.stderr)
        with mic:
            try:
                while True:
                    await vs.send_audio(await mic_queue.get())
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
        _print_summary(vs.logger)
    speaker.stop()
    speaker.close()
