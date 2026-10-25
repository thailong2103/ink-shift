"""Coordinate postprocessing, letterbox scaling math, RDP polygon compression, and crop slicing."""

from __future__ import annotations

import dataclasses
import functools
import io
from collections.abc import Sequence
from typing import Any

import cv2
import numpy as np
from PIL import Image

from src.backend.detection.base import DetectedBubble, DetectedText


def compute_letterbox_params(
    orig_w: int, orig_h: int, target_size: int = 1024
) -> tuple[float, int, int]:
    """Calculate scale factor and padding offsets for square letterboxed model input.

    Args:
        orig_w: Original image width in pixels (> 0).
        orig_h: Original image height in pixels (> 0).
        target_size: Square target dimension for model input (default 1024).

    Returns:
        tuple of (scale, pad_x, pad_y) where:
            scale: Multiplier applied to original dimensions.
            pad_x: Left/right pixel padding on the target canvas.
            pad_y: Top/bottom pixel padding on the target canvas.
    """
    if orig_w <= 0 or orig_h <= 0:
        raise ValueError(f"Image dimensions must be positive integers: w={orig_w}, h={orig_h}")

    scale = min(target_size / orig_w, target_size / orig_h)
    new_w = round(orig_w * scale)
    new_h = round(orig_h * scale)

    pad_x = (target_size - new_w) // 2
    pad_y = (target_size - new_h) // 2

    return scale, pad_x, pad_y


def invert_letterbox_coords(
    x: float,
    y: float,
    scale: float,
    pad_x: int,
    pad_y: int,
    orig_w: int,
    orig_h: int,
    clamped: bool = True,
) -> tuple[int, int]:
    """Map coordinates from letterboxed model space back to original image space.

    Args:
        x: X-coordinate in model space (0 to target_size).
        y: Y-coordinate in model space (0 to target_size).
        scale: Scale multiplier from compute_letterbox_params.
        pad_x: X-padding from compute_letterbox_params.
        pad_y: Y-padding from compute_letterbox_params.
        orig_w: Original image width in physical pixels.
        orig_h: Original image height in physical pixels.
        clamped: Whether to clamp coordinates within [0, orig_w] and [0, orig_h].

    Returns:
        tuple of (orig_x, orig_y).
    """
    if scale <= 0:
        raise ValueError(f"Scale must be strictly positive: {scale}")

    orig_x = round((x - pad_x) / scale)
    orig_y = round((y - pad_y) / scale)

    if clamped:
        orig_x = max(0, min(orig_w, orig_x))
        orig_y = max(0, min(orig_h, orig_y))

    return orig_x, orig_y


def polygon_to_bounding_box(
    polygon: Sequence[tuple[int, int]],
) -> tuple[int, int, int, int]:
    """Compute axis-aligned bounding box from a list of polygon vertices.

    Args:
        polygon: List of (x, y) vertex points.

    Returns:
        tuple of (ymin_px, xmin_px, ymax_px, xmax_px) in physical pixels.
    """
    if not polygon:
        raise ValueError("Polygon must contain at least one vertex point")

    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    return min_y, min_x, max_y, max_x


def normalize_box_to_1000(
    ymin_px: int,
    xmin_px: int,
    ymax_px: int,
    xmax_px: int,
    orig_w: int,
    orig_h: int,
) -> tuple[int, int, int, int]:
    """Normalize physical pixel coordinates into InkShift canonical [0, 1000] space.

    Guarantees:
        - All values integer bounded: 0 <= ymin < ymax <= 1000
        - All values integer bounded: 0 <= xmin < xmax <= 1000

    Args:
        ymin_px: Top boundary in pixels.
        xmin_px: Left boundary in pixels.
        ymax_px: Bottom boundary in pixels.
        xmax_px: Right boundary in pixels.
        orig_w: Original image width.
        orig_h: Original image height.

    Returns:
        tuple of (ymin, xmin, ymax, xmax) in [0, 1000].
    """
    if orig_w <= 0 or orig_h <= 0:
        raise ValueError(f"Invalid image dimensions: w={orig_w}, h={orig_h}")

    ymin = max(0, min(1000, round((ymin_px / orig_h) * 1000)))
    xmin = max(0, min(1000, round((xmin_px / orig_w) * 1000)))
    ymax = max(0, min(1000, round((ymax_px / orig_h) * 1000)))
    xmax = max(0, min(1000, round((xmax_px / orig_w) * 1000)))

    # Ensure box has at least 1 unit width and height
    if ymax <= ymin:
        if ymin >= 1000:
            ymin = 999
            ymax = 1000
        else:
            ymax = ymin + 1

    if xmax <= xmin:
        if xmin >= 1000:
            xmin = 999
            xmax = 1000
        else:
            xmax = xmin + 1

    return ymin, xmin, ymax, xmax


