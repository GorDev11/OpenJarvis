"""Per-request tool manifest routing must preserve full Orchestrator access."""

from __future__ import annotations

import pytest

from openjarvis.agents.tool_manifest import (
    is_standalone_knowledge_question,
    select_request_tool_manifest,
)

_ZIGBEE_QUESTION = (
    "Ի՞նչ է Zigbee տեխնոլոգիան, ինչպես է այն աշխատում "
    "և ինչո՞վ է տարբերվում Wi-Fi-ից խելացի տան սարքերում։"
)


def test_independent_memory_classifier_guards_tools_and_context():
    names = ["shell_exec", "web_search"]
    assert is_standalone_knowledge_question("esp 32 ?", tool_names=names)
    assert is_standalone_knowledge_question("Ի՞նչ է MQTT-ն", tool_names=names)
    assert is_standalone_knowledge_question(_ZIGBEE_QUESTION, tool_names=names)
    assert not is_standalone_knowledge_question("Ի՞նչ է սա։", tool_names=names)
    assert not is_standalone_knowledge_question(
        "What is ESP32?", tool_names=names, has_conversation_context=True
    )
    assert not is_standalone_knowledge_question("What is shell_exec?", tool_names=names)
    assert not is_standalone_knowledge_question(
        "What is my temperature?", tool_names=names
    )


def _tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": name, "description": f"Tool {name}."},
        }
        for name in (
            "think",
            "calculator",
            "web_search",
            "network_diagnostics",
            "system_diagnostics",
            "shell_exec",
        )
    ]


@pytest.mark.parametrize(
    "question",
    [
        "esp 32 ?",
        "ESP32?",
        "MQTT?",
        "What is ESP32?",
        "Tell me about ESP32",
        "Explain MQTT",
        "How does a transistor work?",
        "Что такое ESP32?",
        "Объясни MQTT",
        "Ի՞նչ է ESP32-ը",
        "Բացատրիր MQTT-ն",
        "Ինչպես է աշխատում ESP32-ը",
        _ZIGBEE_QUESTION,
    ],
)
def test_standalone_knowledge_skips_tool_schema_prefill(question: str):
    original = _tools()
    assert select_request_tool_manifest(question, original) == []
    assert len(original) == 6  # Orchestrator's capabilities remain installed.


@pytest.mark.parametrize(
    "question",
    [
        "What is the weather in Yerevan today?",
        "What is the latest ESP32 firmware release?",
        "Tell me about my downloaded files",
        "What is the current price of an ESP32?",
        "What is shell_exec?",
        "What is system_diagnostics?",
        "Tell me about the previous answer",
        "What is this?",
        "Open the ESP32 documentation and explain it",
        "Explain how to install ESP32 drivers",
        "Բացատրիր իմ ֆայլը",
        "Ի՞նչ է սա։",
        "Что такое цена ESP32 сегодня?",
        "esp 32 ? please search online",
        "Create file?",
        "Send money?",
    ],
)
def test_dynamic_personal_or_action_requests_keep_full_manifest(question: str):
    original = _tools()
    assert select_request_tool_manifest(question, original) == original


@pytest.mark.parametrize(
    "question",
    ["esp 32 ?", "What is ESP32?", "Ի՞նչ է ESP32-ը"],
)
def test_follow_up_knowledge_keeps_tools_when_context_present(question: str):
    original = _tools()
    assert (
        select_request_tool_manifest(question, original, has_conversation_context=True)
        == original
    )


def test_standalone_knowledge_works_without_calculator():
    original = [t for t in _tools() if t["function"]["name"] != "calculator"]
    assert select_request_tool_manifest("esp 32 ?", original) == []
    assert len(original) == 5


@pytest.mark.parametrize(
    "user_input",
    [
        "Հաշվիր 2+2։",
        "Calculate 21*4.",
        "Рассчитай 15-7.",
    ],
)
def test_standalone_arithmetic_advertises_calculator_only(user_input: str):
    original = _tools()
    result = select_request_tool_manifest(user_input, original)

    assert [tool["function"]["name"] for tool in result] == ["calculator"]
    assert len(original) == 6
    assert [tool["function"]["name"] for tool in original] == [
        "think",
        "calculator",
        "web_search",
        "network_diagnostics",
        "system_diagnostics",
        "shell_exec",
    ]


@pytest.mark.parametrize(
    "user_input",
    [
        "Հաշվիր առավելագույն շահույթը՝ A=8200, B=6210, C=11800, 8 ժամում։",
        "Optimize profit for A=8200, B=6210, C=11800 within 8 hours.",
        "Оптимизируй прибыль: A=8200, B=6210, C=11800 за 8 часов.",
    ],
)
def test_self_contained_optimization_omits_schemas_for_one_turn(user_input: str):
    original = _tools()

    assert select_request_tool_manifest(user_input, original) == []
    assert len(original) == 6


def test_self_contained_optimization_remains_schema_free_in_existing_chat():
    original = _tools()

    assert (
        select_request_tool_manifest(
            "Հաշվիր առավելագույն շահույթը՝ A=8200, B=6210, C=11800, 8 ժամում։",
            original,
            has_conversation_context=True,
        )
        == []
    )


@pytest.mark.parametrize(
    "user_input",
    [
        "Find today's gas price online and calculate my profits",
        "Հաշվիր իմ ծախսերը՝ ըստ այսօրվա բենզինի գնի ինտերնետում",
        "Use shell_exec to calculate 2+2",
        "Calculate profits from an attached file",
        "Calculate my profit without any numbers provided",
        "Рассчитай прибыль, проверь систему Windows",
        "Compute 2+2 with calculator and think",
        "What is the weather today?",
        "",
    ],
)
def test_any_external_or_ambiguous_request_keeps_full_manifest(user_input: str):
    original = _tools()
    assert select_request_tool_manifest(user_input, original) == original


def test_follow_up_math_question_retains_full_tool_access():
    original = _tools()
    assert (
        select_request_tool_manifest(
            "Հաշվիր շահույթը", original, has_conversation_context=True
        )
        == original
    )


def test_underspecified_follow_up_optimization_retains_full_tool_access():
    original = _tools()

    assert (
        select_request_tool_manifest(
            "Հաշվիր 5 պատվերների լավագույն համադրությունը",
            original,
            has_conversation_context=True,
        )
        == original
    )


def test_missing_calculator_never_disables_any_tools():
    original = [item for item in _tools() if item["function"]["name"] != "calculator"]
    assert select_request_tool_manifest("Calculate 2+2", original) == original
