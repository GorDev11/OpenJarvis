"""Per-request tool manifest routing must preserve full Orchestrator access."""

from __future__ import annotations

import pytest

from openjarvis.agents.tool_manifest import select_request_tool_manifest


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
