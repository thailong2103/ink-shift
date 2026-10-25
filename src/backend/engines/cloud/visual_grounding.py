"""Set-of-Marks (SoM) Visual Grounding for Cloud Vision Translation."""

from __future__ import annotations

import io
from collections.abc import Sequence

from PIL import Image, ImageDraw, ImageFont

from src.backend.detection.assembler import BubbleWorkItem, prepare_local_work_items
from src.backend.detection.base import DetectedBubble
from src.backend.detection.postprocess import denormalize_box_from_1000


def _load_scaled_font(font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a crisp scalable font with system fallbacks."""
    candidate_fonts = ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf")
    for name in candidate_fonts:
        try:
            return ImageFont.truetype(name, font_size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=font_size)
    except TypeError:
        return ImageFont.load_default()


def draw_set_of_marks(
    image: Image.Image,
    bubbles: Sequence[DetectedBubble],
    work_items: Sequence[BubbleWorkItem] | None = None,
    outline_color: tuple[int, int, int] = (220, 38, 38),  # Crimson red
    badge_bg_color: tuple[int, int, int] = (245, 158, 11),  # Amber gold (vibrant contrast vs manga)
    badge_text_color: tuple[int, int, int] = (0, 0, 0),     # Solid bold black
    badge_border_color: tuple[int, int, int] = (220, 38, 38),  # Crimson red border
    line_width: int | None = None,
) -> Image.Image:
    """Draw thickened rectangular outlines and high-contrast sequential badge numbers onto text boxes.

    Only draws rectangles directly around each translation unit (item.crop_box) and does NOT
    outline the parent speech bubble contours, ensuring the Vision LLM focuses squarely on
    the text regions.

    Args:
        image: Source PIL Image.
        bubbles: Sequence of DetectedBubble instances (pre-sorted in RTL reading order).
        work_items: Optional sequence of pre-computed BubbleWorkItem instances.
        outline_color: RGB tuple for text box boundary outline.
        badge_bg_color: RGB tuple for badge background.
        badge_text_color: RGB tuple for badge text.
        badge_border_color: RGB tuple for badge container border.
        line_width: Optional outline pixel width (defaults to resolution-scaled width >= 2px).

    Returns:
        New PIL Image copy with Set-of-Marks visual annotations.
    """
    marked = image.copy().convert("RGB")
    draw = ImageDraw.Draw(marked)
    orig_w, orig_h = marked.size

    # Calculate resolution-aware dimensions
    actual_line_width = line_width if line_width is not None else max(2, round(min(orig_w, orig_h) * 0.0025))
    font_size = max(16, round(orig_h * 0.016))
    font = _load_scaled_font(font_size)

    items = work_items if work_items is not None else prepare_local_work_items(list(bubbles))

    for idx, item in enumerate(items):
        badge_text = f"[{idx + 1}]"

        # Denormalize target text box (item.crop_box) directly to pixel coordinates
        ymin_px, xmin_px, ymax_px, xmax_px = denormalize_box_from_1000(
            item.crop_box, orig_w, orig_h
        )

        # 1. Draw thickened rectangular outline exclusively around the text box
        draw.rectangle(
            [xmin_px, ymin_px, xmax_px, ymax_px],
            outline=outline_color,
            width=actual_line_width,
        )

        # 2. Draw enlarged high-contrast badge
        bbox = draw.textbbox((0, 0), badge_text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        badge_pad_x = max(4, round(font_size * 0.22))
        badge_pad_y = max(2, round(font_size * 0.12))
        badge_w = text_w + badge_pad_x * 2
        badge_h = text_h + badge_pad_y * 2

        # Position badge at top-left of box, clamped within canvas
        bx = max(0, min(orig_w - badge_w, xmin_px))
        by = max(0, ymin_px - badge_h)
        if by == 0 and ymin_px < badge_h:
            by = min(orig_h - badge_h, ymin_px + actual_line_width + 1)

        draw.rectangle(
            [bx, by, bx + badge_w, by + badge_h],
            fill=badge_bg_color,
            outline=badge_border_color,
            width=max(1, actual_line_width // 2),
        )
        draw.text(
            (bx + badge_pad_x, by + badge_pad_y),
            badge_text,
            fill=badge_text_color,
            font=font,
        )

    return marked


def create_marked_image_bytes(
    image_bytes: bytes,
    bubbles: Sequence[DetectedBubble],
    work_items: Sequence[BubbleWorkItem] | None = None,
    output_format: str = "JPEG",
    quality: int = 90,
    outline_color: tuple[int, int, int] = (220, 38, 38),
    badge_bg_color: tuple[int, int, int] = (245, 158, 11),
    badge_text_color: tuple[int, int, int] = (0, 0, 0),
) -> bytes:
    """Convenience helper to apply Set-of-Marks directly onto image bytes."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except (OSError, ValueError, TypeError):
        # Fallback for mock/test data with non-image bytes
        img = Image.new("RGB", (800, 1200), color="white")
    marked_img = draw_set_of_marks(
        img,
        bubbles,
        work_items=work_items,
        outline_color=outline_color,
        badge_bg_color=badge_bg_color,
        badge_text_color=badge_text_color,
    )
    buffer = io.BytesIO()
    marked_img.save(buffer, format=output_format, quality=quality)
    return buffer.getvalue()


