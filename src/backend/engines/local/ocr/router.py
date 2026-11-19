"""OCR Router for unified auto-multilingual PP-OCRv6 dispatch, hybrid fusion, and chapter caching."""

from __future__ import annotations

import inspect
import io
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
from PIL import Image

from src.backend.detection.postprocess import denormalize_box_from_1000
from src.backend.engines.local.ocr.base import BaseOCREngine
from src.backend.engines.local.ocr.rapid_ocr import RapidOCRAdapter, to_bgr_array
from src.backend.engines.local.ocr.text_assembler import (
    ParagraphCluster,
    classify_box_orientation,
    cluster_lines_bidirectional,
    filter_furigana_boxes,
    is_ambiguous_square_cjk_bubble,
    order_bubble_lines_bidirectional,
    parse_ocr_entry,
)
from src.backend.logging import get_logger

if TYPE_CHECKING:
    from src.backend.detection.assembler import BubbleWorkItem

logger = get_logger("ocr.router")


@dataclass(frozen=True)
class HybridOCRResult:
    """Unified output of a hybrid full-page OCR pass (bubbles + residual prose)."""

    bubble_texts: list[str] = field(default_factory=list)
    residual_clusters: list[ParagraphCluster] = field(default_factory=list)
    detected_source_lang: str = "auto"
    ocr_engine_used: str = "rapidocr"
    page_dominant_vertical: bool = False


