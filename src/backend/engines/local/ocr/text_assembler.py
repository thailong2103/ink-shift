"""Text assembly, line clustering, and de-hyphenation for comic dialogue."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParagraphCluster:
    """Clustered paragraph from multiple horizontal text lines.

    Attributes:
        box_2d: Canonical normalized [0, 1000] integer bounding box: (ymin, xmin, ymax, xmax).
        pixel_box: Bounding box in physical image pixels: (ymin, xmin, ymax, xmax).
        text: Merged and normalized paragraph text.
        confidence: Average detection confidence score across clustered lines.
    """

    box_2d: tuple[int, int, int, int]
    pixel_box: tuple[int, int, int, int]
    text: str
    confidence: float = 1.0


def cluster_lines_to_paragraphs(
    raw_ocr_lines: list[Any],
    image_width: int,
    image_height: int,
    line_height_factor: float = 1.25,
    is_ja: bool = False,
) -> list[ParagraphCluster]:
    """Cluster raw OCR lines into coherent paragraphs using vertical gap and horizontal overlap.

    Args:
        raw_ocr_lines: List of RapidOCR detections: [[box_points, text, confidence], ...].
        image_width: Physical width of the source image in pixels.
        image_height: Physical height of the source image in pixels.
        line_height_factor: Multiplier for average line height determining paragraph break threshold.
        is_ja: When True, applies Japanese-specific CJK character de-spacing.

    Returns:
        List of ParagraphCluster objects sorted in natural reading order (Top-to-Bottom, Left-to-Right).
    """
    if not raw_ocr_lines:
        return []

    # 1. Parse and validate lines
    parsed_lines: list[dict[str, Any]] = []
    for item in raw_ocr_lines:
        if not item or len(item) < 2:
            continue
        box_pts = item[0]
        text = str(item[1]).strip()
        conf = float(item[2]) if len(item) > 2 else 1.0
        if not text or not box_pts or len(box_pts) < 4:
            continue

        ymin = float(min(p[1] for p in box_pts))
        ymax = float(max(p[1] for p in box_pts))
        xmin = float(min(p[0] for p in box_pts))
        xmax = float(max(p[0] for p in box_pts))
        h = max(1.0, ymax - ymin)

        parsed_lines.append({
            "ymin": ymin,
            "ymax": ymax,
            "xmin": xmin,
            "xmax": xmax,
            "h": h,
            "text": text,
            "conf": conf,
        })

    if not parsed_lines:
        return []

    # 2. Sort lines vertically (top-to-bottom, then left-to-right)
    sorted_lines = sorted(parsed_lines, key=lambda l: (l["ymin"], l["xmin"]))

    # 3. Cluster consecutive lines into paragraphs
    clusters: list[list[dict[str, Any]]] = []
    current_cluster: list[dict[str, Any]] = []

    for line in sorted_lines:
        if not current_cluster:
            current_cluster.append(line)
            continue

        prev_line = current_cluster[-1]
        gap_y = line["ymin"] - prev_line["ymax"]
        avg_h = (prev_line["h"] + line["h"]) / 2.0

        # Calculate horizontal overlap between line and cluster bounds
        cluster_xmin = min(l["xmin"] for l in current_cluster)
        cluster_xmax = max(l["xmax"] for l in current_cluster)
        overlap_x = max(0.0, min(line["xmax"], cluster_xmax) - max(line["xmin"], cluster_xmin))

        # Check line spacing: Lines in the same paragraph share vertical proximity
        # and non-negative horizontal overlap (or slight indent)
        same_paragraph = False
        if gap_y <= avg_h * line_height_factor and (overlap_x > 0.0 or gap_y <= 0.4 * avg_h):
            same_paragraph = True

        if same_paragraph:
            current_cluster.append(line)
        else:
            clusters.append(current_cluster)
            current_cluster = [line]

    if current_cluster:
        clusters.append(current_cluster)

    # 4. Construct ParagraphCluster objects with bounding box envelope
    results: list[ParagraphCluster] = []
    w_safe = max(1, image_width)
    h_safe = max(1, image_height)

    for cluster in clusters:
        c_ymin = min(l["ymin"] for l in cluster)
        c_xmin = min(l["xmin"] for l in cluster)
        c_ymax = max(l["ymax"] for l in cluster)
        c_xmax = max(l["xmax"] for l in cluster)

        # Normalize to [0, 1000] canonical coordinate space
        norm_ymin = max(0, min(1000, round((c_ymin / h_safe) * 1000.0)))
        norm_xmin = max(0, min(1000, round((c_xmin / w_safe) * 1000.0)))
        norm_ymax = max(0, min(1000, round((c_ymax / h_safe) * 1000.0)))
        norm_xmax = max(0, min(1000, round((c_xmax / w_safe) * 1000.0)))

        # Guard coordinate sanity: min <= max
        if norm_ymin > norm_ymax:
            norm_ymin, norm_ymax = norm_ymax, norm_ymin
        if norm_xmin > norm_xmax:
            norm_xmin, norm_xmax = norm_xmax, norm_xmin

        # Assemble text cleanly
        raw_texts = [l["text"] for l in cluster]
        if is_ja:
            merged_text = clean_japanese_text("".join(raw_texts))
        else:
            merged_text = assemble_comic_lines(raw_texts)

        avg_conf = sum(l["conf"] for l in cluster) / float(len(cluster))

        results.append(
            ParagraphCluster(
                box_2d=(norm_ymin, norm_xmin, norm_ymax, norm_xmax),
                pixel_box=(round(c_ymin), round(c_xmin), round(c_ymax), round(c_xmax)),
                text=merged_text,
                confidence=round(avg_conf, 3),
            )
        )

    return results


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
