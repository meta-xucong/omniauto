from __future__ import annotations

import ast
import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.optional_plugins.vision import (  # noqa: E402
    VisionHostPorts,
    create_vision_service,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.capture.wechat import (  # noqa: E402
    image_bubble_visual_fingerprint,
    session_split_x,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.errors import (  # noqa: E402
    VISION_IMAGE_CLIPBOARD_CLEAR_FAILED,
)
from apps.wechat_ai_customer_service.adapters.wechat_pr28_runtime_adapter import (  # noqa: E402
    PR28_BLOBS,
)


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(
            f"{message}: expected {expected!r}, got {actual!r}"
        )


def _source(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def _module(relative: str) -> ast.Module:
    return ast.parse(_source(relative), filename=relative)


def check_public_api_import_is_lightweight() -> None:
    code = (
        "import json,sys; "
        "from apps.wechat_ai_customer_service.optional_plugins.vision.api import create_vision_service; "
        "print(json.dumps({'pil': 'PIL' in sys.modules, 'clipboard': 'win32clipboard' in sys.modules, "
        "'voice': any('optional_plugins.voice' in name for name in sys.modules)}))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(completed.stdout)
    assert_true(result == {"pil": False, "clipboard": False, "voice": False}, f"public API loaded optional dependencies: {result}")


def check_legacy_paths_are_logic_free_aliases() -> None:
    facades = (
        "apps/wechat_ai_customer_service/workflows/customer_image_understanding_contract.py",
        "apps/wechat_ai_customer_service/workflows/customer_image_understanding_provider.py",
        "apps/wechat_ai_customer_service/workflows/customer_image_understanding.py",
        "apps/wechat_ai_customer_service/workflows/customer_image_brain_bridge.py",
        "apps/wechat_ai_customer_service/workflows/customer_image_catalog_assist.py",
        "apps/wechat_ai_customer_service/workflows/customer_image_asset_store.py",
        "apps/wechat_ai_customer_service/workflows/customer_image_turn_router.py",
        "apps/wechat_ai_customer_service/internal/scheduler/vision_bridge.py",
        "apps/wechat_ai_customer_service/vehicle_image_retrieval_integration.py",
        "apps/wechat_ai_customer_service/vehicle_image_retrieval_jobs.py",
        "apps/wechat_ai_customer_service/optional_plugins/vehicle_image_retrieval/plugin.py",
        "apps/wechat_ai_customer_service/optional_plugins/vehicle_image_retrieval/descriptor.py",
        "apps/wechat_ai_customer_service/optional_plugins/vehicle_image_retrieval/fingerprint.py",
        "packages/vehicle_image_retrieval/service.py",
    )
    for relative in facades:
        tree = _module(relative)
        implementations = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        assert_true(not implementations, f"legacy facade retains implementation: {relative}")


def _function(relative: str, name: str) -> ast.FunctionDef:
    for node in ast.walk(_module(relative)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function missing: {relative}:{name}")


def check_pr28_blobs_and_legacy_vision_paths_are_quarantined() -> None:
    for relative, expected in PR28_BLOBS.items():
        completed = subprocess.run(
            ["git", "hash-object", "--", relative],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert_true(
            completed.stdout.strip() == expected,
            f"controlled PR #28 baseline file changed: {relative}",
        )

    connector = "apps/wechat_ai_customer_service/adapters/wechat_connector.py"
    sidecar = _source("apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py")
    assert_true(
        "def self_visual_image_messages_from_current_surface(" not in sidecar
        and "wechat_image_save_capture" not in sidecar
        and "detect_visual_image_bubbles" not in sidecar
        and "extract_chat_time_markers" not in sidecar,
        "Sidecar retains a retired image export or image-module import",
    )
    connector_source = _source(connector)
    assert_true(
        "target_not_confirmed_for_image_save" not in connector_source,
        "Connector retains the retired image-only identity state",
    )
    integration = _source(
        "apps/wechat_ai_customer_service/optional_plugins/vision/integrations/wechat_current.py"
    )
    assert_true("call_compat_sidecar" not in integration, "production vision still calls a Sidecar image action")
    assert_true("image-clipboard-copy" not in integration, "retired Sidecar image action remains in production vision")
    worker = _source(
        "apps/wechat_ai_customer_service/optional_plugins/vision/integrations/wechat_worker.py"
    )
    assert_true("execute_wechat_clipboard_image_copy" in worker, "vision worker does not own clipboard copy")
    assert_true("visual_image_messages_from_current_surface" in worker, "vision worker does not own surface observation")
    runtime_adapter = _source(
        "apps/wechat_ai_customer_service/adapters/wechat_pr28_runtime_adapter.py"
    )
    assert_true(
        "pr28_legacy_image_entry_quarantined" not in runtime_adapter
        and "run_customer_clipboard_image_transaction" not in runtime_adapter
        and "run_self_clipboard_image_transaction" not in runtime_adapter,
        "retired PR image entry remains in the host adapter",
    )
    capture_method = _function(
        "apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py",
        "_capture_session",
    )
    capture_source = ast.get_source_segment(
        _source("apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py"),
        capture_method,
    ) or ""
    assert_true("prepare_vision_scheduler_capture" in capture_source, "scheduler does not use the vision-owned capture bridge")
    for forbidden in (
        "observe_current_vision_surface",
        "resolve_pending_visual_occurrence(",
        "confirmed_customer_image_placeholder(",
        "explicit_image_pending",
    ):
        assert_true(forbidden not in capture_source, f"scheduler still owns image orchestration: {forbidden}")
    plan_method = _function(
        "apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py",
        "_plan_reply",
    )
    plan_source = ast.get_source_segment(
        _source("apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py"),
        plan_method,
    ) or ""
    assert_true(
        "run_customer_clipboard_image_transaction" not in plan_source,
        "production planner still discovers the immutable PR image transaction",
    )


def check_retired_file_and_crop_routes_have_no_live_implementation() -> None:
    relative = "apps/wechat_ai_customer_service/optional_plugins/vision/capture/wechat.py"
    for name in (
        "file_sha256",
        "image_dimensions",
        "wait_for_file_stable",
        "save_visual_bubble_crop",
        "save_clipboard_image_to_path",
        "build_saved_image_asset",
        "build_image_saved_payload",
        "build_visual_bubble_archive_payload",
        "execute_wechat_image_save",
    ):
        assert_true(
            f"def {name}(" not in _source(relative),
            f"retired image export remains reachable: {name}",
        )


def check_dependency_direction_and_single_owner() -> None:
    service_tree = _module("apps/wechat_ai_customer_service/optional_plugins/vision/service.py")
    top_imports = [node for node in service_tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    rendered = "\n".join(ast.unparse(node) for node in top_imports)
    forbidden = ("scheduler", "brain", "ledger", "wechat_connector", "sidecar", "optional_plugins.voice", "PIL", "win32clipboard")
    assert_true(not any(item in rendered for item in forbidden), f"vision service has concrete top-level dependency: {rendered}")
    plugin_source = _source("apps/wechat_ai_customer_service/optional_plugins/vision/plugin.py")
    assert_true("workflows.customer_image" not in plugin_source, "vision plugin still imports legacy workflow implementation")
    vision_source = "\n".join(path.read_text(encoding="utf-8") for path in (APP_ROOT / "optional_plugins" / "vision").rglob("*.py"))
    assert_true("optional_plugins.voice" not in vision_source, "vision imports the voice implementation")
    core_source = _source("apps/wechat_ai_customer_service/optional_plugins/vision/vehicle_retrieval/core.py")
    assert_true("apps.wechat_ai_customer_service" not in core_source and "PIL" not in core_source, "portable retrieval core depends on host or image IO")


def check_core_uses_only_neutral_optional_capability_dispatch() -> None:
    """Core may consume existing visual payloads but cannot import Vision code."""

    core_relatives = (
        "apps/wechat_ai_customer_service/workflows/customer_service_brain.py",
        "apps/wechat_ai_customer_service/workflows/listen_and_reply.py",
        "apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py",
        "apps/wechat_ai_customer_service/internal/scheduler/vision_bridge.py",
    )
    for relative in core_relatives:
        source = _source(relative)
        assert_true(
            "optional_plugins.vision" not in source,
            f"core imports a concrete Vision implementation: {relative}",
        )

    runtime = _source("apps/wechat_ai_customer_service/optional_plugins/vision/runtime.py")
    for forbidden in (
        "connector.run_customer_clipboard_image_transaction",
        "connector.run_self_clipboard_image_transaction",
    ):
        assert_true(
            forbidden not in runtime,
            f"Vision runtime still delegates its transaction to Connector: {forbidden}",
        )

    plugin = _source("apps/wechat_ai_customer_service/optional_plugins/vision/plugin.py")
    assert_true(
        "def invoke(" in plugin,
        "the built-in Vision plugin does not expose its supplemental operations through the neutral dispatcher",
    )


class _TargetPort:
    def confirm_target(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "target": str(context.get("target_name") or "Customer A"), "session_key": str(context.get("session_key") or "wx:port")}


class _FramePort:
    def __init__(self) -> None:
        self.surface = Image.new("RGB", (980, 860), (247, 247, 247))
        draw = ImageDraw.Draw(self.surface)
        split = session_split_x(980)
        draw.rectangle([0, 0, split, 860], fill=(240, 240, 240))
        draw.rectangle([split + 12, 90, 972, 760], fill=(255, 255, 255))
        draw.rectangle([split + 42, 260, split + 282, 480], fill=(30, 120, 190))

    def capture_frame(self, context: dict[str, Any]) -> dict[str, Any]:
        if context.get("phase") == "image_context_menu":
            return {
                "ok": True,
                "image": self.surface,
                "ocr_items": [{"text": "复制", "left": 600, "top": 488, "right": 636, "bottom": 508, "center_x": 618, "center_y": 498, "confidence": 0.95}],
            }
        return {"ok": True, "image": self.surface, "messages": [], "ocr_items": []}


class _ActionPort:
    def __init__(self) -> None:
        self.actions: list[tuple[str, int, int]] = []

    def right_click(self, x: int, y: int) -> None:
        self.actions.append(("right_click", x, y))

    def click(self, x: int, y: int) -> None:
        self.actions.append(("click", x, y))


class _ClipboardPort:
    def __init__(self) -> None:
        self.sequences = [10, 11]

    def sequence_number(self) -> int:
        return self.sequences.pop(0)

    def read_current_bitmap(self) -> Image.Image:
        return Image.new("RGB", (120, 80), (40, 130, 210))


class _StrictFramePort:
    def __init__(self) -> None:
        self.surface = Image.new("RGB", (980, 860), (247, 247, 247))
        draw = ImageDraw.Draw(self.surface)
        draw.rectangle([410, 260, 650, 480], fill=(30, 120, 190))
        self.bounds = [410, 260, 650, 480]
        self.fingerprint = image_bubble_visual_fingerprint(
            self.surface,
            tuple(self.bounds),
        )

    def capture_frame(self, context: dict[str, Any]) -> dict[str, Any]:
        if context.get("phase") == "image_context_menu":
            return {
                "ok": True,
                "image": self.surface.copy(),
                "image_size": self.surface.size,
                "screen_origin": [0, 0],
                "ocr_items": [
                    {
                        "text": "复制",
                        "left": 660,
                        "top": 430,
                        "right": 710,
                        "bottom": 458,
                        "center_x": 685,
                        "center_y": 444,
                        "confidence": 0.98,
                        "bounds": [660, 430, 710, 458],
                    }
                ],
            }
        return {
            "ok": True,
            "image": self.surface.copy(),
            "image_size": self.surface.size,
            "screen_origin": [0, 0],
            "messages": [
                {
                    "type": "image",
                    "bounds": list(self.bounds),
                    "anchor": {"x": 530, "y": 370},
                    "image_physical_anchor": {
                        "sender_role": "customer",
                        "visual_side": "customer",
                        "bubble_visual_fingerprint": self.fingerprint,
                        "preceding_stable_message": "",
                        "following_stable_message": "",
                        "occurrence_index": 0,
                        "occurrence_count": 1,
                    },
                }
            ],
        }


class _StrictClipboardPort:
    def __init__(self, frame: _StrictFramePort, *, clear_ok: bool = False) -> None:
        self.frame = frame
        self.clear_ok = clear_ok
        self.sequence_calls = 0

    def sequence_number(self) -> int:
        self.sequence_calls += 1
        return 10 if self.sequence_calls == 1 else 11

    def read_current_bitmap(self) -> Image.Image:
        return self.frame.surface.crop(tuple(self.frame.bounds))

    def clear_current(self, expected_sequence: int) -> dict[str, Any]:
        assert_equal(expected_sequence, 11, "strict cleanup must bind to the copied generation")
        if self.clear_ok:
            return {"ok": True}
        return {"ok": False, "reason": "clipboard_clear_failed"}


class _ProviderPort:
    def __init__(self) -> None:
        self.image: Any = None

    def understand(self, request: dict[str, Any]) -> dict[str, Any]:
        self.image = request.get("image")
        assert_true(self.image is not None and not self.image.released, "provider must receive a live in-memory image")
        return {
            "applied": True,
            "adoptable": True,
            "reason": "test_provider_ready",
            "vision_summary": "一辆蓝色汽车",
            "classification": {"is_vehicle": True, "vehicle_confidence": 0.92},
        }


class _LeasePort:
    @contextmanager
    def lease(self, action: str, *, timeout_seconds: float):
        assert_true(action == "vision_current_image" and timeout_seconds > 0, "vision must request its own bounded RPA lease")
        yield {"acquired": True}


def check_direct_ports_run_complete_ephemeral_transaction() -> None:
    provider = _ProviderPort()
    action = _ActionPort()
    service = create_vision_service(
        ports=VisionHostPorts(
            rpa_lease=_LeasePort(),
            conversation_target=_TargetPort(),
            window_frame=_FramePort(),
            ui_action=action,
            clipboard=_ClipboardPort(),
            vision_provider=provider,
        )
    )
    result = service.inspect_current_conversation(
        {
            "target_name": "Customer A",
            "session_key": "wx:port",
            "pending_signal_id": "image-port-1",
            "side_filter": "customer",
        }
    )
    assert_true(result.get("applied") is True and result.get("adoptable") is True, f"direct ports did not complete: {result}")
    assert_true([item[0] for item in action.actions] == ["right_click", "click"], f"unexpected UI transaction: {action.actions}")
    assert_true(provider.image is not None and provider.image.released, "image memory must be zeroized before API returns")
    serialized = json.dumps(result, ensure_ascii=False)
    assert_true("image_bytes" not in serialized and "saved_image_path" not in serialized, "public result leaked image material")


def check_strict_transaction_fails_closed_when_clipboard_clear_fails() -> None:
    frame = _StrictFramePort()
    provider = _ProviderPort()
    service = create_vision_service(
        ports=VisionHostPorts(
            rpa_lease=_LeasePort(),
            conversation_target=_TargetPort(),
            window_frame=frame,
            ui_action=_ActionPort(),
            clipboard=_StrictClipboardPort(frame),
            vision_provider=provider,
        ),
        config={"strict_image_adapter": True},
    )
    result = service.inspect_current_conversation(
        {
            "target_name": "Customer A",
            "session_key": "wx:strict-port",
            "pending_signal_id": "image-port-strict-1",
            "sender_role": "customer",
            "bubble_rect": list(frame.bounds),
            "image_physical_anchor": {
                "sender_role": "customer",
                "visual_side": "customer",
                "bubble_visual_fingerprint": frame.fingerprint,
                "preceding_stable_message": "",
                "following_stable_message": "",
                "occurrence_index": 0,
                "occurrence_count": 1,
            },
            "config": {"strict_image_adapter": True},
        }
    )
    assert_equal(result.get("applied"), False, "cleanup failure must not report Vision success")
    assert_equal(result.get("reason"), VISION_IMAGE_CLIPBOARD_CLEAR_FAILED, "cleanup failure must retain its stable reason")
    assert_true(provider.image is None, "provider must not run after clipboard cleanup failure")


def check_strict_transaction_completes_and_releases_image_memory() -> None:
    frame = _StrictFramePort()
    provider = _ProviderPort()
    action = _ActionPort()
    service = create_vision_service(
        ports=VisionHostPorts(
            rpa_lease=_LeasePort(),
            conversation_target=_TargetPort(),
            window_frame=frame,
            ui_action=action,
            clipboard=_StrictClipboardPort(frame, clear_ok=True),
            vision_provider=provider,
        ),
        config={
            "strict_image_adapter": True,
            "image_contract": {
                "schemas": {
                    "customer_image_understanding_v1": {
                        "type": "object",
                        "properties": {
                            "applied": {"type": "boolean"},
                            "adoptable": {"type": "boolean"},
                            "reason": {"type": "string"},
                            "vision_summary": {"type": "string", "minLength": 1},
                            "classification": {"type": "object"},
                        },
                        "required": ["applied", "adoptable", "vision_summary"],
                    },
                    "visual_bridge_input_v1": {
                        "type": "object",
                        "properties": {
                            "schema_version": {"type": "integer"},
                            "present": {"type": "boolean"},
                            "vision_summary": {"type": "string"},
                        },
                        "required": ["schema_version", "present", "vision_summary"],
                    },
                }
            },
        },
    )
    result = service.inspect_current_conversation(
        {
            "target_name": "Customer A",
            "session_key": "wx:strict-port-success",
            "pending_signal_id": "image-port-strict-success-1",
            "sender_role": "customer",
            "bubble_rect": list(frame.bounds),
            "image_physical_anchor": {
                "sender_role": "customer",
                "visual_side": "customer",
                "bubble_visual_fingerprint": frame.fingerprint,
                "preceding_stable_message": "",
                "following_stable_message": "",
                "occurrence_index": 0,
                "occurrence_count": 1,
            },
            "config": {"strict_image_adapter": True},
        }
    )
    assert_true(result.get("applied") is True and result.get("adoptable") is True, f"strict transaction did not complete: {result}")
    assert_true([item[0] for item in action.actions] == ["right_click", "click"], f"strict transaction repeated UI actions: {action.actions}")
    assert_true(provider.image is not None and provider.image.released, "strict transaction must release image memory before returning")


def main() -> int:
    checks = [
        check_public_api_import_is_lightweight,
        check_legacy_paths_are_logic_free_aliases,
        check_pr28_blobs_and_legacy_vision_paths_are_quarantined,
        check_retired_file_and_crop_routes_have_no_live_implementation,
        check_dependency_direction_and_single_owner,
        check_core_uses_only_neutral_optional_capability_dispatch,
        check_direct_ports_run_complete_ephemeral_transaction,
        check_strict_transaction_fails_closed_when_clipboard_clear_fails,
        check_strict_transaction_completes_and_releases_image_memory,
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
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
