from __future__ import annotations

import argparse
import ast
import importlib
import inspect
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (PROJECT_ROOT, APP_ROOT, WORKFLOWS_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


SNAPSHOT_PATH = Path(__file__).resolve().parent / "fixtures" / "customer_service_external_contract_snapshot_20260713.json"
MODULES = {
    "listen_and_reply": "listen_and_reply",
    "customer_service_scheduler": (
        "apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler"
    ),
    "customer_service_scheduler_state": (
        "apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler_state"
    ),
    "wechat_win32_ocr_sidecar": "wechat_win32_ocr_sidecar",
}
KEY_SIGNATURES = {
    "listen_and_reply": {
        "TargetConfig",
        "ReplyDecision",
        "attach_voice_transcription_audit",
        "load_config",
        "maybe_auto_transcribe_voice_messages",
        "parse_targets",
        "process_target",
        "select_batch_details",
        "voice_transcription_trigger",
    },
    "customer_service_scheduler": {
        "CustomerServiceSchedulerRuntime",
        "ManagedListenerSchedulerBridge",
        "_merge_voice_transcription_messages",
        "plan_reply_with_listen_workflow",
    },
    "customer_service_scheduler_state": {
        "SchedulerConfig",
        "SchedulerStateStore",
        "cleanup_scheduler_state",
        "enqueue_pending_session",
        "record_capture_result",
    },
    "wechat_win32_ocr_sidecar": {
        "open_voice_transcribe_context_menu",
        "parse_messages_from_ocr",
        "run_action",
        "voice_transcribe_payload",
    },
}


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


def assert_true(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def imported_symbol_names() -> dict[str, set[str]]:
    names = {key: set() for key in MODULES}
    this_file = Path(__file__).resolve()
    for path in APP_ROOT.rglob("*.py"):
        if path.resolve() == this_file or "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            tail = node.module.rsplit(".", 1)[-1]
            if tail not in names:
                continue
            for alias in node.names:
                if alias.name != "*":
                    names[tail].add(alias.name)
    return names


def safe_signature(value: Any) -> str:
    try:
        return str(inspect.signature(value))
    except (TypeError, ValueError):
        return "<unavailable>"


def module_contract(module_key: str, module: Any, imported: set[str]) -> dict[str, Any]:
    module_name = str(getattr(module, "__name__", ""))
    module_defined = {
        name
        for name, value in vars(module).items()
        if not name.startswith("__")
        and (inspect.isfunction(value) or inspect.isclass(value))
        and str(getattr(value, "__module__", "")) == module_name
    }
    required_symbols = sorted(module_defined | imported | KEY_SIGNATURES[module_key])
    missing = [name for name in required_symbols if not hasattr(module, name)]
    if missing:
        raise AssertionError(f"cannot snapshot missing symbols in {module_key}: {missing}")
    signatures = {
        name: safe_signature(getattr(module, name))
        for name in required_symbols
        if callable(getattr(module, name))
    }
    return {
        "required_symbols": required_symbols,
        "signatures": signatures,
        "module_defined_symbols": sorted(module_defined),
        "repository_imported_symbols": sorted(imported),
    }


def build_snapshot() -> dict[str, Any]:
    imported = imported_symbol_names()
    contracts: dict[str, Any] = {}
    for key, import_name in MODULES.items():
        module = importlib.import_module(import_name)
        contracts[key] = module_contract(key, module, imported[key])
    state_module = importlib.import_module(MODULES["customer_service_scheduler_state"])
    with tempfile.TemporaryDirectory() as temp_dir:
        store = state_module.SchedulerStateStore(
            tenant_id="contract-snapshot",
            path=Path(temp_dir) / "scheduler_state.json",
        )
        state_keys = sorted(store.empty_state())
    return {
        "snapshot_version": 1,
        "modules": contracts,
        "scheduler_empty_state_keys": state_keys,
    }


def write_snapshot() -> None:
    snapshot = build_snapshot()
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"WROTE {SNAPSHOT_PATH}")


def check_snapshot() -> None:
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    actual = build_snapshot()
    assert_equal(
        actual.get("scheduler_empty_state_keys"),
        expected.get("scheduler_empty_state_keys"),
        "scheduler empty-state fields changed",
    )
    for module_key, expected_contract in (expected.get("modules") or {}).items():
        actual_contract = (actual.get("modules") or {}).get(module_key) or {}
        missing = sorted(
            set(expected_contract.get("required_symbols") or [])
            - set(actual_contract.get("required_symbols") or [])
        )
        assert_true(not missing, f"external symbols removed from {module_key}: {missing}")
        actual_signatures = actual_contract.get("signatures") or {}
        for name, signature in (expected_contract.get("signatures") or {}).items():
            assert_equal(
                actual_signatures.get(name),
                signature,
                f"external signature changed for {module_key}.{name}",
            )


def check_voice_and_image_legacy_result_shapes() -> None:
    workflow = importlib.import_module(MODULES["listen_and_reply"])
    normal_voice = workflow.voice_transcription_trigger(
        {"messages": [{"type": "text", "sender": "customer", "content": "你好"}]}
    )
    assert_equal(
        sorted(normal_voice),
        ["pending_signal_kind", "reason", "should_run"],
        "voice trigger result fields changed",
    )
    assert_true(normal_voice.get("should_run") is False, "plain text must not trigger voice RPA")

    image_router = importlib.import_module("customer_image_turn_router")
    image_trigger = image_router.customer_image_capture_trigger(
        payload={"messages": []},
        pending_signal={"pending_signal_kind": "image_capture", "pending_signal_text": "[图片]"},
    )
    assert_equal(
        sorted(image_trigger),
        ["evidence_count", "pending_signal_id", "pending_signal_kind", "reason", "should_run"],
        "image trigger result fields changed",
    )
    assert_true(image_trigger.get("should_run") is True, "image signal must keep legacy trigger behavior")


def check_scheduler_state_compact_storage_preserves_semantics() -> None:
    state_module = importlib.import_module(MODULES["customer_service_scheduler_state"])
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "scheduler_state.json"
        store = state_module.SchedulerStateStore(tenant_id="contract-storage", path=path)
        state = store.empty_state()
        original_updated_at = state.get("updated_at")
        state["captures"]["capture-1"] = {
            "status": "captured",
            "messages": [{"content": "中文状态合同", "sender": "customer"}],
        }
        store.save(state)
        raw = path.read_text(encoding="utf-8")
        loaded = store.load()
        assert_true("\n  \"" not in raw, "scheduler state unexpectedly uses indented JSON")
        assert_equal(
            state.get("updated_at"),
            original_updated_at,
            "SchedulerStateStore.save mutated the caller state",
        )
        expected = dict(state)
        expected["updated_at"] = loaded.get("updated_at")
        assert_equal(loaded, expected, "compact scheduler state changed JSON semantics")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-snapshot", action="store_true")
    args = parser.parse_args()
    if args.write_snapshot:
        write_snapshot()
        return 0

    checks = [
        check_snapshot,
        check_voice_and_image_legacy_result_shapes,
        check_scheduler_state_compact_storage_preserves_semantics,
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
