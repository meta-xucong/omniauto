"""Offline regression checks for the WeChat AI customer-service app.

This runner does not connect to WeChat and does not call an LLM provider.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (WORKFLOWS_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from customer_data_capture import extract_customer_data  # noqa: E402
from knowledge_loader import build_evidence_pack  # noqa: E402
from product_knowledge import decide_product_knowledge_reply, load_product_knowledge  # noqa: E402


DEFAULT_SCENARIO_PATH = APP_ROOT / "tests" / "scenarios" / "offline_regression.json"
PRODUCT_KNOWLEDGE_PATH = APP_ROOT / "data" / "compiled" / "structured_compat" / "product_knowledge.example.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIO_PATH)
    args = parser.parse_args()

    result = run_scenarios(args.scenarios)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def run_scenarios(path: Path) -> dict[str, Any]:
    scenarios = json.loads(path.read_text(encoding="utf-8"))
    product_knowledge = load_product_knowledge(PRODUCT_KNOWLEDGE_PATH)
    results = []
    for scenario in scenarios:
        try:
            output = evaluate_scenario(scenario, product_knowledge)
            assert_expectations(scenario, output)
            results.append({"name": scenario["name"], "ok": True})
        except Exception as exc:
            results.append({"name": scenario.get("name", "<unnamed>"), "ok": False, "error": repr(exc)})
    failures = [item for item in results if not item.get("ok")]
    return {
        "ok": not failures,
        "scenario_path": str(path),
        "count": len(results),
        "failures": failures,
        "results": results,
    }


def evaluate_scenario(scenario: dict[str, Any], product_knowledge: dict[str, Any]) -> dict[str, Any]:
    kind = scenario.get("kind")
    text = str(scenario.get("text") or "")
    context = scenario.get("context", {}) or {}
    if kind == "product_knowledge":
        return decide_product_knowledge_reply(text, product_knowledge, context=context)
    if kind == "evidence_pack":
        return build_evidence_pack(text, context=context)
    if kind == "data_capture":
        return asdict(extract_customer_data(text, required_fields=scenario.get("required_fields") or ["name", "phone"]))
    raise ValueError(f"Unsupported scenario kind: {kind}")


def assert_expectations(scenario: dict[str, Any], output: dict[str, Any]) -> None:
    for path, expected in (scenario.get("expect_equal", {}) or {}).items():
        actual = get_path(output, path)
        if actual != expected:
            raise AssertionError(f"{path}: expected {expected!r}, got {actual!r}")

    for path, needles in (scenario.get("expect_contains", {}) or {}).items():
        actual = str(get_path(output, path) or "")
        for needle in needles:
            if str(needle) not in actual:
                raise AssertionError(f"{path}: expected to contain {needle!r}, got {actual!r}")

    for path, needles in (scenario.get("expect_not_contains", {}) or {}).items():
        actual = str(get_path(output, path) or "")
        for needle in needles:
            if str(needle) in actual:
                raise AssertionError(f"{path}: expected not to contain {needle!r}, got {actual!r}")

    for path, checks in (scenario.get("expect_max_occurrences", {}) or {}).items():
        actual = str(get_path(output, path) or "")
        for needle, maximum in checks.items():
            count = actual.count(str(needle))
            if count > int(maximum):
                raise AssertionError(f"{path}: expected {needle!r} at most {maximum} time(s), got {count} in {actual!r}")

    for path, expected_items in (scenario.get("expect_in", {}) or {}).items():
        actual = get_path(output, path)
        if not isinstance(actual, list):
            raise AssertionError(f"{path}: expected list, got {type(actual).__name__}")
        for expected in expected_items:
            if expected not in actual:
                raise AssertionError(f"{path}: expected item {expected!r} in {actual!r}")


def get_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            raise KeyError(path)
    return value


if __name__ == "__main__":
    raise SystemExit(main())
