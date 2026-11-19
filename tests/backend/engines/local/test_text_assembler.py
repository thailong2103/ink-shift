"""Unit tests for comic text line assembly and Japanese text cleaning."""

from __future__ import annotations

from src.backend.engines.local.ocr.text_assembler import (
    ParagraphCluster,
    assemble_comic_lines,
    clean_cjk_text,
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



# ---------------------------------------------------------------------------
# Bi-Directional Geometry, Furigana & Square CJK Tests (Phase 46 / ADR-019)
# ---------------------------------------------------------------------------


def test_clean_cjk_text_chinese_and_japanese() -> None:
    """clean_cjk_text strips inter-character spaces in both Chinese and Japanese."""
    assert clean_cjk_text("你 好 世 界 ！") == "你好世界！"
    assert clean_cjk_text("こ ん に ち は") == "こんにちは"
    assert clean_cjk_text("这是 Apple Pro 测 试") == "这是 Apple Pro 测试"


def test_classify_box_orientation() -> None:
    """classify_box_orientation detects vertical, horizontal, and square quads."""
    from src.backend.engines.local.ocr.text_assembler import classify_box_orientation

    assert classify_box_orientation([[0, 0], [30, 0], [30, 120], [0, 120]]) == "vertical"
    assert classify_box_orientation([[0, 0], [180, 0], [180, 30], [0, 30]]) == "horizontal"
    assert classify_box_orientation([[0, 0], [50, 0], [50, 50], [0, 50]]) == "square"


def test_filter_furigana_boxes_removes_thin_ruby_right_of_column() -> None:
    """Thin Ruby strips immediately right of vertical main columns must be filtered out."""
    from src.backend.engines.local.ocr.text_assembler import filter_furigana_boxes, parse_ocr_entry

    col1 = parse_ocr_entry([[100, 10], [140, 10], [140, 200], [100, 200]], "漢字本文", 0.99)
    col2 = parse_ocr_entry([[40, 10], [80, 10], [80, 200], [40, 200]], "次の列だ", 0.99)
    ruby = parse_ocr_entry([[144, 20], [156, 20], [156, 120], [144, 120]], "かんじ", 0.90)
    assert col1 and col2 and ruby

    filtered = filter_furigana_boxes([col1, ruby, col2])
    assert [b["text"] for b in filtered] == ["漢字本文", "次の列だ"]


def test_order_bubble_lines_bidirectional_vertical_rtl() -> None:
    """Vertical columns inside a bubble must read Right-to-Left, Top-to-Bottom."""
    from src.backend.engines.local.ocr.text_assembler import order_bubble_lines_bidirectional, parse_ocr_entry

    right_col = parse_ocr_entry([[120, 20], [155, 20], [155, 180], [120, 180]], "右の列", 0.99)
    left_col = parse_ocr_entry([[60, 20], [95, 20], [95, 180], [60, 180]], "左の列", 0.99)
    assert right_col and left_col

    text, direction = order_bubble_lines_bidirectional([left_col, right_col])
    assert direction == "vertical"
    assert text == "右の列左の列"


def test_is_ambiguous_square_cjk_bubble() -> None:
    """Detects tight 3x3 Chinese grid mis-split on vertically oriented manga pages."""
    from src.backend.engines.local.ocr.text_assembler import is_ambiguous_square_cjk_bubble, parse_ocr_entry

    rows = [
        parse_ocr_entry([[100, 100], [230, 100], [230, 136], [100, 136]], "救别你", 0.7),
        parse_ocr_entry([[100, 144], [230, 144], [230, 180], [100, 180]], "命过是", 0.7),
        parse_ocr_entry([[100, 188], [230, 188], [230, 224], [100, 224]], "啊来谁", 0.7),
    ]
    clean_rows = [r for r in rows if r is not None]
    assert is_ambiguous_square_cjk_bubble(clean_rows, page_dominant_vertical=True) is True
    assert is_ambiguous_square_cjk_bubble(clean_rows, page_dominant_vertical=False) is False

    # Pure English lines must NOT trigger Chinese 3x3 guard even on square bbox
    en_rows = [
        parse_ocr_entry([[100, 100], [230, 100], [230, 136], [100, 136]], "WAIT", 0.99),
        parse_ocr_entry([[100, 144], [230, 144], [230, 180], [100, 180]], "HERE", 0.99),
    ]
    assert is_ambiguous_square_cjk_bubble([r for r in en_rows if r is not None], page_dominant_vertical=True) is False


def test_cluster_lines_bidirectional_mixed_vertical_and_horizontal() -> None:
    """Mixed vertical narration columns and horizontal footnote paragraphs cluster independently."""
    from src.backend.engines.local.ocr.text_assembler import cluster_lines_bidirectional

    raw_lines = [
        # Vertical RTL narration block on right side
        [[[850.0, 100.0], [890.0, 100.0], [890.0, 400.0], [850.0, 400.0]], "今日は", 0.99],
        [[[790.0, 100.0], [830.0, 100.0], [830.0, 400.0], [790.0, 400.0]], "いい天気", 0.99],
        # Horizontal English footnote at bottom
        [[[100.0, 800.0], [500.0, 800.0], [500.0, 825.0], [100.0, 825.0]], "Editor note line 1", 0.98],
        [[[100.0, 840.0], [450.0, 840.0], [450.0, 865.0], [100.0, 865.0]], "Editor note line 2", 0.97],
    ]
    clusters = cluster_lines_bidirectional(raw_lines, image_width=1000, image_height=1000)
    assert len(clusters) == 2

    vert = [c for c in clusters if c.direction == "vertical"]
    horiz = [c for c in clusters if c.direction == "horizontal"]
    assert len(vert) == 1
    assert len(horiz) == 1
    assert vert[0].text == "今日はいい天気"
    assert horiz[0].text == "Editor note line 1 Editor note line 2"


# ---------------------------------------------------------------------------
# Phase 47 / Option A: 2D Spatial Clustering & Panel/Bubble Barrier Tests
# ---------------------------------------------------------------------------


def test_cluster_vertical_does_not_bridge_distant_same_column_across_panels() -> None:
    """Vertically distant boxes in the same X column across panels must stay separate."""
    from src.backend.engines.local.ocr.text_assembler import cluster_lines_bidirectional

    raw_lines = [
        [[[110.0, 132.0], [150.0, 132.0], [150.0, 230.0], [110.0, 230.0]], "上のコマ", 0.92],
        [[[112.0, 598.0], [152.0, 598.0], [152.0, 707.0], [112.0, 707.0]], "中のコマ", 0.90],
        [[[108.0, 915.0], [148.0, 915.0], [148.0, 999.0], [108.0, 999.0]], "下のコマ", 0.91],
    ]
    clusters = cluster_lines_bidirectional(raw_lines, image_width=1000, image_height=1000)

    assert len(clusters) == 3
    assert all((c.box_2d[2] - c.box_2d[0]) < 200 for c in clusters)


def test_cluster_horizontal_does_not_bridge_distant_same_row() -> None:
    """Horizontally distant boxes sharing the same Y band must not merge into one bar."""
    from src.backend.engines.local.ocr.text_assembler import cluster_lines_bidirectional

    raw_lines = [
        [[[50.0, 200.0], [250.0, 200.0], [250.0, 225.0], [50.0, 225.0]], "Left panel text", 0.95],
        [[[600.0, 200.0], [850.0, 200.0], [850.0, 225.0], [600.0, 225.0]], "Right panel text", 0.96],
    ]
    clusters = cluster_lines_bidirectional(raw_lines, image_width=1000, image_height=1000)

    assert len(clusters) == 2
    assert {c.text for c in clusters} == {"Left panel text", "Right panel text"}


def test_cluster_vertical_merges_same_column_split_by_small_gap() -> None:
    """Split segments stacked inside the same vertical column must merge cleanly."""
    from src.backend.engines.local.ocr.text_assembler import cluster_lines_bidirectional

    raw_lines = [
        [[[200.0, 100.0], [235.0, 100.0], [235.0, 220.0], [200.0, 220.0]], "上から", 0.97],
        [[[202.0, 240.0], [235.0, 240.0], [235.0, 340.0], [202.0, 340.0]], "下に", 0.96],
    ]
    clusters = cluster_lines_bidirectional(raw_lines, image_width=1000, image_height=1000)

    assert len(clusters) == 1
    assert clusters[0].direction == "vertical"
    assert clusters[0].text == "上から下に"
    assert clusters[0].box_2d == (100, 200, 340, 235)


def test_cluster_respects_panel_barrier_including_inset_panel() -> None:
    """Adjacent columns separated by a panel or inset-panel boundary must never merge."""
    from src.backend.engines.local.ocr.text_assembler import cluster_lines_bidirectional

    # Adjacent side-by-side panels
    split_lines = [
        [[[460.0, 100.0], [490.0, 100.0], [490.0, 300.0], [460.0, 300.0]], "左枠の文字", 0.95],
        [[[510.0, 100.0], [540.0, 100.0], [540.0, 300.0], [510.0, 300.0]], "右枠の文字", 0.95],
    ]
    split_panels = [(0, 0, 500, 495), (0, 505, 500, 1000)]
    split_clusters = cluster_lines_bidirectional(
        split_lines,
        image_width=1000,
        image_height=1000,
        panel_boxes=split_panels,
    )
    assert len(split_clusters) == 2

    # Inset panel nested inside outer panel
    inset_lines = [
        [[[550.0, 250.0], [585.0, 250.0], [585.0, 450.0], [550.0, 450.0]], "内枠", 0.94],
        [[[610.0, 250.0], [645.0, 250.0], [645.0, 450.0], [610.0, 450.0]], "外枠", 0.94],
    ]
    inset_panels = [(0, 0, 900, 900), (200, 200, 600, 600)]
    inset_clusters = cluster_lines_bidirectional(
        inset_lines,
        image_width=1000,
        image_height=1000,
        panel_boxes=inset_panels,
    )
    assert len(inset_clusters) == 2


def test_cluster_respects_bubble_barrier_and_filters_bubble_overlap() -> None:
    """Merge is blocked when union overlaps a speech bubble (>25%), and overlapping residuals (>30%) drop."""
    from src.backend.engines.local.ocr.text_assembler import cluster_lines_bidirectional

    bubble_boxes = [(140, 200, 280, 240)]
    flanking_lines = [
        [[[150.0, 120.0], [195.0, 120.0], [195.0, 300.0], [150.0, 300.0]], "左側の文", 0.95],
        [[[245.0, 120.0], [290.0, 120.0], [290.0, 300.0], [245.0, 300.0]], "右側の文", 0.95],
    ]
    clusters = cluster_lines_bidirectional(
        flanking_lines,
        image_width=1000,
        image_height=1000,
        panel_boxes=[(0, 0, 1000, 1000)],
        bubble_boxes=bubble_boxes,
    )
    assert len(clusters) == 2

    # Standalone residual box inside/overlapping >30% of the speech bubble must be dropped
    overlapping_lines = [
        *flanking_lines,
        [[[202.0, 150.0], [238.0, 150.0], [238.0, 270.0], [202.0, 270.0]], "重複残余", 0.95],
    ]
    filtered_clusters = cluster_lines_bidirectional(
        overlapping_lines,
        image_width=1000,
        image_height=1000,
        panel_boxes=[(0, 0, 1000, 1000)],
        bubble_boxes=bubble_boxes,
    )
    assert len(filtered_clusters) == 2
    assert {c.text for c in filtered_clusters} == {"右側の文", "左側の文"}
