"""Unit and integration tests for Localhost Boundary Security Middleware."""

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.security.middleware import (
    ALLOWED_CORS_ORIGINS,
    SecurityHeadersMiddleware,
    validate_image_magic_bytes,
)


def create_test_security_app() -> FastAPI:
    """Create a lightweight test FastAPI app with security middleware mounted."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/translate")
    async def translate() -> dict[str, str]:
        return {"status": "translated"}

    @app.get("/api/v1/cache/{image_hash}")
    async def get_cache(image_hash: str) -> dict[str, str]:
        return {"hash": image_hash}

    return app


class TestSecurityMiddleware(unittest.TestCase):
    """Test security middleware enforcing header checks, payload caps, and CORS origins."""

    def setUp(self) -> None:
        self.app = create_test_security_app()
        self.client = TestClient(self.app)

    def test_health_check_exempt_from_client_header(self) -> None:
        """Health check endpoint can be probed without X-InkShift-Client header."""
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_translate_requires_client_header_rejects_missing(self) -> None:
        """Calling /api/v1/translate without valid client header returns 403 Forbidden."""
        response = self.client.post("/api/v1/translate", json={"image": "abc"})
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "FORBIDDEN_CLIENT")

    def test_translate_accepts_extension_client_header(self) -> None:
        """Valid X-InkShift-Client: extension header is accepted."""
        response = self.client.post(
            "/api/v1/translate",
            json={"image": "abc"},
            headers={"X-InkShift-Client": "extension"},
        )
        self.assertEqual(response.status_code, 200)

    def test_translate_accepts_reader_client_header(self) -> None:
        """Valid X-InkShift-Client: reader header is accepted."""
        response = self.client.post(
            "/api/v1/translate",
            json={"image": "abc"},
            headers={"X-InkShift-Client": "reader"},
        )
        self.assertEqual(response.status_code, 200)

    def test_translate_rejects_invalid_client_header_value(self) -> None:
        """Arbitrary client header values are rejected with 403."""
        response = self.client.post(
            "/api/v1/translate",
            json={"image": "abc"},
            headers={"X-InkShift-Client": "malicious_web_page"},
        )
        self.assertEqual(response.status_code, 403)

    def test_cache_endpoint_requires_client_header(self) -> None:
        """Cache lookup endpoint /api/v1/cache/{hash} requires client header."""
        hash_val = "d" * 64
        # Without header
        resp_blocked = self.client.get(f"/api/v1/cache/{hash_val}")
        self.assertEqual(resp_blocked.status_code, 403)

        # With header
        resp_allowed = self.client.get(
            f"/api/v1/cache/{hash_val}",
            headers={"X-InkShift-Client": "extension"},
        )
        self.assertEqual(resp_allowed.status_code, 200)

    def test_oversized_payload_rejected_with_413(self) -> None:
        """Payload exceeding 20MB limit is rejected with HTTP 413 Payload Too Large."""
        headers = {
            "X-InkShift-Client": "extension",
            "Content-Length": "21000000",
        }
        response = self.client.post(
            "/api/v1/translate",
            headers=headers,
            content=b"x" * 100,  # Content-Length header triggers early rejection
        )
        self.assertEqual(response.status_code, 413)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["error"]["code"], "PAYLOAD_TOO_LARGE")
        self.assertIn("20MB", data["error"]["message"])

    def test_invalid_content_length_header_passes_through(self) -> None:
        """A malformed non-integer Content-Length header is safely ignored without crashing."""
        headers = {
            "X-InkShift-Client": "extension",
            "Content-Length": "not-an-integer",
        }
        response = self.client.post("/api/v1/translate", headers=headers, json={"image": "abc"})
        self.assertEqual(response.status_code, 200)


    def test_cors_origin_whitelist_contents(self) -> None:
        """Verify standard origins allowed in CORS whitelist."""
        self.assertIn("http://localhost:8000", ALLOWED_CORS_ORIGINS)
        self.assertIn("http://127.0.0.1:8000", ALLOWED_CORS_ORIGINS)
        self.assertNotIn("*", ALLOWED_CORS_ORIGINS)


class TestImageMagicBytesValidation(unittest.TestCase):
    """Test validation of image format magic bytes."""

    def test_valid_jpeg_magic_bytes(self) -> None:
        jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        self.assertTrue(validate_image_magic_bytes(jpeg_bytes))

    def test_valid_png_magic_bytes(self) -> None:
        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        self.assertTrue(validate_image_magic_bytes(png_bytes))

    def test_valid_webp_magic_bytes(self) -> None:
        webp_bytes = b"RIFF\x00\x00\x00\x00WEBPVP8 "
        self.assertTrue(validate_image_magic_bytes(webp_bytes))

    def test_invalid_text_or_exe_magic_bytes(self) -> None:
        text_bytes = b"Hello, this is not an image."
        exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00"
        self.assertFalse(validate_image_magic_bytes(text_bytes))
        self.assertFalse(validate_image_magic_bytes(exe_bytes))
        self.assertFalse(validate_image_magic_bytes(b""))


if __name__ == "__main__":
    unittest.main()
