"""DeepSeek API connection test for the WeChat customer-service LLM provider.

The script reads the API key from ``DEEPSEEK_API_KEY``. It never accepts an API
key as a command-line argument, so secrets do not end up in shell history or
workflow audit files.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any
try:
    import winreg
except ImportError:  # pragma: no cover - Windows-only fallback.
    winreg = None


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--model", default=os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL))
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    result = test_connection(base_url=args.base_url, model=args.model, timeout=args.timeout)
    print_json(result)
    return 0 if result.get("ok") else 1


def test_connection(base_url: str, model: str, timeout: int = 30) -> dict[str, Any]:
    api_key = read_secret("DEEPSEEK_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "DEEPSEEK_API_KEY is not set",
            "base_url": base_url,
            "model": model,
        }

    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a connection test endpoint."},
            {"role": "user", "content": "Reply with exactly: pong"},
        ],
        "temperature": 0,
        "max_tokens": 8,
        "stream": False,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
            raw = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return {
                "ok": True,
                "base_url": base_url,
                "model": model,
                "status": response.status,
                "response_text": content,
                "usage": data.get("usage", {}),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "base_url": base_url,
            "model": model,
            "status": exc.code,
            "error": summarize_error_body(body),
        }
    except Exception as exc:
        return {
            "ok": False,
            "base_url": base_url,
            "model": model,
            "error": repr(exc),
        }


def summarize_error_body(body: str) -> Any:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body[:500]
    return payload


def read_secret(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    if winreg is None:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value)
    except OSError:
        return ""


def print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
