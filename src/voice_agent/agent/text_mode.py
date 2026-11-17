"""Text-only mode: the same agent as voice mode, driven by typed messages.

Used for interactive testing without a microphone (`voice-agent text`), for the offline demo
(`voice-agent demo`) and for the automated tests (with a scripted model).
"""

from __future__ import annotations

import json
from typing import Any

from agents import Agent, Model, RunConfig, Runner
from agents.items import ToolCallItem, ToolCallOutputItem
from agents.mcp import MCPServer
from agents.models.openai_provider import OpenAIProvider

from ..config import Settings
from ..hitl import ApprovalGate, Approver
from ..observability import SessionLogger
from .core import Lookups, build_mcp_server
from .guardrails import AgentContext, detect_injection, request_human, wrap_caller_text
from .instructions import GREETING

MAX_TURNS = 12  # model calls per caller message, including tool calls


def unwrap_tool_output(output: Any) -> str:
    """MCP results reach the agent as {"type": "text", "text": "..."} (or a list of them)."""
    value = output
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return output
    if isinstance(value, dict) and value.get("type") == "text" and isinstance(value.get("text"), str):
        return value["text"]
    if (
        isinstance(value, list)
        and value
        and all(isinstance(v, dict) and v.get("type") == "text" for v in value)
    ):
        return "\n".join(v.get("text", "") for v in value)
    return output if isinstance(output, str) else json.dumps(output, default=str)


def _tool_result_fields(tool_name: str, output: Any) -> dict:
    """Pick out what the logs and dashboard need from a tool result (e.g. RAG sources)."""
    text = unwrap_tool_output(output)
    fields: dict[str, Any] = {"output": text}
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        data = None
    if isinstance(data, dict):
        if tool_name == "search_knowledge":
            fields.update(
                found=data.get("found"),
                sources=data.get("sources", []),
                chunk_ids=[p.get("chunk_id") for p in data.get("passages", [])],
            )
        for key in ("booked", "cancelled", "created", "tier", "score"):
            if key in data:
                fields[key] = data[key]
    if isinstance(text, str) and text.startswith("Error executing tool"):
        fields["is_error"] = True
    return fields


class TextSession:
    """One conversation. Use as `async with TextSession(...) as s: print(s.greeting); await s.send(...)`."""

    def __init__(
        self,
        settings: Settings,
        approver: Approver,
        *,
        model: Model | str | None = None,
        mcp_server: MCPServer | None = None,
        logger: SessionLogger | None = None,
        approval_timeout: float = 120.0,
        model_label: str | None = None,
        session_info: dict | None = None,
    ) -> None:
        self.settings = settings
        self._model_label = model_label
        self._session_info = session_info or {}
        self.logger = logger or SessionLogger(settings.var_dir / "logs", mode="text")
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
        self.history: list[Any] = []
        self._logged_calls: set[str] = set()
        self._logged_outputs: set[str] = set()
        self._rejected_calls: set[str] = set()
        self.model_requests = 0  # calls to the model (each tool round-trip is one), for cost reporting
        self._model = model or settings.text_model
        self.agent: Agent | None = None
        if isinstance(self._model, str):
            api_key = settings.require_openai_key()  # clear ConfigError if missing
            self.run_config = RunConfig(model_provider=OpenAIProvider(api_key=api_key), tracing_disabled=True)
        else:
            self.run_config = RunConfig(tracing_disabled=True)

    async def __aenter__(self) -> TextSession:
        await self.mcp_server.connect()
        self.agent = Agent[AgentContext](
            name="Oakleaf phone assistant",
            instructions=self.lookups.instructions(),
            model=self._model,
            mcp_servers=[self.mcp_server],
            tools=[request_human],
        )
        self.logger.log(
            "session_start",
            model=self._model_label
            or (self._model if isinstance(self._model, str) else type(self._model).__name__),
            embeddings=self.settings.embeddings_provider,
            **self._session_info,
        )
        self.logger.log("agent", text=GREETING, greeting=True)
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.logger.log(
            "session_end",
            turns=sum(1 for e in self.logger.events if e["type"] == "caller"),
            model_requests=self.model_requests,
        )
        await self.mcp_server.cleanup()

    @property
    def greeting(self) -> str:
        return GREETING

    async def send(self, caller_text: str) -> str:
        """Handle one caller message, including any approvals, and return the agent's reply."""
        if self.agent is None:
            raise RuntimeError("use TextSession as an async context manager")
        suspicious = detect_injection(caller_text)
        self.logger.log("caller", text=caller_text)
        if suspicious:
            self.logger.log("guardrail", kind="suspected_prompt_injection", matches=suspicious)
            warning = "Caller text earlier in this call looked like a prompt-injection attempt."
            if warning not in self.gate.session_warnings:
                self.gate.session_warnings.append(warning)

        run_input = [
            *self.history,
            {"role": "user", "content": wrap_caller_text(caller_text, bool(suspicious))},
        ]
        try:
            result = await Runner.run(
                self.agent, run_input, context=self.context, max_turns=MAX_TURNS, run_config=self.run_config
            )
            self.model_requests += len(result.raw_responses)
            while result.interruptions:
                self._log_new_items(result.new_items)
                state = result.to_state()
                for item in result.interruptions:
                    raw = item.raw_item
                    call_id = getattr(raw, "call_id", None) or getattr(raw, "id", "") or ""
                    arguments = getattr(raw, "arguments", None)
                    decision = await self.gate.review(item.tool_name or "", arguments, call_id)
                    if decision.approved:
                        state.approve(item)
                    else:
                        self._rejected_calls.add(call_id)
                        state.reject(item, rejection_message=self.gate.rejection_message(decision))
                before = len(result.raw_responses)
                result = await Runner.run(
                    self.agent, state, context=self.context, max_turns=MAX_TURNS, run_config=self.run_config
                )
                self.model_requests += max(0, len(result.raw_responses) - before)
        except Exception as exc:
            self.logger.log("error", where="agent_run", error=type(exc).__name__, detail=str(exc)[:300])
            raise

        self._log_new_items(result.new_items)
        self.history = result.to_input_list()
        reply = str(result.final_output or "").strip()
        self.logger.log("agent", text=reply)
        return reply

    def _log_new_items(self, items: list[Any]) -> None:
        names: dict[str, str] = {}
        for item in items:
            if isinstance(item, ToolCallItem):
                raw = item.raw_item
                call_id = getattr(raw, "call_id", None) or getattr(raw, "id", "")
                name = getattr(raw, "name", "") or ""
                names[call_id] = name
                if call_id not in self._logged_calls:
                    self._logged_calls.add(call_id)
                    self.logger.log(
                        "tool_call",
                        tool=name,
                        call_id=call_id,
                        arguments=ApprovalGate.parse_arguments(getattr(raw, "arguments", None)),
                        requires_approval=self.gate.needs_approval(name)
                        if name != "request_human"
                        else False,
                    )
            elif isinstance(item, ToolCallOutputItem):
                raw = item.raw_item
                call_id = (raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", "")) or ""
                if call_id in self._logged_outputs:
                    continue
                self._logged_outputs.add(call_id)
                name = names.get(call_id) or self._name_for(call_id)
                fields = _tool_result_fields(name, item.output)
                if call_id in self._rejected_calls:
                    fields["rejected"] = True
                self.logger.log("tool_result", tool=name, call_id=call_id, **fields)

    def _name_for(self, call_id: str) -> str:
        for event in reversed(self.logger.events):
            if event.get("call_id") == call_id and event.get("tool"):
                return event["tool"]
        return ""
