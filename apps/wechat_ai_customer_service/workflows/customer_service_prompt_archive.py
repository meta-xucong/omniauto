from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]

SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "secret",
    "password",
    "sendkey",
    "x-api-key",
)

DEFAULT_ARCHIVE_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "include_image_prompts": False,
    "include_image_results": False,
    "include_visual_bridge": False,
    "include_visual_brain_prompts": False,
    "include_brain_prompts": True,
    "include_all_brain_prompts": False,
}


def _truthy(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _nested_mapping(source: Mapping[str, Any] | None, key: str) -> Mapping[str, Any] | None:
    if not isinstance(source, Mapping):
        return None
    value = source.get(key)
    return value if isinstance(value, Mapping) else None


def prompt_archive_settings(
    *,
    config: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(DEFAULT_ARCHIVE_SETTINGS)

    local_settings = _nested_mapping(config, "_local_customer_service_settings")
    for candidate in (
        _nested_mapping(config, "prompt_archive"),
        _nested_mapping(local_settings, "prompt_archive"),
        _nested_mapping(settings, "prompt_archive"),
    ):
        if candidate:
            merged.update(dict(candidate))

    enabled_env = os.getenv("CUSTOMER_SERVICE_PROMPT_ARCHIVE_ENABLED")
    if enabled_env is not None:
        merged["enabled"] = _truthy(enabled_env, default=bool(merged.get("enabled", True)))

    root_env = os.getenv("CUSTOMER_SERVICE_PROMPT_ARCHIVE_ROOT")
    if root_env:
        merged["root_path"] = root_env

    return merged


def _active_tenant_id() -> str:
    for env_name in ("WECHAT_KNOWLEDGE_TENANT", "OMNIAUTO_TENANT"):
        value = os.getenv(env_name)
        if value:
            return str(value).strip() or "default"

    try:
        from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id

        return str(active_tenant_id()).strip() or "default"
    except Exception:
        return "default"


def _tenant_runtime_root(tenant_id: str) -> Path:
    try:
        from apps.wechat_ai_customer_service.knowledge_paths import tenant_runtime_root

        return Path(tenant_runtime_root(tenant_id))
    except Exception:
        return PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "tenants" / tenant_id


def _archive_root(*, tenant_id: str, archive_settings: Mapping[str, Any]) -> Path:
    configured = archive_settings.get("root_path") or archive_settings.get("path")
    if configured:
        path = Path(str(configured))
        return path if path.is_absolute() else PROJECT_ROOT / path
    return _tenant_runtime_root(tenant_id) / "customer_service" / "prompt_archive"


def _is_secret_key(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("_", "-")
    return any(fragment.replace("_", "-") in normalized for fragment in SECRET_KEY_FRAGMENTS)


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 24:
        return "<max_depth>"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if _is_secret_key(text_key):
                safe[text_key] = "<redacted>"
            else:
                safe[text_key] = _json_safe(item, depth=depth + 1)
        return safe
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item, depth=depth + 1) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _kind_enabled(kind: str, archive_settings: Mapping[str, Any]) -> bool:
    # An image can only exist during the current clipboard transaction.  These
    # event types were created for the retired file-backed image pipeline and
    # must stay non-persistent even if an old local setting enables them.
    if kind in {"customer_image_understanding_prompt", "customer_image_understanding_retry_prompt"}:
        return False
    if kind in {"customer_image_understanding_result", "customer_image_understanding_error"}:
        return False
    if kind == "customer_image_turn_bridge":
        return False
    if kind == "customer_service_brain_prompt":
        return _truthy(archive_settings.get("include_brain_prompts"), default=True)
    return True


def should_archive_brain_prompt(
    *,
    settings: Mapping[str, Any] | None = None,
    brain_input: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> bool:
    archive_settings = prompt_archive_settings(config=config, settings=settings)
    if not _truthy(archive_settings.get("enabled"), default=True):
        return False
    if not _truthy(archive_settings.get("include_brain_prompts"), default=True):
        return False
    current_message = _nested_mapping(brain_input, "current_message")
    if current_message and current_message.get("visual_bridge_input"):
        # A visual bridge is the text consequence of an ephemeral clipboard
        # image.  Do not archive the expanded Brain prompt for this turn.
        return False
    return _truthy(archive_settings.get("include_all_brain_prompts"), default=False)


def archive_prompt_event(
    kind: str,
    payload: Mapping[str, Any] | None = None,
    *,
    tenant_id: str | None = None,
    config: Mapping[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        archive_settings = prompt_archive_settings(config=config, settings=settings)
        if not _truthy(archive_settings.get("enabled"), default=True):
            return {"ok": True, "archived": False, "reason": "disabled"}
        if not _kind_enabled(kind, archive_settings):
            return {"ok": True, "archived": False, "reason": "kind_disabled"}

        resolved_tenant_id = (tenant_id or _active_tenant_id() or "default").strip() or "default"
        root = _archive_root(tenant_id=resolved_tenant_id, archive_settings=archive_settings)
        root.mkdir(parents=True, exist_ok=True)

        now = datetime.now().astimezone()
        event = {
            "schema_version": 1,
            "created_at": now.isoformat(),
            "kind": str(kind),
            "tenant_id": resolved_tenant_id,
            "payload": _json_safe(payload or {}),
        }
        archive_path = root / f"{now.strftime('%Y%m%d')}.jsonl"
        with archive_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")
        return {"ok": True, "archived": True, "path": str(archive_path)}
    except Exception as exc:
        return {"ok": False, "archived": False, "error": str(exc)}
