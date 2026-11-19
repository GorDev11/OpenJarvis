"""OrchestratorAgent — multi-turn agent with tool-calling loop.

Supports two modes:

- **function_calling** (default): Uses OpenAI-format tool definitions and
  parses ``tool_calls`` from the engine response.
- **structured**: Uses a THOUGHT/TOOL/INPUT/FINAL_ANSWER text format
  (like ReAct) with a canonical system prompt from the orchestrator
  prompt registry.  This is the format used by the SFT/GRPO training
  pipelines, making the Orchestrator a distinctive trainable agent type.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
import time
from typing import Any, Callable, List, Optional

from openjarvis.agents._stubs import (
    _ALLOWED_ENGINE_OPTION_KEYS,
    AgentContext,
    AgentResult,
    ToolUsingAgent,
)
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool

logger = logging.getLogger(__name__)


@AgentRegistry.register("orchestrator")
class OrchestratorAgent(ToolUsingAgent):
    """Multi-turn agent that routes between tools and the LLM.

    Implements a tool-calling loop:
    1. Send messages with tool definitions to the engine.
    2. If the response contains tool_calls, execute them and loop.
    3. If no tool_calls, return the final answer.
    4. Stop after ``max_turns`` iterations.

    In **structured** mode the agent instead uses a
    ``THOUGHT: / TOOL: / INPUT: / FINAL_ANSWER:`` text protocol
    identical to the format used by the orchestrator SFT/GRPO
    training pipelines.
    """

    agent_id = "orchestrator"
    supports_live_stream = True
    _default_temperature = 0.7
    _default_max_tokens = 1024
    _default_max_turns = 10

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        engine_options: Optional[dict[str, Any]] = None,
        mode: str = "function_calling",
        system_prompt: Optional[str] = None,
        prompt_builder: Optional[Any] = None,
        parallel_tools: bool = True,
        interactive: bool = False,
        confirm_callback=None,
        capability_policy: Optional[Any] = None,
        agent_id: Optional[str] = None,
        rate_limiter: Optional[Any] = None,
        before_tool_call: Optional[Callable[[str, dict[str, Any]], bool]] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            engine_options=engine_options,
            interactive=interactive,
            confirm_callback=confirm_callback,
            prompt_builder=prompt_builder,
            capability_policy=capability_policy,
            agent_id=agent_id,
            rate_limiter=rate_limiter,
        )
        self._mode = mode
        self._system_prompt = system_prompt
        self._parallel_tools = parallel_tools
        self._before_tool_call = before_tool_call

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        if self._mode == "structured":
            return self._run_structured(input, context, **kwargs)
        return self._run_function_calling(input, context, **kwargs)

    # ------------------------------------------------------------------
    # Governance hook
    # ------------------------------------------------------------------

    @staticmethod
    def _governance_denial(tool_name: str, reason: str) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            content=(
                f"[Governance] Tool '{tool_name}' was not approved ({reason}). "
                "Adjust your plan and try a different approach."
            ),
            success=False,
        )

    def _check_tool_allowed(self, tc: ToolCall) -> Optional[ToolResult]:
        """Call before_tool_call hook if set.

        Returns None to allow execution, or a denial ToolResult to inject
        instead of running the tool. Invalid arguments and hook failures deny
        execution so a governance integration cannot fail open.
        """
        if self._before_tool_call is None:
            return None

        try:
            tool_args = json.loads(tc.arguments) if tc.arguments else {}
        except (json.JSONDecodeError, TypeError):
            return self._governance_denial(tc.name, "invalid tool arguments")
        if not isinstance(tool_args, dict):
            return self._governance_denial(tc.name, "tool arguments are not an object")

        try:
            allowed = self._before_tool_call(tc.name, tool_args)
        except Exception:
            logger.exception("before_tool_call hook failed for tool %s", tc.name)
            return self._governance_denial(tc.name, "governance check failed")
        if allowed:
            return None
        return self._governance_denial(tc.name, "policy denied the call")

    # ------------------------------------------------------------------
    # Structured mode (THOUGHT/TOOL/INPUT/FINAL_ANSWER)
    # ------------------------------------------------------------------

    def _run_structured(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Build system prompt
        if self._system_prompt:
            sys_prompt = self._system_prompt
        else:
            from openjarvis.learning.intelligence.orchestrator.prompt_registry import (
                build_system_prompt,
            )

            sys_prompt = build_system_prompt(tools=self._tools)

        messages = self._build_messages(input, context, system_prompt=sys_prompt)

        all_tool_results: list[ToolResult] = []
        turns = 0

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            result = self._generate(messages)
            content = result.get("content", "")

            parsed = self._parse_structured_response(content)

            # FINAL_ANSWER -> done
            if parsed["final_answer"]:
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=parsed["final_answer"],
                    tool_results=all_tool_results,
                    turns=turns,
                )

            # TOOL -> execute
            if parsed["tool"]:
                messages.append(Message(role=Role.ASSISTANT, content=content))

                tool_call = ToolCall(
                    id=f"orch_{turns}",
                    name=parsed["tool"],
                    arguments=self._normalize_structured_tool_input(
                        parsed["tool"],
                        parsed["input"],
                    ),
                )
                denial = self._check_tool_allowed(tool_call)
                if denial is not None:
                    tool_result = denial
                else:
                    tool_result = self._executor.execute(tool_call)
                all_tool_results.append(tool_result)

                if tool_result.success:
                    observation = f"Observation: {tool_result.content}"
                else:
                    observation = (
                        f"Observation: Tool '{tool_result.tool_name}' failed: "
                        f"{tool_result.content}"
                    )
                messages.append(Message(role=Role.USER, content=observation))
                continue

            # Neither -> treat content as final answer
            self._emit_turn_end(turns=turns)
            return AgentResult(
                content=content,
                tool_results=all_tool_results,
                turns=turns,
            )

        # Max turns exceeded
        return self._max_turns_result(all_tool_results, turns)

    def _normalize_structured_tool_input(
        self,
        tool_name: str,
        raw_input: str,
    ) -> str:
        """Map unambiguous structured text input to a string parameter."""
        if not raw_input:
            return "{}"

        try:
            parsed_input = json.loads(raw_input)
        except json.JSONDecodeError:
            invalid_json = True
            string_value = raw_input
        else:
            invalid_json = False
            if isinstance(parsed_input, dict):
                return raw_input
            # INPUT is a text protocol. A non-object JSON value such as 42,
            # true, null, or [1, 2] may still be the intended text for a tool's
            # string parameter. Quoted JSON strings are decoded to remove only
            # their surrounding quotes; other values retain their source text.
            string_value = parsed_input if isinstance(parsed_input, str) else raw_input

        tool_spec = None
        for candidate in reversed(self._tools):
            candidate_spec = candidate.spec
            if candidate_spec.name == tool_name:
                tool_spec = candidate_spec
                break
        if tool_spec is None:
            return raw_input

        parameters = tool_spec.parameters
        parameter_container_type = parameters.get("type")
        if parameter_container_type not in (None, "object"):
            return raw_input

        properties = parameters.get("properties", {})
        required = parameters.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            return raw_input

        if len(required) == 1 and required[0] in properties:
            parameter_name = required[0]
        elif not required and len(properties) == 1:
            parameter_name = next(iter(properties))
        else:
            return raw_input

        parameter_schema = properties[parameter_name]
        if not isinstance(parameter_schema, dict):
            return raw_input
        parameter_type = parameter_schema.get("type")
        accepts_string = parameter_type == "string" or (
            isinstance(parameter_type, list) and "string" in parameter_type
        )
        if not accepts_string:
            return raw_input

        allow_object_text = (
            tool_spec.metadata.get("structured_allow_object_text") is True
        )
        starts_like_object = raw_input.lstrip("\ufeff \t\r\n").startswith("{")
        if invalid_json and starts_like_object and not allow_object_text:
            return raw_input

        return json.dumps({parameter_name: string_value})

    @staticmethod
    def _parse_structured_response(text: str) -> dict:
        """Parse THOUGHT/TOOL/INPUT/FINAL_ANSWER from model output."""
        result = {
            "thought": "",
            "tool": "",
            "input": "",
            "final_answer": "",
        }

        thought_match = re.search(
            r"THOUGHT:\s*(.+?)(?=\nTOOL:|\nFINAL[_ ]?ANSWER:|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if thought_match:
            result["thought"] = thought_match.group(1).strip()

        final_match = re.search(
            r"FINAL[_ ]?ANSWER:\s*(.+)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if final_match:
            result["final_answer"] = final_match.group(1).strip()
            return result

        tool_match = re.search(r"TOOL:\s*(.+)", text, re.IGNORECASE)
        if tool_match:
            result["tool"] = tool_match.group(1).strip()

        input_match = re.search(
            r"INPUT:\s*(.+?)(?=\nTHOUGHT:|\nTOOL:|\nFINAL|\Z)",
            text,
            re.DOTALL | re.IGNORECASE,
        )
        if input_match:
            result["input"] = input_match.group(1).strip()

        return result

    # ------------------------------------------------------------------
    # Function-calling mode (original behaviour)
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_stream_tool_calls(
        accumulated: dict[int, dict[str, Any]],
        fragments: list[dict[str, Any]],
    ) -> None:
        """Merge OpenAI-style deltas or already-normalized tool calls."""

        for fallback_index, fragment in enumerate(fragments):
            index = int(fragment.get("index", fallback_index))
            entry = accumulated.setdefault(
                index,
                {"id": "", "name": "", "arguments": ""},
            )
            if fragment.get("id"):
                entry["id"] = str(fragment["id"])
            function = fragment.get("function")
            if not isinstance(function, dict):
                function = fragment
            if function.get("name"):
                entry["name"] += str(function["name"])
            arguments = function.get("arguments")
            if arguments:
                entry["arguments"] += (
                    json.dumps(arguments)
                    if isinstance(arguments, dict)
                    else str(arguments)
                )

    async def _consume_engine_stream(
        self,
        messages: list[Message],
        *,
        stream_callback: Callable[[str], None],
        stream_cancel_event: Any = None,
        **extra_kwargs: Any,
    ) -> dict[str, Any]:
        content_parts: list[str] = []
        tool_fragments: dict[int, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        finish_reason = ""
        response_loop_reason = ""
        response_chars = 0
        # Checking the ENTIRE accumulated text after every single streamed
        # token is quadratic and slows long answers. Bound the delay between
        # checks while retaining an unconditional final-response check below.
        next_response_guard_check = 48

        gen_kwargs = {
            key: value
            for key, value in self._engine_options.items()
            if key in _ALLOWED_ENGINE_OPTION_KEYS
        }
        gen_kwargs.update(extra_kwargs)

        async for chunk in self._engine.stream_full(
            messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            **gen_kwargs,
        ):
            if stream_cancel_event is not None and stream_cancel_event.is_set():
                raise asyncio.CancelledError
            if chunk.content:
                response_chars += len(chunk.content)
                should_check_response = (
                    response_chars >= next_response_guard_check
                    or any(
                        boundary in chunk.content
                        for boundary in ("\n", ".", "!", "?", "։")
                    )
                )
                if self._loop_guard and should_check_response:
                    candidate = "".join(content_parts) + chunk.content
                    verdict = self._loop_guard.check_response(candidate)
                    next_response_guard_check = response_chars + 48
                    if verdict.blocked:
                        response_loop_reason = verdict.reason
                        finish_reason = "loop_guard"
                        if not content_parts:
                            collapsed = self._loop_guard.deduplicate_response(candidate)
                            content_parts.append(collapsed)
                            stream_callback(collapsed)
                        break
                content_parts.append(chunk.content)
                stream_callback(chunk.content)
            if chunk.tool_calls:
                self._merge_stream_tool_calls(tool_fragments, chunk.tool_calls)
            if chunk.usage:
                usage.update(chunk.usage)
            if chunk.finish_reason:
                finish_reason = chunk.finish_reason

        tool_calls = []
        for index in sorted(tool_fragments):
            call = tool_fragments[index]
            tool_calls.append(
                {
                    "id": call["id"] or f"call_{index}",
                    "name": call["name"],
                    "arguments": call["arguments"] or "{}",
                }
            )
        content = "".join(content_parts)
        return {
            "content": content,
            "tool_calls": tool_calls,
            "usage": usage,
            "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop"),
            "_streamed_content": content,
            "_response_loop_reason": response_loop_reason,
        }

    def _generate_streaming(
        self,
        messages: list[Message],
        *,
        stream_callback: Callable[[str], None],
        stream_event_loop: Any = None,
        stream_cancel_event: Any = None,
        **extra_kwargs: Any,
    ) -> dict[str, Any]:
        """Consume ``stream_full`` without blocking the server event loop."""

        if stream_event_loop is None or not stream_event_loop.is_running():
            # The HTTP server always supplies its running loop. A synchronous
            # SDK caller has no safe loop on which to consume an async engine,
            # so retain compatibility with one authoritative generate() call
            # and expose its content through the same callback contract.
            result = self._generate(messages, **extra_kwargs)
            content = result.get("content", "")
            if content:
                stream_callback(content)
            result["_streamed_content"] = content
            return result

        # Expose only counts, never raw system prompts or tool schemas. A
        # large tool manifest can dominate Qwen3.6 hybrid CPU/GPU prefill,
        # even for a greeting. These metrics make that bottleneck measurable
        # without disabling any of the Orchestrator's registered tools.
        tool_definitions = extra_kwargs.get("tools") or []
        tool_count = len(tool_definitions)
        available_tool_count = len(self._tools)
        tool_schema_chars = (
            len(json.dumps(tool_definitions, ensure_ascii=False))
            if tool_definitions
            else 0
        )
        prompt_chars = sum(
            len(str(getattr(message, "content", "") or "")) for message in messages
        )
        logger.info(
            "Orchestrator inference payload: model=%s messages=%d prompt_chars=%d "
            "tool_count=%d available_tool_count=%d tool_schema_chars=%d",
            self._model,
            len(messages),
            prompt_chars,
            tool_count,
            available_tool_count,
            tool_schema_chars,
        )

        publishes_events = getattr(self._engine, "_publishes_events", False)
        if self._bus and not publishes_events:
            self._bus.publish(
                EventType.INFERENCE_START,
                {
                    "model": self._model,
                    "engine": getattr(self._engine, "engine_id", ""),
                    "prompt_chars": prompt_chars,
                    "tool_count": tool_count,
                    "available_tool_count": available_tool_count,
                    "tool_schema_chars": tool_schema_chars,
                },
            )

        coroutine = self._consume_engine_stream(
            messages,
            stream_callback=stream_callback,
            stream_cancel_event=stream_cancel_event,
            **extra_kwargs,
        )
        future = asyncio.run_coroutine_threadsafe(coroutine, stream_event_loop)
        while True:
            if stream_cancel_event is not None and stream_cancel_event.is_set():
                future.cancel()
                raise RuntimeError("Agent stream cancelled by client")
            try:
                result = future.result(timeout=0.05)
                break
            except concurrent.futures.TimeoutError:
                continue

        if self._bus and not publishes_events:
            self._bus.publish(
                EventType.INFERENCE_END,
                {
                    "model": self._model,
                    "usage": result.get("usage", {}),
                    "content": result.get("content", ""),
                    "tool_calls": result.get("tool_calls", []),
                    "finish_reason": result.get("finish_reason", ""),
                },
            )
        return result

    def _run_function_calling(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        run_started = time.perf_counter()
        self._emit_turn_start(input)

        # Build initial messages
        messages = self._build_messages(
            input,
            context,
            system_prompt=self._system_prompt,
        )

        # Get OpenAI-format tool definitions
        openai_tools = self._executor.get_openai_tools() if self._tools else []

        all_tool_results: list[ToolResult] = []
        turns = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        inference_calls = 0
        inference_wall_seconds = 0.0
        initial_prompt_chars = sum(len(message.text or "") for message in messages)
        stream_callback = kwargs.get("stream_callback")
        stream_event_loop = kwargs.get("stream_event_loop")
        stream_cancel_event = kwargs.get("stream_cancel_event")
        streamed_tool_preambles = ""
        first_content_seconds: Optional[float] = None
        model_first_content_seconds: Optional[float] = None

        def record_stream_content(content: str) -> None:
            nonlocal first_content_seconds, model_first_content_seconds
            if content and first_content_seconds is None:
                now = time.perf_counter()
                first_content_seconds = round(now - run_started, 3)
                model_first_content_seconds = round(now - inference_started, 3)
            if stream_callback is not None:
                stream_callback(content)

        from openjarvis.agents.safe_tool_routing import (
            is_pure_greeting,
            select_safe_tool_routes,
        )
        from openjarvis.agents.tool_manifest import select_request_tool_manifest

        deterministic_routes = select_safe_tool_routes(
            input,
            (tool.spec.name for tool in self._tools),
        )
        # Pure standalone greetings require no external operations. Keep the
        # Orchestrator and its full registered tool set intact for all actual
        # tasks, but avoid passing costly function schemas into hybrid GPU/CPU
        # model prefill for "Բարև" / "hello".
        greeting_only = is_pure_greeting(input)
        # The agent and executor always retain ALL permitted tools. Only the
        # per-request advertisement to the local model is compacted for a
        # clearly self-contained arithmetic task; ambiguity falls back to all.
        # Prior chat context can change intent, so never prune a follow-up.
        inference_tools = select_request_tool_manifest(
            input,
            openai_tools,
            has_conversation_context=bool(
                context is not None and context.conversation.messages
            ),
        )

        pending_routed_calls = [
            {
                "id": f"safe_route_{index}",
                "name": route.name,
                "arguments": route.arguments,
            }
            for index, route in enumerate(deterministic_routes, start=1)
        ]

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            # Build generate kwargs
            gen_kwargs: dict[str, Any] = {}
            # A deterministic route already executed exactly the reviewed
            # read-only diagnostic(s) requested by the user. The follow-up
            # model turn must summarize those results, not escalate to a
            # broader tool such as shell_exec or repeat extra diagnostics.
            if inference_tools and not deterministic_routes and not greeting_only:
                gen_kwargs["tools"] = inference_tools

            if pending_routed_calls:
                # Execute explicit, reviewed read-only diagnostics before the
                # model can replace the requested action with prose. The tool
                # results are then fed back to the model for a grounded answer.
                result = {
                    "content": "",
                    "tool_calls": pending_routed_calls,
                    "usage": {},
                    "finish_reason": "tool_calls",
                }
                pending_routed_calls = []
            else:
                inference_started = time.perf_counter()
                try:
                    if stream_callback is not None:
                        result = self._generate_streaming(
                            messages,
                            stream_callback=record_stream_content,
                            stream_event_loop=stream_event_loop,
                            stream_cancel_event=stream_cancel_event,
                            **gen_kwargs,
                        )
                    else:
                        result = self._generate(messages, **gen_kwargs)
                finally:
                    inference_calls += 1
                    inference_wall_seconds += time.perf_counter() - inference_started

            # Accumulate token usage
            usage = result.get("usage", {})
            total_prompt_tokens += usage.get("prompt_tokens", 0)
            total_completion_tokens += usage.get("completion_tokens", 0)

            content = result.get("content", "")
            raw_tool_calls = result.get("tool_calls", [])
            streamed_turn = result.get("_streamed_content", "")
            response_loop_reason = result.get("_response_loop_reason", "")

            # No tool calls -> check continuation, then final answer
            if not raw_tool_calls:
                # A live OpenAI-compatible stream must respect the caller's
                # max_tokens as the total response limit. Automatically
                # issuing two hidden, non-streamed continuation requests made
                # a 768-token Colibri response silently grow to as many as
                # 2304 tokens and left the UI apparently frozen between
                # chunks. Synchronous agent callers retain the historical
                # completion-recovery behaviour.
                content = self._check_continuation(
                    result,
                    messages,
                    max_continuations=(
                        0
                        if stream_callback is not None
                        else kwargs.get("max_continuations", 2)
                    ),
                )
                stripped_content = self._strip_think_tags(content)
                guarded_content = (
                    content
                    if stream_callback is not None and streamed_turn
                    else stripped_content
                )
                if self._loop_guard and not response_loop_reason:
                    response_verdict = self._loop_guard.check_response(guarded_content)
                    if response_verdict.blocked:
                        response_loop_reason = response_verdict.reason
                if (
                    response_loop_reason
                    and self._loop_guard
                    and stream_callback is None
                ):
                    guarded_content = self._loop_guard.deduplicate_response(
                        guarded_content
                    )
                # Preserve byte-for-byte prefix agreement with content already
                # delivered to the UI. Any continuation generated
                # synchronously is replayed by AgentStreamBridge.
                final_content = streamed_tool_preambles + guarded_content
                self._emit_turn_end(
                    turns=turns,
                    content_length=len(final_content),
                )
                metadata = {
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                    "total_tokens": total_prompt_tokens + total_completion_tokens,
                    "deterministic_routes": [
                        route.name for route in deterministic_routes
                    ],
                }
                if response_loop_reason:
                    metadata["response_loop_blocked"] = True
                    metadata["response_loop_reason"] = response_loop_reason
                metadata["finish_reason"] = result.get("finish_reason", "stop")
                # Timings are authoritative only when there are no hidden
                # continuation calls. HTTP callers explicitly request zero.
                if stream_callback is not None or kwargs.get("max_continuations") == 0:
                    metadata["performance"] = {
                        "agent_wall_seconds": round(
                            time.perf_counter() - run_started, 3
                        ),
                        "inference_wall_seconds": round(inference_wall_seconds, 3),
                        "inference_calls": inference_calls,
                        "tool_calls": len(all_tool_results),
                        "prompt_chars": initial_prompt_chars,
                        "first_content_seconds": first_content_seconds,
                        "model_first_content_seconds": model_first_content_seconds,
                        "advertised_tool_count": (
                            len(inference_tools)
                            if not deterministic_routes and not greeting_only
                            else 0
                        ),
                        "registered_tool_count": len(openai_tools),
                    }
                return AgentResult(
                    content=final_content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata=metadata,
                )

            if streamed_turn:
                streamed_tool_preambles += streamed_turn

            # Build ToolCall objects from raw dicts
            tool_calls = [
                ToolCall(
                    id=tc.get("id", f"call_{i}"),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", "{}"),
                )
                for i, tc in enumerate(raw_tool_calls)
            ]

            # Append assistant message with tool calls
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=content,
                    tool_calls=tool_calls,
                )
            )

            # Execute each tool (with loop guard check) and append results
            if self._parallel_tools and len(tool_calls) > 1:
                # Governance callbacks often wrap stateful policy engines and
                # are not assumed to be thread-safe. Evaluate them in request
                # order before dispatching the approved tool work in parallel.
                results_map: dict[int, tuple[ToolCall, ToolResult]] = {}
                approved_calls: list[ToolCall] = []
                for tc in tool_calls:
                    denial = self._check_tool_allowed(tc)
                    if denial is None:
                        approved_calls.append(tc)
                    else:
                        results_map[id(tc)] = (tc, denial)

                def _exec_tool(tc: ToolCall) -> tuple:
                    if self._loop_guard:
                        verdict = self._loop_guard.check_call(
                            tc.name,
                            tc.arguments,
                        )
                        if verdict.blocked:
                            return tc, ToolResult(
                                tool_name=tc.name,
                                content=f"Loop guard: {verdict.reason}",
                                success=False,
                            )
                    return tc, self._executor.execute(tc)

                if approved_calls:
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=len(approved_calls),
                    ) as pool:
                        futures = {
                            pool.submit(_exec_tool, tc): tc for tc in approved_calls
                        }
                        for future in concurrent.futures.as_completed(futures):
                            tc_orig = futures[future]
                            results_map[id(tc_orig)] = future.result()

                # Append results in original order
                for tc in tool_calls:
                    _, tool_result = results_map[id(tc)]
                    all_tool_results.append(tool_result)
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result.content,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
            else:
                # Sequential execution
                for tc in tool_calls:
                    # Governance hook check before execution
                    denial = self._check_tool_allowed(tc)
                    if denial is not None:
                        all_tool_results.append(denial)
                        messages.append(
                            Message(
                                role=Role.TOOL,
                                content=denial.content,
                                tool_call_id=tc.id,
                                name=tc.name,
                            )
                        )
                        continue

                    # Loop guard check before execution
                    if self._loop_guard:
                        verdict = self._loop_guard.check_call(
                            tc.name,
                            tc.arguments,
                        )
                        if verdict.blocked:
                            tool_result = ToolResult(
                                tool_name=tc.name,
                                content=f"Loop guard: {verdict.reason}",
                                success=False,
                            )
                            all_tool_results.append(tool_result)
                            messages.append(
                                Message(
                                    role=Role.TOOL,
                                    content=tool_result.content,
                                    tool_call_id=tc.id,
                                    name=tc.name,
                                )
                            )
                            continue

                    tool_result = self._executor.execute(tc)
                    all_tool_results.append(tool_result)

                    # Append tool response message
                    messages.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result.content,
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )

        # Max turns exceeded
        final_content = self._strip_think_tags(content) if content else ""
        final_content = streamed_tool_preambles + final_content
        self._emit_turn_end(turns=turns, max_turns_exceeded=True)
        return AgentResult(
            content=final_content or "Maximum turns reached without a final answer.",
            tool_results=all_tool_results,
            turns=turns,
            metadata={
                "max_turns_exceeded": True,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "total_tokens": total_prompt_tokens + total_completion_tokens,
                "finish_reason": "length",
                **(
                    {
                        "performance": {
                            "agent_wall_seconds": round(
                                time.perf_counter() - run_started, 3
                            ),
                            "inference_wall_seconds": round(inference_wall_seconds, 3),
                            "inference_calls": inference_calls,
                            "tool_calls": len(all_tool_results),
                            "prompt_chars": initial_prompt_chars,
                            "first_content_seconds": first_content_seconds,
                            "model_first_content_seconds": model_first_content_seconds,
                            "advertised_tool_count": (
                                len(inference_tools)
                                if not deterministic_routes and not greeting_only
                                else 0
                            ),
                            "registered_tool_count": len(openai_tools),
                        }
                    }
                    if (
                        stream_callback is not None
                        or kwargs.get("max_continuations") == 0
                    )
                    else {}
                ),
            },
        )


__all__ = ["OrchestratorAgent"]
