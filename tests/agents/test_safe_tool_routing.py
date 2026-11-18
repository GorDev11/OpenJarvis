"""Conservative multilingual routing for reviewed read-only diagnostics."""

from __future__ import annotations

import pytest

from openjarvis.agents.safe_tool_routing import is_pure_greeting, select_safe_tool_routes


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
        "Օգտագործիր network_diagnostics և system_diagnostics գործիքները",
        "Используй network_diagnostics и system_diagnostics",
        "Use network_diagnostics and system_diagnostics",
    ],
)
def test_explicit_tool_names_accept_use_actions(query: str) -> None:
    routes = select_safe_tool_routes(
        query,
        ["network_diagnostics", "system_diagnostics", "shell_exec"],
    )
    assert [route.name for route in routes] == [
        "network_diagnostics",
        "system_diagnostics",
    ]


@pytest.mark.parametrize(
    "query",
    [
        (
            "Ստուգիր իմ Windows համակարգչի ցանցը network_diagnostics "
            "գործիքով և ցույց տուր IP-ը, gateway-ը ու DNS-ը"
        ),
        "Проверь сеть моего Windows-компьютера инструментом network_diagnostics",
        "Check my Windows computer network with network_diagnostics and show DNS",
    ],
)
def test_explicit_network_tool_does_not_route_system_diagnostics(query: str) -> None:
    routes = select_safe_tool_routes(
        query,
        ["network_diagnostics", "system_diagnostics", "shell_exec"],
    )
    assert [route.name for route in routes] == ["network_diagnostics"]


def test_windows_network_phrase_without_tool_name_does_not_route_system() -> None:
    routes = select_safe_tool_routes(
        "Ստուգիր իմ Windows համակարգչի ցանցը և ցույց տուր gateway-ը ու DNS-ը",
        ["network_diagnostics", "system_diagnostics"],
    )
    assert [route.name for route in routes] == ["network_diagnostics"]


@pytest.mark.parametrize(
    "query",
    [
        "Explain the difference between Ethernet link speed and internet speed",
        "Что такое DNS?",
        "Ի՞նչ է ինտերնետը",
        "Don't check my network; just explain the settings",
        "Մի ստուգիր համակարգիչը, միայն բացատրիր",
        "Մի օգտագործիր network_diagnostics գործիքը",
        "Не используй system_diagnostics",
    ],
)
def test_does_not_route_explanations_or_negated_requests(query: str) -> None:
    assert not select_safe_tool_routes(
        query,
        ["network_diagnostics", "system_diagnostics"],
    )


def test_never_routes_a_tool_that_is_not_available() -> None:
    assert not select_safe_tool_routes("Check my internet", ["calculator"])


@pytest.mark.parametrize(
    "query",
    ["Բարև", "Բարև Ձեզ!", "Բարեւ", "Ողջույն", "Привет!", "Здравствуйте", "Hi", "Hello."],
)
def test_pure_greeting_skips_tool_schemas(query: str) -> None:
    assert is_pure_greeting(query)


@pytest.mark.parametrize(
    "query",
    [
        "Բարև, ստուգիր ինտերնետը",
        "Hello, calculate 2+2",
        "Hi, read my email",
        "Привет, проверь систему",
        "Բարև, բացիր ֆայլը",
        "What is 2+2?",
        "",
    ],
)
def test_real_tasks_never_classified_as_greeting(query: str) -> None:
    assert not is_pure_greeting(query)
