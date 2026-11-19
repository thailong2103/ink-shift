"""Text assembly, bi-directional line clustering, Furigana filtering, and CJK normalization."""

from __future__ import annotations

import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

_CJK_CHAR_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
_CJK_DESPACE_PATTERN = re.compile(
    r"(?<=[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff01-\uffee])"
    r"\s+"
    r"(?=[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff01-\uffee])"
)


@dataclass(frozen=True)
class ParagraphCluster:
    """Clustered paragraph or vertical text block normalized to canonical coordinates.

    Attributes:
        box_2d: Canonical normalized [0, 1000] integer bounding box: (ymin, xmin, ymax, xmax).
        pixel_box: Bounding box in physical image pixels: (ymin, xmin, ymax, xmax).
        text: Merged and normalized paragraph text.
        confidence: Average detection confidence score across clustered lines.
        direction: Detected writing flow ('horizontal' or 'vertical').
    """

    box_2d: tuple[int, int, int, int]
    pixel_box: tuple[int, int, int, int]
    text: str
    confidence: float = 1.0
    direction: Literal["horizontal", "vertical"] = "horizontal"


def contains_cjk(text: str) -> bool:
    """Return True if text contains Japanese Kana or CJK Unified Ideographs."""
    return bool(text and _CJK_CHAR_PATTERN.search(text))


def classify_box_orientation(
    box_pts: Sequence[Sequence[float]],
) -> Literal["vertical", "horizontal", "square"]:
    """Classify a detected text quadrilateral as vertical, horizontal, or ambiguous square."""
    if not box_pts:
        return "horizontal"
    xs = [float(p[0]) for p in box_pts]
    ys = [float(p[1]) for p in box_pts]
    w = max(1.0, max(xs) - min(xs))
    h = max(1.0, max(ys) - min(ys))
    if h / w >= 1.5:
        return "vertical"
    if w / h >= 1.5:
        return "horizontal"
    return "square"


