"""Unit tests for YOLO11s-seg bubble detector, coordinate geometry math, and crop slicing."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from src.backend.detection.base import (
    BaseBubbleDetector,
    DetectedBubble,
    DetectedText,
)
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
from src.backend.detection.yolo11_detector import YOLO11Detector

# ---------------------------------------------------------------------------
# Letterbox & Geometry Math Tests
# ---------------------------------------------------------------------------


def test_letterbox_params_tall_image() -> None:
    """Tall aspect ratio (e.g. standard manga page 800x1200) should letterbox with horizontal padding."""
    scale, pad_x, pad_y = compute_letterbox_params(orig_w=800, orig_h=1200, target_size=1024)
    expected_scale = 1024.0 / 1200.0
    assert pytest.approx(scale, rel=1e-3) == expected_scale
    assert pad_y == 0
    assert pad_x > 0
    new_w = round(800 * scale)
    assert new_w + 2 * pad_x == 1024 or (new_w + 2 * pad_x == 1023)


def test_letterbox_params_wide_image() -> None:
    """Wide aspect ratio (e.g. double-spread 1920x1080) should letterbox with vertical padding."""
    scale, pad_x, pad_y = compute_letterbox_params(orig_w=1920, orig_h=1080, target_size=1024)
    expected_scale = 1024.0 / 1920.0
    assert pytest.approx(scale, rel=1e-3) == expected_scale
    assert pad_x == 0
    assert pad_y > 0


def test_letterbox_params_invalid_dimensions() -> None:
    """Non-positive dimensions must raise ValueError."""
    with pytest.raises(ValueError):
        compute_letterbox_params(orig_w=0, orig_h=1000)
    with pytest.raises(ValueError):
        compute_letterbox_params(orig_w=1000, orig_h=-10)


def test_invert_letterbox_coords() -> None:
    """Inverting letterbox coordinates must correctly return original pixel space."""
    scale, pad_x, pad_y = compute_letterbox_params(orig_w=800, orig_h=1200, target_size=1024)
    orig_x, orig_y = invert_letterbox_coords(512, 512, scale, pad_x, pad_y, orig_w=800, orig_h=1200)
    assert 0 <= orig_x <= 800
    assert 0 <= orig_y <= 1200

    clamped_x, clamped_y = invert_letterbox_coords(-50, 2000, scale, pad_x, pad_y, orig_w=800, orig_h=1200)
    assert clamped_x == 0
    assert clamped_y == 1200


def test_invert_letterbox_invalid_scale() -> None:
    """Negative or zero scale must raise ValueError."""
    with pytest.raises(ValueError):
        invert_letterbox_coords(100, 100, scale=0.0, pad_x=0, pad_y=0, orig_w=800, orig_h=1200)


def test_polygon_to_bounding_box() -> None:
    """Polygon vertices should correctly collapse to axis-aligned bounding box."""
    polygon = [(150, 100), (300, 120), (280, 400), (120, 380)]
    ymin, xmin, ymax, xmax = polygon_to_bounding_box(polygon)
    assert ymin == 100
    assert xmin == 120
    assert ymax == 400
    assert xmax == 300


def test_polygon_to_bounding_box_empty() -> None:
    """Empty polygon must raise ValueError."""
    with pytest.raises(ValueError):
        polygon_to_bounding_box([])


# ---------------------------------------------------------------------------
# Coordinate Normalization & Clamping Tests
# ---------------------------------------------------------------------------


def test_normalize_box_to_1000_standard() -> None:
    """Standard coordinates must convert accurately to [0, 1000] integer scale."""
    ymin, xmin, ymax, xmax = normalize_box_to_1000(
        ymin_px=300, xmin_px=200, ymax_px=600, xmax_px=800, orig_w=1000, orig_h=1200
    )
    assert ymin == 250  # 300 / 1200 * 1000
    assert xmin == 200  # 200 / 1000 * 1000
    assert ymax == 500  # 600 / 1200 * 1000
    assert xmax == 800  # 800 / 1000 * 1000


def test_normalize_box_to_1000_zero_width_edge_case() -> None:
    """Collapsing boxes must be guaranteed to have at least 1 unit width and height."""
    ymin, xmin, ymax, xmax = normalize_box_to_1000(
        ymin_px=500, xmin_px=500, ymax_px=500, xmax_px=500, orig_w=1000, orig_h=1000
    )
    assert ymin == 500
    assert ymax == 501
    assert xmin == 500
    assert xmax == 501


def test_normalize_box_invalid_dimensions() -> None:
    """Invalid image dimensions must raise ValueError."""
    with pytest.raises(ValueError):
        normalize_box_to_1000(0, 0, 100, 100, orig_w=0, orig_h=1000)


def test_denormalize_roundtrip() -> None:
    """Roundtrip normalization and denormalization should be accurate within 1-2 pixels."""
    orig_w, orig_h = 1440, 2160
    initial_box = (150, 200, 450, 700)
    ymin_px, xmin_px, ymax_px, xmax_px = denormalize_box_from_1000(initial_box, orig_w, orig_h)
    recovered = normalize_box_to_1000(ymin_px, xmin_px, ymax_px, xmax_px, orig_w, orig_h)
    assert abs(recovered[0] - initial_box[0]) <= 2
    assert abs(recovered[1] - initial_box[1]) <= 2
    assert abs(recovered[2] - initial_box[2]) <= 2
    assert abs(recovered[3] - initial_box[3]) <= 2


# ---------------------------------------------------------------------------
# Zero-Copy Crop Slicing Tests
# ---------------------------------------------------------------------------


def test_crop_bubble_image() -> None:
    """crop_bubble_image should cleanly slice sub-image without corruption."""
    img = Image.new("RGB", (1000, 1000), color="white")
    for y in range(400, 600):
        for x in range(400, 600):
            img.putpixel((x, y), (255, 0, 0))

    bubble = DetectedBubble(id="test_1", box_2d=(400, 400, 600, 600))
    crop_bytes = crop_bubble_image(img, bubble, output_format="PNG")

    cropped_img = Image.open(io.BytesIO(crop_bytes))
    assert cropped_img.size == (200, 200)
    assert cropped_img.getpixel((100, 100)) == (255, 0, 0)


# ---------------------------------------------------------------------------
# RDP Polygon Extraction & Child Text Assignment Tests
# ---------------------------------------------------------------------------


def test_extract_rdp_polygon_synthetic_circle() -> None:
    """extract_rdp_polygon should decode proto-mask and produce relative % vertices."""
    # Create 32 prototype masks where proto 0 is an ellipse in the center
    protos = np.zeros((32, 256, 256), dtype=np.float32)
    # Draw positive region in proto 0
    yy, xx = np.ogrid[:256, :256]
    # Circle at (100, 100) with radius 30
    mask = ((xx - 100) ** 2 + (yy - 100) ** 2) <= 30**2
    protos[0][mask] = 2.0

    coeffs = np.zeros(32, dtype=np.float32)
    coeffs[0] = 1.0  # Activate proto 0

    # Box in 1024 space corresponding to [70..130] in 256 space -> [280..520]
    box_model = (280.0, 280.0, 520.0, 520.0)

    poly = extract_rdp_polygon(
        mask_coeffs=coeffs,
        protos=protos,
        box_model=box_model,
        scale=1.0,
        pad_x=0,
        pad_y=0,
        orig_w=1024,
        orig_h=1024,
        epsilon_factor=0.004,
    )

    assert len(poly) >= 4
    # All points must be within [0.0, 100.0] relative percentage
    for px, py in poly:
        assert 0.0 <= px <= 100.0
        assert 0.0 <= py <= 100.0


def test_extract_rdp_polygon_fallback_on_empty() -> None:
    """extract_rdp_polygon returns 4-corner fallback when proto-mask has no active region."""
    protos = np.zeros((32, 256, 256), dtype=np.float32)
    coeffs = np.zeros(32, dtype=np.float32)
    box_model = (100.0, 100.0, 200.0, 200.0)

    poly = extract_rdp_polygon(
        mask_coeffs=coeffs,
        protos=protos,
        box_model=box_model,
        scale=1.0,
        pad_x=0,
        pad_y=0,
        orig_w=1024,
        orig_h=1024,
    )
    assert len(poly) == 4
    assert poly == [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


def test_smooth_polygon_chaikin() -> None:
    """smooth_polygon_chaikin should subdivide corners and produce smooth quadratic B-spline vertices."""
    # 4-corner polygon (diamond)
    diamond = [(50.0, 0.0), (100.0, 50.0), (50.0, 100.0), (0.0, 50.0)]
    smoothed_1 = smooth_polygon_chaikin(diamond, iterations=1)
    assert len(smoothed_1) == 8

    smoothed_2 = smooth_polygon_chaikin(diamond, iterations=2)
    assert len(smoothed_2) == 16

    # All points must be valid within [0.0, 100.0]
    for px, py in smoothed_2:
        assert 0.0 <= px <= 100.0
        assert 0.0 <= py <= 100.0


def test_smooth_polygon_chaikin_edge_cases() -> None:
    """smooth_polygon_chaikin handles small inputs, duplicates, and max_points caps cleanly."""
    # Empty and degenerate lists
    assert smooth_polygon_chaikin([]) == []
    assert smooth_polygon_chaikin([(10.0, 10.0), (20.0, 20.0)]) == [(10.0, 10.0), (20.0, 20.0)]

    # Max points cap stops exponential explosion
    pts = [(float(i * 10), float(i * 10)) for i in range(10)]
    capped = smooth_polygon_chaikin(pts, iterations=5, max_points=25)
    assert len(capped) <= 40


def test_assign_child_texts_to_bubbles() -> None:
    """assign_child_texts_to_bubbles should associate child texts and synthesize pseudo-bubbles for orphan texts."""
    bubble1 = DetectedBubble(id="1", box_2d=(100, 100, 400, 400))
    bubble2 = DetectedBubble(id="2", box_2d=(600, 600, 900, 900))

    # Text 1 inside bubble 1
    text1 = DetectedText(box_2d=(150, 150, 250, 250), confidence=0.9)
    # Text 2 inside bubble 1 (e.g. connected bubble)
    text2 = DetectedText(box_2d=(260, 150, 360, 250), confidence=0.88)
    # Text 3 inside bubble 2
    text3 = DetectedText(box_2d=(700, 700, 800, 800), confidence=0.95)
    # Text 4 outside all bubbles (orphan text e.g. Narration box or floating dialogue)
    text4 = DetectedText(box_2d=(10, 10, 50, 50), confidence=0.8)

    updated = assign_child_texts_to_bubbles([bubble1, bubble2], [text1, text2, text3, text4])
    # 2 original bubbles + 1 synthesized pseudo-bubble for text4
    assert len(updated) == 3
    assert len(updated[0].texts) == 2
    assert updated[0].texts[0] == text1
    assert updated[0].texts[1] == text2
    assert len(updated[1].texts) == 1
    assert updated[1].texts[0] == text3

    # Pseudo-bubble for orphan text 4
    pseudo_bubble = updated[2]
    assert pseudo_bubble.id == "3"
    assert pseudo_bubble.confidence == 0.8
    assert len(pseudo_bubble.texts) == 1
    assert pseudo_bubble.texts[0] == text4
    # Bounding box should wrap text4 with padding
    ymin, xmin, ymax, xmax = pseudo_bubble.box_2d
    assert ymin <= 10 and xmin <= 10
    assert ymax >= 50 and xmax >= 50
    # Polygon should be rectangular fallback [0.0, 100.0]
    assert pseudo_bubble.polygon == [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]



# ---------------------------------------------------------------------------
# YOLO11Detector Inference & Protocol Tests
# ---------------------------------------------------------------------------


class MockONNXInput:
    """Mock for ONNX Session input node."""

    def __init__(self, name: str = "images") -> None:
        self.name = name


class MockYOLO11Session:
    """Mock ONNX InferenceSession returning predefined YOLO11 outputs."""

    def __init__(
        self,
        mock_output0: np.ndarray[Any, Any],
        mock_output1: np.ndarray[Any, Any] | None = None,
    ) -> None:
        self._output0 = mock_output0
        self._output1 = mock_output1
        self.ran = False

    def get_inputs(self) -> list[MockONNXInput]:
        return [MockONNXInput()]

    def run(self, output_names: Any, input_feed: dict[str, Any]) -> list[np.ndarray[Any, Any]]:
        self.ran = True
        res = [self._output0]
        if self._output1 is not None:
            res.append(self._output1)
        return res


@pytest.mark.asyncio
async def test_yolo11_detector_with_mock_session() -> None:
    """YOLO11Detector should parse predictions, drop SFX, decode proto-masks, and return bubbles."""
    # 5 anchors (transposed shape: 40 features x 5 anchors)
    # Features: [cx, cy, w, h, bubble, panel, sfx, text, coeff0...coeff31]
    raw_pred = np.zeros((40, 5), dtype=np.float32)

    # Anchor 0: Bubble 1 (top right)
    raw_pred[0:4, 0] = [800.0, 200.0, 150.0, 150.0]
    raw_pred[4, 0] = 0.95  # score_bubble
    raw_pred[8, 0] = 1.0   # activate coeff0

    # Anchor 1: Bubble 2 (bottom left)
    raw_pred[0:4, 1] = [200.0, 700.0, 150.0, 150.0]
    raw_pred[4, 1] = 0.88  # score_bubble
    raw_pred[8, 1] = 1.0   # activate coeff0

    # Anchor 2: SFX class (should be unconditionally ignored!)
    raw_pred[0:4, 2] = [500.0, 500.0, 200.0, 200.0]
    raw_pred[6, 2] = 0.99  # score_sfx

    # Anchor 3: Panel
    raw_pred[0:4, 3] = [512.0, 512.0, 1000.0, 1000.0]
    raw_pred[5, 3] = 0.92  # score_panel

    # Anchor 4: Text inside Bubble 1
    raw_pred[0:4, 4] = [800.0, 200.0, 80.0, 80.0]
    raw_pred[7, 4] = 0.90  # score_text

    # Shape: (1, 40, 5)
    mock_out0 = np.expand_dims(raw_pred, axis=0)

    # Prototype masks (1, 32, 256, 256)
    mock_out1 = np.zeros((1, 32, 256, 256), dtype=np.float32)
    mock_out1[0, 0, 40:60, 190:210] = 2.0  # Positive blob around Bubble 1 in 256 space

    mock_session = MockYOLO11Session(mock_out0, mock_out1)
    detector = YOLO11Detector(onnx_session=mock_session, confidence_threshold=0.5)

    assert isinstance(detector, BaseBubbleDetector)
    assert detector.name == "yolo11s-seg"
    assert await detector.is_available() is True

    dummy_img = Image.new("RGB", (800, 1200), color="white")
    buf = io.BytesIO()
    dummy_img.save(buf, format="JPEG")
    image_bytes = buf.getvalue()

    bubbles, panels = await detector.detect_layout(image_bytes, original_width=800, original_height=1200)
    assert mock_session.ran is True

    # Bubble count must be 2 (SFX anchor ignored)
    assert len(bubbles) == 2
    # Panel count must be 1
    assert len(panels) == 1

    # Check that coordinates are bounded in [0, 1000]
    for b in bubbles:
        ymin, xmin, ymax, xmax = b.box_2d
        assert 0 <= ymin < ymax <= 1000
        assert 0 <= xmin < xmax <= 1000
        assert len(b.polygon) >= 3
        for px, py in b.polygon:
            assert 0.0 <= px <= 100.0
            assert 0.0 <= py <= 100.0

    # Bubble IDs must be sequential strings "1", "2"
    assert [b.id for b in bubbles] == ["1", "2"]

    # Child text must be assigned to Bubble 1 (top right)
    top_bubble = bubbles[0]
    assert len(top_bubble.texts) == 1
    assert top_bubble.texts[0].confidence == 0.9


@pytest.mark.asyncio
async def test_yolo11_detector_class_specific_thresholds() -> None:
    """YOLO11Detector applies class-specific thresholds (bubble: 0.30, text: 0.30, panel: 0.35)."""
    # 4 anchors:
    # Anchor 0: Bubble with score 0.32 (above 0.30 threshold, kept)
    # Anchor 1: Bubble with score 0.28 (below 0.30, rejected)
    # Anchor 2: Panel with score 0.36 (above 0.35, kept)
    # Anchor 3: Text with score 0.31 (above 0.30, kept)
    raw_pred = np.zeros((40, 4), dtype=np.float32)

    raw_pred[0:4, 0] = [300.0, 300.0, 100.0, 100.0]
    raw_pred[4, 0] = 0.32  # bubble kept under 0.30 threshold

    raw_pred[0:4, 1] = [500.0, 500.0, 100.0, 100.0]
    raw_pred[4, 1] = 0.28  # bubble rejected

    raw_pred[0:4, 2] = [512.0, 512.0, 900.0, 900.0]
    raw_pred[5, 2] = 0.36  # panel kept

    raw_pred[0:4, 3] = [300.0, 300.0, 50.0, 50.0]
    raw_pred[7, 3] = 0.31  # text kept

    mock_out0 = np.expand_dims(raw_pred, axis=0)
    mock_session = MockYOLO11Session(mock_out0)
    detector = YOLO11Detector(onnx_session=mock_session)

    dummy_img = Image.new("RGB", (100, 100), color="white")
    buf = io.BytesIO()
    dummy_img.save(buf, format="PNG")

    bubbles, panels = await detector.detect_layout(buf.getvalue(), original_width=100, original_height=100)

    # Bubble 0 is kept, Bubble 1 is rejected
    assert len(bubbles) == 1
    assert bubbles[0].confidence == 0.32
    assert len(bubbles[0].texts) == 1
    assert bubbles[0].texts[0].confidence == 0.31
    assert len(panels) == 1
    assert panels[0].confidence == 0.36



@pytest.mark.asyncio
async def test_yolo11_detector_empty_outputs() -> None:

    """Empty model outputs should cleanly return empty list."""
    mock_session = MockYOLO11Session(np.empty((1, 40, 0), dtype=np.float32))
    detector = YOLO11Detector(onnx_session=mock_session)

    dummy_img = Image.new("RGB", (100, 100), color="white")
    buf = io.BytesIO()
    dummy_img.save(buf, format="PNG")

    bubbles = await detector.detect(buf.getvalue(), original_width=100, original_height=100)
    assert bubbles == []


@pytest.mark.asyncio
async def test_yolo11_detector_missing_model_file() -> None:
    """Missing model weights file must raise FileNotFoundError upon execution."""
    detector = YOLO11Detector(model_path="/non_existent/yolo11s-seg.onnx")
    assert await detector.is_available() is False

    dummy_img = Image.new("RGB", (100, 100), color="white")
    buf = io.BytesIO()
    dummy_img.save(buf, format="JPEG")

    with pytest.raises(FileNotFoundError) as exc_info:
        await detector.detect(buf.getvalue(), original_width=100, original_height=100)

    assert "model weights not found" in str(exc_info.value)


def _read_fixture_bytes(path: str) -> bytes:
    return Path(path).read_bytes()


@pytest.mark.asyncio
async def test_yolo11_detector_real_fixture_inference() -> None:
    """Verify live inference against the actual downloaded model and manga sample fixture."""
    model_path = ".cache/inkshift/models/yolo11s-seg.onnx"
    fixture_path = "tests/fixtures/manga_sample_panel.png"

    if not os.path.exists(model_path) or not os.path.exists(fixture_path):
        pytest.skip("Skipping live inference: model or fixture not present.")

    detector = YOLO11Detector(
        model_path=model_path,
        execution_provider="cpu",  # Run on CPU for deterministic CI/test behavior
        confidence_threshold=0.35,
    )
    assert await detector.is_available() is True

    image_bytes = _read_fixture_bytes(fixture_path)

    bubbles, panels = await detector.detect_layout(image_bytes, original_width=800, original_height=1100)

    # In the manga_sample_panel, there should be at least 1 speech bubble and panels
    assert len(bubbles) >= 1
    assert len(panels) >= 1

    first_bubble = bubbles[0]
    assert first_bubble.id == "1"
    ymin, xmin, ymax, xmax = first_bubble.box_2d
    assert 0 <= ymin < ymax <= 1000
    assert 0 <= xmin < xmax <= 1000

    # Polygon should have 18-25 vertices (or close) and bounded in [0.0, 100.0]
    assert len(first_bubble.polygon) >= 10
    for px, py in first_bubble.polygon:
        assert 0.0 <= px <= 100.0
        assert 0.0 <= py <= 100.0


def test_expand_child_text_boxes_in_polygon_edge_cases() -> None:
    """Test empty child boxes and degenerate polygons fallback cleanly."""
    parent = (100, 100, 400, 400)
    assert expand_child_text_boxes_in_polygon([], [], parent) == []

    child = [(150, 150, 250, 250)]
    # Degenerate polygon (< 3 vertices) returns original boxes
    assert expand_child_text_boxes_in_polygon([(10.0, 10.0)], child, parent) == child


def test_expand_child_text_boxes_in_polygon_expansion_and_collision() -> None:
    """Child text boxes expand to fill available lobe space without colliding."""
    parent = (100, 100, 500, 500)
    polygon = [
        (10.0, 10.0),
        (90.0, 10.0),
        (90.0, 90.0),
        (10.0, 90.0),
    ]
    # Two small child boxes near the center
    child1 = (200, 250, 250, 350)  # Top center
    child2 = (350, 250, 400, 350)  # Bottom center

    expanded = expand_child_text_boxes_in_polygon(polygon, [child1, child2], parent)
    assert len(expanded) == 2

    e1_ymin, e1_xmin, e1_ymax, e1_xmax = expanded[0]
    e2_ymin, e2_xmin, e2_ymax, e2_xmax = expanded[1]

    # Both boxes must have expanded in height and/or width
    e1_area = (e1_ymax - e1_ymin) * (e1_xmax - e1_xmin)
    orig_area1 = (child1[2] - child1[0]) * (child1[3] - child1[1])
    assert e1_area > orig_area1

    e2_area = (e2_ymax - e2_ymin) * (e2_xmax - e2_xmin)
    orig_area2 = (child2[2] - child2[0]) * (child2[3] - child2[1])
    assert e2_area > orig_area2

    # Boxes must not collide (child 1 remains above child 2)
    assert e1_ymax <= e2_ymin

    # Both boxes stay within parent box boundaries
    assert e1_ymin >= parent[0]
    assert e1_xmin >= parent[1]
    assert e2_ymax <= parent[2]
    assert e2_xmax <= parent[3]


def test_yolo11_detector_auto_download_when_missing(tmp_path: Path) -> None:
    """When model weights do not exist and auto_download=True, trigger ensure_model_file."""
    from unittest.mock import MagicMock, patch

    missing_model = str(tmp_path / "missing_yolo.onnx")
    detector = YOLO11Detector(model_path=missing_model, auto_download=True)

    dummy_session = MagicMock()
    with patch("src.backend.detection.downloader.ensure_model_file") as mock_ensure, patch(
        "onnxruntime.InferenceSession", return_value=dummy_session
    ):
        # Simulate ensure_model_file creating the file
        def fake_download(dest_path: Any) -> Path:
            Path(dest_path).write_bytes(b"DUMMY_ONNX_DATA")
            return Path(dest_path)

        mock_ensure.side_effect = fake_download

        detector._ensure_session()
        mock_ensure.assert_called_once_with(missing_model)
        assert detector._session is dummy_session


def test_yolo11_detector_auto_download_disabled_raises_file_not_found(tmp_path: Path) -> None:
    """When model weights do not exist and auto_download=False, raise FileNotFoundError."""
    missing_model = str(tmp_path / "absent_model.onnx")
    detector = YOLO11Detector(model_path=missing_model, auto_download=False)

    with pytest.raises(FileNotFoundError, match="Auto-download is disabled"):
        detector._ensure_session()


@pytest.mark.asyncio
async def test_yolo11_detector_is_available_checks_disk_and_session(tmp_path: Path) -> None:
    """is_available() checks whether weights exist on disk or session is loaded."""
    model_path = tmp_path / "detector_model.onnx"
    detector = YOLO11Detector(model_path=str(model_path))
    assert await detector.is_available() is False

    # Once file exists on disk, is_available is True
    model_file = Path(model_path)
    model_file.write_bytes(b"DUMMY_ONNX_DATA")
    assert await detector.is_available() is True

