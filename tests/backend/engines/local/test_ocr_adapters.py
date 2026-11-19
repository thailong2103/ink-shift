"""Unit tests for RapidOCR DirectML adapter."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from src.backend.detection.assembler import BubbleWorkItem
from src.backend.detection.base import DetectedBubble
from src.backend.engines.local.ocr.base import BaseOCREngine, FullPageOCREngine
from src.backend.engines.local.ocr.rapid_ocr import RapidOCRAdapter

# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------


def make_dummy_crop_bytes(color: str = "white", size: tuple[int, int] = (200, 100)) -> bytes:
    """Create in-memory binary image crop bytes for OCR testing."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# RapidOCRAdapter Tests
# ---------------------------------------------------------------------------


class MockRapidOCREngine:
    """Mock engine simulating rapidocr-onnxruntime output structure."""

    def __init__(self, mock_results: list[Any]) -> None:
        self.mock_results = mock_results
        self.call_count = 0

    def __call__(self, img_np: Any) -> tuple[list[Any], float]:
        self.call_count += 1
        # Returns (result_list, elapse_time)
        return self.mock_results, 0.025


@pytest.mark.asyncio
async def test_rapid_ocr_protocol_conformance() -> None:
    """RapidOCRAdapter must implement BaseOCREngine protocol."""
    adapter = RapidOCRAdapter(rapidocr_engine=MockRapidOCREngine([]))
    assert isinstance(adapter, BaseOCREngine)
    assert adapter.name == "rapidocr"
    assert await adapter.is_available() is True


@pytest.mark.asyncio
async def test_rapid_ocr_recognize_batch() -> None:
    """RapidOCRAdapter should recognize, sort, and assemble multi-line comic speech bubbles."""
    # RapidOCR output format: [[box, text, confidence], ...]
    # Line 2 appears at top y=10.0, Line 1 appears at y=60.0
    mock_data = [
        [[[0, 60], [100, 60], [100, 90], [0, 90]], "HERE?!", 0.98],
        [[[0, 10], [100, 10], [100, 40], [0, 40]], "WHAT ARE YOU DOING", 0.99],
    ]
    mock_engine = MockRapidOCREngine(mock_data)
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)

    crop = make_dummy_crop_bytes()
    results = await adapter.recognize_batch([crop])

    assert len(results) == 1
    # Must be sorted vertically (top line first) and assembled
    assert results[0] == "WHAT ARE YOU DOING HERE?!"
    assert mock_engine.call_count == 1


@pytest.mark.asyncio
async def test_rapid_ocr_empty_and_corrupt_crops() -> None:
    """RapidOCRAdapter should handle empty or corrupt image crops gracefully."""
    mock_engine = MockRapidOCREngine([])
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)

    results = await adapter.recognize_batch([b"", b"not_an_image", make_dummy_crop_bytes()])
    assert results == ["", "", ""]


@pytest.mark.asyncio
async def test_rapid_ocr_empty_batch() -> None:
    """Empty batch should immediately return empty list without engine calls."""
    mock_engine = MockRapidOCREngine([])
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)
    assert await adapter.recognize_batch([]) == []
    assert mock_engine.call_count == 0


