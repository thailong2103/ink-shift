"""Unit tests for comic text line assembly and Japanese text cleaning."""

from __future__ import annotations

from src.backend.engines.local.ocr.text_assembler import (
    ParagraphCluster,
    assemble_comic_lines,
    clean_japanese_text,
    cluster_lines_to_paragraphs,
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


# ---------------------------------------------------------------------------
# cluster_lines_to_paragraphs Tests
# ---------------------------------------------------------------------------


def test_cluster_lines_empty() -> None:
    """Empty or corrupt OCR lines should return empty list."""
    assert cluster_lines_to_paragraphs([], 1000, 1000) == []
    assert cluster_lines_to_paragraphs([None, []], 1000, 1000) == []


def test_cluster_lines_single_paragraph() -> None:
    """Consecutive lines with normal line spacing should cluster into 1 paragraph."""
    # Line 1: y=[50..70], x=[100..500]
    # Line 2: y=[85..105] (gap=15px <= 20px), x=[100..450]
    raw_lines = [
        [[[100.0, 50.0], [500.0, 50.0], [500.0, 70.0], [100.0, 70.0]], "This is the first line", 0.98],
        [[[100.0, 85.0], [450.0, 85.0], [450.0, 105.0], [100.0, 105.0]], "of a single paragraph.", 0.96],
    ]
    clusters = cluster_lines_to_paragraphs(raw_lines, image_width=1000, image_height=1000)
    assert len(clusters) == 1
    p = clusters[0]
    assert isinstance(p, ParagraphCluster)
    assert p.text == "This is the first line of a single paragraph."
    # Bounding box envelope: ymin=50, xmin=100, ymax=105, xmax=500
    assert p.box_2d == (50, 100, 105, 500)
    assert p.pixel_box == (50, 100, 105, 500)
    assert p.confidence == 0.97


def test_cluster_lines_multi_paragraph_break() -> None:
    """Large vertical gap between lines should create two distinct paragraph clusters."""
    # Paragraph 1 (lines 1 & 2): y=[50..105]
    # Paragraph 2 (line 3): y=[180..200] (gap = 180 - 105 = 75px >> 20px)
    raw_lines = [
        [[[100.0, 50.0], [500.0, 50.0], [500.0, 70.0], [100.0, 70.0]], "Paragraph one line one.", 0.95],
        [[[100.0, 85.0], [480.0, 85.0], [480.0, 105.0], [100.0, 105.0]], "Paragraph one line two.", 0.95],
        [[[100.0, 180.0], [450.0, 180.0], [450.0, 200.0], [100.0, 200.0]], "Paragraph two standalone line.", 0.92],
    ]
    clusters = cluster_lines_to_paragraphs(raw_lines, image_width=1000, image_height=1000)
    assert len(clusters) == 2
    assert clusters[0].text == "Paragraph one line one. Paragraph one line two."
    assert clusters[0].box_2d == (50, 100, 105, 500)
    assert clusters[1].text == "Paragraph two standalone line."
    assert clusters[1].box_2d == (180, 100, 200, 450)


def test_cluster_lines_japanese_text_normalization() -> None:
    """Clustering with is_ja=True applies clean_japanese_text and eliminates CJK space."""
    raw_lines = [
        [[[50.0, 50.0], [300.0, 50.0], [300.0, 70.0], [50.0, 70.0]], "憲法の前文は、", 0.99],
        [[[50.0, 85.0], [350.0, 85.0], [350.0, 105.0], [50.0, 105.0]], "「日本国民は」で始まる。", 0.99],
    ]
    clusters = cluster_lines_to_paragraphs(raw_lines, image_width=1000, image_height=1000, is_ja=True)
    assert len(clusters) == 1
    assert clusters[0].text == "憲法の前文は、「日本国民は」で始まる。"