class OCRRouter:
    """Routes OCR tasks automatically with PP-OCRv6_medium DirectML, Korean fallback, and spatial fusion."""

    JAPANESE_KANA_REGEX: ClassVar[re.Pattern[str]] = re.compile(
        r"[\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF]"
    )
    LATIN_SCRIPT_REGEX: ClassVar[re.Pattern[str]] = re.compile(r"[a-zA-Z]")
    HANZI_SCRIPT_REGEX: ClassVar[re.Pattern[str]] = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF]")
    HANGUL_SCRIPT_REGEX: ClassVar[re.Pattern[str]] = re.compile(
        r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]"
    )
    _NON_WORD_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"[\s\W_]+", re.UNICODE)

    def __init__(
        self,
        manga_ocr: BaseOCREngine | None = None,
        rapid_ocr: BaseOCREngine | None = None,
        default_model: str = "auto",
        fallback_model: str = "rapidocr",
    ) -> None:
        self._rapid_ocr: BaseOCREngine = rapid_ocr or RapidOCRAdapter()
        self._manga_ocr: BaseOCREngine = manga_ocr if manga_ocr is not None else self._rapid_ocr
        self._default_model = default_model
        self._fallback_model = fallback_model
        self._chapter_cache: dict[str, str] = {}

    def get_adapter(self, model_name: str) -> BaseOCREngine:
        """Retrieve concrete BaseOCREngine adapter by identifier string or language code."""
        normalized = model_name.lower().strip()
        if normalized in ("manga-ocr", "ja", "japanese"):
            return self._manga_ocr
        if normalized in (
            "rapidocr",
            "en",
            "english",
            "zh",
            "chinese",
            "ko",
            "korean",
        ):
            return self._rapid_ocr
        raise ValueError(
            f"Unknown OCR model '{model_name}'. Valid options: 'auto', 'rapidocr', 'manga-ocr', 'ja', 'en', 'ko', 'zh'."
        )

    def detect_page_language(self, texts: Sequence[str]) -> str:
        """Detect dominant ISO language code across page transcriptions via Unicode script counts."""
        combined = "\n".join(t for t in texts if t and t.strip())
        if not combined:
            return "auto"

        hangul_count = len(self.HANGUL_SCRIPT_REGEX.findall(combined))
        kana_count = len(self.JAPANESE_KANA_REGEX.findall(combined))
        hanzi_count = len(self.HANZI_SCRIPT_REGEX.findall(combined))
        latin_count = len(self.LATIN_SCRIPT_REGEX.findall(combined))

        if hangul_count >= 2:
            return "ko"
        if kana_count >= 2:
            return "ja"
        if hanzi_count >= 2:
            return "zh"
        if latin_count >= 3:
            return "en"
        if kana_count >= 1:
            return "ja"
        if hanzi_count >= 1:
            return "zh"
        if hangul_count >= 1:
            return "ko"
        return "auto"

    def classify_text_script(self, text: str) -> str:
        """Classify script based on Unicode character analysis (legacy compatibility helper)."""
        cleaned = text.strip()
        if not cleaned:
            return self._fallback_model

        has_kana = bool(self.JAPANESE_KANA_REGEX.search(cleaned))
        has_hangul = bool(self.HANGUL_SCRIPT_REGEX.search(cleaned))
        has_latin = bool(self.LATIN_SCRIPT_REGEX.search(cleaned))
        has_hanzi = bool(self.HANZI_SCRIPT_REGEX.search(cleaned))

        if has_kana:
            return "manga-ocr"
        if has_hangul or has_latin or has_hanzi:
            return "rapidocr"
        return self._fallback_model

    async def probe_language(self, sample_crops: list[bytes] | bytes) -> str:
        """Probe sample bubble crop(s) using RapidOCR."""
        crops = [sample_crops] if isinstance(sample_crops, bytes) else sample_crops
        valid_crops = [c for c in crops if c]
        if not valid_crops:
            return self._fallback_model

        try:
            probe_results = await self._rapid_ocr.recognize_batch(valid_crops[:3])
            for text in probe_results:
                cleaned = text.strip()
                if cleaned:
                    detected = self.classify_text_script(cleaned)
                    if detected != self._fallback_model:
                        return detected
            return self._fallback_model
        except (RuntimeError, ValueError, TypeError, OSError):
            return self._fallback_model

    async def resolve_engine(
        self,
        requested_model: str | None = None,
        sample_crops: list[bytes] | None = None,
        chapter_id: str | None = None,
    ) -> BaseOCREngine:
        """Resolve appropriate BaseOCREngine adapter according to override, cache, or probe."""
        target_mode = (
            requested_model if requested_model is not None and requested_model != "" else self._default_model
        ).lower().strip()

        if target_mode in ("manga-ocr", "ja", "japanese"):
            if await self._manga_ocr.is_available():
                return self._manga_ocr
            return self._rapid_ocr

        if target_mode in ("rapidocr", "en", "english", "zh", "chinese", "ko", "korean"):
            return self._rapid_ocr

        if target_mode != "auto":
            raise ValueError(
                f"Unknown OCR model or language '{requested_model}'. Valid options: 'auto', 'rapidocr', 'manga-ocr', 'ja', 'en', 'ko', 'zh'."
            )

        if chapter_id and chapter_id in self._chapter_cache:
            return self.get_adapter(self._chapter_cache[chapter_id])

        if sample_crops:
            detected_model = await self.probe_language(sample_crops)
        else:
            detected_model = self._fallback_model

        if detected_model == "manga-ocr" and not await self._manga_ocr.is_available():
            detected_model = "rapidocr"

        if chapter_id:
            self._chapter_cache[chapter_id] = detected_model

        return self.get_adapter(detected_model)

    async def recognize_routed(
        self,
        image_crops: list[bytes],
        requested_model: str | None = None,
        chapter_id: str | None = None,
    ) -> tuple[list[str], str]:
        """Resolve adapter and transcribe all speech bubble crops in a single call."""
        adapter = await self.resolve_engine(
            requested_model=requested_model,
            sample_crops=image_crops,
            chapter_id=chapter_id,
        )
        texts = await adapter.recognize_batch(image_crops)
        return list(texts), adapter.name

    def get_cached_model(self, chapter_id: str) -> str | None:
        """Get cached OCR model name for a chapter ID."""
        return self._chapter_cache.get(chapter_id)

    def set_cached_model(self, chapter_id: str, model_name: str) -> None:
        """Set cached OCR model name for a chapter ID."""
        self._chapter_cache[chapter_id] = model_name

    def clear_cache(self) -> None:
        """Clear all cached chapter OCR selections."""
        self._chapter_cache.clear()

    async def _invoke_rapid_full_page_or_batch(
        self,
        image_np: np.ndarray[Any, Any] | Image.Image,
        work_items: Sequence[BubbleWorkItem],
        image_width: int,
        image_height: int,
        lang: str = "auto",
    ) -> list[str]:
        """Invoke RapidOCR with full-page spatial mapping or crop-batch fallback."""
        full_page_fn = getattr(self._rapid_ocr, "recognize_full_page", None)
        if full_page_fn is not None and getattr(self._rapid_ocr, "supports_full_page", False):
            try:
                raw_out: Sequence[str] = await full_page_fn(
                    image_np, work_items, image_width, image_height, lang=lang
                )
            except TypeError:
                raw_out = await full_page_fn(image_np, work_items, image_width, image_height)
            return list(raw_out)

        crops = self._crop_work_items(image_np, work_items, image_width, image_height)
        batch_fn: Any = self._rapid_ocr.recognize_batch
        sig_params: Mapping[str, Any] = {}
        try:
            sig_params = inspect.signature(batch_fn).parameters
        except (ValueError, TypeError):
            sig_params = {}
        if "lang" in sig_params:
            batch_out: Sequence[str] = await batch_fn(crops, lang=lang)
        else:
            batch_out = await batch_fn(crops)
        return list(batch_out)

    async def recognize_routed_full_page(
        self,
        image_np: np.ndarray[Any, Any] | Image.Image,
        work_items: Sequence[BubbleWorkItem],
        image_width: int,
        image_height: int,
        requested_model: str | None = None,
        chapter_id: str | None = None,
    ) -> tuple[list[str], str]:
        """Transcribe bubble regions via RapidOCR or legacy custom MangaOCR adapter."""
        if not work_items:
            return [], self._fallback_model

        target_mode = (
            requested_model if requested_model is not None and requested_model != "" else self._default_model
        ).lower().strip()

        valid_modes = (
            "auto",
            "rapidocr",
            "manga-ocr",
            "ja",
            "japanese",
            "en",
            "english",
            "zh",
            "chinese",
            "ko",
            "korean",
        )
        if target_mode not in valid_modes:
            raise ValueError(
                f"Unknown OCR model or language '{requested_model}'. Valid options: 'auto', 'rapidocr', 'manga-ocr', 'ja', 'en', 'ko', 'zh'."
            )

        if target_mode in ("manga-ocr", "ja", "japanese"):
            if await self._manga_ocr.is_available() and self._manga_ocr.name != self._rapid_ocr.name:
                crops = self._crop_work_items(image_np, work_items, image_width, image_height)
                texts = await self._manga_ocr.recognize_batch(crops)
                return list(texts), self._manga_ocr.name
            texts = await self._invoke_rapid_full_page_or_batch(
                image_np, work_items, image_width, image_height, lang="ja"
            )
            return texts, self._rapid_ocr.name

        if target_mode in ("ko", "korean"):
            texts = await self._invoke_rapid_full_page_or_batch(
                image_np, work_items, image_width, image_height, lang="ko"
            )
            return texts, self._rapid_ocr.name

        if target_mode in ("rapidocr", "en", "english", "zh", "chinese"):
            texts = await self._invoke_rapid_full_page_or_batch(
                image_np, work_items, image_width, image_height, lang="auto"
            )
            return texts, self._rapid_ocr.name

        # Auto Mode: Chapter cache hit
        if chapter_id and chapter_id in self._chapter_cache:
            cached = self._chapter_cache[chapter_id]
            target_lang = "ko" if cached == "ko" else "auto"
            texts = await self._invoke_rapid_full_page_or_batch(
                image_np, work_items, image_width, image_height, lang=target_lang
            )
            return texts, self._rapid_ocr.name

        if chapter_id:
            cid_lower = chapter_id.lower()
            if "korean" in cid_lower or "manhwa" in cid_lower:
                self._chapter_cache[chapter_id] = "ko"
                texts = await self._invoke_rapid_full_page_or_batch(
                    image_np, work_items, image_width, image_height, lang="ko"
                )
                return texts, self._rapid_ocr.name

        # Unified single-pass multilingual recognition (PP-OCRv6 covers ZH/JA/EN natively)
        texts = await self._invoke_rapid_full_page_or_batch(
            image_np, work_items, image_width, image_height, lang="auto"
        )
        if chapter_id:
            self._chapter_cache[chapter_id] = self._rapid_ocr.name
        return texts, self._rapid_ocr.name

    @staticmethod
    def _quad_to_bounds_1000(
        quad: np.ndarray[Any, Any],
        image_width: int,
        image_height: int,
    ) -> tuple[float, float, float, float, float, float]:
        """Map physical quad vertices into canonical [0, 1000] bounds and centroid."""
        xs = quad[:, 0]
        ys = quad[:, 1]
        w_safe = float(max(1, image_width))
        h_safe = float(max(1, image_height))
        ymin = (float(ys.min()) / h_safe) * 1000.0
        xmin = (float(xs.min()) / w_safe) * 1000.0
        ymax = (float(ys.max()) / h_safe) * 1000.0
        xmax = (float(xs.max()) / w_safe) * 1000.0
        return ymin, xmin, ymax, xmax, (xmin + xmax) / 2.0, (ymin + ymax) / 2.0

    @staticmethod
    def _overlaps_any_box_iomin(
        box_1000: tuple[float, float, float, float],
        target_boxes: Sequence[tuple[int, int, int, int]],
        threshold: float = 0.40,
    ) -> bool:
        """Return True if intersection over smaller box area meets threshold for any target box."""
        q_ymin, q_xmin, q_ymax, q_xmax = box_1000
        q_area = max(1.0, (q_ymax - q_ymin) * (q_xmax - q_xmin))
        for t_ymin, t_xmin, t_ymax, t_xmax in target_boxes:
            inter_w = max(0.0, min(q_xmax, float(t_xmax)) - max(q_xmin, float(t_xmin)))
            inter_h = max(0.0, min(q_ymax, float(t_ymax)) - max(q_ymin, float(t_ymin)))
            inter_area = inter_w * inter_h
            if inter_area <= 0.0:
                continue
            t_area = max(1.0, float(t_ymax - t_ymin) * float(t_xmax - t_xmin))
            if inter_area / min(q_area, t_area) >= threshold:
                return True
        return False

    @classmethod
    def _overlaps_sfx(
        cls,
        box_1000: tuple[float, float, float, float],
        sfx_boxes: Sequence[tuple[int, int, int, int]],
        threshold: float = 0.40,
    ) -> bool:
        """Return True if IoMin with any YOLO SFX box exceeds threshold."""
        return cls._overlaps_any_box_iomin(box_1000, sfx_boxes, threshold=threshold)

    @classmethod
    def _is_residual_noise_cluster(
        cls,
        cluster: ParagraphCluster,
        has_bubbles: bool,
    ) -> bool:
        """Filter residual non-text noise clusters according to manga vs pure-prose context."""
        meaningful = cls._NON_WORD_PATTERN.sub("", cluster.text)
        if not meaningful:
            return True
        if not has_bubbles:
            return cluster.confidence < 0.40
        if cluster.confidence < 0.50:
            return True
        if len(meaningful) == 1:
            return meaningful.isascii() or cluster.confidence < 0.85
        return (
            len(meaningful) <= 4
            and meaningful.isascii()
            and " " not in cluster.text.strip()
            and cluster.confidence < 0.80
        )

    def _should_retry_korean(
        self,
        recognized: list[tuple[str, float]],
        chapter_id: str | None,
    ) -> bool:
        """Determine whether first-pass PP-OCRv6 results warrant a Korean recognizer pass on cached crops."""
        if not recognized:
            return False

        scores = [conf for _txt, conf in recognized]
        avg_conf = sum(scores) / float(len(scores))
        empty_ratio = sum(1 for txt, _ in recognized if not txt.strip()) / float(len(recognized))
        combined = "\n".join(txt for txt, _ in recognized if txt.strip())

        if self.JAPANESE_KANA_REGEX.search(combined):
            return False

        cid_lower = chapter_id.lower() if chapter_id else ""
        is_korean_hint = "korean" in cid_lower or "manhwa" in cid_lower

        if is_korean_hint and avg_conf < 0.85:
            return True
        return avg_conf < 0.72 or empty_ratio > 0.35

    @staticmethod
    def _quad_to_geometry_stub(quad: np.ndarray[Any, Any]) -> dict[str, Any]:
        """Convert quad into geometry dict for pre-recognition Furigana filtering."""
        xs = quad[:, 0]
        ys = quad[:, 1]
        xmin, xmax = float(xs.min()), float(xs.max())
        ymin, ymax = float(ys.min()), float(ys.max())
        return {
            "xmin": xmin,
            "xmax": xmax,
            "ymin": ymin,
            "ymax": ymax,
            "w": max(1.0, xmax - xmin),
            "h": max(1.0, ymax - ymin),
            "orientation": classify_box_orientation(quad.tolist()),
        }

    def _filter_quad_bucket_furigana(
        self,
        quads: list[np.ndarray[Any, Any]],
    ) -> list[np.ndarray[Any, Any]]:
        """Apply vertical Furigana strip filtering to raw DBNet quads before recognizer inference."""
        if len(quads) < 2:
            return quads
        geom_items = [{**self._quad_to_geometry_stub(q), "idx": idx} for idx, q in enumerate(quads)]
        kept_geom = filter_furigana_boxes(geom_items)
        kept_indices = {int(item["idx"]) for item in kept_geom}
        return [quads[i] for i in range(len(quads)) if i in kept_indices]

    async def recognize_hybrid_page(
        self,
        image_np: np.ndarray[Any, Any] | Image.Image,
        work_items: Sequence[BubbleWorkItem],
        sfx_boxes: Sequence[tuple[int, int, int, int]],
        image_width: int,
        image_height: int,
        chapter_id: str | None = None,
        requested_model: str | None = None,
        panel_boxes: Sequence[tuple[int, int, int, int]] = (),
        orphan_boxes: Sequence[tuple[int, int, int, int]] = (),
    ) -> HybridOCRResult:
        """Execute unified hybrid full-page OCR: spatial bubble fusion + non-SFX prose clustering."""
        rapid_split_capable = isinstance(self._rapid_ocr, RapidOCRAdapter) and self._rapid_ocr.supports_split_pipeline
        if not rapid_split_capable:
            return await self._recognize_hybrid_stub_fallback(
                image_np=image_np,
                work_items=work_items,
                image_width=image_width,
                image_height=image_height,
                chapter_id=chapter_id,
                requested_model=requested_model,
            )

        rapid = self._rapid_ocr
        if not isinstance(rapid, RapidOCRAdapter):
            return HybridOCRResult(bubble_texts=["" for _ in work_items])

        img_bgr = to_bgr_array(image_np)
        all_quads = rapid.detect_text_boxes(img_bgr)
        if not all_quads:
            return HybridOCRResult(bubble_texts=["" for _ in work_items])

        # 1. Spatial Fusion: Partition DBNet quads into Speech Bubbles vs Residual (excluding SFX)
        bubble_quads: dict[int, list[np.ndarray[Any, Any]]] = {idx: [] for idx in range(len(work_items))}
        residual_quads: list[np.ndarray[Any, Any]] = []
        boxes_canonical = [item.crop_box for item in work_items]
        margin = 6

        for quad in all_quads:
            ymin, xmin, ymax, xmax, norm_cx, norm_cy = self._quad_to_bounds_1000(
                quad, image_width, image_height
            )
            best_idx = -1
            best_area = float("inf")
            for idx, (b_ymin, b_xmin, b_ymax, b_xmax) in enumerate(boxes_canonical):
                if (
                    (b_ymin - margin) <= norm_cy <= (b_ymax + margin)
                    and (b_xmin - margin) <= norm_cx <= (b_xmax + margin)
                ):
                    area = (b_ymax - b_ymin) * (b_xmax - b_xmin)
                    if area < best_area:
                        best_area = area
                        best_idx = idx

            if best_idx >= 0:
                bubble_quads[best_idx].append(quad)
            elif not self._overlaps_sfx((ymin, xmin, ymax, xmax), sfx_boxes):
                residual_quads.append(quad)

        # 2. Pre-filter Furigana inside vertical containers & determine dominant page orientation
        v_count = 0
        h_count = 0
        for idx in range(len(work_items)):
            bubble_quads[idx] = self._filter_quad_bucket_furigana(bubble_quads[idx])
            for quad in bubble_quads[idx]:
                orient = classify_box_orientation(quad.tolist())
                if orient == "vertical":
                    v_count += 1
                elif orient == "horizontal":
                    h_count += 1

        residual_quads = self._filter_quad_bucket_furigana(residual_quads)
        for quad in residual_quads:
            orient = classify_box_orientation(quad.tolist())
            if orient == "vertical":
                v_count += 1
            elif orient == "horizontal":
                h_count += 1

        page_dominant_vertical = v_count > h_count and v_count >= 2

        # 3. Build single flat list of perspective crops across bubbles + residual prose
        crop_manifest: list[tuple[str, int, np.ndarray[Any, Any]]] = []
        crops_bgr: list[np.ndarray[Any, Any]] = []
        for idx in range(len(work_items)):
            for quad in bubble_quads[idx]:
                crop_manifest.append(("bubble", idx, quad))
                crops_bgr.append(rapid.crop_quad(img_bgr, quad))
        for quad in residual_quads:
            crop_manifest.append(("residual", -1, quad))
            crops_bgr.append(rapid.crop_quad(img_bgr, quad))

        if not crops_bgr:
            return HybridOCRResult(
                bubble_texts=["" for _ in work_items],
                page_dominant_vertical=page_dominant_vertical,
            )

        # 4. Run 1-pass PP-OCRv6_medium or cached Korean recognizer on reused crops
        has_bubbles = len(work_items) > 0
        use_ko = bool(chapter_id and self._chapter_cache.get(chapter_id) == "ko")
        recognized = rapid.recognize_crops(crops_bgr, use_korean=use_ko)
        ocr_engine_used = "rapidocr-ko" if use_ko else "rapidocr"

        ko_probe_source = (
            [rec for (kind, _, _), rec in zip(crop_manifest, recognized) if kind == "bubble"]
            if has_bubbles
            else recognized
        )
        if not ko_probe_source:
            ko_probe_source = recognized

        if not use_ko and self._should_retry_korean(ko_probe_source, chapter_id):
            ko_recognized = rapid.recognize_crops(crops_bgr, use_korean=True)
            ko_text_joined = "\n".join(txt for txt, _ in ko_recognized if txt.strip())
            has_hangul = len(self.HANGUL_SCRIPT_REGEX.findall(ko_text_joined)) >= 1
            if has_hangul:
                v6_avg = sum(c for _, c in recognized) / float(len(recognized))
                ko_avg = sum(c for _, c in ko_recognized) / float(len(ko_recognized))
                if ko_avg > v6_avg or v6_avg < 0.72:
                    recognized = ko_recognized
                    use_ko = True
                    ocr_engine_used = "rapidocr-ko"
                    if chapter_id:
                        self._chapter_cache[chapter_id] = "ko"

        # 5. Reassemble entries into bubbles vs context-filtered residual list
        bubble_entries: dict[int, list[dict[str, Any]]] = {idx: [] for idx in range(len(work_items))}
        residual_raw_lines: list[list[Any]] = []
        for (kind, b_idx, quad), (txt, conf) in zip(crop_manifest, recognized):
            if not txt:
                continue
            if kind == "bubble":
                entry = parse_ocr_entry(quad.tolist(), txt, conf)
                if entry is not None:
                    bubble_entries[b_idx].append(entry)
            else:
                q_bounds = self._quad_to_bounds_1000(quad, image_width, image_height)[:4]
                if not has_bubbles:
                    min_conf = 0.40
                elif orphan_boxes and self._overlaps_any_box_iomin(
                    q_bounds, orphan_boxes, threshold=0.35
                ):
                    min_conf = 0.50
                else:
                    min_conf = 0.55
                if float(conf) < min_conf:
                    continue
                residual_raw_lines.append([quad.tolist(), txt, conf])

        # 6. Guard ambiguous 3x3 tight square CJK grid bubbles on vertical pages
        if not use_ko:
            for idx, item in enumerate(work_items):
                entries = bubble_entries[idx]
                if not is_ambiguous_square_cjk_bubble(entries, page_dominant_vertical):
                    continue
                px_box = denormalize_box_from_1000(item.crop_box, image_width, image_height)
                rechecked = rapid.recheck_ambiguous_square_bubble(img_bgr, px_box, use_korean=False)
                if not rechecked:
                    continue
                prev_avg = sum(float(e["conf"]) for e in entries) / float(len(entries))
                new_avg = sum(conf for _, _, conf in rechecked) / float(len(rechecked))
                if new_avg >= prev_avg or new_avg >= 0.75:
                    new_entries = [
                        e
                        for quad_pts, r_txt, r_conf in rechecked
                        if (e := parse_ocr_entry(quad_pts.tolist(), r_txt, r_conf)) is not None
                    ]
                    if new_entries:
                        bubble_entries[idx] = new_entries

        bubble_texts: list[str] = []
        for idx in range(len(work_items)):
            text, _dir = order_bubble_lines_bidirectional(
                bubble_entries[idx], page_dominant_vertical=page_dominant_vertical
            )
            bubble_texts.append(text)

        raw_residual_clusters = cluster_lines_bidirectional(
            residual_raw_lines,
            image_width=image_width,
            image_height=image_height,
            panel_boxes=panel_boxes,
            bubble_boxes=boxes_canonical,
        )
        residual_clusters = [
            cluster
            for cluster in raw_residual_clusters
            if not self._is_residual_noise_cluster(cluster, has_bubbles=has_bubbles)
        ]

        all_texts = [*bubble_texts, *(c.text for c in residual_clusters if c.text.strip())]
        detected_lang = self.detect_page_language(all_texts)

        if chapter_id and not use_ko and chapter_id not in self._chapter_cache:
            self._chapter_cache[chapter_id] = "rapidocr"

        return HybridOCRResult(
            bubble_texts=bubble_texts,
            residual_clusters=residual_clusters,
            detected_source_lang=detected_lang,
            ocr_engine_used=ocr_engine_used,
            page_dominant_vertical=page_dominant_vertical,
        )

    async def _recognize_hybrid_stub_fallback(
        self,
        image_np: np.ndarray[Any, Any] | Image.Image,
        work_items: Sequence[BubbleWorkItem],
        image_width: int,
        image_height: int,
        chapter_id: str | None = None,
        requested_model: str | None = None,
    ) -> HybridOCRResult:
        """Delegate cleanly when mock/stub OCR engines are injected in unit tests."""
        bubble_texts: list[str] = []
        residual_clusters: list[ParagraphCluster] = []
        engine_used = self._fallback_model

        if work_items:
            bubble_texts, engine_used = await self.recognize_routed_full_page(
                image_np=image_np,
                work_items=work_items,
                image_width=image_width,
                image_height=image_height,
                requested_model=requested_model or self._default_model,
                chapter_id=chapter_id,
            )
        elif hasattr(self._rapid_ocr, "recognize_direct_paragraphs"):
            residual_clusters, engine_used = await self.recognize_routed_paragraphs(
                image_np=image_np,
                image_width=image_width,
                image_height=image_height,
                requested_model=requested_model or self._default_model,
                chapter_id=chapter_id,
            )

        all_texts = [*bubble_texts, *(c.text for c in residual_clusters if c.text.strip())]
        detected_lang = self.detect_page_language(all_texts)
        return HybridOCRResult(
            bubble_texts=bubble_texts,
            residual_clusters=residual_clusters,
            detected_source_lang=detected_lang,
            ocr_engine_used=engine_used,
            page_dominant_vertical=False,
        )

    @staticmethod
    def _crop_work_items(
        image_np: np.ndarray[Any, Any] | Image.Image,
        work_items: Sequence[BubbleWorkItem],
        image_width: int,
        image_height: int,
    ) -> list[bytes]:
        """Crop dialogue regions from image into PNG byte buffers."""
        if isinstance(image_np, Image.Image):
            img_arr = np.array(image_np.convert("RGB"))
        else:
            img_arr = image_np

        crops_bytes: list[bytes] = []
        for item in work_items:
            ymin, xmin, ymax, xmax = item.crop_box
            y1 = max(0, int(ymin * image_height / 1000))
            y2 = min(image_height, max(y1 + 1, int(ymax * image_height / 1000)))
            x1 = max(0, int(xmin * image_width / 1000))
            x2 = min(image_width, max(x1 + 1, int(xmax * image_width / 1000)))

            crop_slice = img_arr[y1:y2, x1:x2]
            crop_pil = Image.fromarray(crop_slice)
            buf = io.BytesIO()
            crop_pil.save(buf, format="PNG", compress_level=1)
            crops_bytes.append(buf.getvalue())
        return crops_bytes

    async def recognize_routed_paragraphs(
        self,
        image_np: np.ndarray[Any, Any] | Image.Image,
        image_width: int,
        image_height: int,
        requested_model: str = "auto",
        chapter_id: str | None = None,
    ) -> tuple[list[ParagraphCluster], str]:
        """Recognize and cluster full-page prose/novel text directly into paragraphs without bubbles."""
        target_mode = (
            requested_model if requested_model is not None and requested_model != "" else self._default_model
        ).lower().strip()

        if target_mode in ("manga-ocr", "ja", "japanese"):
            lang = "ja"
        elif target_mode in ("ko", "korean"):
            lang = "ko"
        elif target_mode in ("zh", "chinese", "en", "english"):
            lang = "zh"
        else:
            lang = "ko" if (chapter_id and self._chapter_cache.get(chapter_id) == "ko") else "auto"

        direct_fn = getattr(self._rapid_ocr, "recognize_direct_paragraphs", None)
        if direct_fn is not None:
            paragraphs: list[ParagraphCluster] = await direct_fn(
                image_np=image_np,
                image_width=image_width,
                image_height=image_height,
                lang=lang,
            )
            return paragraphs, self._rapid_ocr.name

        return [], self._fallback_model
