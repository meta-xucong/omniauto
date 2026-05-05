"""Visible platform safety-rule loading for WeChat customer-service runtime."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parents[1]
DEFAULT_PLATFORM_SAFETY_RULES_PATH = APP_ROOT / "configs" / "platform_safety_rules.example.json"


def resolve_platform_safety_rules_path(settings: dict[str, Any] | None = None) -> Path:
    settings = settings or {}
    explicit = str(settings.get("platform_safety_rules_path") or "").strip()
    env_value = os.environ.get("WECHAT_PLATFORM_SAFETY_RULES_PATH", "").strip()
    raw = explicit or env_value or str(DEFAULT_PLATFORM_SAFETY_RULES_PATH)
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def load_platform_safety_rules(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    path = resolve_platform_safety_rules_path(settings)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"ok": False, "path": str(path), "error": "platform_safety_rules_file_missing", "item": empty_rules()}
    except Exception as exc:
        return {"ok": False, "path": str(path), "error": repr(exc), "item": empty_rules()}
    if not isinstance(payload, dict):
        return {"ok": False, "path": str(path), "error": "platform_safety_rules_not_object", "item": empty_rules()}
    item = normalize_platform_safety_rules(payload)
    item["_path"] = str(path)
    return {"ok": True, "path": str(path), "item": item}


def save_platform_safety_rules(payload: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    path = resolve_platform_safety_rules_path(settings)
    item = normalize_platform_safety_rules(payload)
    item.pop("_path", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "path": str(path), "item": item}


def normalize_platform_safety_rules(payload: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(payload)
    item.setdefault("schema_version", 1)
    item.setdefault("title", "平台底线规则")
    item.setdefault("description", "所有客户通用的自动回复安全边界。行业专属规则不应写在这里。")
    item.setdefault("prompt_rules", [])
    item.setdefault("guard_terms", {})
    item["prompt_rules"] = normalize_prompt_rules(item.get("prompt_rules"))
    item["guard_terms"] = normalize_guard_terms(item.get("guard_terms"))
    return item


def empty_rules() -> dict[str, Any]:
    return normalize_platform_safety_rules({"schema_version": 1, "prompt_rules": [], "guard_terms": {}})


def normalize_prompt_rules(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rules: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            continue
        instruction = str(raw.get("instruction") or raw.get("description") or "").strip()
        if not instruction:
            continue
        rules.append(
            {
                "id": str(raw.get("id") or f"rule_{index + 1}").strip(),
                "title": str(raw.get("title") or raw.get("id") or f"规则 {index + 1}").strip(),
                "description": str(raw.get("description") or "").strip(),
                "instruction": instruction,
                "enabled": raw.get("enabled", True) is not False,
            }
        )
    return rules


def normalize_guard_terms(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, raw in value.items():
        if isinstance(raw, list):
            normalized[str(key)] = [str(item).strip() for item in raw if str(item).strip()]
        elif isinstance(raw, dict):
            normalized[str(key)] = normalize_guard_terms(raw)
    return normalized


def enabled_prompt_instructions(rules: dict[str, Any]) -> list[str]:
    return [
        str(item.get("instruction") or "").strip()
        for item in rules.get("prompt_rules", []) or []
        if isinstance(item, dict) and item.get("enabled", True) is not False and str(item.get("instruction") or "").strip()
    ]


def guard_term_set(rules: dict[str, Any], name: str) -> set[str]:
    terms = rules.get("guard_terms", {}) if isinstance(rules.get("guard_terms"), dict) else {}
    value = terms.get(name, [])
    if not isinstance(value, list):
        return set()
    return {str(item).strip() for item in value if str(item).strip()}
