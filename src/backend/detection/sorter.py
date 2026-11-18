"""2-Tier RTL Manga Reading Order Sorter (Panel -> In-Panel 1.5Y - X)."""

from __future__ import annotations

import dataclasses
import functools

from src.backend.detection.base import DetectedBubble, DetectedPanel


def _compare_panels(p1: DetectedPanel, p2: DetectedPanel) -> int:
    """Compare two manga panels for Japanese RTL narrative reading order.

    Rule:
        - If two panels overlap vertically by > 30% of the smaller panel's height,
          they belong to the same row. In Japanese manga, the rightmost panel is read first.
        - Otherwise, the higher panel (smaller ymin) is read first.
    """
    p1_ymin, p1_xmin, p1_ymax, p1_xmax = p1.box_2d
    p2_ymin, p2_xmin, p2_ymax, p2_xmax = p2.box_2d

    p1_h = max(1, p1_ymax - p1_ymin)
    p2_h = max(1, p2_ymax - p2_ymin)

    overlap_y = max(0, min(p1_ymax, p2_ymax) - max(p1_ymin, p2_ymin))
    min_h = min(p1_h, p2_h)

    # Overlap threshold: 30% of the smaller panel height
    if overlap_y / min_h > 0.3:
        # Same row: right-to-left (larger x is read first)
        p1_cx = (p1_xmin + p1_xmax) / 2.0
        p2_cx = (p2_xmin + p2_xmax) / 2.0
        if p1_cx > p2_cx:
            return -1
        if p1_cx < p2_cx:
            return 1
        return 0

    # Different rows: top-to-bottom (smaller ymin is read first)
    if p1_ymin < p2_ymin:
        return -1
    if p1_ymin > p2_ymin:
        return 1
    return 0


def _compare_bubbles_in_panel(b1: DetectedBubble, b2: DetectedBubble) -> int:
    """Compare two speech bubbles within the same panel (or page) for RTL manga reading order.

    Rule:
        - If two bubbles share a horizontal conversational tier:
          (vertical overlap > 30% of the smaller bubble's height, AND neither bubble
          starts below the vertical center of the other),
          Japanese manga reads Right-to-Left (larger X coordinate first).
        - Otherwise, they belong to different vertical tiers:
          Top-to-Bottom reads first (smaller vertical center / top edge).
    """
    y1_min, x1_min, y1_max, x1_max = b1.box_2d
    y2_min, x2_min, y2_max, x2_max = b2.box_2d

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
        # Same tier: Right-to-Left (larger X read first)
        if cx1 > cx2:
            return -1
        if cx1 < cx2:
            return 1
        return 0

    # Different tiers: Top-to-Bottom (smaller cy read first)
    if cy1 < cy2:
        return -1
    if cy1 > cy2:
        return 1
    return 0


class MangaReadingOrderSorter:
    """2-tier hierarchical manga reading order sorter."""

    @staticmethod
    def sort(
        bubbles: list[DetectedBubble],
        panels: list[DetectedPanel],
    ) -> list[DetectedBubble]:
        """Sort bubbles into Japanese Right-to-Left, Top-to-Bottom narrative sequence.

        Args:
            bubbles: List of detected speech bubbles in [0, 1000] canonical coordinates.
            panels: List of detected manga panels in [0, 1000] canonical coordinates.

        Returns:
            List of bubbles sorted in reading order, re-indexed with IDs '1', '2', ...
        """
        if not bubbles:
            return []

        # If no panels detected (e.g. borderless manga), sort all bubbles by Tier 2 comparator
        if not panels:
            sorted_bubbles = sorted(bubbles, key=functools.cmp_to_key(_compare_bubbles_in_panel))
            return [
                dataclasses.replace(b, id=str(i + 1), panel_index=-1)
                for i, b in enumerate(sorted_bubbles)
            ]

        # 1. Sort panels in Japanese reading order (top-to-bottom, right-to-left)
        sorted_panels = sorted(panels, key=functools.cmp_to_key(_compare_panels))

        # 2. Group bubbles into sorted panels
        panel_buckets: dict[int, list[DetectedBubble]] = {
            i: [] for i in range(len(sorted_panels))
        }
        unassigned_bubbles: list[DetectedBubble] = []

        for bubble in bubbles:
            ymin, xmin, ymax, xmax = bubble.box_2d
            b_cy = (ymin + ymax) / 2.0
            b_cx = (xmin + xmax) / 2.0

            best_panel_idx = -1
            best_area = float("inf")

            for p_idx, panel in enumerate(sorted_panels):
                p_ymin, p_xmin, p_ymax, p_xmax = panel.box_2d
                if p_ymin <= b_cy <= p_ymax and p_xmin <= b_cx <= p_xmax:
                    area = (p_ymax - p_ymin) * (p_xmax - p_xmin)
                    if area < best_area:
                        best_area = area
                        best_panel_idx = p_idx

            if best_panel_idx >= 0:
                panel_buckets[best_panel_idx].append(bubble)
            else:
                unassigned_bubbles.append(bubble)

        # 3. Sort bubbles within each panel bucket using Tier 2 comparator
        ordered_bubbles: list[DetectedBubble] = []

        # If there are unassigned bubbles, treat them as a virtual panel placed by their bounding box
        virtual_panels_with_bubbles: list[tuple[DetectedPanel, int, list[DetectedBubble]]] = []
        for p_idx, panel in enumerate(sorted_panels):
            p_bubbles = panel_buckets[p_idx]
            if p_bubbles:
                virtual_panels_with_bubbles.append((panel, p_idx, p_bubbles))

        if unassigned_bubbles:
            # Create a virtual panel wrapping unassigned bubbles
            u_ymins = [b.box_2d[0] for b in unassigned_bubbles]
            u_xmins = [b.box_2d[1] for b in unassigned_bubbles]
            u_ymaxs = [b.box_2d[2] for b in unassigned_bubbles]
            u_xmaxs = [b.box_2d[3] for b in unassigned_bubbles]
            u_panel = DetectedPanel(
                box_2d=(min(u_ymins), min(u_xmins), max(u_ymaxs), max(u_xmaxs)),
                confidence=1.0,
            )
            virtual_panels_with_bubbles.append((u_panel, -1, unassigned_bubbles))

        # Re-sort virtual panels so unassigned clusters appear in their proper page location
        final_panel_order = sorted(
            virtual_panels_with_bubbles,
            key=lambda item: functools.cmp_to_key(_compare_panels)(item[0]),
        )

        for _, assigned_idx, p_bubbles in final_panel_order:
            sorted_in_panel = sorted(p_bubbles, key=functools.cmp_to_key(_compare_bubbles_in_panel))
            for b in sorted_in_panel:
                ordered_bubbles.append(dataclasses.replace(b, panel_index=assigned_idx))

        # 4. Re-index sequential bubble IDs: '1', '2', '3', ...
        return [
            dataclasses.replace(b, id=str(i + 1))
            for i, b in enumerate(ordered_bubbles)
        ]


def sort_manga_reading_order(
    bubbles: list[DetectedBubble],
    panels: list[DetectedPanel],
) -> list[DetectedBubble]:
    """Convenience functional wrapper for MangaReadingOrderSorter.sort."""
    return MangaReadingOrderSorter.sort(bubbles, panels)
