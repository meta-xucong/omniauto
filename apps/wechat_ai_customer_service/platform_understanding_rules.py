"""Visible platform understanding dictionaries for WeChat customer-service runtime."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parents[1]
DEFAULT_PLATFORM_UNDERSTANDING_RULES_PATH = APP_ROOT / "configs" / "platform_understanding_rules.example.json"


def resolve_platform_understanding_rules_path(settings: dict[str, Any] | None = None) -> Path:
    settings = settings or {}
    explicit = str(settings.get("platform_understanding_rules_path") or "").strip()
    env_value = os.environ.get("WECHAT_PLATFORM_UNDERSTANDING_RULES_PATH", "").strip()
    raw = explicit or env_value or str(DEFAULT_PLATFORM_UNDERSTANDING_RULES_PATH)
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def load_platform_understanding_rules(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    path = resolve_platform_understanding_rules_path(settings)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"ok": False, "path": str(path), "error": "platform_understanding_rules_file_missing", "item": empty_rules()}
    except Exception as exc:
        return {"ok": False, "path": str(path), "error": repr(exc), "item": empty_rules()}
    if not isinstance(payload, dict):
        return {"ok": False, "path": str(path), "error": "platform_understanding_rules_not_object", "item": empty_rules()}
    item = normalize_platform_understanding_rules(payload)
    item["_path"] = str(path)
    return {"ok": True, "path": str(path), "item": item}


def save_platform_understanding_rules(payload: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    path = resolve_platform_understanding_rules_path(settings)
    item = normalize_platform_understanding_rules(payload)
    item.pop("_path", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return {"ok": True, "path": str(path), "item": item}


def normalize_platform_understanding_rules(payload: dict[str, Any]) -> dict[str, Any]:
    item = copy.deepcopy(payload)
    item.setdefault("schema_version", 1)
    item.setdefault("title", "平台通用理解词典")
    item.setdefault("description", "所有客户通用的基础意图、检索和归类词典。行业专属业务规则不应写在这里。")
    item["intent_keywords"] = normalize_map_of_string_lists(item.get("intent_keywords"))
    item["intent_groups"] = normalize_map_of_string_lists(item.get("intent_groups"))
    item["policy_type_to_intent"] = normalize_string_map(item.get("policy_type_to_intent"))
    item["policy_tags"] = normalize_string_map(item.get("policy_tags"))
    item["policy_type_tags"] = normalize_map_of_string_lists(item.get("policy_type_tags"))
    item["policy_key_tags"] = normalize_map_of_string_lists(item.get("policy_key_tags"))
    item["product_knowledge_keywords"] = normalize_map_of_string_lists(item.get("product_knowledge_keywords"))
    item["semantic_equivalents"] = normalize_map_of_string_lists(item.get("semantic_equivalents"))
    item["rag"] = normalize_map_of_string_lists(item.get("rag"))
    item["risk_keywords"] = normalize_map_of_string_lists(item.get("risk_keywords"))
    item["customer_data_field_labels"] = normalize_map_of_string_lists(item.get("customer_data_field_labels"))
    item["quantity_units"] = normalize_string_list(item.get("quantity_units"))
    return item


def empty_rules() -> dict[str, Any]:
    return normalize_platform_understanding_rules({"schema_version": 1})


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def normalize_map_of_string_lists(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    return {str(key).strip(): normalize_string_list(raw) for key, raw in value.items() if str(key).strip()}


def normalize_string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, raw in value.items():
        clean_key = str(key).strip()
        clean_value = str(raw).strip()
        if clean_key and clean_value:
            result[clean_key] = clean_value
    return result


def platform_understanding_item(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    return load_platform_understanding_rules(settings).get("item", {})


def string_list(name: str, settings: dict[str, Any] | None = None) -> list[str]:
    item = platform_understanding_item(settings)
    return list(item.get(name, []) or []) if isinstance(item.get(name), list) else []


def string_set(name: str, settings: dict[str, Any] | None = None) -> set[str]:
    return set(string_list(name, settings=settings))


def map_of_lists(name: str, settings: dict[str, Any] | None = None) -> dict[str, list[str]]:
    item = platform_understanding_item(settings)
    value = item.get(name, {})
    return normalize_map_of_string_lists(value)


def string_map(name: str, settings: dict[str, Any] | None = None) -> dict[str, str]:
    item = platform_understanding_item(settings)
    return normalize_string_map(item.get(name, {}))


def intent_keywords(settings: dict[str, Any] | None = None) -> dict[str, list[str]]:
    return map_of_lists("intent_keywords", settings=settings)


def intent_group(name: str, settings: dict[str, Any] | None = None) -> set[str]:
    groups = map_of_lists("intent_groups", settings=settings)
    return set(groups.get(name, []) or [])


def product_keywords(name: str, settings: dict[str, Any] | None = None) -> list[str]:
    groups = map_of_lists("product_knowledge_keywords", settings=settings)
    return list(groups.get(name, []) or [])


def rag_terms(name: str, settings: dict[str, Any] | None = None) -> set[str]:
    groups = map_of_lists("rag", settings=settings)
    return set(groups.get(name, []) or [])


def risk_keywords(name: str, settings: dict[str, Any] | None = None) -> list[str]:
    groups = map_of_lists("risk_keywords", settings=settings)
    return list(groups.get(name, []) or [])


def semantic_equivalents(settings: dict[str, Any] | None = None) -> dict[str, tuple[str, ...]]:
    return {key: tuple(values) for key, values in map_of_lists("semantic_equivalents", settings=settings).items()}


def quantity_unit_pattern(settings: dict[str, Any] | None = None) -> str:
    units = string_list("quantity_units", settings=settings)
    if not units:
        return r"个|件|台|套|箱"
    return "|".join(sorted((escape_regex(item) for item in units), key=len, reverse=True))


def escape_regex(value: str) -> str:
    import re

    return re.escape(str(value))
