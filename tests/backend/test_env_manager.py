"""Unit tests for atomic .env file manager and key masking utility."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.backend.security.env_manager import (
    atomic_write_env,
    get_provider_status,
    mask_api_key,
    merge_env_lines,
    parse_env_dict,
    read_env_lines,
    sync_runtime_settings,
)


def test_mask_api_key() -> None:
    """Validate sensitive credential masking formats."""
    assert mask_api_key(None) is None
    assert mask_api_key("") is None
    assert mask_api_key("   ") is None
    assert mask_api_key("short") == "********"
    assert mask_api_key("1234567890") == "********"
    assert mask_api_key("AIzaSyD-1234567890abcdef") == "AIzaSy...cdef"
    assert mask_api_key("sk-proj-1234567890abcdefghijk") == "sk-pro...hijk"


def test_read_env_lines_nonexistent(tmp_path: Path) -> None:
    """Non-existent environment file returns empty list cleanly."""
    file = tmp_path / "nonexistent.env"
    lines = read_env_lines(str(file))
    assert lines == []


def test_parse_env_dict() -> None:
    """Parse key-value pairs ignoring comments and stripping quotes."""
    lines = [
        "# Initial comment\n",
        "GEMINI_API_KEY=\"AIzaSy123\"\n",
        "\n",
        "XKIRO_MODEL='qwen/qwen2.5'\n",
        "PORT=8000\n",
        "# Trailing comment\n",
    ]
    parsed = parse_env_dict(lines)
    assert parsed["GEMINI_API_KEY"] == "AIzaSy123"
    assert parsed["XKIRO_MODEL"] == "qwen/qwen2.5"
    assert parsed["PORT"] == "8000"
    assert "# Initial comment" not in parsed


def test_merge_env_lines_preserves_comments_and_updates_in_place() -> None:
    """Update existing variables in-place and append new variables at the bottom."""
    existing = [
        "# Section A\n",
        'GEMINI_API_KEY="old-gemini-key"\n',
        "PORT=8000\n",
    ]
    updates = {
        "GEMINI_API_KEY": "new-gemini-key",
        "ANTHROPIC_API_KEY": "new-claude-key",
    }
    merged = merge_env_lines(existing, updates)

    expected = [
        "# Section A\n",
        'GEMINI_API_KEY="new-gemini-key"\n',
        "PORT=8000\n",
        "\n",
        'ANTHROPIC_API_KEY="new-claude-key"\n',
    ]
    assert merged == expected


def test_atomic_write_env(tmp_path: Path) -> None:
    """Ensure atomic write persists changes safely and preserves unedited keys."""
    env_file = tmp_path / "subfolder" / ".env"
    initial_content = [
        "# Important Comment\n",
        'INKSHIFT_PORT="8000"\n',
        'GEMINI_API_KEY="initial-key"\n',
    ]
    env_file.parent.mkdir(parents=True, exist_ok=True)
    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(initial_content)

    # 1. Update existing key and add new key
    atomic_write_env(str(env_file), {"GEMINI_API_KEY": "updated-key", "OPENAI_API_KEY": "sk-test"})

    assert not (tmp_path / "subfolder" / ".env.tmp").exists()

    with open(env_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert lines[0] == "# Important Comment\n"
    assert lines[1] == 'INKSHIFT_PORT="8000"\n'
    assert lines[2] == 'GEMINI_API_KEY="updated-key"\n'
    assert 'OPENAI_API_KEY="sk-test"\n' in lines


def test_sync_runtime_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify synchronization into os.environ and Settings object."""
    class DummySettings:
        gemini_api_key: str = ""
        openai_api_key: str = ""
        xkiro_api_key: str = ""
        xkiro_base_url: str = ""

    settings = DummySettings()
    updates = {
        "GEMINI_API_KEY": "new-gemini",
        "OPENAI_API_KEY": "new-openai",
        "CUSTOM_API_KEY": "new-custom-key",
        "CUSTOM_BASE_URL": "https://custom.api/v1",
    }

    sync_runtime_settings(updates, settings)

    assert os.environ["GEMINI_API_KEY"] == "new-gemini"
    assert os.environ["OPENAI_API_KEY"] == "new-openai"
    assert settings.gemini_api_key == "new-gemini"
    assert settings.openai_api_key == "new-openai"
    assert settings.xkiro_api_key == "new-custom-key"
    assert settings.xkiro_base_url == "https://custom.api/v1"


def test_get_provider_status() -> None:
    """Verify masked status generation for 4 providers."""
    class MockSettings:
        gemini_api_key: str = "AIzaSyD-1234567890abcdef"
        openai_api_key: str = ""
        anthropic_api_key: str = "sk-ant-api03-1234567890abcdefghij"
        anthropic_base_url: str = "https://api.anthropic.com/v1"
        xkiro_api_key: str = "sk-custom-test-123456789"
        xkiro_base_url: str = "https://api.openrouter.ai/v1"

    settings = MockSettings()
    status = get_provider_status(settings)

    assert status["google"]["configured"] is True
    assert status["google"]["masked_key"] == "AIzaSy...cdef"

    assert status["openai"]["configured"] is False
    assert status["openai"]["masked_key"] is None

    assert status["anthropic"]["configured"] is True
    assert status["anthropic"]["masked_key"] == "sk-ant...ghij"

    assert status["custom"]["configured"] is True
    assert status["custom"]["base_url"] == "https://api.openrouter.ai/v1"
