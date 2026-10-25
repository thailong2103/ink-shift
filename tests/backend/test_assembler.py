"""Unit tests for detection assembler and safe-zone block construction."""

from __future__ import annotations

from src.backend.detection.assembler import (
    assemble_translated_blocks,
    compute_safe_render_box,
    prepare_local_work_items,
)
from src.backend.detection.base import DetectedBubble, DetectedText


def test_compute_safe_render_box_simple_polygon() -> None:
    """Simple 4-vertex bounding box polygon should not calculate complex expansion."""
    simple_bubble = DetectedBubble(
        id="1",
        box_2d=(100, 100, 300, 400),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.95,
    )
    render_box, is_safe_child = compute_safe_render_box(simple_bubble)
    assert render_box == (100, 100, 300, 400)
    assert is_safe_child is False


def test_compute_safe_render_box_complex_polygon_with_single_text() -> None:
    """Complex polygon (>4 vertices) with single child text should compute safe expanded box."""
    complex_poly = [
        (20.0, 0.0),
        (80.0, 0.0),
        (100.0, 50.0),
        (80.0, 100.0),
        (20.0, 100.0),
        (0.0, 50.0),
    ]
    bubble = DetectedBubble(
        id="2",
        box_2d=(100, 100, 500, 500),
        polygon=complex_poly,
        confidence=0.92,
        texts=[DetectedText(box_2d=(250, 250, 350, 350), confidence=0.88)],
    )
    render_box, is_safe_child = compute_safe_render_box(bubble)
    assert isinstance(render_box, tuple)
    assert len(render_box) == 4
    # Expanded box inside polygon must stay within bubble outer box
    ymin, xmin, ymax, xmax = render_box
    assert ymin >= 100
    assert xmin >= 100
    assert ymax <= 500
    assert xmax <= 500
    assert is_safe_child is True


def test_compute_safe_render_box_complex_polygon_without_text() -> None:
    """Complex polygon with no child texts should seed from bubble center."""
    complex_poly = [
        (10.0, 0.0),
        (90.0, 0.0),
        (100.0, 50.0),
        (90.0, 100.0),
        (10.0, 100.0),
        (0.0, 50.0),
    ]
    bubble = DetectedBubble(
        id="3",
        box_2d=(100, 100, 400, 400),
        polygon=complex_poly,
        confidence=0.9,
        texts=[],
    )
    render_box, is_safe_child = compute_safe_render_box(bubble)
    assert len(render_box) == 4
    assert is_safe_child is True


def test_prepare_local_work_items_multi_child() -> None:
    """Merged bubble with multiple child texts produces distinct child work items."""
    complex_poly = [
        (0.0, 0.0),
        (50.0, 0.0),
        (100.0, 0.0),
        (100.0, 100.0),
        (50.0, 100.0),
        (0.0, 100.0),
    ]
    bubble = DetectedBubble(
        id="bubble_merged",
        box_2d=(100, 100, 600, 600),
        polygon=complex_poly,
        confidence=0.94,
        texts=[
            DetectedText(box_2d=(120, 120, 200, 200), confidence=0.85),
            DetectedText(box_2d=(400, 400, 500, 500), confidence=0.89),
        ],
    )
    items = prepare_local_work_items([bubble])
    assert len(items) == 2
    assert items[0].is_child is True
    assert items[0].child_index == 0
    assert items[0].parent_bubble.id == "bubble_merged"
    assert items[1].is_child is True
    assert items[1].child_index == 1


def test_assemble_translated_blocks_dict_cloud_mode() -> None:
    """Cloud mode assembly maps translation dictionary to bubbles with polygon safe-zones."""
    complex_poly = [
        (20.0, 0.0),
        (80.0, 0.0),
        (100.0, 50.0),
        (80.0, 100.0),
        (20.0, 100.0),
        (0.0, 50.0),
    ]
    bubbles = [
        DetectedBubble(
            id="1",
            box_2d=(50, 50, 200, 300),
            polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            confidence=0.91,
        ),
        DetectedBubble(
            id="2",
            box_2d=(300, 100, 800, 600),
            polygon=complex_poly,
            confidence=0.96,
            texts=[DetectedText(box_2d=(400, 200, 600, 400), confidence=0.9)],
        ),
    ]
    translations = {"1": "Hello world", "2": "Dialogue inside safe polygon"}

    blocks = assemble_translated_blocks(bubbles, translations)
    assert len(blocks) == 2

    # Block 1 (simple rect)
    b1 = blocks[0]
    assert b1.id == "1"
    assert b1.translated_text == "Hello world"
    assert b1.box == (50, 50, 200, 300)
    assert b1.parent_box is None
    assert b1.parent_bubble_id is None

    # Block 2 (complex polygon)
    b2 = blocks[1]
    assert b2.id == "2"
    assert b2.translated_text == "Dialogue inside safe polygon"
    assert b2.parent_box == (300, 100, 800, 600)
    assert b2.parent_bubble_id == "2"
    assert b2.polygon == complex_poly


def test_assemble_translated_blocks_list_local_mode() -> None:
    """Local mode assembly supports fine-grained work items, raw_texts, and translations."""
    bubbles = [
        DetectedBubble(
            id="10",
            box_2d=(100, 100, 400, 400),
            polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            confidence=0.9,
        )
    ]
    translations = ["Đã dịch câu"]
    raw_texts = ["元のテキスト"]

    blocks = assemble_translated_blocks(
        bubbles,
        translations=translations,
        raw_texts=raw_texts,
    )
    assert len(blocks) == 1
    assert blocks[0].id == "blk_0"
    assert blocks[0].translated_text == "Đã dịch câu"
    assert blocks[0].source_text == "元のテキスト"