def denormalize_box_from_1000(
    box_2d: tuple[int, int, int, int],
    orig_w: int,
    orig_h: int,
) -> tuple[int, int, int, int]:
    """Map canonical [0, 1000] coordinates back to physical pixel boundaries.

    Args:
        box_2d: (ymin, xmin, ymax, xmax) in [0, 1000].
        orig_w: Original image width.
        orig_h: Original image height.

    Returns:
        tuple of (ymin_px, xmin_px, ymax_px, xmax_px) in physical pixels.
    """
    ymin, xmin, ymax, xmax = box_2d
    ymin_px = max(0, min(orig_h, round((ymin / 1000.0) * orig_h)))
    xmin_px = max(0, min(orig_w, round((xmin / 1000.0) * orig_w)))
    ymax_px = max(0, min(orig_h, round((ymax / 1000.0) * orig_h)))
    xmax_px = max(0, min(orig_w, round((xmax / 1000.0) * orig_w)))

    # Ensure valid slice range
    if ymax_px <= ymin_px:
        ymax_px = min(orig_h, ymin_px + 1)
    if xmax_px <= xmin_px:
        xmax_px = min(orig_w, xmin_px + 1)

    return ymin_px, xmin_px, ymax_px, xmax_px


def crop_bubble_image(
    image: Image.Image,
    bubble: DetectedBubble,
    output_format: str = "PNG",
) -> bytes:
    """Crop speech bubble region from a PIL image using canonical [0, 1000] coordinates.

    Args:
        image: Source PIL Image.
        bubble: DetectedBubble containing normalized box_2d.
        output_format: Format for output bytes ('PNG' or 'JPEG').

    Returns:
        Binary bytes of the cropped image region.
    """
    orig_w, orig_h = image.size
    ymin_px, xmin_px, ymax_px, xmax_px = denormalize_box_from_1000(
        bubble.box_2d, orig_w, orig_h
    )

    cropped = image.crop((xmin_px, ymin_px, xmax_px, ymax_px))

    buffer = io.BytesIO()
    cropped.save(buffer, format=output_format)
    return buffer.getvalue()


def smooth_polygon_chaikin(
    points: list[tuple[float, float]],
    iterations: int = 2,
    max_points: int = 80,
) -> list[tuple[float, float]]:
    """Smooth polygon vertices using Chaikin's corner-cutting subdivision algorithm.

    Converts a polygonal outline into a curvature-continuous quadratic B-spline curve,
    eliminating discrete pixel stair-steps and jagged angles while strictly preserving
    the overall bubble geometry.

    Args:
        points: List of (x, y) relative percentage [0.0, 100.0] vertices of a closed polygon.
        iterations: Number of corner-cutting subdivision passes (default 2).
        max_points: Point count threshold above which further subdivision is skipped (default 80).

    Returns:
        Smoothed list of (x, y) relative percentage vertices.
    """
    if len(points) < 4:
        return points

    # Filter out immediate consecutive duplicate points
    unique_points: list[tuple[float, float]] = []
    for pt in points:
        if not unique_points or pt != unique_points[-1]:
            unique_points.append(pt)
    if len(unique_points) > 2 and unique_points[0] == unique_points[-1]:
        unique_points.pop()

    if len(unique_points) < 4:
        return points

    curr = np.array(unique_points, dtype=np.float32)

    for _ in range(iterations):
        n = len(curr)
        if n >= max_points:
            break
        next_pts = np.roll(curr, -1, axis=0)
        q = 0.75 * curr + 0.25 * next_pts
        r = 0.25 * curr + 0.75 * next_pts
        interleaved = np.empty((2 * n, 2), dtype=np.float32)
        interleaved[0::2] = q
        interleaved[1::2] = r
        curr = interleaved

    result: list[tuple[float, float]] = []
    for p in curr:
        rx = round(float(np.clip(p[0], 0.0, 100.0)), 2)
        ry = round(float(np.clip(p[1], 0.0, 100.0)), 2)
        result.append((rx, ry))

    return result


