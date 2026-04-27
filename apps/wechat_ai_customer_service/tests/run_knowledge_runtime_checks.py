"""Checks for classified knowledge runtime and evidence resolution."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
TEST_ROOT = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts" / "knowledge_runtime_checks"
for path in (PROJECT_ROOT, WORKFLOWS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.admin_backend.services.knowledge_base_store import KnowledgeBaseStore  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.knowledge_registry import KnowledgeRegistry  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.knowledge_schema_manager import KnowledgeSchemaManager  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import default_admin_knowledge_base_root  # noqa: E402
from evidence_resolver import EvidenceResolver  # noqa: E402
from knowledge_runtime import KnowledgeRuntime  # noqa: E402


def main() -> int:
    results = []
    for check in CHECKS:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            break
    failures = [item for item in results if not item["ok"]]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    cleanup()
    return 1 if failures else 0


def check_product_alias_hits_products() -> None:
    pack = resolve("商用冰箱多少钱？")
    assert_has_item(pack, "products", "commercial_fridge_bx_200")
    assert_in("products", pack["matched_categories"], "product category should be matched")
    assert_equal(pack["safety"]["must_handoff"], False, "normal product question should not hand off")


def check_public_product_discount_not_blocked_by_chat_template() -> None:
    pack = resolve("买10台商用冰箱有优惠吗？")
    assert_has_item(pack, "products", "commercial_fridge_bx_200")
    assert_has_item(pack, "chats", "discount_handoff")
    assert_equal(pack["safety"]["must_handoff"], False, "public product tier discount should not be blocked by generic chat template")


def check_invoice_hits_policies() -> None:
    pack = resolve("可以开增值税专用发票吗？")
    assert_has_item(pack, "policies", "invoice")
    assert_equal(pack["safety"]["allowed_auto_reply"], True, "invoice policy should be auto-replyable")


def check_public_bank_account_can_auto_reply() -> None:
    pack = resolve("对公账户和银行账号发我一个")
    assert_has_item(pack, "policies", "bank_account")
    assert_equal(pack["safety"]["must_handoff"], False, "public bank account info should remain auto-replyable")


def check_context_product_shipping() -> None:
    pack = resolve("发江苏南京，包邮吗？", context={"last_product_id": "commercial_fridge_bx_200"})
    item = assert_has_item(pack, "products", "commercial_fridge_bx_200")
    assert_in("conversation_context", item["matched_fields"], "context product should be marked")
    assert_contains(item["reply_excerpt"], "江浙沪", "context product excerpt should include shipping policy")


def check_chat_style_hits_chats() -> None:
    pack = resolve("哈哈我先随便看看，客服辛苦了")
    assert_has_item(pack, "chats", "small_talk_service_pivot")
    assert_equal(pack["safety"]["must_handoff"], False, "small talk can stay auto-replyable")


def check_global_guidelines_are_layered_style_context() -> None:
    pack = resolve("\u4f60\u597d\uff0c\u6211\u5148\u968f\u4fbf\u770b\u770b")
    item = assert_has_item(pack, "global_guidelines", "customer_service_style_guidelines")
    assert_in("always_include", item["matched_fields"], "global guidelines should be layered into normal replies")
    assert_equal(item["requires_handoff"], False, "global guidelines must not force handoff")


def check_product_scoped_rule_requires_product_context() -> None:
    pack = resolve("\u667a\u80fd\u6307\u7eb9\u95e8\u9501 FL-920 \u5b89\u88c5\u670d\u52a1\u600e\u4e48\u786e\u8ba4\uff1f")
    assert_has_item(pack, "products", "fl-920")
    scoped = assert_has_item(pack, "product_rules", "door-lock-installation")
    assert_equal(scoped["requires_handoff"], True, "product-specific installation rule should require handoff")

    unrelated = resolve("\u666e\u901a\u5b89\u88c5\u670d\u52a1\u600e\u4e48\u786e\u8ba4\uff1f")
    for item in unrelated.get("evidence_items", []) or []:
        if item.get("category_id") == "product_rules" and item.get("item_id") == "door-lock-installation":
            raise AssertionError(f"product-scoped rule leaked without product context: {unrelated}")


def check_manual_boundary_requires_handoff() -> None:
    pack = resolve("这个订单能不能月结，合同可以盖章吗？")
    assert_equal(pack["safety"]["must_handoff"], True, "contract/monthly payment needs handoff")
    assert_in("handoff_intent_detected", pack["safety"]["reasons"], "handoff intent should be recorded")
    assert_has_category(pack, "policies")


def check_unknown_business_question_handoffs() -> None:
    pack = resolve("你们老板喜欢什么颜色的咖啡杯？")
    assert_equal(pack["safety"]["must_handoff"], True, "unknown business-adjacent question should hand off")
    assert_in("no_relevant_business_evidence", pack["safety"]["reasons"], "unknown question should record missing evidence")


def check_custom_category_can_return_evidence() -> None:
    root = prepare_custom_root()
    resolver = EvidenceResolver(KnowledgeRuntime(root=root))
    pack = resolver.resolve("黑金卡权益是什么？")
    assert_has_item(pack, "custom_runtime", "black_card_rules")
    assert_in("custom_runtime", pack["matched_categories"], "custom category should be visible to runtime")


def resolve(text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return EvidenceResolver().resolve(text, context=context or {})


def prepare_custom_root() -> Path:
    cleanup()
    shutil.copytree(default_admin_knowledge_base_root(), TEST_ROOT)
    registry = KnowledgeRegistry(root=TEST_ROOT)
    registry.create_custom_category(
        "custom_runtime",
        "Runtime Custom",
        "Used only by runtime checks.",
        participates_in_reply=True,
    )
    schema_manager = KnowledgeSchemaManager(registry)
    store = KnowledgeBaseStore(registry, schema_manager)
    result = store.save_item(
        "custom_runtime",
        {
            "schema_version": 1,
            "category_id": "custom_runtime",
            "id": "black_card_rules",
            "data": {
                "title": "黑金卡规则",
                "content": "黑金卡权益属于测试自定义知识，可按会员规则介绍，但实际承诺需人工确认。",
            },
            "runtime": {"allow_auto_reply": True, "requires_handoff": False, "risk_level": "normal"},
        },
    )
    if not result.get("ok"):
        raise AssertionError(f"custom item save failed: {result}")
    return TEST_ROOT


def cleanup() -> None:
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT)


def assert_has_item(pack: dict[str, Any], category_id: str, item_id: str) -> dict[str, Any]:
    for item in pack.get("evidence_items", []) or []:
        if item.get("category_id") == category_id and item.get("item_id") == item_id:
            return item
    raise AssertionError(f"missing evidence item: {category_id}/{item_id}; pack={pack}")


def assert_has_category(pack: dict[str, Any], category_id: str) -> None:
    if category_id not in (pack.get("matched_categories") or []):
        raise AssertionError(f"missing category: {category_id}; pack={pack}")


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_in(expected: Any, values: list[Any], message: str) -> None:
    if expected not in values:
        raise AssertionError(f"{message}: expected {expected!r} in {values!r}")


def assert_contains(actual: str, expected: str, message: str) -> None:
    if expected not in actual:
        raise AssertionError(f"{message}: expected {expected!r} in {actual!r}")


CHECKS = [
    check_product_alias_hits_products,
    check_public_product_discount_not_blocked_by_chat_template,
    check_invoice_hits_policies,
    check_public_bank_account_can_auto_reply,
    check_context_product_shipping,
    check_chat_style_hits_chats,
    check_global_guidelines_are_layered_style_context,
    check_product_scoped_rule_requires_product_context,
    check_manual_boundary_requires_handoff,
    check_unknown_business_question_handoffs,
    check_custom_category_can_return_evidence,
]


if __name__ == "__main__":
    raise SystemExit(main())