@pytest.mark.asyncio
async def test_rapid_ocr_engine_initialization_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing rapidocr dependency must raise RuntimeError during inference."""
    adapter = RapidOCRAdapter(rapidocr_engine=None)

    def failing_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "rapidocr":
            raise ImportError("Simulated missing package")
        import importlib
        return importlib.__import__(name, *args, **kwargs)

    import importlib
    monkeypatch.setattr(importlib, "import_module", failing_import)

    with pytest.raises(RuntimeError) as exc_info:
        await adapter.recognize_batch([make_dummy_crop_bytes()])
    assert "Failed to initialize RapidOCR" in str(exc_info.value)


# ---------------------------------------------------------------------------
# RapidOCR Japanese & Multilingual Tests (ADR-017)
# ---------------------------------------------------------------------------


class MockRapidJapaneseEngine:
    """Mock engine simulating RapidOCR with Japanese output."""

    def __init__(self, transcription: str = "私 は   逃 げ ま す ！") -> None:
        self.transcription = transcription
        self.call_count = 0

    def __call__(self, img_np: Any) -> tuple[list[Any], float]:
        self.call_count += 1
        box = [[0, 0], [10, 0], [10, 10], [0, 10]]
        return [[box, self.transcription, 0.95]], 0.025


@pytest.mark.asyncio
async def test_rapid_ocr_japanese_transcription() -> None:
    """RapidOCRAdapter should transcribe Japanese text via DirectML mock."""
    mock_engine = MockRapidJapaneseEngine("何をしているの？")
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)

    assert isinstance(adapter, BaseOCREngine)
    assert adapter.name == "rapidocr"
    assert await adapter.is_available() is True

    crop = make_dummy_crop_bytes()
    results = await adapter.recognize_batch([crop])

    assert len(results) == 1
    assert results[0] == "何をしているの？"
    assert mock_engine.call_count == 1


# ---------------------------------------------------------------------------
# FullPageOCREngine & Spatial Mapping Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rapid_ocr_full_page_protocol_conformance() -> None:
    """RapidOCRAdapter must implement FullPageOCREngine protocol."""
    adapter = RapidOCRAdapter(rapidocr_engine=MockRapidOCREngine([]))
    assert isinstance(adapter, FullPageOCREngine)
    assert adapter.supports_full_page is True
    assert adapter.name == "rapidocr"


@pytest.mark.asyncio
async def test_rapid_ocr_recognize_full_page_spatial_mapping() -> None:
    """RapidOCRAdapter should map detected lines into containing bubbles and sort vertically."""
    # Canonical space: [0, 1000]
    b1 = DetectedBubble(id="b1", box_2d=(100, 100, 300, 400))
    b2 = DetectedBubble(id="b2", box_2d=(500, 500, 800, 900))
    b3 = DetectedBubble(id="b3", box_2d=(850, 100, 950, 300))

    item1 = BubbleWorkItem(
        crop_box=(100, 100, 300, 400),
        render_box=(100, 100, 300, 400),
        parent_bubble=b1,
        is_child=False,
        child_index=0,
        confidence=0.99,
    )
    item2 = BubbleWorkItem(
        crop_box=(500, 500, 800, 900),
        render_box=(500, 500, 800, 900),
        parent_bubble=b2,
        is_child=False,
        child_index=0,
        confidence=0.99,
    )
    item3 = BubbleWorkItem(
        crop_box=(850, 100, 950, 300),
        render_box=(850, 100, 950, 300),
        parent_bubble=b3,
        is_child=False,
        child_index=0,
        confidence=0.99,
    )

    # Mock OCR output on 1000x1000 image:
    # Item for Bubble 1 - Line 2 (y=220)
    # Item for Bubble 1 - Line 1 (y=150) -> should be sorted before Line 2
    # Item for Bubble 2 - Line 1 (y=600)
    # Outside item (y=50, x=50) -> outside all bubbles, should be ignored
    mock_results = [
        [[[150.0, 220.0], [350.0, 220.0], [350.0, 250.0], [150.0, 250.0]], "WORLD!", 0.95],
        [[[150.0, 150.0], [350.0, 150.0], [350.0, 180.0], [150.0, 180.0]], "HELLO", 0.98],
        [[[550.0, 600.0], [750.0, 600.0], [750.0, 640.0], [550.0, 640.0]], "SECOND BUBBLE", 0.92],
        [[[10.0, 50.0], [80.0, 50.0], [80.0, 70.0], [10.0, 70.0]], "OUTSIDE SFX", 0.70],
    ]

    mock_engine = MockRapidOCREngine(mock_results)
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)

    img_dummy = Image.new("RGB", (1000, 1000), color="white")
    results = await adapter.recognize_full_page(
        image_np=img_dummy,
        work_items=[item1, item2, item3],
        image_width=1000,
        image_height=1000,
    )

    assert len(results) == 3
    # Bubble 1: sorted top-to-bottom
    assert results[0] == "HELLO WORLD!"
    # Bubble 2: single line
    assert results[1] == "SECOND BUBBLE"
    # Bubble 3: no text
    assert results[2] == ""
    # Single call on full image!
    assert mock_engine.call_count == 1


@pytest.mark.asyncio
async def test_rapid_ocr_recognize_full_page_empty_work_items() -> None:
    """recognize_full_page should return empty list when no work items provided."""
    mock_engine = MockRapidOCREngine([])
    adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)
    results = await adapter.recognize_full_page(
        image_np=Image.new("RGB", (100, 100)),
        work_items=[],
        image_width=100,
        image_height=100,
    )
    assert results == []
    assert mock_engine.call_count == 0


@pytest.mark.asyncio
async def test_rapid_ocr_multilingual_pool_caching() -> None:
    """RapidOCRAdapter maintains a lazy-loading pool and reuses cached instances."""
    mock_default = MockRapidOCREngine([[[[0, 0], [10, 0], [10, 10], [0, 10]], "DEFAULT", 0.9]])
    mock_ja = MockRapidOCREngine([[[[0, 0], [10, 0], [10, 10], [0, 10]], "こんにちは", 0.9]])

    adapter = RapidOCRAdapter(rapidocr_engine=mock_default)
    # Manually seed the pool
    adapter._engines["ja"] = mock_ja

    # Calling with lang="ja" must use mock_ja
    res_ja = await adapter.recognize_batch([make_dummy_crop_bytes()], lang="ja")
    assert res_ja == ["こんにちは"]
    assert mock_ja.call_count == 1
    assert mock_default.call_count == 0

    # Calling with lang="zh" must use mock_default
    res_zh = await adapter.recognize_batch([make_dummy_crop_bytes()], lang="zh")
    assert res_zh == ["DEFAULT"]
    assert mock_default.call_count == 1


@pytest.mark.asyncio
async def test_rapid_ocr_japanese_text_cleaning() -> None:
    """Japanese text assembly should strip accidental whitespace between CJK characters."""
    # Accidental space between Hiragana
    mock_ja = MockRapidOCREngine([
        [[[0, 0], [10, 0], [10, 10], [0, 10]], "こん にち は", 0.9]
    ])
    adapter = RapidOCRAdapter(rapidocr_engine=mock_ja)
    adapter._engines["ja"] = mock_ja

    res = await adapter.recognize_batch([make_dummy_crop_bytes()], lang="ja")
    # CJK whitespace stripped
    assert res == ["こんにちは"]


@pytest.mark.asyncio
async def test_rapid_ocr_offline_korean_fallback() -> None:
    """If Korean model is missing and auto-download fails, _ensure_ko_rec returns None gracefully."""
    from unittest.mock import patch

    adapter = RapidOCRAdapter(rapidocr_engine=None)

    with patch("src.backend.detection.downloader.ensure_ocr_model_files", return_value=None):
        ko_engine = adapter._ensure_ko_rec()
        assert ko_engine is None


@pytest.mark.asyncio
async def test_rapid_ocr_create_ort_session_directml_with_cpu_fallback() -> None:
    """_create_ort_session requests DmlExecutionProvider first and falls back cleanly on error."""
    from unittest.mock import MagicMock, patch

    dummy_cpu_sess = MagicMock()
    dummy_cpu_sess.get_providers.return_value = ["CPUExecutionProvider"]

    calls: list[tuple[list[Any], Any]] = []

    def fake_inference_session(
        path: str, sess_options: Any = None, providers: list[Any] | None = None
    ) -> Any:
        prov_list = providers or []
        calls.append((prov_list, sess_options))
        if any(isinstance(p, tuple) and p[0] == "DmlExecutionProvider" for p in prov_list):
            raise RuntimeError("DirectML unavailable on CI host")
        return dummy_cpu_sess

    with patch("onnxruntime.InferenceSession", side_effect=fake_inference_session):
        sess = RapidOCRAdapter._create_ort_session("dummy.onnx", execution_provider="directml", role="rec")
        assert sess is dummy_cpu_sess
        assert len(calls) == 2
        assert calls[0][0][0][0] == "DmlExecutionProvider"
        assert calls[0][1] is not None
        assert calls[0][1].enable_mem_pattern is False
        assert calls[1][0] == ["CPUExecutionProvider"]


def test_rapid_ocr_hybrid_routes_det_cpu_and_rec_directml() -> None:
    """Hybrid mode routes DET to CPUExecutionProvider and REC/KO_REC to DmlExecutionProvider."""
    from unittest.mock import MagicMock, patch

    import onnxruntime as ort

    recorded: list[tuple[str, Any, list[Any]]] = []

    def fake_inference_session(
        path: str, sess_options: Any = None, providers: list[Any] | None = None
    ) -> Any:
        recorded.append((path, sess_options, providers or []))
        sess = MagicMock()
        sess.get_providers.return_value = providers or []
        return sess

    with patch("onnxruntime.InferenceSession", side_effect=fake_inference_session):
        RapidOCRAdapter._create_ort_session("det.onnx", execution_provider="hybrid", role="det", cpu_threads=6)
        RapidOCRAdapter._create_ort_session("rec.onnx", execution_provider="hybrid", role="rec", cpu_threads=6)
        RapidOCRAdapter._create_ort_session("rec.onnx", execution_provider="cpu", role="rec", cpu_threads=4)

    det_path, det_opts, det_provs = recorded[0]
    assert det_path == "det.onnx"
    assert det_provs == ["CPUExecutionProvider"]
    assert det_opts.intra_op_num_threads == 6
    assert det_opts.execution_mode == ort.ExecutionMode.ORT_SEQUENTIAL

    rec_path, rec_opts, rec_provs = recorded[1]
    assert rec_path == "rec.onnx"
    assert rec_provs[0][0] == "DmlExecutionProvider"
    assert rec_opts.enable_mem_pattern is False
    assert rec_opts.execution_mode == ort.ExecutionMode.ORT_SEQUENTIAL

    cpu_path, cpu_opts, cpu_provs = recorded[2]
    assert cpu_path == "rec.onnx"
    assert cpu_provs == ["CPUExecutionProvider"]
    assert cpu_opts.intra_op_num_threads == 4


def test_rapid_ocr_det_limit_side_len_default_1280_and_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_ensure_det_and_rec applies limit_side_len=1280 by default and honors constructor override."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    monkeypatch.delenv("INKSHIFT_LOCAL_OCR_DET_LIMIT_SIDE_LEN", raising=False)
    det_file = tmp_path / "det.onnx"
    rec_file = tmp_path / "rec.onnx"
    det_file.write_bytes(b"DET")
    rec_file.write_bytes(b"REC")

    captured_det_cfgs: list[dict[str, Any]] = []

    class FakeOmegaConf:
        @staticmethod
        def to_container(node: Any, resolve: bool = False) -> dict[str, Any]:
            return dict(node)

        @staticmethod
        def create(data: dict[str, Any], flags: dict[str, Any] | None = None) -> dict[str, Any]:
            return data

    class FakeDet:
        def __init__(self, cfg: dict[str, Any]) -> None:
            captured_det_cfgs.append(cfg)

    class FakeRec:
        def __init__(self, cfg: dict[str, Any]) -> None:
            self.cfg = cfg

    base_cfg = SimpleNamespace(
        Det={},
        Rec={},
        EngineConfig=SimpleNamespace(onnxruntime={}),
    )
    fake_sess = MagicMock()
    fake_sess.get_providers.return_value = ["CPUExecutionProvider"]

    def fake_ensure_ocr(kind: str, **_kwargs: Any) -> Path:
        return det_file if kind == "det" else rec_file

    adapter_default = RapidOCRAdapter(execution_provider="hybrid")
    adapter_override = RapidOCRAdapter(execution_provider="hybrid", det_limit_side_len=960)

    with (
        patch.object(
            RapidOCRAdapter,
            "_load_rapidocr_base_cfg",
            return_value=(base_cfg, tmp_path, FakeDet, FakeRec, FakeOmegaConf),
        ),
        patch("src.backend.detection.downloader.ensure_ocr_model_files", side_effect=fake_ensure_ocr),
        patch.object(RapidOCRAdapter, "_create_ort_session", return_value=fake_sess),
    ):
        adapter_default._ensure_det_and_rec()
        adapter_override._ensure_det_and_rec()

    assert captured_det_cfgs[0]["limit_side_len"] == 1280
    assert captured_det_cfgs[1]["limit_side_len"] == 960


def test_rapid_ocr_unload_sessions_releases_and_preserves_mocks() -> None:
    """unload_sessions releases native engines cleanly while preserving injected test mocks."""
    from unittest.mock import MagicMock

    adapter = RapidOCRAdapter(rapidocr_engine=None)
    assert adapter.is_loaded is False
    assert adapter.unload_sessions() is False

    adapter._det_engine = MagicMock()
    adapter._rec_engine = MagicMock()
    adapter._ko_rec_engine = MagicMock()
    adapter._engines["ko"] = adapter._ko_rec_engine
    adapter._ko_load_attempted = True
    adapter.mark_used()

    assert adapter.is_loaded is True
    assert adapter.last_used_monotonic is not None
    assert adapter.unload_sessions() is True
    assert adapter.is_loaded is False
    assert adapter._det_engine is None
    assert adapter._rec_engine is None
    assert adapter._ko_rec_engine is None
    assert "ko" not in adapter._engines
    assert adapter._ko_load_attempted is False
    assert adapter.last_used_monotonic is None
    assert adapter.unload_sessions() is False

    mock_engine = MockRapidOCREngine([])
    mock_adapter = RapidOCRAdapter(rapidocr_engine=mock_engine)
    assert mock_adapter.is_loaded is False
    assert mock_adapter.unload_sessions() is False
    assert mock_adapter._engines["default"] is mock_engine


@pytest.mark.asyncio
async def test_rapid_ocr_vertical_rtl_sorting_in_full_page() -> None:
    """recognize_full_page orders vertical CJK columns Right-to-Left inside bubbles."""
    b1 = DetectedBubble(id="b1", box_2d=(100, 100, 500, 400))
    item1 = BubbleWorkItem(
        crop_box=(100, 100, 500, 400),
        render_box=(100, 100, 500, 400),
        parent_bubble=b1,
        is_child=False,
        child_index=0,
        confidence=0.99,
    )
    mock_results = [
        # Left vertical column (x=150..185, h=150)
        [[[150.0, 150.0], [185.0, 150.0], [185.0, 300.0], [150.0, 300.0]], "第二列", 0.97],
        # Right vertical column (x=280..315, h=150) -> MUST be read FIRST!
        [[[280.0, 150.0], [315.0, 150.0], [315.0, 300.0], [280.0, 300.0]], "第一列", 0.99],
    ]
    adapter = RapidOCRAdapter(rapidocr_engine=MockRapidOCREngine(mock_results))
    results = await adapter.recognize_full_page(
        image_np=Image.new("RGB", (1000, 1000), color="white"),
        work_items=[item1],
        image_width=1000,
        image_height=1000,
    )
    assert results == ["第一列第二列"]


@pytest.mark.asyncio
async def test_rapid_ocr_recheck_ambiguous_square_bubble_maps_coords() -> None:
    """recheck_ambiguous_square_bubble rotates 90 CCW and maps boxes back into page pixel space."""
    import numpy as np

    adapter = RapidOCRAdapter(rapidocr_engine=None)
    # 100x100 bubble crop inside a 500x500 page at [ymin=100, xmin=200, ymax=200, xmax=300]
    rot_box = np.array([[10.0, 5.0], [80.0, 5.0], [80.0, 25.0], [10.0, 25.0]], dtype=np.float32)

    from unittest.mock import patch

    with (
        patch.object(adapter, "detect_text_boxes", return_value=[rot_box]),
        patch.object(adapter, "crop_quad", return_value=np.zeros((20, 70, 3), dtype=np.uint8)),
        patch.object(adapter, "recognize_crops", return_value=[("第一列", 0.98)]),
    ):
        page_bgr = np.full((500, 500, 3), 255, dtype=np.uint8)
        mapped = adapter.recheck_ambiguous_square_bubble(page_bgr, (100, 200, 200, 300))
        assert mapped is not None
        assert len(mapped) == 1
        quad_orig, txt, conf = mapped[0]
        assert txt == "第一列"
        assert conf == 0.98
        # Bounding box in original space must lie inside (200..300, 100..200) and be vertical (h > w)
        w_orig = float(quad_orig[:, 0].max() - quad_orig[:, 0].min())
        h_orig = float(quad_orig[:, 1].max() - quad_orig[:, 1].min())
        assert h_orig > w_orig
        assert 200.0 <= float(quad_orig[:, 0].min()) <= float(quad_orig[:, 0].max()) <= 300.0
        assert 100.0 <= float(quad_orig[:, 1].min()) <= float(quad_orig[:, 1].max()) <= 200.0



