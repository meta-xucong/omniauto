"""Focused regression checks for the AI smart recorder V2 flow."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("WECHAT_STORAGE_BACKEND", "file")

from fastapi.testclient import TestClient


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.app import create_app  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.candidate_badges import enrich_candidate  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.formal_review_state import acknowledge_item, enrich_knowledge_item, mark_item_new  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.learning_service import LearningService  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.rag_admin_service import RagAdminService, annotate_experience, build_candidate_from_experience  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.raw_message_learning_service import RawMessageLearningService  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.raw_message_store import RawMessageStore  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.upload_store import UploadStore  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import tenant_context, tenant_raw_inbox_root, tenant_review_candidates_root, tenant_root, tenant_runtime_root  # noqa: E402
from apps.wechat_ai_customer_service.workflows.rag_experience_store import RagExperienceStore  # noqa: E402


TEST_TENANT = "smart_recorder_test"
def main() -> int:
    candidate_ids: list[str] = []
    try:
        with tenant_context(TEST_TENANT):
            cleanup_runtime()
            results = [
                check_raw_message_store_and_learning(candidate_ids),
                check_raw_wechat_product_master_is_blocked(),
                check_rag_product_master_promotion_is_blocked(),
                check_upload_learning_uses_rag_experience(candidate_ids),
                check_badges_and_review_state(),
                check_admin_api_surfaces(),
            ]
        payload = {"ok": all(item["ok"] for item in results), "results": results}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 1
    finally:
        cleanup_candidates(candidate_ids)
        with tenant_context(TEST_TENANT):
            cleanup_runtime()


def check_raw_message_store_and_learning(candidate_ids: list[str]) -> dict[str, Any]:
    store = RawMessageStore()
    conversation = {
        "target_name": "智能记录测试群",
        "display_name": "智能记录测试群",
        "conversation_type": "group",
        "selected_by_user": True,
        "notify_enabled": False,
        "learning_enabled": True,
        "source": {"type": "test"},
    }
    messages = [
        {
            "id": "msg-001",
            "type": "text",
            "sender": "张三",
            "content": "公司名称：蓝鲸智能科技有限公司\n主营范围：智能门锁安装和售后服务\n标准回复：我们主营智能门锁安装和售后服务，可按项目安排师傅。",
            "time": "2026-05-01 10:00:00",
        },
        {
            "id": "msg-002",
            "type": "text",
            "sender": "李四",
            "content": "开票信息和安装售后也按这个规则回复客户。",
            "time": "2026-05-01 10:01:00",
        },
    ]
    first = store.upsert_messages(conversation, messages, source_module="smart_recorder_test", batch_reason="test_capture")
    assert_true(first["inserted_count"] == 2, "raw message insert count")
    duplicate = store.upsert_messages(conversation, messages, source_module="smart_recorder_test", batch_reason="test_capture")
    assert_true(duplicate["inserted_count"] == 0, "duplicate raw messages should not be inserted twice")
    assert_true(duplicate["duplicate_count"] == 2, "duplicate raw messages should be reported")
    listed = store.list_conversations(conversation_type="group", status="all")
    assert_true(any(item["target_name"] == "智能记录测试群" for item in listed), "group conversation should be listed")

    learning = RawMessageLearningService().process_batch(first["batch"]["batch_id"], use_llm=False)
    candidate_ids.extend(learning.get("candidate_ids", []) or [])
    assert_true(learning.get("ok") is True, "raw batch learning should be ok")
    assert_equal(learning.get("candidate_count", 0), 0, "raw batch should only create RAG experience, not review candidates")
    assert_true(str(learning.get("rag_experience_id") or "").startswith("rag_exp_"), "raw batch should first create a rag experience")
    processed = store.get_batch(first["batch"]["batch_id"])
    assert_true(processed and processed.get("status") == "processed", "raw batch should be marked processed")
    assert_true(processed.get("rag_experience_id") == learning.get("rag_experience_id"), "raw batch should keep rag experience trace")
    experiences = RagExperienceStore().list(status="active", limit=20)
    assert_true(any(item.get("experience_id") == learning.get("rag_experience_id") for item in experiences), "rag experience should be stored")
    assert_true(not learning.get("candidate_ids"), "raw batch should not return candidate ids before manual RAG promotion")
    promoted = RagAdminService().promote_experience(str(learning.get("rag_experience_id")), {"target_category": "policies"})
    assert_true(promoted.get("ok") is True, f"manual RAG promotion should create candidate: {promoted}")
    first_candidate_id = promoted["candidate"]["candidate_id"]
    candidate_ids.append(first_candidate_id)
    candidate_path = tenant_review_candidates_root(TEST_TENANT) / "pending" / f"{first_candidate_id}.json"
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert_equal(candidate.get("source", {}).get("type"), "rag_experience", "candidate should be linked from rag experience")
    assert_equal(candidate.get("review", {}).get("rag_experience_id"), learning.get("rag_experience_id"), "candidate should trace rag experience")
    return {"name": "raw_message_store_and_learning", "ok": True, "candidate_ids": candidate_ids}


def check_raw_wechat_product_master_is_blocked() -> dict[str, Any]:
    store = RawMessageStore()
    conversation = {
        "target_name": "source_authority_private_probe",
        "display_name": "source_authority_private_probe",
        "conversation_type": "private",
        "learning_enabled": True,
        "notify_enabled": False,
        "source": {"type": "test"},
    }
    messages = [
        {
            "id": "source-policy-product-001",
            "type": "text",
            "sender": "customer",
            "content": (
                "商品资料：\n"
                "商品名称：2020款丰田卡罗拉1.2T自动挡\n"
                "型号/SKU：SOURCE-POLICY-COROLLA\n"
                "类目：二手燃油车\n"
                "价格：69800\n"
                "单位：台\n"
                "库存：1\n"
            ),
            "time": "2026-05-04 12:00:00",
        }
    ]
    result = store.upsert_messages(conversation, messages, source_module="source_authority_test", batch_reason="test_capture")
    learning = RawMessageLearningService().process_batch(result["batch"]["batch_id"], use_llm=False)
    assert_true(learning.get("ok") is True, "raw product-like chat learning should finish")
    assert_equal(learning.get("candidate_count"), 0, "raw WeChat product master data should not enter pending candidates")
    assert_equal(learning.get("skipped_source_policy_count", 0), 0, "source policy is enforced later if a user manually promotes this RAG experience")
    batch = store.get_batch(result["batch"]["batch_id"])
    assert_true(batch and batch.get("candidate_count", 0) == 0, "batch should record strict RAG-only learning")
    assert_true(str(learning.get("rag_experience_id") or "").startswith("rag_exp_"), "blocked raw product should still keep RAG trace")
    return {"name": "raw_wechat_product_master_is_blocked", "ok": True, "rag_experience_id": learning.get("rag_experience_id")}


def check_rag_product_master_promotion_is_blocked() -> dict[str, Any]:
    product_payload = {
        "name": "2020款丰田卡罗拉1.2T自动挡",
        "sku": "SOURCE-POLICY-COROLLA",
        "category": "二手燃油车",
        "price": 69800,
        "unit": "台",
        "inventory": 1,
    }
    experience = {
        "experience_id": "source_policy_rag_product_probe",
        "status": "active",
        "source_type": "raw_wechat_private",
        "summary": json.dumps(product_payload, ensure_ascii=False),
        "reply_text": "[车金AI] 这台卡罗拉参考价6.98万，库存1台。",
        "usage": {"reply_count": 3},
        "rag_hit": {"source_type": "wechat_raw_message", "category": "private", "text": "[车金AI] 这台卡罗拉参考价6.98万，库存1台。"},
    }
    annotated = annotate_experience(experience, [])
    assert_equal(annotated.get("formal_relation"), "blocked_by_source_policy", "raw-chat product RAG should be blocked in review relation")
    try:
        build_candidate_from_experience(experience, preferred_category="products")
    except ValueError as exc:
        assert_true("不能升级为商品资料" in str(exc) or "不能新增或修改商品资料" in str(exc), "block message should explain product authority")
    else:
        raise AssertionError("raw-chat product RAG must not promote into product candidate")
    return {"name": "rag_product_master_promotion_is_blocked", "ok": True}


def check_upload_learning_uses_rag_experience(candidate_ids: list[str]) -> dict[str, Any]:
    upload = UploadStore().save_upload(
        "smart_recorder_upload_probe.txt",
        (
            "商品资料：智能记录员上传测试车源\n"
            "商品名称：2023款比亚迪宋PLUS DM-i 冠军版\n"
            "型号：UPLOAD-SONGPLUS-20260501\n"
            "商品类目：二手车/SUV\n"
            "价格：11.80万\n"
            "单位：台\n"
            "库存：1\n"
            "发货：南京门店可看车，试驾需提前预约\n"
            "售后：车况以检测报告为准\n"
        ).encode("utf-8"),
        "products",
    )
    assert_true(upload.get("ok") is True, f"upload should be saved: {upload}")
    job = LearningService().create_job([upload["item"]["upload_id"]], use_llm=False)
    candidate_ids.extend(job.get("job", {}).get("candidate_ids", []) or [])
    assert_true(job.get("ok") is True, "upload learning should be ok")
    assert_equal(job.get("job", {}).get("candidate_count", 0), 0, "upload learning should only create RAG experience")
    rag_ids = job.get("job", {}).get("rag_experience_ids", []) or []
    assert_true(bool(rag_ids) and str(rag_ids[0]).startswith("rag_exp_"), "upload learning should first create rag experience")
    assert_true(not job["job"]["candidate_ids"], "upload learning should not create pending candidates automatically")
    return {"name": "upload_learning_uses_rag_experience", "ok": True, "candidate_ids": []}


def check_badges_and_review_state() -> dict[str, Any]:
    candidate = {
        "candidate_id": "candidate_badge_test",
        "source": {"type": "rag_experience", "original_type": "raw_wechat_group"},
        "detected_tags": ["wechat_group_chat"],
        "proposal": {"formal_patch": {"target_category": "policies"}},
        "review": {"status": "pending", "completeness_status": "ready"},
        "intake": {"status": "ready", "warnings": []},
    }
    enriched = enrich_candidate(candidate)
    badge_keys = {item["key"] for item in enriched["display_badges"]}
    assert_true({"complete", "rag_generated", "wechat_group", "can_promote"}.issubset(badge_keys), "candidate badges should include V2 status markers")

    item = mark_item_new({"id": "formal_badge_test", "data": {}}, {"source_module": "candidate"})
    assert_true(item["review_state"]["is_new"] is True, "formal item should be marked new")
    formal = enrich_knowledge_item(item)
    assert_true(any(badge["key"] == "new_unread" for badge in formal["display_badges"]), "formal new badge should render")
    acknowledged = acknowledge_item(item)
    assert_true(acknowledged["review_state"]["is_new"] is False, "acknowledge should clear new marker")
    return {"name": "badges_and_review_state", "ok": True}


def check_admin_api_surfaces() -> dict[str, Any]:
    client = TestClient(create_app())
    headers = {"X-Tenant-ID": TEST_TENANT}
    index = client.get("/")
    assert_true("AI智能记录员" in index.text, "admin UI should expose recorder page")
    assert_true("按类型导出Excel" in index.text, "admin UI should expose type export")

    summary = client.get("/api/raw-messages/summary", headers=headers)
    assert_equal(summary.status_code, 200, "raw message summary endpoint")
    recorder = client.get("/api/recorder/summary", headers=headers)
    assert_equal(recorder.status_code, 200, "recorder summary endpoint")
    export = client.post("/api/exports/knowledge", headers=headers, json={"sort_by": "time"})
    assert_equal(export.status_code, 200, "knowledge export endpoint")
    export_payload = export.json()
    assert_true(export_payload.get("ok") is True and Path(export_payload.get("path", "")).exists(), "knowledge export file should be created")
    return {"name": "admin_api_surfaces", "ok": True}


def cleanup_runtime() -> None:
    root = tenant_runtime_root(TEST_TENANT)
    if root.exists():
        shutil.rmtree(root)
    rag_root = tenant_root(TEST_TENANT) / "rag_experience"
    if rag_root.exists():
        shutil.rmtree(rag_root)
    raw_inbox = tenant_raw_inbox_root(TEST_TENANT)
    if raw_inbox.exists():
        shutil.rmtree(raw_inbox)


def cleanup_candidates(candidate_ids: list[str]) -> None:
    for candidate_id in candidate_ids:
        for status in ("pending", "approved", "rejected"):
            path = tenant_review_candidates_root(TEST_TENANT) / status / f"{candidate_id}.json"
            if path.exists():
                path.unlink()


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