def parse_ocr_entry(
    box_pts: Sequence[Sequence[float]],
    text: str,
    conf: float = 1.0,
) -> dict[str, Any] | None:
    """Build normalized geometry dictionary from a 4-point quad, recognized text, and score."""
    if not box_pts or len(box_pts) < 4:
        return None
    xs = [float(p[0]) for p in box_pts]
    ys = [float(p[1]) for p in box_pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    w = max(1.0, xmax - xmin)
    h = max(1.0, ymax - ymin)
    return {
        "ymin": ymin,
        "ymax": ymax,
        "xmin": xmin,
        "xmax": xmax,
        "cx": (xmin + xmax) / 2.0,
        "cy": (ymin + ymax) / 2.0,
        "w": w,
        "h": h,
        "orientation": classify_box_orientation(box_pts),
        "text": text.strip(),
        "conf": float(conf),
    }


def _parse_raw_ocr_lines(raw_ocr_lines: Sequence[Any]) -> list[dict[str, Any]]:
    """Convert raw RapidOCR line tuples/lists into geometry dictionaries."""
    parsed: list[dict[str, Any]] = []
    for item in raw_ocr_lines:
        if not item or len(item) < 2:
            continue
        box_pts = item[0]
        text = str(item[1]).strip()
        conf = float(item[2]) if len(item) > 2 else 1.0
        if not text:
            continue
        entry = parse_ocr_entry(box_pts, text, conf)
        if entry is not None:
            parsed.append(entry)
    return parsed


def filter_furigana_boxes(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter narrow Japanese Ruby/Furigana strips adjacent to the right edge of vertical columns.

    Uses relative median column width inside the local container (bubble or page cluster)
    and never drops horizontal lines or standalone narrow bubbles.
    """
    vertical_boxes = [b for b in boxes if b.get("orientation") == "vertical"]
    if len(vertical_boxes) < 2:
        return boxes

    median_w = float(statistics.median(float(b["w"]) for b in vertical_boxes))
    if median_w <= 1.0:
        return boxes

    main_columns = [b for b in vertical_boxes if float(b["w"]) >= 0.70 * median_w]
    if not main_columns:
        return boxes

    kept: list[dict[str, Any]] = []
    for box in boxes:
        w = float(box["w"])
        if box.get("orientation") == "horizontal" or w >= 0.55 * median_w:
            kept.append(box)
            continue

        is_ruby = False
        b_ymin, b_ymax, b_xmin = float(box["ymin"]), float(box["ymax"]), float(box["xmin"])
        b_h = max(1.0, float(box["h"]))
        for col in main_columns:
            if col is box:
                continue
            gap_from_col_right = b_xmin - float(col["xmax"])
            overlap_y = max(0.0, min(b_ymax, float(col["ymax"])) - max(b_ymin, float(col["ymin"])))
            min_h = min(b_h, max(1.0, float(col["h"])))
            if (
                -0.15 * median_w <= gap_from_col_right <= 0.75 * median_w
                and overlap_y >= 0.25 * min_h
            ):
                is_ruby = True
                break

        if not is_ruby:
            kept.append(box)

    return kept if kept else boxes


def is_ambiguous_square_cjk_bubble(
    boxes: Sequence[dict[str, Any]],
    page_dominant_vertical: bool,
) -> bool:
    """Detect tight 3x3 square CJK grid bubbles that DBNet may slice into horizontal rows."""
    if not page_dominant_vertical or not (2 <= len(boxes) <= 5):
        return False

    if any(b.get("orientation") == "vertical" for b in boxes):
        return False

    # Skip pure non-CJK (e.g. English) bubbles when text is already populated
    joined = "".join(str(b.get("text", "")) for b in boxes)
    if joined and not contains_cjk(joined):
        return False

    union_w = max(float(b["xmax"]) for b in boxes) - min(float(b["xmin"]) for b in boxes)
    union_h = max(float(b["ymax"]) for b in boxes) - min(float(b["ymin"]) for b in boxes)
    ratio = union_w / max(1.0, union_h)
    if not (0.72 <= ratio <= 1.38):
        return False

    ordered = sorted(boxes, key=lambda b: float(b["ymin"]))
    avg_h = sum(float(b["h"]) for b in ordered) / float(len(ordered))
    max_gap = max(
        float(ordered[idx + 1]["ymin"]) - float(ordered[idx]["ymax"])
        for idx in range(len(ordered) - 1)
    )
    return max_gap <= 0.65 * max(1.0, avg_h)


def _group_same_row_ltr(lines: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group horizontally aligned boxes onto the same row (sorted left-to-right), top-to-bottom."""
    if not lines:
        return []
    by_y = sorted(lines, key=lambda b: (float(b["cy"]), float(b["xmin"])))
    rows: list[list[dict[str, Any]]] = []
    for box in by_y:
        placed = False
        b_ymin, b_ymax = float(box["ymin"]), float(box["ymax"])
        b_h = max(1.0, float(box["h"]))
        for row in reversed(rows):
            ref = row[0]
            overlap_y = max(0.0, min(b_ymax, float(ref["ymax"])) - max(b_ymin, float(ref["ymin"])))
            min_h = min(b_h, max(1.0, float(ref["h"])))
            if overlap_y / min_h > 0.50:
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])

    for row in rows:
        row.sort(key=lambda b: float(b["cx"]))
    rows.sort(key=lambda r: sum(float(b["cy"]) for b in r) / float(len(r)))
    return rows


