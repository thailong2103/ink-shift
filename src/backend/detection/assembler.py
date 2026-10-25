"""Shared TranslatedBlock Assembly and Safe-Zone Fitting Module.

Calculates safe-zone render boxes within irregular speech bubble polygons,
links parent bounding boxes, determines reading directions, and constructs
canonical TranslatedBlock models shared across Local and Cloud engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.backend.detection.base import DetectedBubble
from src.backend.detection.postprocess import expand_child_text_boxes_in_polygon
from src.backend.schemas.contract import TranslatedBlock


@dataclass(frozen=True)
class BubbleWorkItem:
    """Pre-processed crop and render work item for an individual text region."""

    crop_box: tuple[int, int, int, int]
    render_box: tuple[int, int, int, int]
    parent_bubble: DetectedBubble
    is_child: bool
    child_index: int
    confidence: float


def compute_safe_render_box(
    bubble: DetectedBubble,
) -> tuple[tuple[int, int, int, int], bool]:
    """Calculate the safe rectangular text-fitting box inside a bubble polygon.

    Args:
        bubble: Detected speech bubble with normalized [0, 1000] box and polygon.

    Returns:
        tuple of (render_box, is_safe_child) where is_safe_child is True if render_box
        is distinct from the whole outer bounding box.
    """
    has_complex_polygon = len(bubble.polygon) > 4
    if not has_complex_polygon:
        return bubble.box_2d, False

    if len(bubble.texts) == 1:
        seed_box = bubble.texts[0].box_2d
    elif len(bubble.texts) > 1:
        ymin = min(ct.box_2d[0] for ct in bubble.texts)
        xmin = min(ct.box_2d[1] for ct in bubble.texts)
        ymax = max(ct.box_2d[2] for ct in bubble.texts)
        xmax = max(ct.box_2d[3] for ct in bubble.texts)
        seed_box = (ymin, xmin, ymax, xmax)
    else:
        ymin, xmin, ymax, xmax = bubble.box_2d
        cy = (ymin + ymax) // 2
        cx = (xmin + xmax) // 2
        seed_box = (
            max(0, cy - 10),
            max(0, cx - 10),
            min(1000, cy + 10),
            min(1000, cx + 10),
        )

    expanded_boxes = expand_child_text_boxes_in_polygon(
        polygon_rel=bubble.polygon,
        child_boxes_1000=[seed_box],
        parent_box_1000=bubble.box_2d,
    )
    exp_box = expanded_boxes[0] if expanded_boxes else bubble.box_2d
    is_safe_child = exp_box != bubble.box_2d
    return exp_box, is_safe_child


def prepare_local_work_items(
    bubbles: list[DetectedBubble],
) -> list[BubbleWorkItem]:
    """Break bubbles into fine-grained crop and render items for local OCR and translation.

    Handles connected/merged bubbles by treating each child text line independently,
    expanding safe zones inside the bubble polygon.

    Args:
        bubbles: List of detected speech bubbles.

    Returns:
        List of BubbleWorkItem instances ready for OCR cropping and translation.
    """
    work_items: list[BubbleWorkItem] = []

    for bubble in bubbles:
        if len(bubble.texts) > 1:
            child_boxes = [ct.box_2d for ct in bubble.texts]
            expanded_boxes = expand_child_text_boxes_in_polygon(
                polygon_rel=bubble.polygon,
                child_boxes_1000=child_boxes,
                parent_box_1000=bubble.box_2d,
            )
            for c_idx, ct in enumerate(bubble.texts):
                exp_box = (
                    expanded_boxes[c_idx]
                    if c_idx < len(expanded_boxes)
                    else ct.box_2d
                )
                work_items.append(
                    BubbleWorkItem(
                        crop_box=ct.box_2d,
                        render_box=exp_box,
                        parent_bubble=bubble,
                        is_child=True,
                        child_index=c_idx,
                        confidence=ct.confidence,
                    )
                )
        elif len(bubble.texts) == 1:
            ct = bubble.texts[0]
            has_complex_polygon = len(bubble.polygon) > 4
            if has_complex_polygon:
                expanded_boxes = expand_child_text_boxes_in_polygon(
                    polygon_rel=bubble.polygon,
                    child_boxes_1000=[ct.box_2d],
                    parent_box_1000=bubble.box_2d,
                )
                exp_box = expanded_boxes[0] if expanded_boxes else ct.box_2d
                is_safe_child = exp_box != bubble.box_2d
                work_items.append(
                    BubbleWorkItem(
                        crop_box=ct.box_2d,
                        render_box=exp_box,
                        parent_bubble=bubble,
                        is_child=is_safe_child,
                        child_index=0,
                        confidence=ct.confidence,
                    )
                )
            else:
                work_items.append(
                    BubbleWorkItem(
                        crop_box=ct.box_2d,
                        render_box=bubble.box_2d,
                        parent_bubble=bubble,
                        is_child=False,
                        child_index=0,
                        confidence=ct.confidence,
                    )
                )
        else:
            has_complex_polygon = len(bubble.polygon) > 4
            if has_complex_polygon:
                ymin, xmin, ymax, xmax = bubble.box_2d
                cy = (ymin + ymax) // 2
                cx = (xmin + xmax) // 2
                seed_box = (
                    max(0, cy - 10),
                    max(0, cx - 10),
                    min(1000, cy + 10),
                    min(1000, cx + 10),
                )
                expanded_boxes = expand_child_text_boxes_in_polygon(
                    polygon_rel=bubble.polygon,
                    child_boxes_1000=[seed_box],
                    parent_box_1000=bubble.box_2d,
                )
                exp_box = expanded_boxes[0] if expanded_boxes else bubble.box_2d
                is_safe_child = exp_box != bubble.box_2d
                work_items.append(
                    BubbleWorkItem(
                        crop_box=bubble.box_2d,
                        render_box=exp_box,
                        parent_bubble=bubble,
                        is_child=is_safe_child,
                        child_index=0,
                        confidence=bubble.confidence,
                    )
                )
            else:
                work_items.append(
                    BubbleWorkItem(
                        crop_box=bubble.box_2d,
                        render_box=bubble.box_2d,
                        parent_bubble=bubble,
                        is_child=False,
                        child_index=0,
                        confidence=bubble.confidence,
                    )
                )

    return work_items


def assemble_translated_blocks(
    bubbles: list[DetectedBubble],
    translations: dict[str, str] | list[str],
    raw_texts: list[str] | None = None,
    work_items: list[BubbleWorkItem] | None = None,
) -> list[TranslatedBlock]:
    """Assemble final TranslatedBlock models with polygon safe-zones and parent linking.

    Supports both:
    1. Cloud Engine format (dict mapping badge ID or bubble ID -> translated text).
    2. Local Engine format (list of translated texts matching fine-grained work items).

    When a speech bubble contains multiple child text regions, fine-grained child blocks
    are generated with parent_box and parent_bubble_id linking, synchronized across both
    Local and Cloud engines.

    Args:
        bubbles: List of detected speech bubbles.
        translations: Either a mapping of {badge_id/bubble_id: translated_text} or a list of translated texts.
        raw_texts: Optional list of original OCR texts for local engine pipeline.
        work_items: Optional precomputed list of BubbleWorkItem instances.

    Returns:
        List of TranslatedBlock models ready for client overlay rendering.
    """
    blocks: list[TranslatedBlock] = []
    items = work_items if work_items is not None else prepare_local_work_items(bubbles)

    for idx, item in enumerate(items):
        if isinstance(translations, dict):
            # Look up translation: 1-based index (e.g. "1"), bracketed ("[1]"), parent bubble ID (for single bubbles), or block ID
            parent_id_lookup = (
                translations.get(item.parent_bubble.id)
                if len(item.parent_bubble.texts) <= 1
                else None
            )
            trans_text = (
                translations.get(str(idx + 1))
                or translations.get(f"[{idx + 1}]")
                or parent_id_lookup
                or translations.get(f"blk_{idx}_{item.child_index + 1}")
                or ""
            )
        else:
            trans_text = translations[idx] if idx < len(translations) else ""

        # Omit blocks where translation is empty, whitespace-only, or filtered out non-text
        if not trans_text.strip():
            continue

        raw_text = (
            raw_texts[idx]
            if (raw_texts is not None and idx < len(raw_texts))
            else None
        )

        ymin, xmin, ymax, xmax = item.render_box
        direction: Literal["vertical", "horizontal"] = (
            "vertical" if (ymax - ymin) >= (xmax - xmin) else "horizontal"
        )

        if len(item.parent_bubble.texts) > 1:
            blk_id = f"blk_{idx}_{item.child_index + 1}"
            parent_id: str | None = item.parent_bubble.id
            parent_box: tuple[int, int, int, int] | None = item.parent_bubble.box_2d
        else:
            if isinstance(translations, dict):
                blk_id = item.parent_bubble.id
            else:
                blk_id = f"blk_{idx}"

            if item.is_child:
                parent_id = item.parent_bubble.id
                parent_box = item.parent_bubble.box_2d
            else:
                parent_id = None
                parent_box = None

        blocks.append(
            TranslatedBlock(
                id=blk_id,
                box=item.render_box,
                parent_box=parent_box,
                polygon=(
                    item.parent_bubble.polygon
                    if item.parent_bubble.polygon
                    else None
                ),
                parent_bubble_id=parent_id,
                source_text=raw_text if raw_text else None,
                translated_text=trans_text,
                direction=direction,
                confidence=item.confidence,
            )
        )

    return blocks

