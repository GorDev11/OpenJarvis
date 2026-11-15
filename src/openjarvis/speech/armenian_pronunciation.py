"""Pronunciation-only Latin-name normalization for Armenian Pocket-TTS.

The visible chat text is never changed. Only the string handed to the
Armenian voice model is rewritten. The lexicon is deliberately conservative:
common tech names are mapped to readable Armenian approximations; unknown
Latin words in an Armenian passage are spelled as letters rather than being
assigned a speculative English pronunciation.
"""

from __future__ import annotations

import re

# Case-insensitive whole Latin tokens; hyphenated or dotted product names stay
# together (for example, Wi-Fi and Node.js). Armenian suffixes remain intact.
_LATIN_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9]*(?:[._+-][A-Za-z0-9]+)*")
_ARMENIAN = re.compile(r"[\u0531-\u0556\u0561-\u0587]")
_PROTECTED = re.compile(
    r"(?:https?://|www\.)\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    re.IGNORECASE,
)

# These are spoken forms, NOT translations. Prefer recognizable names and
# leave standard Armenian context untouched.
_PRONUNCIATIONS: dict[str, str] = {
    "ai": "Էյ Այ",
    "openai": "Օփեն Էյ Այ",
    "chatgpt": "Չաթ Ջի Փի Թի",
    "gpt": "Ջի Փի Թի",
    "gemini": "Ջեմինի",
    "openjarvis": "Օփեն Ջարվիս",
    "jarvis": "Ջարվիս",
    "openclaw": "Օփեն Քլո",
    "claude": "Քլոդ",
    "deepseek": "Դիփսիք",
    "qwen": "Քուեն",
    "kimi": "Քիմի",
    "ollama": "Օլամա",
    "google": "Գուգլ",
    "github": "Գիթհաբ",
    "git": "Գիթ",
    "windows": "Վինդոուզ",
    "microsoft": "Մայքրոսոֆթ",
    "chrome": "Քրոմ",
    "python": "Փայթոն",
    "javascript": "Ջավասքրիփթ",
    "typescript": "Թայփսքրիփթ",
    "node.js": "Նոուդ Ջեյ Էս",
    "next.js": "Նեքսթ Ջեյ Էս",
    "react": "Ռիաքթ",
    "docker": "Դոքեր",
    "linux": "Լինուքս",
    "iphone": "Այֆոն",
    "ios": "Այ Օ Էս",
    "android": "Անդրոիդ",
    "telegram": "Տելեգրամ",
    "whatsapp": "Վոթսափ",
    "youtube": "Յութուբ",
    "facebook": "Ֆեյսբուք",
    "wifi": "Վայֆայ",
    "wi-fi": "Վայֆայ",
    "mqtt": "Էմ Քյու Թի Թի",
    "esp32": "Ի Էս Փի երեսուներկու",
    "api": "Էյ Փի Այ",
    "json": "Ջեյսոն",
    "http": "Էյչ Թի Թի Փի",
    "https": "Էյչ Թի Թի Փի Էս",
    "html": "Էյչ Թի Էմ Էլ",
    "css": "Սի Էս Էս",
    "usb": "Յու Էս Բի",
    "cpu": "Սի Փի Յու",
    "gpu": "Ջի Փի Յու",
    "nvidia": "Էնվիդիա",
    "rtx": "Ար Թի Էքս",
    "tts": "Թի Թի Էս",
    "stt": "Էս Թի Թի",
    "llm": "Էլ Էլ Էմ",
    "ui": "Յու Այ",
    "ux": "Յու Էքս",
    "iot": "Այ Օ Թի",
}

_ENGLISH_LETTERS = {
    "a": "Էյ", "b": "Բի", "c": "Սի", "d": "Դի", "e": "Ի",
    "f": "Էֆ", "g": "Ջի", "h": "Էյչ", "i": "Այ", "j": "Ջեյ",
    "k": "Քեյ", "l": "Էլ", "m": "Էմ", "n": "Էն", "o": "Օ",
    "p": "Փի", "q": "Քյու", "r": "Ար", "s": "Էս", "t": "Թի",
    "u": "Յու", "v": "Վի", "w": "Դաբլյու", "x": "Էքս",
    "y": "Վայ", "z": "Զեդ",
}
_DIGITS = {
    "0": "զրո", "1": "մեկ", "2": "երկու", "3": "երեք",
    "4": "չորս", "5": "հինգ", "6": "վեց", "7": "յոթ",
    "8": "ութ", "9": "ինը",
}


def normalize_armenian_speech(text: str) -> str:
    """Prepare mixed Armenian/Latin text for Armenian-only synthesis.

    Known names get their conventional Armenian spoken forms. In an Armenian
    passage, an unknown Latin word is spelled out as a last resort instead of
    feeding unsupported Latin graphemes to the Armenian tokenizer. Plain
    English paragraphs, links and email addresses are left untouched.
    """
    if not text or not _LATIN_TOKEN.search(text):
        return text

    has_armenian = bool(_ARMENIAN.search(text))

    def pronounce(match: re.Match[str]) -> str:
        token = match.group()
        known = _PRONUNCIATIONS.get(token.casefold())
        if known:
            return known

        # Preserve paths, domains, file extensions, versions, and unusual
        # punctuation rather than inventing a pronunciation.
        if "." in token or "_" in token or "+" in token:
            return token
        if not has_armenian:
            return token
        if len(token) > 32:
            return token

        letters = [_ENGLISH_LETTERS.get(char.lower(), _DIGITS.get(char)) for char in token]
        if any(part is None for part in letters):
            return token
        return " ".join(letters)

    def normalize_segment(segment: str) -> str:
        return _LATIN_TOKEN.sub(pronounce, segment)

    parts: list[str] = []
    cursor = 0
    for protected in _PROTECTED.finditer(text):
        parts.append(normalize_segment(text[cursor : protected.start()]))
        parts.append(protected.group())
        cursor = protected.end()
    parts.append(normalize_segment(text[cursor:]))
    return "".join(parts)
