"""OCR Router for intelligent adapter dispatch, Unicode script detection, and chapter-level caching."""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar

import numpy as np
from PIL import Image

from src.backend.engines.local.ocr.base import BaseOCREngine
from src.backend.logging import get_logger

if TYPE_CHECKING:
    from src.backend.detection.assembler import BubbleWorkItem

logger = get_logger("ocr.router")


class OCRRouter:
    """Routes OCR tasks to DirectML RapidOCR with full-page and crop support, and chapter-level caching."""

    # Unicode ranges for Japanese Kana:
    # Hiragana: \u3040-\u309F, Katakana: \u30A0-\u30FF, Katakana Extensions: \u31F0-\u31FF
    JAPANESE_KANA_REGEX: ClassVar[re.Pattern[str]] = re.compile(
        r"[\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF]"
    )
    # Latin alphabet: A-Z, a-z
    LATIN_SCRIPT_REGEX: ClassVar[re.Pattern[str]] = re.compile(r"[a-zA-Z]")
    # CJK Unified Ideographs (Hanzi/Kanji): \u4E00-\u9FFF
    HANZI_SCRIPT_REGEX: ClassVar[re.Pattern[str]] = re.compile(r"[\u4E00-\u9FFF]")
    # Korean Hangul: Syllables \uAC00-\uD7AF, Jamo \u1100-\u11FF, Compatibility Jamo \u3130-\u318F
    HANGUL_SCRIPT_REGEX: ClassVar[re.Pattern[str]] = re.compile(
        r"[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]"
    )

    def __init__(
        self,
        manga_ocr: BaseOCREngine | None = None,
        rapid_ocr: BaseOCREngine | None = None,
        default_model: str = "auto",
        fallback_model: str = "rapidocr",
    ) -> None:
        """Initialize OCRRouter with specialized or consolidated OCR adapters.

        Args:
            manga_ocr: Optional specialized Japanese OCR adapter. If omitted, aliases to rapid_ocr.
            rapid_ocr: Multilingual/Japanese OCR adapter (e.g. RapidOCRAdapter).
            default_model: Default selection mode ('auto', 'rapidocr', 'manga-ocr').
            fallback_model: Fallback adapter identifier ('rapidocr' or 'manga-ocr').
        """
        from src.backend.engines.local.ocr.rapid_ocr import RapidOCRAdapter

        self._rapid_ocr: BaseOCREngine = rapid_ocr or RapidOCRAdapter()
        # If manga_ocr is explicitly provided (e.g. In unit tests), use it;
        # otherwise (production without MangaOCR), alias cleanly to rapid_ocr
        self._manga_ocr: BaseOCREngine = manga_ocr if manga_ocr is not None else self._rapid_ocr
        self._default_model = default_model
        self._fallback_model = fallback_model
        self._chapter_cache: dict[str, str] = {}

    def get_adapter(self, model_name: str) -> BaseOCREngine:
        """Retrieve concrete BaseOCREngine adapter by identifier string or language code.

        Args:
            model_name: Identifier ('manga-ocr', 'rapidocr', 'ja', 'en', 'ko', 'zh').

        Returns:
            The corresponding BaseOCREngine adapter.

        Raises:
            ValueError: If model_name is not registered.
        """
        normalized = model_name.lower().strip()
        if normalized in ("manga-ocr", "ja", "japanese"):
            return self._manga_ocr
        elif normalized in (
            "rapidocr",
            "en",
            "english",
            "zh",
            "chinese",
            "ko",
            "korean",
        ):
            return self._rapid_ocr
        else:
            raise ValueError(
                f"Unknown OCR model '{model_name}'. Valid options: 'auto', 'rapidocr', 'manga-ocr', 'ja', 'en', 'ko', 'zh'."
            )

    def classify_text_script(self, text: str) -> str:
        """Classify script based on Unicode character analysis.

        - Hiragana or Katakana present -> 'manga-ocr'
        - Hangul present -> 'rapidocr'
        - Latin alphabet present -> 'rapidocr'
        - Hanzi present without Kana -> 'rapidocr'
        - Empty or punctuation-only -> fallback_model

        Args:
            text: Dialogue text string to analyze.

        Returns:
            Target adapter identifier ('manga-ocr' or 'rapidocr').
        """
        cleaned = text.strip()
        if not cleaned:
            return self._fallback_model

        has_kana = bool(self.JAPANESE_KANA_REGEX.search(cleaned))
        has_hangul = bool(self.HANGUL_SCRIPT_REGEX.search(cleaned))
        has_latin = bool(self.LATIN_SCRIPT_REGEX.search(cleaned))
        has_hanzi = bool(self.HANZI_SCRIPT_REGEX.search(cleaned))

        if has_kana:
            decision = "manga-ocr"
        elif has_hangul or has_latin or has_hanzi:
            decision = "rapidocr"
        else:
            decision = self._fallback_model

        logger.debug(
            "classify_text_script: '%s' (kana=%s, hangul=%s, latin=%s, hanzi=%s) -> adapter [%s]",
            cleaned[:30],
            has_kana,
            has_hangul,
            has_latin,
            has_hanzi,
            decision,
        )
        return decision

    async def probe_language(self, sample_crops: list[bytes] | bytes) -> str:
        """Probe sample bubble crop(s) using RapidOCR.

        Args:
            sample_crops: One or more binary image crops from the current page.

        Returns:
            Detected adapter identifier ('manga-ocr' or 'rapidocr').
        """
        crops = [sample_crops] if isinstance(sample_crops, bytes) else sample_crops
        valid_crops = [c for c in crops if c]
        if not valid_crops:
            return self._fallback_model

        logger.debug("probe_language: probing %d valid crops via RapidOCR...", len(valid_crops))
        try:
            probe_results = await self._rapid_ocr.recognize_batch(valid_crops[:3])
            for text in probe_results:
                cleaned = text.strip()
                if cleaned:
                    detected = self.classify_text_script(cleaned)
                    if detected != self._fallback_model:
                        logger.debug("probe_language: determined script '%s' from sample '%s'", detected, cleaned[:30])
                        return detected
            return self._fallback_model
        except (RuntimeError, ValueError, TypeError, OSError) as probe_err:
            logger.debug("probe_language exception: %s; using fallback [%s]", probe_err, self._fallback_model)
            return self._fallback_model

    async def resolve_engine(
        self,
        requested_model: str | None = None,
        sample_crops: list[bytes] | None = None,
        chapter_id: str | None = None,
    ) -> BaseOCREngine:
        """Resolve appropriate BaseOCREngine adapter according to override, cache, or probe.

        Args:
            requested_model: User-specified model ('auto', 'rapidocr', 'ja', 'en', etc.).
            sample_crops: List of bubble image crops available for probing.
            chapter_id: Optional unique chapter identifier to leverage cache.

        Returns:
            Resolved BaseOCREngine adapter instance.
        """
        target_mode = (
            requested_model if requested_model is not None and requested_model != "" else self._default_model
        ).lower().strip()

        # 1. Manual override or specific language code
        if target_mode in ("manga-ocr", "ja", "japanese"):
            if await self._manga_ocr.is_available():
                return self._manga_ocr
            logger.info("MangaOCR unavailable on host; falling back to RapidOCR adapter")
            return self._rapid_ocr

        if target_mode in (
            "rapidocr",
            "en",
            "english",
            "zh",
            "chinese",
            "ko",
            "korean",
        ):
            return self._rapid_ocr

        if target_mode != "auto":
            raise ValueError(
                f"Unknown OCR model or language '{requested_model}'. Valid options: 'auto', 'rapidocr', 'manga-ocr', 'ja', 'en', 'ko', 'zh'."
            )

        # 2. Check chapter cache for auto mode
        if chapter_id and chapter_id in self._chapter_cache:
            cached_model = self._chapter_cache[chapter_id]
            logger.debug("Chapter cache HIT (chapter '%s'): using adapter [%s]", chapter_id, cached_model)
            return self.get_adapter(cached_model)

        # 3. Auto-probe language from sample crops
        if sample_crops and len(sample_crops) > 0:
            detected_model = await self.probe_language(sample_crops)
        else:
            detected_model = self._fallback_model

        if detected_model == "manga-ocr" and not await self._manga_ocr.is_available():
            logger.info("MangaOCR unavailable on host; falling back to RapidOCR adapter")
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
        """Resolve adapter and transcribe all speech bubble crops in a single call.

        Args:
            image_crops: List of binary image crops.
            requested_model: Optional user-specified model ('auto', 'rapidocr', 'ja', etc.).
            chapter_id: Optional chapter ID for caching.

        Returns:
            Tuple of (transcribed_texts, engine_name_used).
        """
        adapter = await self.resolve_engine(
            requested_model=requested_model,
            sample_crops=image_crops,
            chapter_id=chapter_id,
        )
        texts = await adapter.recognize_batch(image_crops)
        return texts, adapter.name

    def get_cached_model(self, chapter_id: str) -> str | None:
        """Get cached OCR model name for a chapter ID."""
        return self._chapter_cache.get(chapter_id)

    def set_cached_model(self, chapter_id: str, model_name: str) -> None:
        """Set cached OCR model name for a chapter ID."""
        self._chapter_cache[chapter_id] = model_name

    def clear_cache(self) -> None:
        """Clear all cached chapter OCR selections."""
        self._chapter_cache.clear()

    async def recognize_routed_full_page(
        self,
        image_np: np.ndarray[Any, Any] | Image.Image,
        work_items: Sequence[BubbleWorkItem],
        image_width: int,
        image_height: int,
        requested_model: str | None = None,
        chapter_id: str | None = None,
    ) -> tuple[list[str], str]:
        """Transcribe text using single-pass full-page recognition or intelligent crop fallback.

        Executes full-page recognition via RapidOCR with DirectML GPU acceleration across all
        languages (Japanese, English, Korean, Chinese). Falls back to crop-based recognition
        if full-page mode is unsupported.

        Args:
            image_np: RGB numpy array or PIL Image of the uncropped page.
            work_items: Sequence of BubbleWorkItem instances.
            image_width: Original image width in pixels.
            image_height: Original image height in pixels.
            requested_model: User-specified model ('auto', 'rapidocr', 'ja', 'en', etc.).
            chapter_id: Optional unique chapter identifier for caching.

        Returns:
            Tuple of (transcribed_texts, engine_name_used).
        """
        if not work_items:
            return [], self._fallback_model

        target_mode = (
            requested_model if requested_model is not None and requested_model != "" else self._default_model
        ).lower().strip()

        # Validate requested model/language
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

        # 1. Explicit Japanese override
        if target_mode in ("manga-ocr", "ja", "japanese"):
            # If manga_ocr is distinct and available (e.g. Unit test stub), use it
            if await self._manga_ocr.is_available() and self._manga_ocr.name != self._rapid_ocr.name:
                crops = self._crop_work_items(image_np, work_items, image_width, image_height)
                texts = await self._manga_ocr.recognize_batch(crops)
                return texts, self._manga_ocr.name

            # Consolidated RapidOCR DirectML path (Fast, sub-second on AMD 780M, no crash!)
            if hasattr(self._rapid_ocr, "recognize_full_page") and getattr(self._rapid_ocr, "supports_full_page", False):
                texts = await self._rapid_ocr.recognize_full_page(image_np, work_items, image_width, image_height)
                return texts, self._rapid_ocr.name
            crops = self._crop_work_items(image_np, work_items, image_width, image_height)
            texts = await self._rapid_ocr.recognize_batch(crops)
            return texts, self._rapid_ocr.name

        # 2. Explicit Non-Japanese override
        if target_mode in ("rapidocr", "en", "english", "zh", "chinese", "ko", "korean"):
            if hasattr(self._rapid_ocr, "recognize_full_page") and getattr(self._rapid_ocr, "supports_full_page", False):
                texts = await self._rapid_ocr.recognize_full_page(image_np, work_items, image_width, image_height)
                return texts, self._rapid_ocr.name
            crops = self._crop_work_items(image_np, work_items, image_width, image_height)
            texts = await self._rapid_ocr.recognize_batch(crops)
            return texts, self._rapid_ocr.name

        # 3. Auto Mode: Check chapter cache
        if chapter_id and chapter_id in self._chapter_cache:
            cached_model = self._chapter_cache[chapter_id]
            logger.debug("Chapter cache HIT (chapter '%s'): using adapter [%s]", chapter_id, cached_model)
            if cached_model == "rapidocr" and hasattr(self._rapid_ocr, "recognize_full_page") and getattr(self._rapid_ocr, "supports_full_page", False):
                texts = await self._rapid_ocr.recognize_full_page(image_np, work_items, image_width, image_height)
                return texts, self._rapid_ocr.name
            else:
                adapter = self.get_adapter(cached_model)
                crops = self._crop_work_items(image_np, work_items, image_width, image_height)
                texts = await adapter.recognize_batch(crops)
                return texts, adapter.name

        # 4. Auto Mode: Single-pass probe via RapidOCR Full-Page
        if hasattr(self._rapid_ocr, "recognize_full_page") and getattr(self._rapid_ocr, "supports_full_page", False):
            rapid_texts = await self._rapid_ocr.recognize_full_page(image_np, work_items, image_width, image_height)
            has_kana = any(bool(self.JAPANESE_KANA_REGEX.search(t)) for t in rapid_texts if t.strip())
            if has_kana and self._manga_ocr.name != self._rapid_ocr.name and await self._manga_ocr.is_available():
                if chapter_id:
                    self._chapter_cache[chapter_id] = "manga-ocr"
                crops = self._crop_work_items(image_np, work_items, image_width, image_height)
                texts = await self._manga_ocr.recognize_batch(crops)
                return texts, self._manga_ocr.name
            else:
                if chapter_id:
                    self._chapter_cache[chapter_id] = "rapidocr"
                return rapid_texts, self._rapid_ocr.name

        # Fallback if rapid_ocr does not support full-page (e.g. Basic mock)
        crops = self._crop_work_items(image_np, work_items, image_width, image_height)
        return await self.recognize_routed(crops, requested_model="auto", chapter_id=chapter_id)

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
