"""Shared LLM provider configuration for the WeChat customer-service app."""

from __future__ import annotations

import os
from collections.abc import Callable


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_PRO_MODEL = "deepseek-v4-pro"
DEFAULT_DEEPSEEK_FLASH_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_MODEL = DEFAULT_DEEPSEEK_PRO_MODEL
DEFAULT_DEEPSEEK_CONTEXT_WINDOW_TOKENS = 1_000_000
DEFAULT_DEEPSEEK_TIMEOUT_SECONDS = 120


SecretReader = Callable[[str], str]


def read_secret(name: str) -> str:
    """Read a secret from process env first, then the current user's Windows env."""
    value = os.getenv(name)
    if value:
        return value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            registry_value, _ = winreg.QueryValueEx(key, name)
            return str(registry_value)
    except Exception:
        return ""


def resolve_deepseek_model(
    *,
    explicit_model: str | None = None,
    read_secret_fn: SecretReader = read_secret,
) -> str:
    model = str(explicit_model or "").strip()
    if model:
        return model
    return str(read_secret_fn("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL).strip() or DEFAULT_DEEPSEEK_MODEL


def resolve_deepseek_tier_model(
    *,
    tier: str,
    explicit_model: str | None = None,
    read_secret_fn: SecretReader = read_secret,
) -> str:
    """Resolve the model for a quality tier.

    `DEEPSEEK_MODEL` remains the legacy Pro/default override. Flash and Pro can
    be configured independently with `DEEPSEEK_FLASH_MODEL` and
    `DEEPSEEK_PRO_MODEL` so cost routing does not accidentally collapse back to
    one global model.
    """
    model = str(explicit_model or "").strip()
    if model:
        return model
    normalized = normalize_deepseek_model_tier(tier)
    if normalized == "flash":
        return (
            str(read_secret_fn("DEEPSEEK_FLASH_MODEL") or DEFAULT_DEEPSEEK_FLASH_MODEL).strip()
            or DEFAULT_DEEPSEEK_FLASH_MODEL
        )
    return (
        str(read_secret_fn("DEEPSEEK_PRO_MODEL") or read_secret_fn("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_PRO_MODEL).strip()
        or DEFAULT_DEEPSEEK_PRO_MODEL
    )


def normalize_deepseek_model_tier(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text in {"flash", "fast", "cheap", "economy", "lite"}:
        return "flash"
    if text in {"pro", "quality", "reasoning", "deep"}:
        return "pro"
    return "pro"


def resolve_deepseek_base_url(
    *,
    explicit_base_url: str | None = None,
    read_secret_fn: SecretReader = read_secret,
) -> str:
    base_url = str(explicit_base_url or "").strip()
    if base_url:
        return base_url
    return str(read_secret_fn("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).strip() or DEFAULT_DEEPSEEK_BASE_URL


def resolve_deepseek_max_tokens(
    default: int,
    *,
    read_secret_fn: SecretReader = read_secret,
) -> int:
    return positive_int(read_secret_fn("DEEPSEEK_MAX_TOKENS"), default)


def resolve_deepseek_timeout(
    default: int = DEFAULT_DEEPSEEK_TIMEOUT_SECONDS,
    *,
    read_secret_fn: SecretReader = read_secret,
) -> int:
    return positive_int(read_secret_fn("DEEPSEEK_TIMEOUT_SECONDS"), default)


def positive_int(value: str | int | None, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return max(1, int(default))
    return parsed if parsed > 0 else max(1, int(default))
