"""Conservative rule-based routing for explicit, read-only diagnostics.

This is a narrow safety net for local models that occasionally answer a clear
diagnostic request in prose instead of emitting a tool call. It deliberately
routes only reviewed, read-only tools with fixed arguments. Ambiguous requests
remain entirely model-routed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SafeToolRoute:
    """A deterministic call to a reviewed read-only tool."""

    name: str
    arguments: str = "{}"


_ACTION_PATTERNS = (
    # Armenian
    r"\bստուգ(?:իր|ել|եք)\b",
    r"\bախտորոշ(?:իր|ել|եք)\b",
    r"\bցույց\s+տ(?:ուր|վեք)\b",
    r"\bգտ(?:իր|նել|եք)\b.{0,30}\bխնդիր",
    r"\b(?:օգտագործ|գործարկ)(?:իր|ել|եք)\b",
    # Russian
    r"\bпров(?:ерь|ерить|ерьте)\b",
    r"\bдиагност(?:ируй|ировать|ика|ируйте)\b",
    r"\bпокаж(?:и|ите)\b",
    r"\bнайд(?:и|ите|ти)\b.{0,30}\bпроблем",
    r"\b(?:используй|использовать|используйте|запусти|запустить|запустите)\b",
    # English
    r"\b(?:check|diagnose|inspect|test|scan|show|find|use|run)\b",
)

_NEGATION_PATTERNS = (
    r"\b(?:do\s+not|don't|dont|without)\b",
    r"\b(?:не\s+(?:провер|диагност|использ|запус)|без\s+провер)\w*",
    r"\b(?:մի\s+(?:ստուգ|օգտագործ|գործարկ)|չ(?:ստուգ|օգտագործ|գործարկ)|առանց\s+ստուգ)\w*",
)

_NETWORK_PATTERNS = (
    r"\b(?:internet|network|wi[ -]?fi|lan|dns|gateway)\b",
    r"\b(?:интернет|сет[ьи]|wi[ -]?fi|вайфай|днс|шлюз)\b",
    r"(?:ինտերնետ|ցանց|վայֆայ|wi[ -]?fi|dns|դնս|gateway|շլյուզ)",
    r"(?:միացված|подключенн|connected).{0,25}(?:սարք|устройств|device)",
)

_SYSTEM_GENERIC_PATTERNS = (
    r"\b(?:computer|system|windows)\b",
    r"\b(?:компьютер|систем|windows)\w*",
    r"(?:համակարգիչ|համակարգ|windows)",
)

_SYSTEM_DETAIL_PATTERNS = (
    r"\b(?:cpu|ram|memory|gpu|disk|drive|process|service|installed\s+(?:apps?|programs?)|event\s+errors?)\b",
    r"\b(?:процессор|памят|озу|видеокарт|gpu|диск|процесс|служб|установленн.{0,12}программ|событи.{0,8}ошиб)\w*",
    r"(?:պրոցեսոր|cpu|օպերատիվ\s+հիշող|ram|գրաֆիկական|gpu|սկավառակ|գործընթաց|ծառայություն|տեղադրված\s+ծրագր|համակարգային\s+սխալ)",
)

_COMBINED_SYSTEM_NETWORK_PATTERNS = (
    (
        r"\b(?:computer|system|windows)\b\s*,?\s+(?:and|plus)\s+"
        r"\b(?:internet|network|wi[ -]?fi|lan|dns|gateway)\b"
    ),
    (
        r"\b(?:internet|network|wi[ -]?fi|lan|dns|gateway)\b\s*,?\s+"
        r"(?:and|plus)\s+\b(?:computer|system|windows)\b"
    ),
    (
        r"\b(?:компьютер|систем|windows)\w*\s*,?\s+и\s+"
        r"\b(?:интернет|сет[ьи]|wi[ -]?fi|вайфай|днс|шлюз)\b"
    ),
    (
        r"\b(?:интернет|сет[ьи]|wi[ -]?fi|вайфай|днс|шлюз)\b\s*,?\s+"
        r"и\s+\b(?:компьютер|систем|windows)\w*"
    ),
    (
        r"(?:համակարգիչ|համակարգ|windows)(?:ը|ն)?\s*,?\s+"
        r"(?:և|եւ|ու)\s+"
        r"(?:ինտերնետ|ցանց|վայֆայ|wi[ -]?fi|dns|դնս|gateway|շլյուզ)"
        r"(?:ը|ն)?"
    ),
    (
        r"(?:ինտերնետ|ցանց|վայֆայ|wi[ -]?fi|dns|դնս|gateway|շլյուզ)"
        r"(?:ը|ն)?\s*,?\s+(?:և|եւ|ու)\s+"
        r"(?:համակարգիչ|համակարգ|windows)(?:ը|ն)?"
    ),
)


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(
        re.search(pattern, text, re.IGNORECASE | re.DOTALL) for pattern in patterns
    )


# Only these standalone social greetings qualify. Anything containing a task,
# a comma followed by instructions, code, a URL, or additional words stays on
# normal tool-capable inference. All tools remain registered and available.
_GREETING_ONLY = re.compile(
    r"(?:բարև(?: ձեզ)?|բարեւ(?: ձեզ)?|ողջույն|привет|здравствуйте|"
    r"добрый день|доброе утро|hello|hi|hey)[!?.։՜՚]*",
    flags=re.IGNORECASE,
)


def is_pure_greeting(user_input: str) -> bool:
    """Skip unnecessary tool schemas for an exact social greeting only.

    Not a separate Fast Chat mode: the caller still uses Orchestrator, its
    usual system prompt, stream, security boundaries and loop guard. We omit
    expensive tool schemas only when there is no requested tool work.
    """
    text = " ".join((user_input or "").casefold().strip().split())
    return bool(_GREETING_ONLY.fullmatch(text))


def select_safe_tool_routes(
    user_input: str,
    available_tools: Iterable[str],
) -> list[SafeToolRoute]:
    """Select unambiguous read-only diagnostics available to the agent.

    The function never routes mutating tools, shell commands, file writes, or
    tools with model-generated arguments. A request must contain both an
    imperative diagnostic action and a matching subject.
    """

    text = " ".join((user_input or "").casefold().split())
    if not text or _matches_any(_NEGATION_PATTERNS, text):
        return []
    if not _matches_any(_ACTION_PATTERNS, text):
        return []

    available = set(available_tools)
    explicitly_named = [
        name
        for name in ("network_diagnostics", "system_diagnostics")
        if name in available and re.search(rf"\b{re.escape(name)}\b", text)
    ]
    if explicitly_named:
        return [SafeToolRoute(name) for name in explicitly_named]

    network_requested = _matches_any(_NETWORK_PATTERNS, text)
    generic_system_requested = _matches_any(_SYSTEM_GENERIC_PATTERNS, text)
    detailed_system_requested = _matches_any(_SYSTEM_DETAIL_PATTERNS, text)
    combined_request = _matches_any(_COMBINED_SYSTEM_NETWORK_PATTERNS, text)

    routes: list[SafeToolRoute] = []
    if "network_diagnostics" in available and network_requested:
        routes.append(SafeToolRoute("network_diagnostics"))
    if "system_diagnostics" in available and (
        detailed_system_requested
        or combined_request
        or (generic_system_requested and not network_requested)
    ):
        routes.append(SafeToolRoute("system_diagnostics"))
    return routes


__all__ = ["SafeToolRoute", "select_safe_tool_routes", "is_pure_greeting"]
