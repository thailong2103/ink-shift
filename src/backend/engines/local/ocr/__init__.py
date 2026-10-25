"""OCR module exports."""

from src.backend.engines.local.ocr.base import BaseOCREngine
from src.backend.engines.local.ocr.manga_ocr import MangaOCRAdapter
from src.backend.engines.local.ocr.rapid_ocr import RapidOCRAdapter
from src.backend.engines.local.ocr.router import OCRRouter
from src.backend.engines.local.ocr.text_assembler import (
    assemble_comic_lines,
    clean_japanese_text,
)

__all__ = [
    "BaseOCREngine",
    "MangaOCRAdapter",
    "OCRRouter",
    "RapidOCRAdapter",
    "assemble_comic_lines",
    "clean_japanese_text",
]
