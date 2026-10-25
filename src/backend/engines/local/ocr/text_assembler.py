"""Text assembly, line clustering, and de-hyphenation for comic dialogue."""

from __future__ import annotations

import re


def assemble_comic_lines(raw_lines: list[str]) -> str:
    """Merge wrapped lines inside a comic speech bubble and resolve hyphenation.

    Rules:
    1. If a line ends with a single hyphen '-' (word hyphenation across lines),
       strip the hyphen and join directly without space (e.g. 'DIS-' + 'APPEAR' -> 'DISAPPEAR').
    2. If a line ends with multiple hyphens (e.g. '--' representing an em-dash/pause),
       preserve the dash and join with a space (e.g. 'WAIT--' + 'NO' -> 'WAIT-- NO').
    3. Standard lines are joined with a single space.
    4. Consecutive internal spaces and leading/trailing whitespace are normalized.

    Args:
        raw_lines: List of text lines inside a single speech bubble.

    Returns:
        Clean, assembled dialogue string ready for translation.
    """
    if not raw_lines:
        return ""

    merged = ""
    for line in raw_lines:
        cleaned = line.strip()
        if not cleaned:
            continue

        if not merged:
            merged = cleaned
            continue

        # Check for trailing hyphens in previously accumulated text
        if merged.endswith("-") and not merged.endswith("--"):
            # De-hyphenate split word across line break
            # Example: "DIS-" + "APPEARED" -> "DISAPPEARED"
            # Example: "under-" + "stand" -> "understand"
            merged = merged[:-1] + cleaned
        else:
            # Regular line join with whitespace
            merged = f"{merged} {cleaned}"

    # Normalize multiple whitespace characters
    merged = re.sub(r"[ \t]+", " ", merged)
    return merged.strip()


def clean_japanese_text(raw_text: str) -> str:
    """Clean Japanese manga OCR transcription.

    Rules:
    1. Removes line breaks and carriage returns.
    2. Removes accidental whitespace between Japanese Kana/Kanji/Punctuation characters
       while preserving intentional spaces between Latin words if present.
    3. Trims leading and trailing whitespace.

    Args:
        raw_text: Raw OCR transcribed Japanese text.

    Returns:
        Normalized Japanese sentence string.
    """
    if not raw_text:
        return ""

    # Replace newlines with spaces
    text = raw_text.replace("\r", " ").replace("\n", " ")

    # Remove whitespace between CJK characters (Hiragana, Katakana, Kanji, fullwidth symbols)
    # CJK range: \u3000-\u30ff (Punctuation, Hiragana, Katakana), \u4e00-\u9fff (Kanji), \uff01-\uffee (Fullwidth)
    cjk_pattern = (
        r"(?<=[\u3000-\u30ff\u4e00-\u9fff\uff01-\uffee])"
        r"\s+"
        r"(?=[\u3000-\u30ff\u4e00-\u9fff\uff01-\uffee])"
    )
    text = re.sub(cjk_pattern, "", text)

    # Normalize remaining spaces
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
