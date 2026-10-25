"""Unit tests for comic text line assembly and Japanese text cleaning."""

from __future__ import annotations

from src.backend.engines.local.ocr.text_assembler import (
    assemble_comic_lines,
    clean_japanese_text,
)

# ---------------------------------------------------------------------------
# assemble_comic_lines Tests
# ---------------------------------------------------------------------------


def test_assemble_comic_lines_empty() -> None:
    """Empty line list must return empty string."""
    assert assemble_comic_lines([]) == ""
    assert assemble_comic_lines(["", "   ", "\t"]) == ""


def test_assemble_comic_lines_standard() -> None:
    """Standard multi-line dialogue should join with single spaces."""
    lines = ["WHAT ARE", "YOU DOING", "HERE?!"]
    assert assemble_comic_lines(lines) == "WHAT ARE YOU DOING HERE?!"


def test_assemble_comic_lines_dehyphenation_uppercase() -> None:
    """Uppercase split words ending with single hyphen must be merged without spaces."""
    lines = ["HE HAS", "DIS-", "APPEARED!"]
    assert assemble_comic_lines(lines) == "HE HAS DISAPPEARED!"


def test_assemble_comic_lines_dehyphenation_lowercase() -> None:
    """Lowercase split words ending with single hyphen must be merged without spaces."""
    lines = ["under-", "stand", "the", "situa-", "tion."]
    assert assemble_comic_lines(lines) == "understand the situation."


def test_assemble_comic_lines_preserves_emdash() -> None:
    """Double hyphens (em-dash/pause) must not be treated as word splits."""
    lines = ["WAIT--", "WHO ARE YOU?"]
    assert assemble_comic_lines(lines) == "WAIT-- WHO ARE YOU?"


def test_assemble_comic_lines_normalizes_whitespace() -> None:
    """Extra leading, trailing, and internal spaces should be normalized cleanly."""
    lines = ["   I DON'T   ", "   KNOW   ", "   WHAT HAPPENED   "]
    assert assemble_comic_lines(lines) == "I DON'T KNOW WHAT HAPPENED"


# ---------------------------------------------------------------------------
# clean_japanese_text Tests
# ---------------------------------------------------------------------------


def test_clean_japanese_text_empty() -> None:
    """Empty string should return empty string."""
    assert clean_japanese_text("") == ""
    assert clean_japanese_text("   \n\t  ") == ""


def test_clean_japanese_text_removes_newlines() -> None:
    """Carriage returns and newlines should be removed."""
    raw = "何をしているの？\r\n早く逃げて！"
    assert clean_japanese_text(raw) == "何をしているの？早く逃げて！"


def test_clean_japanese_text_removes_spaces_between_cjk() -> None:
    """Accidental whitespace between Japanese characters must be removed."""
    raw = "こ ん に ち は 、 私 は ア イ ス が 好 き で す ！"
    assert clean_japanese_text(raw) == "こんにちは、私はアイスが好きです！"


def test_clean_japanese_text_preserves_latin_spaces() -> None:
    """Spaces between Latin words inside mixed Japanese text must be preserved."""
    raw = "これは Apple iPhone 15 Pro です。"
    assert clean_japanese_text(raw) == "これは Apple iPhone 15 Pro です。"
