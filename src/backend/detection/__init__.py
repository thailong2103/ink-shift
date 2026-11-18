"""Shared Manga Speech Bubble and Layout Detection Module.

Elevates YOLO11s-seg detection, RDP polygon compression, and 2-tier RTL reading order sorting
into a unified prerequisite step shared by both on-device (local) and cloud vision engines.
"""

from src.backend.detection.assembler import (
    BubbleWorkItem,
    assemble_translated_blocks,
    compute_safe_render_box,
    prepare_local_work_items,
)
from src.backend.detection.base import (
    BaseBubbleDetector,
    DetectedBubble,
    DetectedPanel,
    DetectedText,
)
from src.backend.detection.downloader import ensure_model_file
from src.backend.detection.postprocess import (
    assign_child_texts_to_bubbles,
    compute_letterbox_params,
    crop_bubble_image,
    denormalize_box_from_1000,
    expand_child_text_boxes_in_polygon,
    extract_rdp_polygon,
    invert_letterbox_coords,
    normalize_box_to_1000,
    polygon_to_bounding_box,
    smooth_polygon_chaikin,
)
from src.backend.detection.sorter import (
    MangaReadingOrderSorter,
    sort_manga_reading_order,
)
from src.backend.detection.yolo11_detector import YOLO11Detector

__all__ = [
    "BaseBubbleDetector",
    "BubbleWorkItem",
    "DetectedBubble",
    "DetectedPanel",
    "DetectedText",
    "MangaReadingOrderSorter",
    "YOLO11Detector",
    "assemble_translated_blocks",
    "assign_child_texts_to_bubbles",
    "compute_letterbox_params",
    "compute_safe_render_box",
    "crop_bubble_image",
    "denormalize_box_from_1000",
    "ensure_model_file",
    "expand_child_text_boxes_in_polygon",
    "extract_rdp_polygon",
    "invert_letterbox_coords",
    "normalize_box_to_1000",
    "polygon_to_bounding_box",
    "prepare_local_work_items",
    "smooth_polygon_chaikin",
    "sort_manga_reading_order",
]

