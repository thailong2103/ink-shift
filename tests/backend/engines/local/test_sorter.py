"""Unit tests for 2-Tier RTL Manga Reading Order Sorter."""

from __future__ import annotations

from src.backend.detection.base import DetectedBubble, DetectedPanel
from src.backend.detection.sorter import (
    MangaReadingOrderSorter,
    sort_manga_reading_order,
)


def test_sorter_empty_inputs() -> None:
    """Empty bubble list returns empty list."""
    assert MangaReadingOrderSorter.sort([], []) == []


def test_sorter_no_panels_borderless_manga() -> None:
    """When no panels are provided, bubbles are sorted purely by Tier 2 (1.5Y - X)."""
    # 4 speech bubbles on a borderless manga page
    # Bubble A: Top-Right (cy=150, cx=800 -> 1.5*150 - 800 = -575)
    b_tr = DetectedBubble(id="raw_tr", box_2d=(100, 700, 200, 900))
    # Bubble B: Top-Left (cy=150, cx=200 -> 1.5*150 - 200 = 25)
    b_tl = DetectedBubble(id="raw_tl", box_2d=(100, 100, 200, 300))
    # Bubble C: Bottom-Right (cy=750, cx=800 -> 1.5*750 - 800 = 325)
    b_br = DetectedBubble(id="raw_br", box_2d=(700, 700, 800, 900))
    # Bubble D: Bottom-Left (cy=750, cx=200 -> 1.5*750 - 200 = 925)
    b_bl = DetectedBubble(id="raw_bl", box_2d=(700, 100, 800, 300))

    # Pass in shuffled order
    shuffled = [b_bl, b_tr, b_tl, b_br]
    ordered = sort_manga_reading_order(shuffled, [])

    # Order must be: Top-Right -> Top-Left -> Bottom-Right -> Bottom-Left
    assert len(ordered) == 4
    assert [b.box_2d for b in ordered] == [
        b_tr.box_2d,
        b_tl.box_2d,
        b_br.box_2d,
        b_bl.box_2d,
    ]
    # Re-indexed sequential IDs: '1', '2', '3', '4'
    assert [b.id for b in ordered] == ["1", "2", "3", "4"]
    # panel_index should be -1
    for b in ordered:
        assert b.panel_index == -1


def test_sorter_two_tier_standard_panels() -> None:
    """Manga reading order prioritizes top-right panel first, then in-panel reading order."""
    # Panel 0: Top-Right (50..450, 500..950)
    p_tr = DetectedPanel(box_2d=(50, 500, 450, 950))
    # Panel 1: Top-Left (50..450, 50..450)
    p_tl = DetectedPanel(box_2d=(50, 50, 450, 450))
    # Panel 2: Bottom-Wide (500..950, 50..950)
    p_bottom = DetectedPanel(box_2d=(500, 50, 950, 950))

    panels = [p_tl, p_bottom, p_tr]  # shuffled panels

    # Bubbles inside Panel TR
    b_tr_1 = DetectedBubble(id="b_tr_1", box_2d=(80, 750, 180, 900))  # top in panel TR
    b_tr_2 = DetectedBubble(id="b_tr_2", box_2d=(250, 550, 350, 700))  # bottom in panel TR

    # Bubble inside Panel TL
    b_tl_1 = DetectedBubble(id="b_tl_1", box_2d=(100, 100, 200, 300))

    # Bubbles inside Panel Bottom
    b_bot_1 = DetectedBubble(id="b_bot_1", box_2d=(550, 700, 650, 850))  # right
    b_bot_2 = DetectedBubble(id="b_bot_2", box_2d=(600, 150, 700, 300))  # left

    all_bubbles = [b_bot_2, b_tr_2, b_tl_1, b_bot_1, b_tr_1]
    ordered = MangaReadingOrderSorter.sort(all_bubbles, panels)

    assert len(ordered) == 5
    # Order: Panel TR (b_tr_1, b_tr_2) -> Panel TL (b_tl_1) -> Panel Bottom (b_bot_1, b_bot_2)
    assert [b.box_2d for b in ordered] == [
        b_tr_1.box_2d,
        b_tr_2.box_2d,
        b_tl_1.box_2d,
        b_bot_1.box_2d,
        b_bot_2.box_2d,
    ]
    assert [b.id for b in ordered] == ["1", "2", "3", "4", "5"]


