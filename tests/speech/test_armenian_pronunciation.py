"""Pure pronunciation tests; no model downloads or GPU needed."""

from openjarvis.speech.armenian_pronunciation import normalize_armenian_speech


def test_known_names_inside_armenian_prose():
    original = "Ես օգտագործում եմ ChatGPT, Gemini, AI և OpenJarvis։"
    assert normalize_armenian_speech(original) == (
        "Ես օգտագործում եմ Չաթ Ջի Փի Թի, Ջեմինի, Էյ Այ և Օփեն Ջարվիս։"
    )


def test_armenian_suffixes_and_case_insensitive_names():
    original = "ChatGPT-ի ու OpenJarvis-ում աշխատող AI-ն օգնում են։"
    assert normalize_armenian_speech(original) == (
        "Չաթ Ջի Փի Թի-ի ու Օփեն Ջարվիս-ում աշխատող Էյ Այ-ն օգնում են։"
    )
    assert normalize_armenian_speech("Փորձարկիր chatgpt-ը և GEMINI-ն։") == (
        "Փորձարկիր Չաթ Ջի Փի Թի-ը և Ջեմինի-ն։"
    )


def test_home_automation_abbreviations():
    text = "ESP32, Wi-Fi, MQTT, CPU և GPU համակարգերը։"
    assert normalize_armenian_speech(text) == (
        "Ի Էս Փի երեսուներկու, Վայֆայ, Էմ Քյու Թի Թի, "
        "Սի Փի Յու և Ջի Փի Յու համակարգերը։"
    )


def test_unknown_latin_tokens_spelled_as_letters_only_with_armenian():
    assert normalize_armenian_speech("Սա XYZ համակարգն է։") == (
        "Սա Էքս Վայ Զեդ համակարգն է։"
    )
    assert normalize_armenian_speech("An unknown English phrase") == (
        "An unknown English phrase"
    )


def test_urls_emails_and_versions_are_not_modified():
    text = (
        "Տե՛ս https://example.org/AI կամ me@openjarvis.dev, ինչպես նաև v1.2 տարբերակը։"
    )
    assert normalize_armenian_speech(text) == text


def test_no_change_for_armenian_only_or_empty_text():
    for text in ("", "Բարև, ես Ջարվիսն եմ։", "   "):
        assert normalize_armenian_speech(text) == text