def extract_rdp_polygon(
    mask_coeffs: np.ndarray[Any, np.dtype[np.float32]],
    protos: np.ndarray[Any, np.dtype[np.float32]],
    box_model: tuple[float, float, float, float],
    scale: float,
    pad_x: int,
    pad_y: int,
    orig_w: int,
    orig_h: int,
    epsilon_factor: float = 0.0035,
) -> list[tuple[float, float]]:
    """Decode prototype mask for a bubble and simplify into smooth 35-80 relative % polygon vertices.

    Args:
        mask_coeffs: 1D array of 32 mask coefficients from YOLO11 output0.
        protos: 3D array of 32 prototype masks (32, 256, 256) from YOLO11 output1.
        box_model: Bounding box (x1, y1, x2, y2) in 1024x1024 letterboxed model space.
        scale: Letterbox scale factor.
        pad_x: Letterbox X padding.
        pad_y: Letterbox Y padding.
        orig_w: Original image width in pixels.
        orig_h: Original image height in pixels.
        epsilon_factor: RDP approximation factor relative to arc length (default 0.0035).

    Returns:
        List of (x, y) polygon vertices in [0.0, 100.0] percentage relative to bubble bbox.
    """
    fallback_polygon: list[tuple[float, float]] = [
        (0.0, 0.0),
        (100.0, 0.0),
        (100.0, 100.0),
        (0.0, 100.0),
    ]

    if mask_coeffs.size != 32 or protos.shape[0] != 32:
        return fallback_polygon

    # 1. Dot product across 32 channels: (32,) . (32, 256, 256) -> (256, 256)
    m256 = np.tensordot(mask_coeffs, protos, axes=(0, 0))
    # Direct threshold: sigmoid(x) > 0.5 <=> x > 0.0
    bin_mask = (m256 > 0.0).astype(np.uint8) * 255

    # 2. Crop to bubble bounding box in 256x256 prototype mask space
    bx1, by1, bx2, by2 = box_model
    mx1 = max(0, min(255, round(bx1 * 0.25)))
    my1 = max(0, min(255, round(by1 * 0.25)))
    mx2 = max(0, min(255, round(bx2 * 0.25)))
    my2 = max(0, min(255, round(by2 * 0.25)))

    if mx2 <= mx1 or my2 <= my1:
        return fallback_polygon

    cropped = np.zeros_like(bin_mask)
    cropped[my1 : my2 + 1, mx1 : mx2 + 1] = bin_mask[my1 : my2 + 1, mx1 : mx2 + 1]

    # 3. Contour extraction directly on cropped mask
    # Preserves native bubble ink boundary without dilating across the artist's black stroke
    contours, _ = cv2.findContours(cropped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return fallback_polygon

    main_cnt = max(contours, key=cv2.contourArea)
    if cv2.contourArea(main_cnt) < 4.0:
        return fallback_polygon

    # 4. Ramer-Douglas-Peucker (RDP) polygon simplification
    peri = cv2.arcLength(main_cnt, True)
    approx = cv2.approxPolyDP(main_cnt, epsilon_factor * peri, True)
    if len(approx) < 4:
        approx = cv2.approxPolyDP(main_cnt, (epsilon_factor * 0.5) * peri, True)
    if len(approx) < 3:
        return fallback_polygon

    # 5. Compute original bubble bounding box in physical pixels
    orig_x1, orig_y1 = invert_letterbox_coords(bx1, by1, scale, pad_x, pad_y, orig_w, orig_h)
    orig_x2, orig_y2 = invert_letterbox_coords(bx2, by2, scale, pad_x, pad_y, orig_w, orig_h)
    bubble_xmin = min(orig_x1, orig_x2)
    bubble_ymin = min(orig_y1, orig_y2)
    bubble_xmax = max(orig_x1, orig_x2)
    bubble_ymax = max(orig_y1, orig_y2)
    box_w = max(1, bubble_xmax - bubble_xmin)
    box_h = max(1, bubble_ymax - bubble_ymin)

    # 6. Map vertices from 256x256 -> 1024x1024 -> original px -> relative [0.0, 100.0]%
    polygon_points: list[tuple[float, float]] = []
    for item in approx:
        p256_x = float(item[0][0])
        p256_y = float(item[0][1])
        p1024_x = p256_x * 4.0
        p1024_y = p256_y * 4.0
        orig_px, orig_py = invert_letterbox_coords(
            p1024_x, p1024_y, scale, pad_x, pad_y, orig_w, orig_h
        )
        rel_x = round(max(0.0, min(100.0, ((orig_px - bubble_xmin) / box_w) * 100.0)), 2)
        rel_y = round(max(0.0, min(100.0, ((orig_py - bubble_ymin) / box_h) * 100.0)), 2)
        polygon_points.append((rel_x, rel_y))

    if len(polygon_points) < 3:
        return fallback_polygon

    # 7. Apply Chaikin corner-cutting smoothing to eliminate discrete pixel stepping
    return smooth_polygon_chaikin(polygon_points, iterations=2)


def assign_child_texts_to_bubbles(
    bubbles: list[DetectedBubble],
    texts: list[DetectedText],
) -> list[DetectedBubble]:
    """Map detected child text blocks to their containing speech bubble.

    Synthesizes rectangular Pseudo-Bubbles for orphan texts (narration boxes, floating monologues)
    that do not fall into any detected speech bubble.

    Args:
        bubbles: List of detected speech bubbles with canonical [0, 1000] coordinates.
        texts: List of detected text blocks with canonical [0, 1000] coordinates.

    Returns:
        List of DetectedBubble instances updated with associated child texts and synthesized pseudo-bubbles.
    """
    if not texts:
        return bubbles

    # Map of bubble index to list of child DetectedText
    assignments: dict[int, list[DetectedText]] = {i: [] for i in range(len(bubbles))}
    orphan_texts: list[DetectedText] = []

    for text in texts:
        t_ymin, t_xmin, t_ymax, t_xmax = text.box_2d
        t_cy = (t_ymin + t_ymax) / 2.0
        t_cx = (t_xmin + t_xmax) / 2.0

        best_idx = -1
        best_area = float("inf")

        for idx, bubble in enumerate(bubbles):
            b_ymin, b_xmin, b_ymax, b_xmax = bubble.box_2d
            if b_ymin <= t_cy <= b_ymax and b_xmin <= t_cx <= b_xmax:
                area = (b_ymax - b_ymin) * (b_xmax - b_xmin)
                if area < best_area:
                    best_area = area
                    best_idx = idx

        if best_idx >= 0:
            assignments[best_idx].append(text)
        else:
            orphan_texts.append(text)

    def _compare_texts_rtl(t1: DetectedText, t2: DetectedText) -> int:
        y1_min, x1_min, y1_max, x1_max = t1.box_2d
        y2_min, x2_min, y2_max, x2_max = t2.box_2d

        cy1 = (y1_min + y1_max) / 2.0
        cy2 = (y2_min + y2_max) / 2.0
        cx1 = (x1_min + x1_max) / 2.0
        cx2 = (x2_min + x2_max) / 2.0

        overlap_y = max(0, min(y1_max, y2_max) - max(y1_min, y2_min))
        h1 = max(1, y1_max - y1_min)
        h2 = max(1, y2_max - y2_min)
        min_h = min(h1, h2)

        same_tier = False
        if overlap_y / min_h > 0.3 and not (y1_min > cy2 or y2_min > cy1):
            same_tier = True

        if same_tier:
            if cx1 > cx2:
                return -1
            if cx1 < cx2:
                return 1
            return 0

        if cy1 < cy2:
            return -1
        if cy1 > cy2:
            return 1
        return 0

    # Reconstruct DetectedBubble instances with assigned child texts sorted in RTL reading order
    updated_bubbles: list[DetectedBubble] = []
    for idx, bubble in enumerate(bubbles):
        child_texts = sorted(assignments.get(idx, []), key=functools.cmp_to_key(_compare_texts_rtl))
        updated_bubbles.append(dataclasses.replace(bubble, texts=child_texts))

    # Synthesize Pseudo-Bubbles for orphan texts (Narration boxes, floating dialogue)
    start_id = len(bubbles) + 1
    for o_idx, orphan in enumerate(orphan_texts):
        ymin, xmin, ymax, xmax = orphan.box_2d
        h = ymax - ymin
        w = xmax - xmin
        # Safe padding: 4% of dimension or at least 2 units in [0, 1000] space
        pad_y = max(2, round(h * 0.04))
        pad_x = max(2, round(w * 0.04))
        p_ymin = max(0, ymin - pad_y)
        p_xmin = max(0, xmin - pad_x)
        p_ymax = min(1000, ymax + pad_y)
        p_xmax = min(1000, xmax + pad_x)

        pseudo_bubble = DetectedBubble(
            id=str(start_id + o_idx),
            box_2d=(p_ymin, p_xmin, p_ymax, p_xmax),
            polygon=[(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)],
            texts=[orphan],
            confidence=orphan.confidence,
        )
        updated_bubbles.append(pseudo_bubble)

    return updated_bubbles


def expand_child_text_boxes_in_polygon(
    polygon_rel: list[tuple[float, float]],
    child_boxes_1000: list[tuple[int, int, int, int]],
    parent_box_1000: tuple[int, int, int, int],
    grid_size: int = 100,
    margin_between_boxes: int = 2,
) -> list[tuple[int, int, int, int]]:
    """Expand child text bounding boxes in 4 directions until touching curved polygon or adjacent box.

    Prevents text clipping in connected/merged speech bubbles by maximizing the safe-zone area
    allocated to each child dialogue block inside its respective lobe.

    Args:
        polygon_rel: List of (x, y) relative percentage [0.0, 100.0] vertices of curved balloon contour.
        child_boxes_1000: List of (ymin, xmin, ymax, xmax) canonical coordinates of child texts.
        parent_box_1000: (ymin, xmin, ymax, xmax) canonical coordinates of parent bubble bounding box.
        grid_size: Resolution of the raster grid for mask testing (default 100x100).
        margin_between_boxes: Safety spacing in grid units to prevent collision between adjacent boxes.

    Returns:
        List of expanded (ymin, xmin, ymax, xmax) canonical coordinates corresponding to each child.
    """
    if not child_boxes_1000:
        return []
    if len(polygon_rel) < 3:
        return child_boxes_1000

    p_ymin, p_xmin, p_ymax, p_xmax = parent_box_1000
    p_h = max(1, p_ymax - p_ymin)
    p_w = max(1, p_xmax - p_xmin)

    # 1. Rasterize curved polygon contour into a 2D binary safe-zone mask
    mask: np.ndarray[Any, np.dtype[np.uint8]] = np.zeros((grid_size, grid_size), dtype=np.uint8)
    poly_pts = np.array(
        [
            [
                max(0, min(grid_size - 1, round(x * (grid_size - 1) / 100.0))),
                max(0, min(grid_size - 1, round(y * (grid_size - 1) / 100.0))),
            ]
            for x, y in polygon_rel
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [poly_pts], 1)

    num_boxes = len(child_boxes_1000)
    boxes: list[list[int]] = []

    # 2. Map child centers into grid coordinates
    for c_ymin, c_xmin, c_ymax, c_xmax in child_boxes_1000:
        rel_cy = ((c_ymin + c_ymax) / 2.0 - p_ymin) / p_h * (grid_size - 1)
        rel_cx = ((c_xmin + c_xmax) / 2.0 - p_xmin) / p_w * (grid_size - 1)
        cy = max(0, min(grid_size - 1, round(rel_cy)))
        cx = max(0, min(grid_size - 1, round(rel_cx)))

        # If center falls outside rasterized contour, snap to nearest interior pixel
        if mask[cy, cx] == 0:
            inside_pts = np.argwhere(mask == 1)
            if len(inside_pts) > 0:
                dists = np.sum((inside_pts - np.array([cy, cx])) ** 2, axis=1)
                best_pt = inside_pts[int(np.argmin(dists))]
                cy, cx = int(best_pt[0]), int(best_pt[1])

        y1 = max(0, cy - 1)
        x1 = max(0, cx - 1)
        y2 = min(grid_size - 1, cy + 1)
        x2 = min(grid_size - 1, cx + 1)
        boxes.append([y1, x1, y2, x2])

    def can_move(b_idx: int, direction: str) -> bool:
        y1, x1, y2, x2 = boxes[b_idx]
        if direction == "up":
            if y1 <= 0:
                return False
            ny1 = y1 - 1
            if not np.all(mask[ny1, x1 : x2 + 1] == 1):
                return False
            target_box = (ny1, x1, y2, x2)
        elif direction == "down":
            if y2 >= grid_size - 1:
                return False
            ny2 = y2 + 1
            if not np.all(mask[ny2, x1 : x2 + 1] == 1):
                return False
            target_box = (y1, x1, ny2, x2)
        elif direction == "left":
            if x1 <= 0:
                return False
            nx1 = x1 - 1
            if not np.all(mask[y1 : y2 + 1, nx1] == 1):
                return False
            target_box = (y1, nx1, y2, x2)
        elif direction == "right":
            if x2 >= grid_size - 1:
                return False
            nx2 = x2 + 1
            if not np.all(mask[y1 : y2 + 1, nx2] == 1):
                return False
            target_box = (y1, x1, y2, nx2)
        else:
            return False

        ty1, tx1, ty2, tx2 = target_box
        for o_idx in range(num_boxes):
            if o_idx == b_idx:
                continue
            oy1, ox1, oy2, ox2 = boxes[o_idx]
            if not (
                ty2 + margin_between_boxes < oy1
                or ty1 > oy2 + margin_between_boxes
                or tx2 + margin_between_boxes < ox1
                or tx1 > ox2 + margin_between_boxes
            ):
                return False

        return True

    # 3. Iterative 4-direction expansion until touching boundary or adjacent box
    directions = ["up", "down", "left", "right"]
    expanded_any = True
    iterations = 0
    max_iters = grid_size

    while expanded_any and iterations < max_iters:
        expanded_any = False
        iterations += 1
        for b_idx in range(num_boxes):
            for d in directions:
                if can_move(b_idx, d):
                    if d == "up":
                        boxes[b_idx][0] -= 1
                    elif d == "down":
                        boxes[b_idx][2] += 1
                    elif d == "left":
                        boxes[b_idx][1] -= 1
                    elif d == "right":
                        boxes[b_idx][3] += 1
                    expanded_any = True

    # 4. Convert back to canonical [0, 1000] coordinates
    res: list[tuple[int, int, int, int]] = []
    for y1, x1, y2, x2 in boxes:
        exp_ymin = max(0, min(1000, round(p_ymin + (y1 / (grid_size - 1)) * p_h)))
        exp_xmin = max(0, min(1000, round(p_xmin + (x1 / (grid_size - 1)) * p_w)))
        exp_ymax = max(exp_ymin + 1, min(1000, round(p_ymin + (y2 / (grid_size - 1)) * p_h)))
        exp_xmax = max(exp_xmin + 1, min(1000, round(p_xmin + (x2 / (grid_size - 1)) * p_w)))
        res.append((exp_ymin, exp_xmin, exp_ymax, exp_xmax))

    return res
