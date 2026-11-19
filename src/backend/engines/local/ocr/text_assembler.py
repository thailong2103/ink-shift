"""Text assembly, bi-directional line clustering, Furigana filtering, and CJK normalization."""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Callable, Sequence
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


def _entry_to_box_1000(
    entry: dict[str, Any],
    w_safe: int,
    h_safe: int,
) -> tuple[float, float, float, float]:
    """Convert a geometry entry from physical pixel coordinates to [0, 1000] bounds."""
    ymin = max(0.0, min(1000.0, (float(entry["ymin"]) / float(h_safe)) * 1000.0))
    xmin = max(0.0, min(1000.0, (float(entry["xmin"]) / float(w_safe)) * 1000.0))
    ymax = max(0.0, min(1000.0, (float(entry["ymax"]) / float(h_safe)) * 1000.0))
    xmax = max(0.0, min(1000.0, (float(entry["xmax"]) / float(w_safe)) * 1000.0))
    return (ymin, xmin, ymax, xmax)


def _box_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Compute intersection area between two (ymin, xmin, ymax, xmax) boxes."""
    inter_h = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    inter_w = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return inter_h * inter_w


def _assign_panel_index(
    box_1000: tuple[float, float, float, float],
    panel_boxes: Sequence[tuple[int, int, int, int]],
) -> int:
    """Assign entry to its enclosing panel index, picking smallest panel for nested insets."""
    if not panel_boxes:
        return -1
    cx = (box_1000[1] + box_1000[3]) / 2.0
    cy = (box_1000[0] + box_1000[2]) / 2.0
    best_idx = -1
    best_area = float("inf")
    for idx, (p_ymin, p_xmin, p_ymax, p_xmax) in enumerate(panel_boxes):
        if float(p_ymin) <= cy <= float(p_ymax) and float(p_xmin) <= cx <= float(p_xmax):
            area = float(max(1, p_ymax - p_ymin) * max(1, p_xmax - p_xmin))
            if area < best_area:
                best_area = area
                best_idx = idx
    return best_idx


def _overlaps_any_bubble(
    box_1000: tuple[float, float, float, float],
    bubble_boxes: Sequence[tuple[int, int, int, int]],
    threshold: float,
) -> bool:
    """Return True when intersection-over-min-area with any speech bubble exceeds threshold."""
    box_area = max(1.0, (box_1000[2] - box_1000[0]) * (box_1000[3] - box_1000[1]))
    for b_ymin, b_xmin, b_ymax, b_xmax in bubble_boxes:
        b_box = (float(b_ymin), float(b_xmin), float(b_ymax), float(b_xmax))
        inter = _box_intersection_area(box_1000, b_box)
        if inter <= 0.0:
            continue
        bubble_area = max(1.0, (b_box[2] - b_box[0]) * (b_box[3] - b_box[1]))
        min_area = max(1.0, min(box_area, bubble_area))
        if (inter / min_area) > threshold:
            return True
    return False


def _can_merge_vertical(
    a: dict[str, Any],
    b: dict[str, Any],
    col_width_factor: float = 1.35,
) -> bool:
    """Return True if two vertical entries belong to the same column or adjacent columns."""
    a_w, b_w = float(a["w"]), float(b["w"])
    a_h, b_h = float(a["h"]), float(b["h"])
    w_avg = (a_w + b_w) / 2.0
    w_min = max(1.0, min(a_w, b_w))
    h_min = max(1.0, min(a_h, b_h))
    if max(a_w, b_w) > 2.8 * w_min:
        return False

    gap_x = max(0.0, max(float(a["xmin"]), float(b["xmin"])) - min(float(a["xmax"]), float(b["xmax"])))
    overlap_x = max(0.0, min(float(a["xmax"]), float(b["xmax"])) - max(float(a["xmin"]), float(b["xmin"])))
    gap_y = max(0.0, max(float(a["ymin"]), float(b["ymin"])) - min(float(a["ymax"]), float(b["ymax"])))
    overlap_y = max(0.0, min(float(a["ymax"]), float(b["ymax"])) - max(float(a["ymin"]), float(b["ymin"])))

    adjacent_cols = gap_x <= w_avg * col_width_factor and overlap_y >= 0.15 * h_min
    same_col_split = overlap_x >= 0.35 * w_min and gap_y <= 1.2 * w_avg
    return adjacent_cols or same_col_split


def _can_merge_horizontal(
    a: dict[str, Any],
    b: dict[str, Any],
    line_height_factor: float = 1.25,
) -> bool:
    """Return True if two horizontal entries are stacked lines or split segments on one row."""
    a_w, b_w = float(a["w"]), float(b["w"])
    a_h, b_h = float(a["h"]), float(b["h"])
    h_avg = (a_h + b_h) / 2.0
    h_min = max(1.0, min(a_h, b_h))
    w_min = max(1.0, min(a_w, b_w))
    if max(a_h, b_h) > 2.8 * h_min:
        return False

    gap_y = max(0.0, max(float(a["ymin"]), float(b["ymin"])) - min(float(a["ymax"]), float(b["ymax"])))
    overlap_y = max(0.0, min(float(a["ymax"]), float(b["ymax"])) - max(float(a["ymin"]), float(b["ymin"])))
    gap_x = max(0.0, max(float(a["xmin"]), float(b["xmin"])) - min(float(a["xmax"]), float(b["xmax"])))
    overlap_x = max(0.0, min(float(a["xmax"]), float(b["xmax"])) - max(float(a["xmin"]), float(b["xmin"])))

    stacked_lines = gap_y <= h_avg * line_height_factor and overlap_x >= 0.15 * w_min
    same_row_split = overlap_y >= 0.40 * h_min and gap_x <= 1.5 * h_avg
    return stacked_lines or same_row_split


def _union_find_cluster_entries(
    entries: list[dict[str, Any]],
    can_merge: Callable[[dict[str, Any], dict[str, Any]], bool],
    image_width: int,
    image_height: int,
    panel_boxes: Sequence[tuple[int, int, int, int]] = (),
    bubble_boxes: Sequence[tuple[int, int, int, int]] = (),
    bubble_merge_threshold: float = 0.25,
) -> list[list[dict[str, Any]]]:
    """Group entries using distance-ordered 2D Union-Find while respecting panel/bubble barriers."""
    n = len(entries)
    if n == 0:
        return []

    w_safe = max(1, image_width)
    h_safe = max(1, image_height)
    boxes_1000 = [_entry_to_box_1000(entry, w_safe, h_safe) for entry in entries]
    panel_ids = [_assign_panel_index(box, panel_boxes) for box in boxes_1000]

    edges: list[tuple[float, int, int]] = []
    for i in range(n):
        ei = entries[i]
        for j in range(i + 1, n):
            if panel_ids[i] != panel_ids[j]:
                continue
            ej = entries[j]
            if not can_merge(ei, ej):
                continue
            gx = max(
                0.0,
                max(float(ei["xmin"]), float(ej["xmin"])) - min(float(ei["xmax"]), float(ej["xmax"])),
            )
            gy = max(
                0.0,
                max(float(ei["ymin"]), float(ej["ymin"])) - min(float(ei["ymax"]), float(ej["ymax"])),
            )
            edges.append((math.hypot(gx, gy), i, j))

    edges.sort(key=lambda edge: (edge[0], edge[1], edge[2]))

    parent = list(range(n))
    comp_bounds = list(boxes_1000)

    def find_root(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for _dist, i, j in edges:
        ri = find_root(i)
        rj = find_root(j)
        if ri == rj:
            continue
        bi = comp_bounds[ri]
        bj = comp_bounds[rj]
        candidate_box = (
            min(bi[0], bj[0]),
            min(bi[1], bj[1]),
            max(bi[2], bj[2]),
            max(bi[3], bj[3]),
        )
        if bubble_boxes and _overlaps_any_bubble(candidate_box, bubble_boxes, bubble_merge_threshold):
            continue
        new_root, old_root = (ri, rj) if ri < rj else (rj, ri)
        parent[old_root] = new_root
        comp_bounds[new_root] = candidate_box

    grouped: dict[int, list[dict[str, Any]]] = {}
    for idx, entry in enumerate(entries):
        root = find_root(idx)
        grouped.setdefault(root, []).append(entry)
    return list(grouped.values())


def _cluster_horizontal_entries(
    lines: list[dict[str, Any]],
    image_width: int,
    image_height: int,
    line_height_factor: float = 1.25,
    force_cjk_clean: bool = False,
    panel_boxes: Sequence[tuple[int, int, int, int]] = (),
    bubble_boxes: Sequence[tuple[int, int, int, int]] = (),
) -> list[ParagraphCluster]:
    """Cluster horizontal lines using 2D connected components and panel/bubble barriers."""
    if not lines:
        return []

    sorted_lines = sorted(lines, key=lambda item: (float(item["ymin"]), float(item["xmin"])))
    clusters = _union_find_cluster_entries(
        sorted_lines,
        can_merge=lambda a, b: _can_merge_horizontal(a, b, line_height_factor=line_height_factor),
        image_width=image_width,
        image_height=image_height,
        panel_boxes=panel_boxes,
        bubble_boxes=bubble_boxes,
    )

    w_safe = max(1, image_width)
    h_safe = max(1, image_height)
    built = [
        _build_cluster(cluster, w_safe, h_safe, "horizontal", force_cjk_clean=force_cjk_clean)
        for cluster in clusters
    ]
    built.sort(key=lambda c: (c.box_2d[0], c.box_2d[1]))
    return built


def _cluster_vertical_entries(
    lines: list[dict[str, Any]],
    image_width: int,
    image_height: int,
    col_width_factor: float = 1.35,
    panel_boxes: Sequence[tuple[int, int, int, int]] = (),
    bubble_boxes: Sequence[tuple[int, int, int, int]] = (),
) -> list[ParagraphCluster]:
    """Filter Furigana and cluster vertical text columns Right-to-Left into coherent blocks."""
    if not lines:
        return []

    filtered = filter_furigana_boxes(lines)
    sorted_lines = sorted(filtered, key=lambda item: (-float(item["xmax"]), float(item["ymin"])))
    clusters = _union_find_cluster_entries(
        sorted_lines,
        can_merge=lambda a, b: _can_merge_vertical(a, b, col_width_factor=col_width_factor),
        image_width=image_width,
        image_height=image_height,
        panel_boxes=panel_boxes,
        bubble_boxes=bubble_boxes,
    )

    w_safe = max(1, image_width)
    h_safe = max(1, image_height)
    built = [_build_cluster(cluster, w_safe, h_safe, "vertical") for cluster in clusters]
    built.sort(key=lambda c: (-c.box_2d[3], c.box_2d[0]))
    return built


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
    panel_boxes: Sequence[tuple[int, int, int, int]] = (),
    bubble_boxes: Sequence[tuple[int, int, int, int]] = (),
) -> list[ParagraphCluster]:
    """Cluster raw OCR detections supporting mixed vertical (RTL) and horizontal (LTR) blocks cleanly."""
    parsed = _parse_raw_ocr_lines(raw_ocr_lines)
    if not parsed:
        return []

    v_entries = [b for b in parsed if b["orientation"] == "vertical"]
    h_entries = [b for b in parsed if b["orientation"] == "horizontal"]
    s_entries = [b for b in parsed if b["orientation"] == "square"]

    w_safe = max(1, image_width)
    h_safe = max(1, image_height)
    default_dir: Literal["horizontal", "vertical"] = (
        "vertical" if len(v_entries) > len(h_entries) else "horizontal"
    )
    non_square = v_entries + h_entries
    non_square_panels = (
        [_assign_panel_index(_entry_to_box_1000(nb, w_safe, h_safe), panel_boxes) for nb in non_square]
        if panel_boxes
        else [-1 for _ in non_square]
    )
    for sq in s_entries:
        assigned = default_dir
        sq_panel = (
            _assign_panel_index(_entry_to_box_1000(sq, w_safe, h_safe), panel_boxes)
            if panel_boxes
            else -1
        )
        candidates = (
            [nb for nb, nb_panel in zip(non_square, non_square_panels) if nb_panel == sq_panel]
            if panel_boxes
            else non_square
        )
        if candidates:
            search_radius = 3.0 * max(float(sq["w"]), float(sq["h"]))
            nearest = min(
                candidates,
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
        panel_boxes=panel_boxes,
        bubble_boxes=bubble_boxes,
    )
    horizontal_clusters = _cluster_horizontal_entries(
        h_entries,
        image_width=image_width,
        image_height=image_height,
        line_height_factor=line_height_factor,
        panel_boxes=panel_boxes,
        bubble_boxes=bubble_boxes,
    )

    combined = [*vertical_clusters, *horizontal_clusters]
    if bubble_boxes:
        combined = [
            cluster
            for cluster in combined
            if not _overlaps_any_bubble(
                (
                    float(cluster.box_2d[0]),
                    float(cluster.box_2d[1]),
                    float(cluster.box_2d[2]),
                    float(cluster.box_2d[3]),
                ),
                bubble_boxes,
                threshold=0.30,
            )
        ]
    return combined


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