def test_sorter_unassigned_bubble_fallback() -> None:
    """Unassigned bubble outside panels does not fail and falls back cleanly."""
    panel_bottom = DetectedPanel(box_2d=(500, 50, 950, 950))
    bubble_in_panel = DetectedBubble(id="in_panel", box_2d=(600, 600, 700, 700))

    # Narrator bubble at the top outside any panel
    narrator_bubble = DetectedBubble(id="narrator", box_2d=(50, 500, 150, 700))

    ordered = MangaReadingOrderSorter.sort([bubble_in_panel, narrator_bubble], [panel_bottom])
    assert len(ordered) == 2
    # Narrator bubble at top (y=100) should precede bottom panel bubble (y=650)
    assert ordered[0].box_2d == narrator_bubble.box_2d
    assert ordered[1].box_2d == bubble_in_panel.box_2d
    assert ordered[0].panel_index == -1
    assert ordered[0].id == "1"
    assert ordered[1].id == "2"


def test_sorter_staggered_dialogue_with_bottom_caption() -> None:
    """Staggered dialogue bubbles precede bottom captions even if caption is far to the right."""
    # Top panel (y: 50..400, x: 50..950)
    panel = DetectedPanel(box_2d=(50, 50, 400, 950))

    # Dialogue 1: Top-Right (Thug 1)
    b_dialogue_tr = DetectedBubble(id="tr", box_2d=(101, 764, 235, 873))
    # Dialogue 2: Top-Left (Thug 2) - shares tier with Dialogue 1
    b_dialogue_tl = DetectedBubble(id="tl", box_2d=(195, 175, 353, 334))
    # Caption: Bottom-Right (Chapter title subtitle strip) - below Dialogue 2's center
    b_caption_br = DetectedBubble(id="br_caption", box_2d=(338, 547, 363, 926))

    # Pass in shuffled order
    shuffled = [b_caption_br, b_dialogue_tl, b_dialogue_tr]
    ordered = MangaReadingOrderSorter.sort(shuffled, [panel])

    # Expected narrative order: Top-Right Dialogue -> Top-Left Dialogue -> Bottom-Right Caption
    assert len(ordered) == 3
    assert [b.box_2d for b in ordered] == [
        b_dialogue_tr.box_2d,
        b_dialogue_tl.box_2d,
        b_caption_br.box_2d,
    ]
    assert [b.id for b in ordered] == ["1", "2", "3"]


def test_sorter_tall_bubble_with_right_sfx() -> None:
    """Right-side SFX bubbles are read before left-side tall speech bubbles sharing the tier."""
    panel = DetectedPanel(box_2d=(650, 50, 950, 950))

    # SFX 1 (higher on right)
    sfx1 = DetectedBubble(id="sfx1", box_2d=(762, 616, 792, 705))
    # SFX 2 (lower on right)
    sfx2 = DetectedBubble(id="sfx2", box_2d=(793, 683, 823, 774))
    # Tall Hero speech bubble on left spanning the vertical range
    hero = DetectedBubble(id="hero", box_2d=(703, 166, 887, 405))

    shuffled = [hero, sfx2, sfx1]
    ordered = MangaReadingOrderSorter.sort(shuffled, [panel])

    # Right side elements come first, left side last
    assert len(ordered) == 3
    assert [b.box_2d for b in ordered] == [
        sfx1.box_2d,
        sfx2.box_2d,
        hero.box_2d,
    ]
    assert [b.id for b in ordered] == ["1", "2", "3"]

