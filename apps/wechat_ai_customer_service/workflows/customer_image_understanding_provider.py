from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    from llm_output_adapter import parse_llm_json_object
except Exception:  # pragma: no cover - script mode fallback
    from apps.wechat_ai_customer_service.workflows.llm_output_adapter import parse_llm_json_object  # type: ignore


DEFAULT_MAX_TOKENS = 1800
DEFAULT_TEMPERATURE = 0.1


def data_url_from_image_path(path: str | Path) -> str:
    image_path = Path(path)
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def anthropic_image_part(path: str | Path) -> dict[str, Any]:
    image_path = Path(path)
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime_type,
            "data": encoded,
        },
    }


def build_openai_chat_vision_payload(
    *,
    model: str,
    prompt: str,
    image_paths: list[str],
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> dict[str, Any]:
    content = [{"type": "text", "text": str(prompt or "")}]
    for path in image_paths:
        if not str(path).strip():
            continue
        content.append({"type": "image_url", "image_url": {"url": data_url_from_image_path(path)}})
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max(64, int(max_tokens or DEFAULT_MAX_TOKENS)),
        "temperature": float(temperature),
        "stream": False,
    }


def build_anthropic_messages_vision_payload(
    *,
    model: str,
    prompt: str,
    image_paths: list[str],
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> dict[str, Any]:
    content = [{"type": "text", "text": str(prompt or "")}]
    for path in image_paths:
        if not str(path).strip():
            continue
        content.append(anthropic_image_part(path))
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max(64, int(max_tokens or DEFAULT_MAX_TOKENS)),
        "temperature": float(temperature),
    }


def extract_openai_response_text(data: dict[str, Any]) -> str:
    choice = ((data.get("choices") or [{}])[0] if isinstance(data, dict) else {}) or {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("content") or "").strip()
            if text:
                texts.append(text)
        return "\n".join(texts).strip()
    return ""


def extract_anthropic_response_text(data: dict[str, Any]) -> str:
    items = data.get("content") if isinstance(data, dict) else []
    texts: list[str] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("content") or "").strip()
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def provider_response_diagnostics(data: dict[str, Any]) -> dict[str, Any]:
    """Expose compact response shape hints without depending on hidden reasoning."""
    if not isinstance(data, dict):
        return {"shape": type(data).__name__}
    diagnostics: dict[str, Any] = {"top_keys": sorted(str(key) for key in data.keys())[:12]}
    content = data.get("content")
    if isinstance(content, list):
        diagnostics["content_types"] = [
            str(item.get("type") or ("thinking" if item.get("thinking") else "unknown"))
            for item in content
            if isinstance(item, dict)
        ][:8]
        diagnostics["thinking_chars"] = sum(
            len(str(item.get("thinking") or ""))
            for item in content
            if isinstance(item, dict)
        )
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = ((choices[0] or {}).get("message") if isinstance(choices[0], dict) else {}) or {}
        if isinstance(message, dict):
            diagnostics["message_keys"] = sorted(str(key) for key in message.keys())[:12]
            diagnostics["reasoning_chars"] = len(str(message.get("reasoning_content") or ""))
            diagnostics["content_chars"] = len(str(message.get("content") or ""))
    return diagnostics


def run_customer_image_understanding_provider(
    *,
    api_key: str,
    base_url: str,
    model: str,
    request_style: str,
    prompt: str,
    image_paths: list[str],
    timeout_seconds: int,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> dict[str, Any]:
    clean_style = str(request_style or "openai_chat_vision").strip().lower()
    if clean_style == "anthropic_messages_vision":
        payload = build_anthropic_messages_vision_payload(
            model=model,
            prompt=prompt,
            image_paths=image_paths,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        url = str(base_url or "").rstrip("/") + "/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        extractor = extract_anthropic_response_text
    else:
        payload = build_openai_chat_vision_payload(
            model=model,
            prompt=prompt,
            image_paths=image_paths,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        url = str(base_url or "").rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        extractor = extract_openai_response_text
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds or 1))) as response:
            raw = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status": int(getattr(exc, "code", 0) or 0),
            "error": body[:1200],
            "provider": "",
            "model": model,
            "request_style": clean_style,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": 0,
            "error": repr(exc),
            "provider": "",
            "model": model,
            "request_style": clean_style,
        }
    response_text = extractor(data)
    parsed = parse_llm_json_object(response_text)
    if not isinstance(parsed, dict):
        return {
            "ok": False,
            "status": 200,
            "error": "customer_image_understanding_response_not_json_object",
            "response_text": response_text[:1200],
            "response_diagnostics": provider_response_diagnostics(data),
            "model": model,
            "request_style": clean_style,
        }
    return {
        "ok": True,
        "status": 200,
        "response_text": response_text[:1200],
        "parsed": parsed,
        "model": model,
        "request_style": clean_style,
    }
