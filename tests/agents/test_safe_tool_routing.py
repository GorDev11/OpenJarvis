"""Conservative multilingual routing for reviewed read-only diagnostics."""

from __future__ import annotations

import pytest

from openjarvis.agents.safe_tool_routing import select_safe_tool_routes


@pytest.mark.parametrize(
    "query",
    [
        "Ստուգիր իմ ինտերնետ կապը և ցույց տուր միացված սարքերը",
        "Проверь мой интернет и DNS",
        "Check my network connection and gateway",
    ],
)
def test_routes_explicit_network_diagnostics_in_three_languages(query: str) -> None:
    routes = select_safe_tool_routes(query, ["network_diagnostics"])
    assert [(route.name, route.arguments) for route in routes] == [
        ("network_diagnostics", "{}")
    ]


@pytest.mark.parametrize(
    "query",
    [
        "Ջարվիս, ստուգիր իմ համակարգիչը՝ CPU, RAM, GPU և սկավառակները",
        "Проверь компьютер, процессы и системные ошибки Windows",
        "Inspect my computer CPU, RAM, GPU, disks, and services",
    ],
)
def test_routes_explicit_system_diagnostics_in_three_languages(query: str) -> None:
    routes = select_safe_tool_routes(query, ["system_diagnostics"])
    assert [route.name for route in routes] == ["system_diagnostics"]


def test_combined_request_routes_both_read_only_tools() -> None:
    routes = select_safe_tool_routes(
        "Ստուգիր իմ համակարգիչը և ինտերնետը, գտիր խնդիրները",
        ["network_diagnostics", "system_diagnostics"],
    )
    assert [route.name for route in routes] == [
        "network_diagnostics",
        "system_diagnostics",
    ]


@pytest.mark.parametrize(
    "query",
    [
        "Explain the difference between Ethernet link speed and internet speed",
        "Что такое DNS?",
        "Ի՞նչ է ինտերնետը",
        "Don't check my network; just explain the settings",
        "Մի ստուգիր համակարգիչը, միայն բացատրիր",
    ],
)
def test_does_not_route_explanations_or_negated_requests(query: str) -> None:
    assert not select_safe_tool_routes(
        query,
        ["network_diagnostics", "system_diagnostics"],
    )


def test_never_routes_a_tool_that_is_not_available() -> None:
    assert not select_safe_tool_routes("Check my internet", ["calculator"])
