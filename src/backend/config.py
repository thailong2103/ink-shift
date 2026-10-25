"""Backend configuration settings loaded from environment."""

import os


def load_dotenv(filepath: str = ".env") -> None:
    """Lightweight zero-dependency .env loader for local development."""
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        key, val = stripped.split("=", 1)
                        clean_key = key.strip()
                        clean_val = val.strip().strip("'\"")
                        if clean_key and clean_key not in os.environ:
                            os.environ[clean_key] = clean_val
        except OSError:
            pass


load_dotenv()


class Settings:
    """Backend runtime settings with environment overrides."""

    def __init__(
        self,
        inkshift_db_path: str | None = None,
        inkshift_host: str | None = None,
        inkshift_port: int | None = None,
        inkshift_default_engine: str | None = None,
        max_payload_size: int | None = None,
        gemini_api_key: str | None = None,
        gemini_model: str | None = None,
        gemini_base_url: str | None = None,
        openai_api_key: str | None = None,
        openai_model: str | None = None,
        openai_base_url: str | None = None,
        anthropic_api_key: str | None = None,
        anthropic_model: str | None = None,
        anthropic_base_url: str | None = None,
        custom_api_key: str | None = None,
        custom_model: str | None = None,
        custom_base_url: str | None = None,
        xkiro_api_key: str | None = None,
        xkiro_model: str | None = None,
        xkiro_base_url: str | None = None,
        inkshift_cloud_provider: str | None = None,
        inkshift_cloud_timeout: float | None = None,
        inkshift_local_model_dir: str | None = None,
        inkshift_local_default_ocr: str | None = None,
        inkshift_local_execution_provider: str | None = None,
        inkshift_local_default_translator: str | None = None,
        inkshift_local_detector_model_path: str | None = None,
        inkshift_local_manga_ocr_model_path: str | None = None,
        inkshift_auto_download_models: bool | None = None,
        inkshift_log_level: str | None = None,
        inkshift_log_dir: str | None = None,
    ) -> None:
        self.inkshift_log_level: str = (
            inkshift_log_level
            if inkshift_log_level is not None
            else os.getenv("INKSHIFT_LOG_LEVEL", "WARNING").upper()
        )
        self.inkshift_log_dir: str = (
            inkshift_log_dir
            if inkshift_log_dir is not None
            else os.getenv("INKSHIFT_LOG_DIR", "./data/logs")
        )
        self.inkshift_db_path: str = (
            inkshift_db_path if inkshift_db_path is not None else os.getenv("INKSHIFT_DB_PATH", "./data/cache.db")
        )
        self.inkshift_host: str = (
            inkshift_host if inkshift_host is not None else os.getenv("INKSHIFT_HOST", "127.0.0.1")
        )
        self.inkshift_port: int = (
            inkshift_port if inkshift_port is not None else int(os.getenv("INKSHIFT_PORT", "8000"))
        )
        self.inkshift_default_engine: str = (
            inkshift_default_engine
            if inkshift_default_engine is not None
            else os.getenv("INKSHIFT_DEFAULT_ENGINE", "mock")
        )
        self.max_payload_size: int = (
            max_payload_size
            if max_payload_size is not None
            else int(os.getenv("INKSHIFT_MAX_PAYLOAD_SIZE", "20000000"))
        )
        self.gemini_api_key: str = (
            gemini_api_key if gemini_api_key is not None else os.getenv("GEMINI_API_KEY", "")
        )
        self.gemini_model: str = (
            gemini_model if gemini_model is not None else os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        )
        self.gemini_base_url: str = (
            gemini_base_url
            if gemini_base_url is not None
            else os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
        )
        self.openai_api_key: str = (
            openai_api_key if openai_api_key is not None else os.getenv("OPENAI_API_KEY", "")
        )
        self.openai_model: str = (
            openai_model if openai_model is not None else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        )
        self.openai_base_url: str = (
            openai_base_url
            if openai_base_url is not None
            else os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        )
        self.anthropic_api_key: str = (
            anthropic_api_key if anthropic_api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")
        )
        self.anthropic_model: str = (
            anthropic_model
            if anthropic_model is not None
            else os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
        )
        self.anthropic_base_url: str = (
            anthropic_base_url
            if anthropic_base_url is not None
            else os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
        )
        # Custom / Third-Party OpenAI-Compatible settings (with xKiro fallback)
        self.custom_api_key: str = (
            custom_api_key
            if custom_api_key is not None
            else (xkiro_api_key if xkiro_api_key is not None else (os.getenv("CUSTOM_API_KEY", "") or os.getenv("XKIRO_API_KEY", "")))
        )
        self.custom_model: str = (
            custom_model
            if custom_model is not None
            else (xkiro_model if xkiro_model is not None else (os.getenv("CUSTOM_MODEL", "") or os.getenv("XKIRO_MODEL", "")))
        )
        self.custom_base_url: str = (
            custom_base_url
            if custom_base_url is not None
            else (xkiro_base_url if xkiro_base_url is not None else (os.getenv("CUSTOM_BASE_URL", "") or os.getenv("XKIRO_BASE_URL", "https://api.xkiro.com/v1")))
        )
        # Retain xkiro aliases for backwards compatibility with existing tests
        self.xkiro_api_key: str = self.custom_api_key
        self.xkiro_model: str = self.custom_model
        self.xkiro_base_url: str = self.custom_base_url
        self.inkshift_cloud_provider: str = (
            inkshift_cloud_provider
            if inkshift_cloud_provider is not None
            else os.getenv("INKSHIFT_CLOUD_PROVIDER", "gemini")
        )
        self.inkshift_cloud_timeout: float = (
            inkshift_cloud_timeout
            if inkshift_cloud_timeout is not None
            else float(os.getenv("INKSHIFT_CLOUD_TIMEOUT", "30.0"))
        )
        self.inkshift_local_model_dir: str = (
            inkshift_local_model_dir
            if inkshift_local_model_dir is not None
            else os.getenv("INKSHIFT_LOCAL_MODEL_DIR", "./.cache/inkshift/models")
        )
        self.inkshift_local_default_ocr: str = (
            inkshift_local_default_ocr
            if inkshift_local_default_ocr is not None
            else os.getenv("INKSHIFT_LOCAL_DEFAULT_OCR", "auto")
        )
        self.inkshift_local_execution_provider: str = (
            inkshift_local_execution_provider
            if inkshift_local_execution_provider is not None
            else os.getenv("INKSHIFT_LOCAL_EXECUTION_PROVIDER", "directml")
        )
        self.inkshift_local_default_translator: str = (
            inkshift_local_default_translator
            if inkshift_local_default_translator is not None
            else os.getenv("INKSHIFT_LOCAL_DEFAULT_TRANSLATOR", "google-free")
        )
        self.inkshift_local_detector_model_path: str = (
            inkshift_local_detector_model_path
            if inkshift_local_detector_model_path is not None
            else os.getenv("INKSHIFT_LOCAL_DETECTOR_MODEL_PATH", "")
        )
        self.inkshift_local_manga_ocr_model_path: str = (
            inkshift_local_manga_ocr_model_path
            if inkshift_local_manga_ocr_model_path is not None
            else os.getenv("INKSHIFT_LOCAL_MANGA_OCR_MODEL_PATH", "")
        )
        self.inkshift_auto_download_models: bool = (
            inkshift_auto_download_models
            if inkshift_auto_download_models is not None
            else os.getenv("INKSHIFT_AUTO_DOWNLOAD_MODELS", "true").lower() in ("true", "1", "yes")
        )