def _sort_vertical_columns_rtl(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group stacked boxes into vertical columns ordered Right-to-Left, Top-to-Bottom."""
    if not lines:
        return []
    columns: list[list[dict[str, Any]]] = []
    for box in sorted(lines, key=lambda b: (-float(b["cx"]), float(b["cy"]))):
        b_xmin, b_xmax = float(box["xmin"]), float(box["xmax"])
        b_w = max(1.0, float(box["w"]))
        best_col: list[dict[str, Any]] | None = None
        best_overlap = 0.0
        for col in columns:
            c_xmin = min(float(item["xmin"]) for item in col)
            c_xmax = max(float(item["xmax"]) for item in col)
            overlap_x = max(0.0, min(b_xmax, c_xmax) - max(b_xmin, c_xmin))
            min_w = min(b_w, max(1.0, c_xmax - c_xmin))
            ratio = overlap_x / min_w
            if ratio > 0.30 and ratio > best_overlap:
                best_overlap = ratio
                best_col = col
        if best_col is not None:
            best_col.append(box)
        else:
            columns.append([box])

    columns.sort(key=lambda col: -(sum(float(item["cx"]) for item in col) / float(len(col))))
    ordered: list[dict[str, Any]] = []
    for col in columns:
        col.sort(key=lambda item: float(item["cy"]))
        ordered.extend(col)
    return ordered


def _merge_lines_by_direction(
    lines: list[dict[str, Any]],
    direction: Literal["horizontal", "vertical"],
) -> str:
    """Join sorted line entries according to writing direction and script conventions."""
    if not lines:
        return ""
    if direction == "vertical":
        filtered = filter_furigana_boxes(lines)
        ordered = _sort_vertical_columns_rtl(filtered)
        return clean_cjk_text("".join(str(item["text"]) for item in ordered))

    rows = _group_same_row_ltr(lines)
    row_strings = [assemble_comic_lines([str(item["text"]) for item in row]) for row in rows]
    assembled = assemble_comic_lines(row_strings)
    if contains_cjk(assembled):
        return clean_cjk_text(assembled)
    return assembled


def order_bubble_lines_bidirectional(
    lines: list[dict[str, Any]],
    page_dominant_vertical: bool = False,
) -> tuple[str, Literal["horizontal", "vertical"]]:
    """Assemble OCR detections inside a speech bubble using automatic vertical/horizontal ordering."""
    if not lines:
        return "", "horizontal"

    v_count = sum(1 for item in lines if item.get("orientation") == "vertical")
    h_count = sum(1 for item in lines if item.get("orientation") == "horizontal")

    if v_count > h_count:
        direction: Literal["horizontal", "vertical"] = "vertical"
    elif h_count > v_count:
        direction = "horizontal"
    else:
        union_w = max(float(b["xmax"]) for b in lines) - min(float(b["xmin"]) for b in lines)
        union_h = max(float(b["ymax"]) for b in lines) - min(float(b["ymin"]) for b in lines)
        is_tall = union_h > union_w * 1.15
        direction = "vertical" if (page_dominant_vertical or is_tall) else "horizontal"

    return _merge_lines_by_direction(lines, direction), direction


def _build_cluster(
    cluster: list[dict[str, Any]],
    w_safe: int,
    h_safe: int,
    direction: Literal["horizontal", "vertical"],
    force_cjk_clean: bool = False,
) -> ParagraphCluster:
    """Create a canonical normalized ParagraphCluster from grouped geometry entries."""
    c_ymin = min(float(item["ymin"]) for item in cluster)
    c_xmin = min(float(item["xmin"]) for item in cluster)
    c_ymax = max(float(item["ymax"]) for item in cluster)
    c_xmax = max(float(item["xmax"]) for item in cluster)

    norm_ymin = max(0, min(1000, round((c_ymin / h_safe) * 1000.0)))
    norm_xmin = max(0, min(1000, round((c_xmin / w_safe) * 1000.0)))
    norm_ymax = max(0, min(1000, round((c_ymax / h_safe) * 1000.0)))
    norm_xmax = max(0, min(1000, round((c_xmax / w_safe) * 1000.0)))

    if norm_ymin > norm_ymax:
        norm_ymin, norm_ymax = norm_ymax, norm_ymin
    if norm_xmin > norm_xmax:
        norm_xmin, norm_xmax = norm_xmax, norm_xmin

    if direction == "vertical":
        merged_text = _merge_lines_by_direction(cluster, "vertical")
    else:
        raw_texts = [str(item["text"]) for item in cluster]
        if force_cjk_clean:
            merged_text = clean_cjk_text("".join(raw_texts))
        else:
            merged_text = _merge_lines_by_direction(cluster, "horizontal")

    avg_conf = sum(float(item["conf"]) for item in cluster) / float(len(cluster))
    return ParagraphCluster(
        box_2d=(norm_ymin, norm_xmin, norm_ymax, norm_xmax),
        pixel_box=(round(c_ymin), round(c_xmin), round(c_ymax), round(c_xmax)),
        text=merged_text,
        confidence=round(avg_conf, 3),
        direction=direction,
    )


def _cluster_horizontal_entries(
    lines: list[dict[str, Any]],
    image_width: int,
    image_height: int,
    line_height_factor: float = 1.25,
    force_cjk_clean: bool = False,
) -> list[ParagraphCluster]:
    """Cluster horizontal lines using vertical gap and horizontal overlap (Top-to-Bottom, LTR)."""
    if not lines:
        return []

    sorted_lines = sorted(lines, key=lambda item: (float(item["ymin"]), float(item["xmin"])))
    clusters: list[list[dict[str, Any]]] = []
    current_cluster: list[dict[str, Any]] = []

    for line in sorted_lines:
        if not current_cluster:
            current_cluster.append(line)
            continue

        prev_line = current_cluster[-1]
        gap_y = float(line["ymin"]) - float(prev_line["ymax"])
        avg_h = (float(prev_line["h"]) + float(line["h"])) / 2.0

        cluster_xmin = min(float(item["xmin"]) for item in current_cluster)
        cluster_xmax = max(float(item["xmax"]) for item in current_cluster)
        overlap_x = max(0.0, min(float(line["xmax"]), cluster_xmax) - max(float(line["xmin"]), cluster_xmin))

        if gap_y <= avg_h * line_height_factor and (overlap_x > 0.0 or gap_y <= 0.4 * avg_h):
            current_cluster.append(line)
        else:
            clusters.append(current_cluster)
            current_cluster = [line]

    if current_cluster:
        clusters.append(current_cluster)

    w_safe = max(1, image_width)
    h_safe = max(1, image_height)
    return [
        _build_cluster(cluster, w_safe, h_safe, "horizontal", force_cjk_clean=force_cjk_clean)
        for cluster in clusters
    ]


def _cluster_vertical_entries(
    lines: list[dict[str, Any]],
    image_width: int,
    image_height: int,
    col_width_factor: float = 1.35,
) -> list[ParagraphCluster]:
    """Filter Furigana and cluster vertical text columns Right-to-Left into coherent blocks."""
    if not lines:
        return []

    filtered = filter_furigana_boxes(lines)
    sorted_lines = sorted(filtered, key=lambda item: (-float(item["xmax"]), float(item["ymin"])))
    clusters: list[list[dict[str, Any]]] = []
    current_cluster: list[dict[str, Any]] = []

    for line in sorted_lines:
        if not current_cluster:
            current_cluster.append(line)
            continue

        cluster_xmin = min(float(item["xmin"]) for item in current_cluster)
        cluster_ymin = min(float(item["ymin"]) for item in current_cluster)
        cluster_ymax = max(float(item["ymax"]) for item in current_cluster)
        avg_w = sum(float(item["w"]) for item in current_cluster) / float(len(current_cluster))
        avg_w = (avg_w + float(line["w"])) / 2.0

        gap_x = cluster_xmin - float(line["xmax"])
        overlap_y = max(0.0, min(float(line["ymax"]), cluster_ymax) - max(float(line["ymin"]), cluster_ymin))

        if gap_x <= avg_w * col_width_factor and (overlap_y > 0.0 or gap_x <= 0.4 * avg_w):
            current_cluster.append(line)
        else:
            clusters.append(current_cluster)
            current_cluster = [line]

    if current_cluster:
        clusters.append(current_cluster)

    w_safe = max(1, image_width)
    h_safe = max(1, image_height)
    return [_build_cluster(cluster, w_safe, h_safe, "vertical") for cluster in clusters]


def cluster_lines_to_paragraphs(
    raw_ocr_lines: list[Any],
    image_width: int,
    image_height: int,
    line_height_factor: float = 1.25,
    is_ja: bool = False,
) -> list[ParagraphCluster]:
    """Cluster raw OCR lines into coherent horizontal paragraphs using vertical gap and horizontal overlap.

    Args:
        raw_ocr_lines: List of RapidOCR detections: [[box_points, text, confidence], ...].
        image_width: Physical width of the source image in pixels.
        image_height: Physical height of the source image in pixels.
        line_height_factor: Multiplier for average line height determining paragraph break threshold.
        is_ja: When True, applies Japanese/CJK character de-spacing unconditionally.

    Returns:
        List of ParagraphCluster objects sorted Top-to-Bottom, Left-to-Right.
    """
    parsed_lines = _parse_raw_ocr_lines(raw_ocr_lines)
    return _cluster_horizontal_entries(
        parsed_lines,
        image_width=image_width,
        image_height=image_height,
        line_height_factor=line_height_factor,
        force_cjk_clean=is_ja,
    )


def cluster_lines_bidirectional(
    raw_ocr_lines: Sequence[Any],
    image_width: int,
    image_height: int,
    line_height_factor: float = 1.25,
    col_width_factor: float = 1.35,
) -> list[ParagraphCluster]:
    """Cluster raw OCR detections supporting mixed vertical (RTL) and horizontal (LTR) blocks on the same page."""
    parsed = _parse_raw_ocr_lines(raw_ocr_lines)
    if not parsed:
        return []

    v_entries = [b for b in parsed if b["orientation"] == "vertical"]
    h_entries = [b for b in parsed if b["orientation"] == "horizontal"]
    s_entries = [b for b in parsed if b["orientation"] == "square"]

    default_dir: Literal["horizontal", "vertical"] = (
        "vertical" if len(v_entries) > len(h_entries) else "horizontal"
    )
    non_square = v_entries + h_entries
    for sq in s_entries:
        assigned = default_dir
        if non_square:
            search_radius = 3.0 * max(float(sq["w"]), float(sq["h"]))
            nearest = min(
                non_square,
                key=lambda nb: ((float(nb["cx"]) - float(sq["cx"])) ** 2 + (float(nb["cy"]) - float(sq["cy"])) ** 2)
                ** 0.5,
            )
            dist = ((float(nearest["cx"]) - float(sq["cx"])) ** 2 + (float(nearest["cy"]) - float(sq["cy"])) ** 2) ** 0.5
            if dist <= search_radius:
                assigned = "vertical" if nearest["orientation"] == "vertical" else "horizontal"
        if assigned == "vertical":
            v_entries.append(sq)
        else:
            h_entries.append(sq)

    vertical_clusters = _cluster_vertical_entries(
        v_entries,
        image_width=image_width,
        image_height=image_height,
        col_width_factor=col_width_factor,
    )
    horizontal_clusters = _cluster_horizontal_entries(
        h_entries,
        image_width=image_width,
        image_height=image_height,
        line_height_factor=line_height_factor,
    )

    return [*vertical_clusters, *horizontal_clusters]


def assemble_comic_lines(raw_lines: list[str]) -> str:
    """Merge wrapped lines inside a comic speech bubble and resolve hyphenation."""
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

        if merged.endswith("-") and not merged.endswith("--"):
            merged = merged[:-1] + cleaned
        else:
            merged = f"{merged} {cleaned}"

    merged = re.sub(r"[ \t]+", " ", merged)
    return merged.strip()


def clean_cjk_text(raw_text: str) -> str:
    """Clean Japanese/Chinese manga OCR transcription by stripping spurious inter-CJK whitespace."""
    if not raw_text:
        return ""

    text = raw_text.replace("\r", " ").replace("\n", " ")
    text = _CJK_DESPACE_PATTERN.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def clean_japanese_text(raw_text: str) -> str:
    """Clean Japanese/CJK manga OCR transcription (alias of clean_cjk_text)."""
    return clean_cjk_text(raw_text)
