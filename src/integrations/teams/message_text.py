"""Conservative cleanup of Teams Activity.text before persistence or execution."""
import unicodedata

MAX_MESSAGE_CHARS = 8000
# Remove invisible direction overrides/isolates and common copy/paste artifacts.
# Preserve joiners (U+200C/U+200D), which are meaningful in languages and emoji.
_INVISIBLE_CONTROLS = frozenset("\u061c\u200b\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff")


def clean_message_text(text: str) -> str:
    """Keep user text as data, not HTML; errors contain only fixed reason codes.

    This is input hygiene, not prompt-injection protection. Authorization, code
    validation, and output escaping remain responsible for those boundaries.
    """
    if not isinstance(text, str):
        raise ValueError("invalid_text")
    # Bound the original input too: padding/control removal cannot bypass the cap.
    if len(text) > MAX_MESSAGE_CHARS:
        raise ValueError("text_too_long")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = "".join(
        char for char in text
        if char not in _INVISIBLE_CONTROLS
        and (char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cs"})
    ).strip()
    if not text:
        raise ValueError("empty_text")
    return text
