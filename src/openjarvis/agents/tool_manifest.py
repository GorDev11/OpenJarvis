"""Conservative per-request tool manifest selection for local Orchestrator inference.

Registered tools and the ToolExecutor are NEVER changed. On a narrowly
recognized arithmetic expression, advertising only calculator avoids
unnecessary function-schema prefill on CPU/GPU hybrid models. A fully
self-contained optimization problem needs model reasoning rather than an
external action, so it can omit schemas for that turn. Any ambiguous,
external-data, multi-tool, or genuinely contextual task keeps the full tool
manifest. Do not use this to bypass tool approvals or capability policy.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

_MATH_TASK = re.compile(
    r"\b(?:calculat\w*|comput\w*|arithmetic|knapsack|"
    r"optimis\w*|optimiz\w*|sum\b|profit\b|"
    r"вычисл\w*|рассчита\w*|посчита\w*|прибыл\w*|"
    r"математик\w*)\b"
    r"|(?:հաշվ\w*|շահույթ\w*|գումար\w*|մաթեմատիկ\w*|"
    r"համադրությ\w*|առավելագույն\s+շահույթ)",
    re.IGNORECASE,
)

_OPTIMIZATION_TASK = re.compile(
    r"\b(?:knapsack|optimis\w*|optimiz\w*|profit\w*|combination\w*|"
    r"прибыл\w*|комбинац\w*|оптимиз\w*)\b"
    r"|(?:շահույթ\w*|համադրությ\w*|առավելագույն\s+շահույթ|օպտիմալ\w*)",
    re.IGNORECASE,
)

# If a request might need data or another action, expose ALL tools rather
# than making a wrong routing decision. Also check explicit tool names below.
_EXTERNAL_OR_ACTION = re.compile(
    r"\b(?:search|browse|internet|online|website|web|current|latest|today|"
    r"live|news|mail|email|calendar|file|folder|document|drive|"
    r"upload|download|install|open|run|execute|shell|terminal|"
    r"network|system|windows|device|diagnos\w*|"
    r"гугл\w*|интернет\w*|сайт\w*|поиск\w*|найди|"
    r"файл\w*|письм\w*|скача\w*|установ\w*|запуст\w*|"
    r"команд\w*|систем\w*|сет\w*)\b"
    r"|(?:ինտերնետ|կայք|որոնիր|գտիր|այսօր|վերջին|նորություններ|"
    r"ֆայլ|թղթապանակ|նամակ|օրացույց|ներբեռնի|տեղադրի|"
    r"բացիր|գործարկիր|համակարգիչ|համակարգի|ցանց)",
    re.IGNORECASE,
)


def select_request_tool_manifest(
    user_input: str,
    tools: Sequence[dict[str, Any]],
    *,
    has_conversation_context: bool = False,
) -> list[dict[str, Any]]:
    """Choose a minimal manifest only for unambiguous, self-contained math.

    All other prompts retain all tool definitions, including code execution,
    file tools, MCP tools, etc., subject to existing security approvals.
    """
    full_manifest = list(tools)
    if not full_manifest:
        return full_manifest

    text = " ".join((user_input or "").split())
    # Without supplied numeric inputs a "calculate" request may require
    # retrieving data first. Do not narrow its available tool choices.
    if not text or not re.search(r"[0-9]", text) or not _MATH_TASK.search(text):
        return full_manifest
    if _EXTERNAL_OR_ACTION.search(text):
        return full_manifest
    # Greeting-prefixed instructions are mixed-intent turns. Retain the full
    # manifest rather than guessing from one mathematical verb.
    if re.match(
        r"^(?:hello|hi|hey|привет|բարև|բարեւ)\s*[,，،]",
        text,
        re.IGNORECASE,
    ):
        return full_manifest

    by_name = {
        definition.get("function", {}).get("name"): definition
        for definition in full_manifest
        if isinstance(definition, dict) and isinstance(definition.get("function"), dict)
    }
    calculator = by_name.get("calculator")
    if calculator is None:
        return full_manifest

    # A request explicitly mentioning a different tool must not hide it.
    for name in by_name:
        if (
            name != "calculator"
            and name
            and re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text, re.IGNORECASE)
        ):
            return full_manifest

    optimization_task = bool(_OPTIMIZATION_TASK.search(text))
    numeric_inputs = re.findall(r"(?<!\w)[+-]?(?:\d+(?:[.,]\d+)?)(?!\w)", text)

    # A follow-up normally keeps every capability because earlier turns may
    # change the current instruction. A fully specified optimization prompt
    # is the safe exception: multiple numeric inputs plus optimization intent
    # make it independent of earlier chat, and calculator cannot solve the
    # combinatorial reasoning by itself. Omitting schemas here avoids a slow,
    # unnecessary tool-call turn while leaving every registered tool intact
    # for subsequent requests.
    if has_conversation_context and not (
        optimization_task and len(numeric_inputs) >= 2
    ):
        return full_manifest

    if optimization_task and len(numeric_inputs) >= 2:
        return []

    return [calculator]


__all__ = ["select_request_tool_manifest"]