def test_assemble_translated_blocks_dict_multi_child_mode() -> None:
    """Dict mode with multi-child bubble produces fine-grained child blocks linked to parent."""
    poly = [(5.0, 5.0), (95.0, 5.0), (95.0, 95.0), (5.0, 95.0)]
    bubble = DetectedBubble(
        id="1",
        box_2d=(100, 150, 300, 350),
        polygon=poly,
        confidence=0.95,
        texts=[
            DetectedText(box_2d=(110, 160, 190, 340), confidence=0.9),
            DetectedText(box_2d=(210, 160, 290, 340), confidence=0.88),
        ],
    )

    # LLM returns translations keyed by sequential badge IDs "1" and "2"
    translations = {
        "1": "Dòng thoại trên",
        "2": "Dòng thoại dưới",
    }

    blocks = assemble_translated_blocks([bubble], translations=translations)
    assert len(blocks) == 2

    # Block 1 (child 0)
    assert blocks[0].id == "blk_0_1"
    assert blocks[0].translated_text == "Dòng thoại trên"
    assert blocks[0].parent_bubble_id == "1"
    assert blocks[0].parent_box == (100, 150, 300, 350)
    assert blocks[0].polygon == poly
    assert blocks[0].box[0] >= 100
    assert blocks[0].box[2] <= 300

    # Block 2 (child 1)
    assert blocks[1].id == "blk_1_2"
    assert blocks[1].translated_text == "Dòng thoại dưới"
    assert blocks[1].parent_bubble_id == "1"
    assert blocks[1].parent_box == (100, 150, 300, 350)
    assert blocks[1].polygon == poly
    assert blocks[1].box[0] >= 100
    assert blocks[1].box[2] <= 300


def test_assemble_translated_blocks_mixed_multi_and_single_bubbles() -> None:
    """Dict mode with mixed multi-child and single-child bubbles maps sequential keys correctly."""
    bubble1 = DetectedBubble(
        id="1",
        box_2d=(100, 150, 300, 350),
        polygon=[(5.0, 5.0), (95.0, 5.0), (95.0, 95.0), (5.0, 95.0)],
        confidence=0.95,
        texts=[
            DetectedText(box_2d=(110, 160, 190, 340), confidence=0.9),
            DetectedText(box_2d=(210, 160, 290, 340), confidence=0.88),
        ],
    )
    bubble2 = DetectedBubble(
        id="2",
        box_2d=(400, 500, 550, 700),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.92,
        texts=[
            DetectedText(box_2d=(420, 520, 530, 680), confidence=0.92),
        ],
    )

    # Sequential keys 1, 2 for Bubble 1's children, and 3 for Bubble 2
    translations = {
        "1": "Child 1 of Bubble 1",
        "2": "Child 2 of Bubble 1",
        "3": "Single text of Bubble 2",
    }

    blocks = assemble_translated_blocks([bubble1, bubble2], translations=translations)
    assert len(blocks) == 3

    # Block 1 (child 0 of bubble 1)
    assert blocks[0].id == "blk_0_1"
    assert blocks[0].translated_text == "Child 1 of Bubble 1"
    assert blocks[0].parent_bubble_id == "1"
    assert blocks[0].parent_box == bubble1.box_2d

    # Block 2 (child 1 of bubble 1)
    assert blocks[1].id == "blk_1_2"
    assert blocks[1].translated_text == "Child 2 of Bubble 1"
    assert blocks[1].parent_bubble_id == "1"
    assert blocks[1].parent_box == bubble1.box_2d

    # Block 3 (bubble 2)
    assert blocks[2].id == "2"
    assert blocks[2].translated_text == "Single text of Bubble 2"


def test_assemble_translated_blocks_omits_empty_and_whitespace_translations_dict() -> None:
    """Dict mode omits entries where translated text is empty or only whitespace."""
    bubble1 = DetectedBubble(
        id="b1",
        box_2d=(100, 100, 200, 200),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.9,
    )
    bubble2 = DetectedBubble(
        id="b2",
        box_2d=(300, 300, 400, 400),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.9,
    )
    bubble3 = DetectedBubble(
        id="b3",
        box_2d=(500, 500, 600, 600),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.9,
    )

    translations = {
        "1": "Dòng thoại hợp lệ",
        "2": "",
        "3": "   \n\t  ",
    }

    blocks = assemble_translated_blocks([bubble1, bubble2, bubble3], translations=translations)
    assert len(blocks) == 1
    assert blocks[0].id == "b1"
    assert blocks[0].translated_text == "Dòng thoại hợp lệ"


def test_assemble_translated_blocks_omits_empty_and_whitespace_translations_list() -> None:
    """List mode omits entries where translated text is empty or only whitespace."""
    bubble1 = DetectedBubble(
        id="b1",
        box_2d=(100, 100, 200, 200),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.9,
    )
    bubble2 = DetectedBubble(
        id="b2",
        box_2d=(300, 300, 400, 400),
        polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
        confidence=0.9,
    )

    translations = ["", "Dịch câu 2"]
    blocks = assemble_translated_blocks([bubble1, bubble2], translations=translations)
    assert len(blocks) == 1
    assert blocks[0].id == "blk_1"
    assert blocks[0].translated_text == "Dịch câu 2"


