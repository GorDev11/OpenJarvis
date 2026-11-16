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
    # Russian
    r"\bпров(?:ерь|ерить|ерьте)\b",
    r"\bдиагност(?:ируй|ировать|ика|ируйте)\b",
    r"\bпокаж(?:и|ите)\b",
    r"\bнайд(?:и|ите|ти)\b.{0,30}\bпроблем",
    # English
    r"\b(?:check|diagnose|inspect|test|scan|show|find)\b",
)

_NEGATION_PATTERNS = (
    r"\b(?:do\s+not|don't|dont|without)\b",
    r"\b(?:не\s+провер|не\s+диагност|без\s+провер)\w*",
    r"\b(?:մի\s+ստուգ|չստուգ|առանց\s+ստուգ)\w*",
)

_NETWORK_PATTERNS = (
    r"\b(?:internet|network|wi[ -]?fi|lan|dns|gateway)\b",
    r"\b(?:интернет|сет[ьи]|wi[ -]?fi|вайфай|днс|шлюз)\b",
    r"(?:ինտերնետ|ցանց|վայֆայ|wi[ -]?fi|dns|դնս|gateway|շլյուզ)",
    r"(?:միացված|подключенн|connected).{0,25}(?:սարք|устройств|device)",
)

_SYSTEM_PATTERNS = (
    r"\b(?:computer|system|windows|cpu|ram|memory|gpu|disk|drive|process|service|installed\s+(?:apps?|programs?)|event\s+errors?)\b",
    r"\b(?:компьютер|систем|windows|процессор|памят|озу|видеокарт|gpu|диск|процесс|служб|установленн.{0,12}программ|событи.{0,8}ошиб)\w*",
    r"(?:համակարգիչ|համակարգ|windows|պրոցեսոր|cpu|օպերատիվ\s+հիշող|ram|գրաֆիկական|gpu|սկավառակ|գործընթաց|ծառայություն|տեղադրված\s+ծրագր|համակարգային\s+սխալ)",
)


def _matches_any(patterns: tuple[str, ...], text: str) -> bool:
    return any(
        re.search(pattern, text, re.IGNORECASE | re.DOTALL) for pattern in patterns
    )


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
    routes: list[SafeToolRoute] = []
    if "network_diagnostics" in available and _matches_any(_NETWORK_PATTERNS, text):
        routes.append(SafeToolRoute("network_diagnostics"))
    if "system_diagnostics" in available and _matches_any(_SYSTEM_PATTERNS, text):
        routes.append(SafeToolRoute("system_diagnostics"))
    return routes


__all__ = ["SafeToolRoute", "select_safe_tool_routes"]
