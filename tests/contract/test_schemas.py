"""Contract schema and security boundary tests for InkShift API."""

import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from src.backend.schemas.contract import (
    APIErrorResponse,
    TranslatedBlock,
    TranslationRequest,
    TranslationResponse,
)


class TestContractSchemas(unittest.TestCase):
    """Test suite verifying API contracts and security validation boundaries."""

    def setUp(self) -> None:
        self.fixtures_dir = Path(__file__).resolve().parent.parent / "fixtures"
        self.golden_fixture_path = self.fixtures_dir / "sample_page_response.json"

    def test_golden_master_fixture_validates_successfully(self) -> None:
        """SC-3: Verify the standard golden fixture parses into TranslationResponse."""
        with open(self.golden_fixture_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        response = TranslationResponse.model_validate(raw_data)
        self.assertTrue(response.success)
        self.assertEqual(len(response.blocks), 2)
        self.assertEqual(response.blocks[0].box, (120, 450, 280, 720))
        self.assertEqual(response.blocks[0].translated_text, "Cậu đang làm cái gì thế?")
        self.assertFalse(response.from_cache)

    def test_translation_request_valid_payload(self) -> None:
        """Verify TranslationRequest correctly parses valid input and sets defaults."""
        payload = {
            "image": "data:image/jpeg;base64,dGVzdA==",
            "image_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "source_lang": "ja",
            "target_lang": "vi",
            "engine": "cloud",
            "force_refresh": True,
        }
        request = TranslationRequest.model_validate(payload)
        self.assertEqual(request.source_lang, "ja")
        self.assertEqual(request.target_lang, "vi")
        self.assertEqual(request.engine, "cloud")
        self.assertTrue(request.force_refresh)

    def test_translation_request_defaults(self) -> None:
        """Verify TranslationRequest applies canonical default values."""
        request = TranslationRequest(image="data:image/png;base64,abc")
        self.assertIsNone(request.image_hash)
        self.assertEqual(request.source_lang, "auto")
        self.assertEqual(request.target_lang, "vi")
        self.assertEqual(request.engine, "auto")
        self.assertFalse(request.force_refresh)

    def test_bounding_box_out_of_bounds_rejected(self) -> None:
        """SC-4: Verify coordinates < 0 or > 1000 raise ValidationError."""
        # Value > 1000
        with self.assertRaises(ValidationError):
            TranslatedBlock(
                id="blk_invalid_1",
                box=(0, 0, 1001, 500),
                translated_text="Lỗi",
            )

        # Value < 0
        with self.assertRaises(ValidationError):
            TranslatedBlock(
                id="blk_invalid_2",
                box=(-1, 0, 500, 500),
                translated_text="Lỗi",
            )

    def test_bounding_box_inverted_coordinates_rejected(self) -> None:
        """Verify ymin > ymax or xmin > xmax is rejected."""
        # ymin > ymax
        with self.assertRaises(ValidationError):
            TranslatedBlock(
                id="blk_invalid_ymin",
                box=(600, 100, 400, 300),
                translated_text="Lỗi",
            )

        # xmin > xmax
        with self.assertRaises(ValidationError):
            TranslatedBlock(
                id="blk_invalid_xmin",
                box=(100, 600, 300, 400),
                translated_text="Lỗi",
            )

    def test_image_hash_path_traversal_and_malformed_rejected(self) -> None:
        """Verify image_hash strictly enforces SHA-256 64-character hex regex."""
        malicious_hashes = [
            "../../etc/passwd",
            "..\\..\\windows\\system32",
            "invalid_hash_value",
            "e3b0c442",  # Too short
            "g" * 64,    # Non-hex characters
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855extra",  # Too long
        ]
        for bad_hash in malicious_hashes:
            with self.subTest(hash=bad_hash), self.assertRaises(ValidationError):
                TranslationRequest(
                    image="data:image/jpeg;base64,abc",
                    image_hash=bad_hash,
                )

    def test_image_payload_max_length_enforced(self) -> None:
        """Verify image payload over 20MB character limit is rejected."""
        valid_large_image = "a" * 20_000_000
        req = TranslationRequest(image=valid_large_image)
        self.assertEqual(len(req.image), 20_000_000)

        oversized_image = "a" * 20_000_001
        with self.assertRaises(ValidationError):
            TranslationRequest(image=oversized_image)

    def test_confidence_score_boundaries(self) -> None:
        """Verify confidence is strictly clamped to [0.0, 1.0]."""
        # Valid bounds
        block_low = TranslatedBlock(
            id="blk_0",
            box=(0, 0, 100, 100),
            translated_text="OK",
            confidence=0.0,
        )
        self.assertEqual(block_low.confidence, 0.0)

        block_high = TranslatedBlock(
            id="blk_1",
            box=(0, 0, 100, 100),
            translated_text="OK",
            confidence=1.0,
        )
        self.assertEqual(block_high.confidence, 1.0)

        # > 1.0 rejected
        with self.assertRaises(ValidationError):
            TranslatedBlock(
                id="blk_invalid",
                box=(0, 0, 100, 100),
                translated_text="Lỗi",
                confidence=1.01,
            )

        # < 0.0 rejected
        with self.assertRaises(ValidationError):
            TranslatedBlock(
                id="blk_invalid",
                box=(0, 0, 100, 100),
                translated_text="Lỗi",
                confidence=-0.01,
            )

    def test_translation_request_valid_image_hash(self) -> None:
        """Verify valid 64-character SHA-256 hex string is accepted."""
        valid_hash = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        req = TranslationRequest(
            image="data:image/jpeg;base64,abc",
            image_hash=valid_hash,
        )
        self.assertEqual(req.image_hash, valid_hash)

    def test_translation_response_rejects_negative_latency(self) -> None:
        """Verify negative execution time is rejected."""
        with self.assertRaises(ValidationError):
            TranslationResponse(
                page_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                engine_used="gemini-2.0-flash",
                execution_time_ms=-1,
                blocks=[],
            )

    def test_extra_fields_forbidden(self) -> None:
        """Verify strict payload hygiene: unexpected fields are rejected."""
        with self.assertRaises(ValidationError):
            TranslationRequest.model_validate({
                "image": "data:image/jpeg;base64,abc",
                "unexpected_field": "hacker_payload",
            })

    def test_api_error_response_structure(self) -> None:
        """SC-5: Verify structured error response format with multiple detail shapes."""
        # Dict details
        error_payload = {
            "success": False,
            "error": {
                "code": "CACHE_MISS",
                "message": "Page has not been translated yet",
                "details": {"image_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
            },
        }
        error_resp = APIErrorResponse.model_validate(error_payload)
        self.assertFalse(error_resp.success)
        self.assertEqual(error_resp.error.code, "CACHE_MISS")
        self.assertIsInstance(error_resp.error.details, dict)

        # String details
        str_error = APIErrorResponse(
            error={
                "code": "BAD_REQUEST",
                "message": "Invalid request parameter",
                "details": "image is missing",
            }
        )
        self.assertEqual(str_error.error.details, "image is missing")

        # None details
        none_error = APIErrorResponse(
            error={
                "code": "INTERNAL_ERROR",
                "message": "Unexpected error",
            }
        )
        self.assertIsNone(none_error.error.details)


if __name__ == "__main__":
    unittest.main()

