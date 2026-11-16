"""GuardrailsEngine — security-aware inference engine wrapper."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Dict, List, Optional, Sequence

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine, StreamChunk
from openjarvis.security._stubs import BaseScanner
from openjarvis.security.scanner import PIIScanner, SecretScanner
from openjarvis.security.types import RedactionMode, ScanResult


class SecurityBlockError(Exception):
    """Raised when mode is BLOCK and security findings are detected."""


class GuardrailsEngine(InferenceEngine):
    """Wraps an existing ``InferenceEngine`` with security scanning.

    Not registered in ``EngineRegistry`` — instantiated dynamically to wrap
    any engine at runtime.

    Parameters
    ----------
    engine:
        The wrapped inference engine.
    scanners:
        List of scanners to run.  Defaults to ``SecretScanner`` + ``PIIScanner``.
    mode:
        Action taken on findings: WARN, REDACT, or BLOCK.
    scan_input:
        Whether to scan input messages.
    scan_output:
        Whether to scan output content.
    bus:
        Optional event bus for publishing security events.
    """

    def __init__(
        self,
        engine: InferenceEngine,
        *,
        scanners: Optional[List[BaseScanner]] = None,
        mode: RedactionMode = RedactionMode.WARN,
        scan_input: bool = True,
        scan_output: bool = True,
        bus: Optional[EventBus] = None,
        pii_passthrough_tools: Optional[Sequence[str]] = None,
    ) -> None:
        self._engine = engine
        self._scanners: List[BaseScanner] = (
            scanners
            if scanners is not None
            else [
                SecretScanner(),
                PIIScanner(),
            ]
        )
        self._mode = mode
        self._scan_input = scan_input
        self._scan_output = scan_output
        self._bus = bus
        self._pii_passthrough_tools = frozenset(pii_passthrough_tools or ())

    # -- properties ----------------------------------------------------------

    @property
    def engine_id(self) -> str:  # type: ignore[override]
        """Delegate to the wrapped engine."""
        return self._engine.engine_id

    # -- scanning helpers ----------------------------------------------------

    def _scan_text(self, text: str, *, include_pii: bool = True) -> ScanResult:
        """Run all scanners on *text* and merge findings."""
        merged = ScanResult()
        for scanner in self._scanners:
            if not include_pii and getattr(scanner, "scanner_id", "") == "pii":
                continue
            result = scanner.scan(text)
            merged.findings.extend(result.findings)
        return merged

    def _redact_text(self, text: str, *, include_pii: bool = True) -> str:
        """Run all scanners' redact() on *text*."""
        result = text
        for scanner in self._scanners:
            if not include_pii and getattr(scanner, "scanner_id", "") == "pii":
                continue
            result = scanner.redact(result)
        return result

    def _handle_findings(
        self,
        text: str,
        result: ScanResult,
        direction: str,
        *,
        include_pii: bool = True,
    ) -> str:
        """Apply the configured mode to findings.

        Parameters
        ----------
        text:
            The original text.
        result:
            Scan result containing findings.
        direction:
            ``"input"`` or ``"output"`` — used in event data.

        Returns
        -------
        str
            Possibly modified text (unchanged for WARN, redacted for REDACT).

        Raises
        ------
        SecurityBlockError
            If mode is BLOCK.
        """
        finding_dicts = [
            {
                "pattern": f.pattern_name,
                "threat": f.threat_level.value,
                "description": f.description,
            }
            for f in result.findings
        ]

        if self._mode == RedactionMode.WARN:
            if self._bus:
                self._bus.publish(
                    EventType.SECURITY_ALERT,
                    {
                        "direction": direction,
                        "findings": finding_dicts,
                        "mode": "warn",
                    },
                )
            return text

        if self._mode == RedactionMode.REDACT:
            if self._bus:
                self._bus.publish(
                    EventType.SECURITY_ALERT,
                    {
                        "direction": direction,
                        "findings": finding_dicts,
                        "mode": "redact",
                    },
                )
            return self._redact_text(text, include_pii=include_pii)

        # BLOCK mode
        if self._bus:
            self._bus.publish(
                EventType.SECURITY_BLOCK,
                {
                    "direction": direction,
                    "findings": finding_dicts,
                    "mode": "block",
                },
            )
        raise SecurityBlockError(
            f"Security scan blocked {direction}: "
            f"{len(result.findings)} finding(s) detected"
        )

    def _allows_trusted_tool_pii(self, message: Message) -> bool:
        """Allow PII only for explicitly trusted local diagnostic results."""

        return (
            message.role == Role.TOOL
            and bool(message.name)
            and message.name in self._pii_passthrough_tools
        )

    def _has_trusted_tool_pii(self, messages: Sequence[Message]) -> bool:
        """Return whether this turn contains a trusted diagnostic result.

        Historical network results must not disable output PII scanning for a
        later user turn. Only trusted tool messages after the most recent user
        message can ground the response currently being generated.
        """

        last_user_index = max(
            (
                index
                for index, message in enumerate(messages)
                if message.role == Role.USER
            ),
            default=-1,
        )
        return any(
            self._allows_trusted_tool_pii(message)
            for message in messages[last_user_index + 1 :]
        )

    def _prepare_messages(self, messages: Sequence[Message]) -> Sequence[Message]:
        """Apply input policy without mutating the caller's messages."""
        # Scan input messages
        if self._scan_input:
            processed = list(messages)
            for i, msg in enumerate(processed):
                if msg.content:
                    include_pii = not self._allows_trusted_tool_pii(msg)
                    result = self._scan_text(msg.content, include_pii=include_pii)
                    if not result.clean:
                        processed[i] = Message(
                            role=msg.role,
                            content=self._handle_findings(
                                msg.content,
                                result,
                                "input",
                                include_pii=include_pii,
                            ),
                            name=msg.name,
                            tool_calls=msg.tool_calls,
                            tool_call_id=msg.tool_call_id,
                            metadata=msg.metadata,
                            images=msg.images,
                        )
            return processed

        return messages

    # -- InferenceEngine interface -------------------------------------------

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Scan input, call wrapped engine, scan output."""
        trusted_tool_pii = self._has_trusted_tool_pii(messages)
        messages = self._prepare_messages(messages)

        # Call wrapped engine
        response = self._engine.generate(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        # Scan output
        if self._scan_output:
            content = response.get("content", "")
            if content:
                result = self._scan_text(
                    content,
                    include_pii=not trusted_tool_pii,
                )
                if not result.clean:
                    response["content"] = self._handle_findings(
                        content,
                        result,
                        "output",
                        include_pii=not trusted_tool_pii,
                    )

        return response

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Scan input before yielding tokens; scan output post-hoc for alerts."""
        trusted_tool_pii = self._has_trusted_tool_pii(messages)
        messages = self._prepare_messages(messages)
        accumulated = []
        async for token in self._engine.stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            accumulated.append(token)
            yield token

        # Post-hoc scan of accumulated output for logging only
        if self._scan_output:
            full_output = "".join(accumulated)
            if full_output:
                result = self._scan_text(
                    full_output,
                    include_pii=not trusted_tool_pii,
                )
                if not result.clean and self._bus:
                    finding_dicts = [
                        {
                            "pattern": f.pattern_name,
                            "threat": f.threat_level.value,
                            "description": f.description,
                        }
                        for f in result.findings
                    ]
                    self._bus.publish(
                        EventType.SECURITY_ALERT,
                        {
                            "direction": "output",
                            "findings": finding_dicts,
                            "mode": "stream_post_hoc",
                        },
                    )

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator["StreamChunk"]:
        """Scan input before yielding chunks; scan output post-hoc for alerts."""
        trusted_tool_pii = self._has_trusted_tool_pii(messages)
        messages = self._prepare_messages(messages)
        accumulated: list[str] = []
        async for chunk in self._engine.stream_full(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            if chunk.content:
                accumulated.append(chunk.content)
            yield chunk

        # Post-hoc scan of accumulated output
        if self._scan_output:
            full_output = "".join(accumulated)
            if full_output:
                result = self._scan_text(
                    full_output,
                    include_pii=not trusted_tool_pii,
                )
                if not result.clean and self._bus:
                    finding_dicts = [
                        {
                            "pattern": f.pattern_name,
                            "threat": f.threat_level.value,
                            "description": f.description,
                        }
                        for f in result.findings
                    ]
                    self._bus.publish(
                        EventType.SECURITY_ALERT,
                        {
                            "direction": "output",
                            "findings": finding_dicts,
                            "mode": "stream_full_post_hoc",
                        },
                    )

    def list_models(self) -> List[str]:
        """Delegate to wrapped engine."""
        return self._engine.list_models()

    def health(self) -> bool:
        """Delegate to wrapped engine."""
        return self._engine.health()

    def close(self) -> None:
        """Release resources held by the wrapped engine."""
        self._engine.close()


__all__ = ["GuardrailsEngine", "SecurityBlockError"]
