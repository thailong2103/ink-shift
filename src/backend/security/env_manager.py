"""Atomic environment variable file manager and credential masking utility.

Provides atomic read/modify/write operations for .env files without corrupting
comments or line structures, sensitive key masking, and runtime memory synchronization.
"""

from __future__ import annotations

import os
from typing import Any


def mask_api_key(key: str | None) -> str | None:
    """Mask sensitive API keys for display in UI, exposing only prefix and suffix.

    Examples:
        None -> None
        "" -> None
        "12345" -> "********"
        "AIzaSyD-1234567890abcdef" -> "AIzaSy...cdef"
    """
    if not key or not key.strip():
        return None
    cleaned = key.strip()
    if len(cleaned) <= 10:
        return "********"
    return f"{cleaned[:6]}...{cleaned[-4:]}"


def read_env_lines(filepath: str = ".env") -> list[str]:
    """Read all lines from the environment file if it exists."""
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.readlines()
    except OSError:
        return []


def parse_env_dict(lines: list[str]) -> dict[str, str]:
    """Parse key-value pairs from lines, ignoring comments and invalid lines."""
    result: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, v = stripped.split("=", 1)
            clean_k = k.strip()
            clean_v = v.strip().strip("'\"")
            if clean_k:
                result[clean_k] = clean_v
    return result


def merge_env_lines(existing_lines: list[str], updates: dict[str, str]) -> list[str]:
    """Merge updates into existing lines, preserving existing comments and ordering.

    Args:
        existing_lines: Raw lines read from the .env file.
        updates: Mapping of environment keys to their new values.

    Returns:
        Updated list of lines with existing keys modified in-place and new keys appended.
    """
    remaining_updates = dict(updates)
    merged: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k, _ = stripped.split("=", 1)
            clean_k = k.strip()
            if clean_k in remaining_updates:
                new_val = remaining_updates.pop(clean_k)
                merged.append(f'{clean_k}="{new_val}"\n')
                continue
        merged.append(line)

    # Append any remaining new keys at the end
    if remaining_updates:
        if merged and not merged[-1].endswith("\n"):
            merged[-1] = merged[-1] + "\n"
        if merged and merged[-1].strip() != "":
            merged.append("\n")
        for k, v in remaining_updates.items():
            merged.append(f'{k}="{v}"\n')

    return merged


def atomic_write_env(filepath: str, updates: dict[str, str]) -> None:
    """Atomically update key-value pairs in the specified .env file using a temp file swap.

    Args:
        filepath: Absolute or relative path to the target .env file.
        updates: Mapping of variable names to string values.
    """
    existing_lines = read_env_lines(filepath)
    new_lines = merge_env_lines(existing_lines, updates)

    # Ensure parent directory exists
    parent_dir = os.path.dirname(filepath)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    temp_path = f"{filepath}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    # Atomic rename (safe against power loss / concurrent read on POSIX and NTFS)
    os.replace(temp_path, filepath)


def sync_runtime_settings(updates: dict[str, str], settings: Any | None = None) -> None:
    """Synchronize updated environment variables into os.environ and active Settings instance."""
    for key, val in updates.items():
        clean_key = key.strip()
        clean_val = val.strip()
        os.environ[clean_key] = clean_val

        if settings is not None:
            # Map common environment variables to Settings attributes
            attr_name = clean_key.lower()
            if hasattr(settings, attr_name):
                setattr(settings, attr_name, clean_val)
            # Legacy alias mappings
            if clean_key == "CUSTOM_API_KEY" and hasattr(settings, "xkiro_api_key"):
                settings.xkiro_api_key = clean_val
            if clean_key == "CUSTOM_BASE_URL" and hasattr(settings, "xkiro_base_url"):
                settings.xkiro_base_url = clean_val
            if clean_key == "GEMINI_API_KEY" and hasattr(settings, "gemini_api_key"):
                settings.gemini_api_key = clean_val


def get_provider_status(settings: Any) -> dict[str, dict[str, Any]]:
    """Inspect configured Settings and return masked status metadata for all 4 providers."""
    # 1. Google Gemini
    google_key = getattr(settings, "gemini_api_key", None)
    if google_key is None:
        google_key = os.getenv("GEMINI_API_KEY", "")
    google_status: dict[str, Any] = {
        "configured": bool(google_key and google_key.strip()),
        "masked_key": mask_api_key(google_key),
    }

    # 2. OpenAI Official
    openai_key = getattr(settings, "openai_api_key", None)
    if openai_key is None:
        openai_key = os.getenv("OPENAI_API_KEY", "")
    openai_base = getattr(settings, "openai_base_url", None)
    if not openai_base:
        openai_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_status: dict[str, Any] = {
        "configured": bool(openai_key and openai_key.strip()),
        "masked_key": mask_api_key(openai_key),
        "base_url": openai_base,
    }

    # 3. Anthropic Claude
    anthropic_key = getattr(settings, "anthropic_api_key", None)
    if anthropic_key is None:
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_base = getattr(settings, "anthropic_base_url", None)
    if not anthropic_base:
        anthropic_base = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
    anthropic_status: dict[str, Any] = {
        "configured": bool(anthropic_key and anthropic_key.strip()),
        "masked_key": mask_api_key(anthropic_key),
        "base_url": anthropic_base,
    }

    # 4. Custom OpenAI-Compatible
    custom_key = getattr(settings, "custom_api_key", None)
    if custom_key is None:
        custom_key = getattr(settings, "xkiro_api_key", None)
    if custom_key is None:
        custom_key = os.getenv("CUSTOM_API_KEY", "") or os.getenv("XKIRO_API_KEY", "")

    custom_base = getattr(settings, "custom_base_url", None)
    if not custom_base:
        custom_base = getattr(settings, "xkiro_base_url", None)
    if not custom_base:
        custom_base = os.getenv("CUSTOM_BASE_URL", "") or os.getenv("XKIRO_BASE_URL", "https://api.xkiro.com/v1")

    custom_status: dict[str, Any] = {
        "configured": bool(custom_key and custom_key.strip()),
        "masked_key": mask_api_key(custom_key),
        "base_url": custom_base,
    }

    return {
        "google": google_status,
        "openai": openai_status,
        "anthropic": anthropic_status,
        "custom": custom_status,
    }
