from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT, APP_ROOT / "workflows", APP_ROOT / "adapters"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.optional_plugins.registry import (  # noqa: E402
    get_optional_capability_status,
    register_optional_capability,
    reset_optional_capabilities_for_tests,
    resolve_optional_capability,
    unregister_optional_capability,
)


def assert_true(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_registry_import_is_lazy() -> None:
    reset_optional_capabilities_for_tests()
    assert_true(
        "apps.wechat_ai_customer_service.optional_plugins.voice.plugin" not in sys.modules,
        "voice implementation loaded with neutral registry",
    )
    assert_true(
        "apps.wechat_ai_customer_service.optional_plugins.vision.plugin" not in sys.modules,
        "vision implementation loaded with neutral registry",
    )
    status = get_optional_capability_status("voice")
    assert_true(status == {
        "capability": "voice",
        "registered": False,
        "loaded": False,
        "available": False,
        "error": "",
    }, f"unexpected unloaded status: {status}")


def check_voice_only_resolution_does_not_load_vision() -> None:
    reset_optional_capabilities_for_tests()
    plugin = resolve_optional_capability("voice")
    assert_true(plugin is not None and plugin.available(), "default voice plugin unavailable")
    result = plugin.should_run(
        {"payload": {"messages": [{"type": "text", "content": "你好"}]}}
    )
    assert_true(result.get("should_run") is False, f"plain text entered voice capability: {result}")
    assert_true(
        "apps.wechat_ai_customer_service.optional_plugins.vision.plugin" not in sys.modules,
        "resolving voice loaded vision implementation",
    )


def check_vision_only_implementation_has_no_voice_dependency() -> None:
    source_path = APP_ROOT / "optional_plugins" / "vision" / "plugin.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    assert_true(
        not any("optional_plugins.voice" in name for name in imports),
        f"vision plugin imports voice implementation: {imports}",
    )
    reset_optional_capabilities_for_tests()
    plugin = resolve_optional_capability("vision")
    assert_true(plugin is not None and plugin.available(), "default vision plugin unavailable")
    result = plugin.should_run(
        {
            "payload": {"messages": []},
            "pending_signal": {"pending_signal_kind": "image_capture", "pending_signal_id": "p1"},
        }
    )
    assert_true(result.get("should_run") is True, f"image signal missed by vision plugin: {result}")


def check_custom_plugins_can_replace_builtins_independently() -> None:
    class CustomPlugin:
        def __init__(self, capability: str) -> None:
            self.capability = capability
            self.name = f"custom_{capability}"

        def available(self) -> bool:
            return True

        def should_run(self, context: dict[str, Any]) -> dict[str, Any]:
            return {"should_run": True, "custom": self.capability}

        def run(self, context: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "custom": self.capability}

    reset_optional_capabilities_for_tests()
    voice = CustomPlugin("voice")
    vision = CustomPlugin("vision")
    register_optional_capability("voice", plugin=voice)
    register_optional_capability("vision", plugin=vision)
    assert_true(resolve_optional_capability("voice") is voice, "custom voice plugin was not retained")
    assert_true(resolve_optional_capability("vision") is vision, "custom vision plugin was not retained")
    unregister_optional_capability("voice")
    assert_true(resolve_optional_capability("vision") is vision, "removing voice changed vision plugin")


def check_missing_plugin_fails_closed_without_exception() -> None:
    reset_optional_capabilities_for_tests()
    register_optional_capability(
        "voice",
        factory_path="apps.wechat_ai_customer_service.optional_plugins.missing:create_plugin",
    )
    assert_true(resolve_optional_capability("voice") is None, "missing plugin unexpectedly resolved")
    status = get_optional_capability_status("voice")
    assert_true(status.get("loaded") is True, f"missing plugin attempt not recorded: {status}")
    assert_true(bool(status.get("error")), f"missing plugin error not retained: {status}")


def check_voice_win32_action_uses_injected_sidecar_primitives() -> None:
    from apps.wechat_ai_customer_service.optional_plugins.voice.win32_action import (
        execute_voice_transcribe,
    )

    class Screenshot:
        size = (980, 860)

    class FakeSidecarOps:
        def capture_wechat(self, hwnd: int, *, artifact_dir: str | None, label: str):
            return Screenshot(), f"{label}.png"

        def run_ocr(self, screenshot: Any) -> list[dict[str, Any]]:
            return []

        def get_window_geometry(self, hwnd: int) -> dict[str, Any]:
            return {"width": 980, "height": 860}

        def parse_messages_from_ocr(self, items: Any, image_size: Any, **kwargs: Any):
            return []

        def find_latest_untranscribed_voice_duration_target(
            self,
            items: Any,
            image_size: Any,
            *,
            screenshot: Any,
        ) -> None:
            return None

    result = execute_voice_transcribe(
        sidecar_ops=FakeSidecarOps(),
        hwnd=1,
        probe={"online": True},
        target="contract-target",
    )
    assert_true(
        result.get("state") == "voice_transcribe_target_not_found",
        f"voice Win32 compatibility state changed: {result}",
    )
    assert_true(result.get("messages") == [], f"voice result shape changed: {result}")


def main() -> int:
    checks = [
        check_registry_import_is_lazy,
        check_voice_only_resolution_does_not_load_vision,
        check_vision_only_implementation_has_no_voice_dependency,
        check_custom_plugins_can_replace_builtins_independently,
        check_missing_plugin_fails_closed_without_exception,
        check_voice_win32_action_uses_injected_sidecar_primitives,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - test harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            break
    failures = [item for item in results if not item.get("ok")]
    print(
        json.dumps(
            {"ok": not failures, "count": len(results), "failures": failures, "results": results},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
