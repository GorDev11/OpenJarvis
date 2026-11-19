"""Conservative per-request tool manifest selection for local Orchestrator inference.

Registered tools and the ToolExecutor are NEVER changed. On a narrowly
recognized standalone knowledge question or arithmetic expression, only the
necessary schemas are advertised. This avoids
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


# An independent factual question may omit expensive model-facing tool schemas
# while keeping the SAME Orchestrator and all registered tools/permissions.
# Ambiguity, conversation context, external data or actions keep the full list.
_FACTUAL_PREFIX = re.compile(
    r"^(?:what\s+(?:is|are|was|were)\s+|tell\s+me\s+about\s+|"
    r"explain\s+|define\s+|how\s+does\s+.+?\s+work\s*\??|"
    r"что\s+такое\s+|объясни\s+|расскажи\s+(?:о|об)\s+|"
    r"(?:ի՞նչ|ինչ)\s+է\s+|բացատրիր\s+|ինչպես\s+է\s+աշխատում\s+)",
    re.IGNORECASE,
)
# Conservative shorthand for device/protocol names, e.g. "esp 32 ?" / "MQTT?".
_SHORT_FACTUAL_TOPIC = re.compile(
    r"^(?:[a-z]{2,12}\s*\d{1,5}|[A-Z][A-Z0-9+#-]{1,14}|"
    r"python|javascript|typescript|linux|docker|esp32|mqtt|arduino|zigbee|"
    r"bluetooth)\s*\?$",
    re.IGNORECASE,
)
_LIVE_OR_PERSONAL_DATA = re.compile(
    r"\b(?:now|today|tomorrow|yesterday|latest|current|recent|newest|"
    r"weather|forecast|prices?|stocks?|exchange|availability|buy|purchase|"
    r"shop|best|top|reviews?|releases?|updates?|nearby|github|my|our|"
    r"your|mine|ours|"
    r"сейчас|сегодня|завтра|вчера|последн\w*|актуальн\w*|"
    r"погод\w*|цен\w*|купить|новост\w*|мой|мо[еяию]|наши?\w*)\b"
    r"|(?:այսօր|վաղը|երեկ|հիմա|ներկայում|վերջին|նորագույն|"
    r"եղանակ|գին|արժեք|գնելու|գնել|լուրեր|թարմացում|"
    r"լավագույն|իմ|մեր|քո)",
    re.IGNORECASE,
)
_CONTEXT_REFERENCE = re.compile(
    r"\b(?:this|that|these|those|it|above|previous|same|"
    r"это|этот|эта|эти|выше|предыдущ\w*)\b"
    r"|(?:սա|դա|այս|նախորդ|վերևի)",
    re.IGNORECASE,
)
_POSSIBLE_ACTION = re.compile(
    r"\b(?:send|delete|remove|create|edit|write|modify|post|publish|"
    r"schedule|message|read|save|set|change|fix|start|stop|turn|"
    r"enable|disable|connect|check|show|make|use|run|print|copy|move|"
    r"rename|share|invite|call|pay|order|book|"
    r"удали\w*|отправ\w*|созда\w*|измен\w*|запиши\w*|"
    r"настро\w*|открой\w*|включ\w*|выключ\w*)\b"
    r"|(?:ուղարկ|ջնջ|ստեղծ|փոխիր|գրիր|կարգավոր|բացիր|"
    r"միացրու|անջատիր|պահպանիր|պատվիր|զանգիր)",
    re.IGNORECASE,
)


def _is_standalone_knowledge_question(
    text: str,
    tools: Sequence[dict[str, Any]],
    *,
    has_conversation_context: bool,
) -> bool:
    """Omit tool schemas only for independent, clearly informational input."""
    if has_conversation_context or not text or len(text) > 240:
        return False
    if (
        _EXTERNAL_OR_ACTION.search(text)
        or _LIVE_OR_PERSONAL_DATA.search(text)
        or _CONTEXT_REFERENCE.search(text)
        or _POSSIBLE_ACTION.search(text)
    ):
        return False

    # Explicit tool name is always a reason to advertise the whole manifest.
    for definition in tools:
        function = definition.get("function") if isinstance(definition, dict) else None
        name = function.get("name", "") if isinstance(function, dict) else ""
        if name and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
            return False

    return bool(_SHORT_FACTUAL_TOPIC.fullmatch(text) or _FACTUAL_PREFIX.match(text))


def select_request_tool_manifest(
    user_input: str,
    tools: Sequence[dict[str, Any]],
    *,
    has_conversation_context: bool = False,
) -> list[dict[str, Any]]:
    """Select a minimal safe manifest for independent knowledge or math.

    All other prompts retain all tool definitions, including code execution,
    file tools, MCP tools, etc., subject to existing security approvals.
    """
    full_manifest = list(tools)
    if not full_manifest:
        return full_manifest

    text = " ".join((user_input or "").split())
    # No tool capability is removed: only the model-facing JSON schema is
    # omitted for a clearly self-contained factual question.
    if _is_standalone_knowledge_question(
        text, full_manifest, has_conversation_context=has_conversation_context
    ):
        return []
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
