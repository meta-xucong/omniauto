"""Chaptered checks for the WeChat AI customer-service admin backend."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from openpyxl import Workbook


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
ADMIN_UPLOAD_INDEX = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "admin" / "uploads_index.json"
ADMIN_DRAFTS_ROOT = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "admin" / "drafts"
ADMIN_JOBS_ROOT = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "admin" / "jobs"
ADMIN_GENERATOR_ROOT = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "admin" / "generator_sessions"
DIAGNOSTIC_IGNORES_PATH = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "admin" / "diagnostic_ignores.json"
TEST_ARTIFACTS = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts"
VERSIONS_ROOT = APP_ROOT / "data" / "versions"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.app import create_app  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.diagnostics_service import DiagnosticsService  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.knowledge_deduper import KnowledgeDeduper  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.knowledge_compiler import KnowledgeCompiler, compile_faq  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.learning_service import LearningService  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services import learning_service as learning_service_module  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, default_admin_knowledge_base_root, tenant_product_item_knowledge_root  # noqa: E402
from apps.wechat_ai_customer_service.storage import get_postgres_store, load_storage_config  # noqa: E402
from apps.wechat_ai_customer_service.workflows import generate_review_candidates as review_candidate_generator  # noqa: E402
from apps.wechat_ai_customer_service.workflows.rag_experience_store import RagExperienceStore  # noqa: E402
from apps.wechat_ai_customer_service.workflows.rag_layer import RagService  # noqa: E402


CHAPTERS = ["foundation", "readonly", "drafts", "generator", "candidates", "diagnostics", "all"]
KNOWLEDGE_BASE_ROOT = default_admin_knowledge_base_root()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chapter", choices=CHAPTERS, default="all")
    args = parser.parse_args()

    old_mirror = os.environ.get("WECHAT_POSTGRES_MIRROR_FILES")
    if old_mirror is None and os.environ.get("WECHAT_STORAGE_BACKEND", "").strip().lower() == "postgres":
        os.environ["WECHAT_POSTGRES_MIRROR_FILES"] = "0"
    try:
        result = run_checks(args.chapter)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    finally:
        if old_mirror is None:
            os.environ.pop("WECHAT_POSTGRES_MIRROR_FILES", None)
        else:
            os.environ["WECHAT_POSTGRES_MIRROR_FILES"] = old_mirror


def run_checks(chapter: str) -> dict[str, Any]:
    client = TestClient(create_app())
    checks = checks_for_chapter(chapter)
    results = []
    for check in checks:
        try:
            check(client)
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            if chapter != "all":
                break
    failures = [item for item in results if not item.get("ok")]
    return {"ok": not failures, "chapter": chapter, "count": len(results), "failures": failures, "results": results}


def checks_for_chapter(chapter: str) -> list[Any]:
    foundation = [
        check_health,
        check_index_page,
        check_static_assets,
        check_rag_status_and_search_api,
        check_rag_experience_api,
    ]
    if chapter == "foundation":
        return foundation
    readonly = [
        check_knowledge_overview,
        check_knowledge_categories_api,
        check_knowledge_products,
        check_knowledge_faqs_and_policies,
        check_knowledge_styles_and_persona,
        check_knowledge_raw_json,
    ]
    if chapter == "readonly":
        return [*foundation, *readonly]
    drafts = [
        check_draft_create_validate_diff_apply_and_rollback,
    ]
    if chapter == "drafts":
        return [*foundation, *readonly, *drafts]
    generator = [
        check_ai_knowledge_generator_flow,
    ]
    if chapter == "generator":
        return [*foundation, *readonly, *generator]
    candidates = [
        check_upload_learning_candidate_apply_and_reject,
    ]
    if chapter == "candidates":
        return [*foundation, *readonly, *drafts, *generator, *candidates]
    diagnostics = [
        check_diagnostics_and_system_status,
    ]
    if chapter == "diagnostics":
        return [*foundation, *readonly, *drafts, *generator, *candidates, *diagnostics]
    if chapter == "all":
        return [*foundation, *readonly, *drafts, *generator, *candidates, *diagnostics]
    return foundation


def check_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert_equal(response.status_code, 200, "health status")
    payload = response.json()
    assert_true(payload.get("ok") is True, "health should be ok")
    assert_equal(payload.get("app"), "wechat_ai_customer_service_admin", "health app id")


def check_index_page(client: TestClient) -> None:
    response = client.get("/")
    assert_equal(response.status_code, 200, "index status")
    text = response.text
    assert_true("WeChat AI Service" in text, "index should render app shell")
    assert_true("/static/styles.css" in text, "index should link stylesheet")
    assert_true('id="upload-file" type="file" multiple' in text, "upload input should support multiple files")
    assert_true("知识录入与学习" in text, "index should group upload, learning, and candidate review")
    assert_true("AI参考资料" in text, "index should group reference material and dialogue experience")
    assert_true("AI整理资料" in text, "index should expose one-click material learning")
    assert_true("待确认知识" in text, "index should expose simple candidate review wording")


def check_static_assets(client: TestClient) -> None:
    css = client.get("/static/styles.css")
    js = client.get("/static/app.js")
    assert_equal(css.status_code, 200, "css status")
    assert_equal(js.status_code, 200, "js status")
    assert_true("backdrop-filter" in css.text, "glass style should use backdrop-filter")
    assert_true("refreshHealth" in js.text, "frontend should bind health check")
    assert_true("candidate-apply" in js.text, "frontend should expose candidate apply action")
    assert_true("candidate-reject" in js.text, "frontend should expose candidate reject action")
    assert_true("version-rollback" in js.text, "frontend should expose version rollback action")
    assert_true("create-backup" in js.text, "frontend should expose manual backup action")
    assert_true("sendGeneratorMessage" in js.text, "frontend should expose AI knowledge generator")
    assert_true("confirm-generator" in js.text, "frontend should expose generator confirm action")
    assert_true("save-generator-draft" in js.text, "frontend should allow editing generator drafts before save")
    assert_true("/draft" in js.text, "frontend should call generator draft update endpoint")
    assert_true("diagnostic-ignore" in js.text, "frontend should expose diagnostic ignore action")
    assert_true("price_tiers" in js.text, "frontend should render tier price business controls")
    assert_true("没有待学习的上传资料" in js.text, "frontend should no-op when there are no uploads to learn")
    assert_true("/api/uploads/batch" in js.text, "frontend should use batch upload endpoint")
    assert_true('getElementById("upload-file").addEventListener("change"' in js.text, "frontend should auto-upload after file selection")
    assert_true("setUploadBusy(true" in js.text, "frontend should show upload progress")
    assert_true("use_llm: true" in js.text, "frontend should request LLM-assisted upload learning")
    assert_true("skipped_duplicate_count" in js.text, "frontend should show duplicate-skip count after learning")
    assert_true("upload-delete" in js.text, "frontend should expose upload delete action")
    assert_true("workflow-tab" in js.text, "frontend should expose grouped workflow tabs")
    assert_true("activeIntakeTab" in js.text, "frontend should keep intake subpage state")
    assert_true("viewAliases" in js.text, "frontend should keep old deep links compatible")
    assert_true("candidateIsIncomplete" in js.text, "frontend should mark incomplete candidates")
    assert_true("candidate-supplement-save" in js.text, "frontend should expose candidate supplement action")
    assert_true("/supplement" in js.text, "frontend should call candidate supplement endpoint")
    assert_true("candidate-category-change" in js.text, "frontend should expose candidate category correction action")
    assert_true("/category" in js.text, "frontend should call candidate category correction endpoint")
    assert_true("setLearningBusy(true" in js.text, "frontend should show upload learning progress")
    assert_true("clearCandidateDetail(\"已应用入库" in js.text, "frontend should clear candidate detail after apply")
    assert_true("候选应用失败" in js.text, "frontend should surface failed candidate apply instead of silently refreshing")
    assert_true("if (reasonInput === null) return" in js.text, "frontend should cancel reject without rejecting")
    assert_true("loading-spinner" in css.text, "frontend should include loading spinner style")
    assert_true("knowledge-form" in js.text, "frontend should render business forms")
    assert_true("category-select" in js.text, "frontend should expose category selector")
    assert_true("rag-search" in js.text, "frontend should expose rag search action")
    assert_true("/api/rag/status" in js.text, "frontend should call rag status endpoint")
    assert_true("/api/rag/sources" in js.text, "frontend should call rag source list endpoint")
    assert_true("/api/rag/analytics" in js.text, "frontend should call rag analytics endpoint")
    assert_true("ai_reference" in js.text, "frontend should expose AI reference page")
    assert_true("/api/rag/experiences" in js.text, "frontend should call rag experience endpoint")
    assert_true("status=all" in js.text, "frontend should show all rag experience statuses")
    assert_true("rag-experience-discard" in js.text, "frontend should expose rag experience discard action")
    assert_true("rag-experience-promote" in js.text, "frontend should expose rag experience promotion action")
    assert_true("formal_relation" in js.text, "frontend should render rag/formal knowledge relationship")
    assert_true("quality-chip" in js.text, "frontend should render rag experience quality chips")
    assert_true("retrieval_allowed" in js.text, "frontend should render rag retrieval eligibility")
    assert_true("rag_evidence" in js.text, "frontend should render candidate rag evidence")
    assert_true('id="rag-source-list"' in client.get("/").text, "frontend should expose rag source list")
    assert_true("已导入资料" in client.get("/").text, "frontend should expose imported reference material")
    assert_true("对话中学到的经验" in client.get("/").text, "frontend should expose dialogue experience")


def check_rag_status_and_search_api(client: TestClient) -> None:
    status = client.get("/api/rag/status")
    assert_equal(status.status_code, 200, "rag status endpoint")
    payload = status.json()
    assert_true(payload.get("ok") is True, "rag status ok")
    assert_true("source_count" in payload, "rag status source count")
    assert_true("experience_counts" in payload, "rag status should include experience counts")

    sources = client.get("/api/rag/sources", params={"limit": 5})
    assert_equal(sources.status_code, 200, "rag source list endpoint")
    source_payload = sources.json()
    assert_true(source_payload.get("ok") is True, "rag source list ok")
    assert_true("sources" in source_payload and "chunks" in source_payload, "rag source list should expose sources and chunks")

    rebuild = client.post("/api/rag/rebuild")
    assert_equal(rebuild.status_code, 200, "rag rebuild endpoint")
    assert_true(rebuild.json().get("ok") is True, "rag rebuild ok")

    search = client.post("/api/rag/search", json={"query": "商用冰箱 发货", "limit": 3})
    assert_equal(search.status_code, 200, "rag search endpoint")
    assert_true(search.json().get("ok") is True, "rag search ok")
    assert_equal(search.json().get("retrieval_mode"), "hybrid_lexical_semantic", "rag search should expose hybrid mode")

    analytics = client.get("/api/rag/analytics")
    assert_equal(analytics.status_code, 200, "rag analytics endpoint")
    assert_true(analytics.json().get("ok") is True, "rag analytics ok")
    assert_true("formalization_candidates" in analytics.json(), "rag analytics should expose formalization candidates")


def check_rag_experience_api(client: TestClient) -> None:
    store = RagExperienceStore()
    cleanup_rag_experience_probe(store)
    try:
        record = store.record_reply(
            target="admin_rag_experience_probe",
            message_ids=["admin-rag-exp-001"],
            question="客户随口问公寓门锁安装要不要提前留电源",
            reply_text="一般建议提前确认门厚、开孔和供电方式，我先按常规安装注意事项给您整理。",
            raw_reply_text="一般建议提前确认门厚、开孔和供电方式，我先按常规安装注意事项给您整理。",
            intent_assist={"intent": "product_detail", "recommended_action": "answer"},
            rag_reply={
                "applied": True,
                "hit": {
                    "chunk_id": "admin-rag-exp-chunk",
                    "source_id": "admin-rag-exp-source",
                    "score": 0.91,
                    "category": "product_explanations",
                    "source_type": "rag_soft_reference",
                    "product_id": "fl-920",
                    "text": "智能门锁安装前建议确认门厚、锁体开孔、供电方式和现场网络。",
                },
            },
        )
        assert_true(record.get("quality", {}).get("retrieval_allowed") is True, "high quality rag experience should be retrieval eligible")
        listed = client.get("/api/rag/experiences", params={"status": "active", "limit": 50})
        assert_equal(listed.status_code, 200, "rag experience list endpoint")
        items = listed.json().get("items", [])
        assert_true(any(item.get("experience_id") == record["experience_id"] for item in items), "rag experience should be listed as active")
        assert_equal(listed.json().get("formal_knowledge_policy"), "rag_experience_only_not_formal_knowledge", "rag experience policy marker")
        listed_record = next(item for item in items if item.get("experience_id") == record["experience_id"])
        assert_true(listed_record.get("quality", {}).get("retrieval_allowed") is True, "rag experience API should expose retrieval eligibility")
        assert_true(listed_record.get("quality", {}).get("band") in {"high", "medium"}, "rag experience API should expose quality band")

        search = client.post("/api/rag/search", json={"query": "公寓门锁安装提前留电源", "limit": 10})
        assert_equal(search.status_code, 200, "rag experience search endpoint")
        assert_true(
            any(hit.get("source_id") == record["experience_id"] and hit.get("source_type") == "rag_experience" for hit in search.json().get("hits", [])),
            "active rag experience should participate in rag retrieval",
        )

        low_record = store.record_reply(
            target="admin_rag_experience_probe",
            message_ids=["admin-rag-exp-low"],
            question="客户随口问一个资料里很弱相关的门锁颜色偏好",
            reply_text="这个我只能按现有资料做轻参考，不能当成正式规则。",
            raw_reply_text="这个我只能按现有资料做轻参考，不能当成正式规则。",
            intent_assist={"intent": "product_detail", "recommended_action": "answer"},
            rag_reply={
                "applied": True,
                "hit": {
                    "chunk_id": "admin-rag-exp-low-chunk",
                    "source_id": "admin-rag-exp-low-source",
                    "score": 0.05,
                    "category": "product_explanations",
                    "source_type": "rag_soft_reference",
                    "product_id": "fl-920",
                    "text": "门锁颜色偏好来自一次很弱相关的闲聊摘录。",
                },
            },
        )
        assert_true(low_record.get("quality", {}).get("retrieval_allowed") is False, "low quality rag experience should not be retrieval eligible")
        low_search = client.post("/api/rag/search", json={"query": "门锁颜色偏好弱相关闲聊摘录", "limit": 10})
        assert_equal(low_search.status_code, 200, "low quality rag search endpoint")
        assert_true(
            not any(hit.get("source_id") == low_record["experience_id"] for hit in low_search.json().get("hits", [])),
            "low quality active rag experience should not participate in retrieval",
        )

        listed_all = client.get("/api/rag/experiences", params={"status": "all", "limit": 50}).json()
        all_items = listed_all.get("items", [])
        active_item = next(item for item in all_items if item.get("experience_id") == record["experience_id"])
        assert_true("formal_relation" in active_item, "rag experience should expose formal relation annotation")
        assert_true("recommended_action" in active_item, "rag experience should expose recommended action")
        assert_true("formal_relation_cache" in active_item, "rag experience should expose formal relation cache")
        low_item = next(item for item in all_items if item.get("experience_id") == low_record["experience_id"])
        assert_true(low_item.get("quality", {}).get("retrieval_allowed") is False, "low quality item should remain visible for review")

        promoted = client.post(
            f"/api/rag/experiences/{record['experience_id']}/promote",
            json={"source": "admin backend check"},
        )
        assert_equal(promoted.status_code, 200, "rag experience promote endpoint")
        promoted_payload = promoted.json()
        assert_true(promoted_payload.get("ok"), f"rag experience promote should be ok: {promoted_payload}")
        candidate_id = promoted_payload.get("candidate", {}).get("candidate_id")
        assert_true(str(candidate_id).startswith("rag_promote_"), "promote should create a rag candidate id")
        pending_candidates = client.get("/api/candidates", params={"status": "pending"}).json().get("items", [])
        assert_true(candidate_id in {item.get("candidate_id") for item in pending_candidates}, "promoted rag experience should appear as pending candidate")
        promoted_all = client.get("/api/rag/experiences", params={"status": "all", "limit": 50}).json().get("items", [])
        promoted_item = next(item for item in promoted_all if item.get("experience_id") == record["experience_id"])
        assert_equal(promoted_item.get("status"), "promoted", "rag experience should be marked promoted")
        assert_equal(promoted_item.get("formal_relation"), "promoted", "promoted experience should expose promoted relation")
        search_promoted = client.post("/api/rag/search", json={"query": "公寓门锁安装提前留电源", "limit": 10}).json().get("hits", [])
        assert_true(not any(hit.get("source_id") == record["experience_id"] for hit in search_promoted), "promoted rag experience should not participate in retrieval")

        discarded = client.post(
            f"/api/rag/experiences/{record['experience_id']}/discard",
            json={"reason": "admin backend check"},
        )
        assert_equal(discarded.status_code, 200, "rag experience discard endpoint")
        assert_equal(discarded.json().get("item", {}).get("status"), "discarded", "rag experience should be discarded")

        listed_after = client.get("/api/rag/experiences", params={"status": "active", "limit": 50}).json().get("items", [])
        assert_true(not any(item.get("experience_id") == record["experience_id"] for item in listed_after), "discarded rag experience should not be in active list")
        search_after = client.post("/api/rag/search", json={"query": "公寓门锁安装提前留电源", "limit": 10}).json().get("hits", [])
        assert_true(not any(hit.get("source_id") == record["experience_id"] for hit in search_after), "discarded rag experience should not participate in retrieval")
    finally:
        cleanup_rag_experience_probe(store)


def cleanup_rag_experience_probe(store: RagExperienceStore) -> None:
    experience_ids = [
        str(item.get("experience_id") or "")
        for item in store.list(status="all", limit=500)
        if item.get("target") == "admin_rag_experience_probe"
    ]
    cleanup_rag_promotion_candidates(experience_ids)
    config = load_storage_config()
    if config.use_postgres and config.postgres_configured:
        db = get_postgres_store(tenant_id=store.tenant_id, config=config)
        if db.available():
            db.execute(
                f"DELETE FROM {db.schema}.rag_experiences WHERE tenant_id = %s AND payload->>'target' = %s",
                [store.tenant_id, "admin_rag_experience_probe"],
            )

    if store.path.exists():
        records = json.loads(store.path.read_text(encoding="utf-8"))
        if isinstance(records, list):
            filtered = [item for item in records if item.get("target") != "admin_rag_experience_probe"]
            store.path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")
    RagService(tenant_id=store.tenant_id).rebuild_index()


def cleanup_rag_promotion_candidates(experience_ids: list[str]) -> None:
    if not experience_ids:
        return
    review_root = APP_ROOT / "data" / "review_candidates"
    for path in review_root.glob("*/*.json"):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        source = item.get("source") if isinstance(item.get("source"), dict) else {}
        if str(source.get("experience_id") or "") in experience_ids:
            path.unlink()
    config = load_storage_config()
    if config.use_postgres and config.postgres_configured:
        db = get_postgres_store(config=config)
        if db.available():
            for experience_id in experience_ids:
                db.execute(
                    f"DELETE FROM {db.schema}.review_candidates WHERE tenant_id = %s AND payload->'source'->>'experience_id' = %s",
                    [active_tenant_id(), experience_id],
                )


def check_knowledge_overview(client: TestClient) -> None:
    response = client.get("/api/knowledge/overview")
    assert_equal(response.status_code, 200, "overview status")
    payload = response.json()
    assert_true(payload.get("ok") is True, "overview should be ok")
    counts = payload.get("counts", {})
    assert_true(int(counts.get("products", 0)) >= 1, "overview should count products")
    assert_true(int(counts.get("faqs", 0)) >= 1, "overview should count faqs")


def check_knowledge_categories_api(client: TestClient) -> None:
    response = client.get("/api/knowledge/categories")
    assert_equal(response.status_code, 200, "categories status")
    items = response.json().get("items", [])
    ids = {item.get("id") for item in items}
    assert_true({"products", "chats", "policies", "erp_exports"}.issubset(ids), "categories should include default modules")
    assert_true({"product_faq", "product_rules", "product_explanations"}.issubset(ids), "categories should include product-scoped modules")
    products = next(item for item in items if item.get("id") == "products")
    assert_true(products.get("schema", {}).get("fields"), "category should include schema fields")
    assert_true(products.get("resolver", {}).get("match_fields"), "category should include resolver")
    detail = client.get("/api/knowledge/categories/products/items/commercial_fridge_bx_200")
    assert_equal(detail.status_code, 200, "category item detail status")
    assert_true(detail.json().get("item", {}).get("data", {}).get("aliases"), "category item should expose form data")
    scoped_detail = client.get("/api/knowledge/categories/product_rules/items/door-lock-installation")
    assert_equal(scoped_detail.status_code, 200, "product-scoped item detail status")
    assert_equal(scoped_detail.json().get("item", {}).get("data", {}).get("product_id"), "fl-920", "product-scoped item should expose product id")


def check_knowledge_products(client: TestClient) -> None:
    response = client.get("/api/knowledge/products")
    assert_equal(response.status_code, 200, "products status")
    items = response.json().get("items", [])
    ids = {item.get("id") for item in items}
    assert_true("commercial_fridge_bx_200" in ids, "products should include fridge fixture")
    detail = client.get("/api/knowledge/products/commercial_fridge_bx_200").json().get("item")
    assert_true(detail and "aliases" in detail, "product detail should include aliases")


def check_knowledge_faqs_and_policies(client: TestClient) -> None:
    faqs = client.get("/api/knowledge/faqs")
    policies = client.get("/api/knowledge/policies")
    assert_equal(faqs.status_code, 200, "faqs status")
    assert_equal(policies.status_code, 200, "policies status")
    intents = {item.get("intent") for item in faqs.json().get("items", [])}
    assert_true("invoice" in intents, "faqs should include invoice")
    assert_true("company_profile" in policies.json().get("items", {}), "policies should include company profile")


def check_knowledge_styles_and_persona(client: TestClient) -> None:
    styles = client.get("/api/knowledge/styles")
    persona = client.get("/api/knowledge/persona")
    assert_equal(styles.status_code, 200, "styles status")
    assert_equal(persona.status_code, 200, "persona status")
    assert_true(styles.json().get("items"), "styles should not be empty")
    assert_true("prompt_files" in persona.json().get("item", {}), "persona should include prompt files")


def check_knowledge_raw_json(client: TestClient) -> None:
    response = client.get("/api/knowledge/raw-json", params={"file": "product_knowledge"})
    assert_equal(response.status_code, 200, "raw json status")
    assert_true("products" in response.json().get("content", {}), "raw product knowledge should include products")


def check_draft_create_validate_diff_apply_and_rollback(client: TestClient) -> None:
    created_version_ids: list[str] = []
    raw = client.get("/api/knowledge/raw-json", params={"file": "style_examples"}).json()["content"]
    original_ids = {item.get("id") for item in raw.get("examples", [])}
    test_id = "admin_check_style_example"
    snapshot_id = ""
    try:
        raw["examples"] = [item for item in raw.get("examples", []) if item.get("id") != test_id]
        raw["examples"].append(
            {
                "id": test_id,
                "intent_tags": ["small_talk"],
                "message": "测试话术，仅用于管理台回归。",
            }
        )
        created = client.post(
            "/api/drafts",
            json={"target_file": "style_examples", "content": raw, "summary": "admin check style add"},
        ).json()
        assert_true(created.get("ok"), "draft create should be ok")
        draft_id = created["draft"]["draft_id"]

        validation = client.post(f"/api/drafts/{draft_id}/validate").json()
        assert_true(validation.get("ok"), f"draft should validate: {validation}")
        diff = client.get(f"/api/drafts/{draft_id}/diff").json().get("diff", [])
        assert_true(any(test_id in line for line in diff), "draft diff should include test id")
        applied = client.post(f"/api/drafts/{draft_id}/apply").json()
        assert_true(applied.get("ok"), f"draft apply should be ok: {applied}")
        snapshot_id = applied["snapshot"]["version_id"]
        created_version_ids.append(snapshot_id)

        after_apply = client.get("/api/knowledge/styles").json().get("items", [])
        assert_true(test_id in {item.get("id") for item in after_apply}, "applied style should be visible")
        versions = client.get("/api/versions").json().get("items", [])
        assert_true(any(item.get("version_id") == snapshot_id for item in versions), "snapshot should be listed")
        rollback = client.post(f"/api/versions/{snapshot_id}/rollback").json()
        assert_true(rollback.get("ok"), f"rollback should be ok: {rollback}")
        backup_id = rollback.get("backup", {}).get("version_id")
        if backup_id:
            created_version_ids.append(backup_id)
        after_rollback = client.get("/api/knowledge/styles").json().get("items", [])
        final_ids = {item.get("id") for item in after_rollback}
        assert_true(test_id not in final_ids, "rollback should remove the temporary style id")
        assert_true(original_ids.issubset(final_ids), "rollback should preserve original style ids")
    finally:
        if snapshot_id:
            current_ids = {item.get("id") for item in client.get("/api/knowledge/styles").json().get("items", [])}
            if test_id in current_ids:
                rollback = client.post(f"/api/versions/{snapshot_id}/rollback").json()
                backup_id = rollback.get("backup", {}).get("version_id")
                if backup_id:
                    created_version_ids.append(backup_id)
        for version_id in created_version_ids:
            remove_version_snapshot(version_id)


def check_ai_knowledge_generator_flow(client: TestClient) -> None:
    created_item_paths: list[Path] = []
    created_session_ids: list[str] = []
    try:
        message = (
            "\u65b0\u589e\u5546\u54c1\uff1a\u7ba1\u7406\u53f0\u751f\u6210\u5668\u6d4b\u8bd5\u5546\u54c1\uff0c"
            "\u5355\u4ef788\u5143/\u4ef6\uff0c10\u4ef6\u4ee5\u4e0a80\u5143\uff0c"
            "\u5e93\u5b5820\u4ef6\uff0c24\u5c0f\u65f6\u53d1\u8d27"
        )
        created = client.post("/api/generator/sessions", json={"message": message, "use_llm": False}).json()
        assert_true(created.get("ok"), f"generator session should be ok: {created}")
        session = created["session"]
        created_session_ids.append(session["session_id"])
        assert_equal(session.get("status"), "ready", "complete generator input should be ready")
        assert_equal(session.get("category_id"), "products", "generator should classify product input")
        assert_equal(session.get("intake", {}).get("status"), "ready", "generator intake should mark complete input ready")
        assert_true(session.get("summary_rows"), "generator should return business summary rows")
        item_id = session["draft_item"]["id"]
        assert_true(session["draft_item"]["data"].get("additional_details"), "generator should preserve raw description details")
        created_item_paths.append(KNOWLEDGE_BASE_ROOT / "products" / "items" / f"{item_id}.json")

        saved = client.post(f"/api/generator/sessions/{session['session_id']}/confirm").json()
        assert_true(saved.get("ok"), f"generator confirm should be ok: {saved}")
        products = client.get("/api/knowledge/categories/products/items").json().get("items", [])
        assert_true(item_id in {item.get("id") for item in products}, "generated product should be visible")

        scoped_rule = client.post(
            "/api/generator/sessions",
            json={
                "message": (
                    "\u5546\u54c1ID\uff1afl-920\uff1b"
                    "\u89c4\u5219\u540d\u79f0\uff1a\u7ba1\u7406\u53f0\u6d4b\u8bd5\u5b89\u88c5\u89c4\u5219\uff1b"
                    "\u6807\u51c6\u56de\u590d\uff1a\u5b89\u88c5\u670d\u52a1\u9700\u8981\u6839\u636e\u57ce\u5e02\u548c\u95e8\u578b\u4eba\u5de5\u786e\u8ba4\u3002"
                ),
                "preferred_category_id": "product_rules",
                "use_llm": False,
            },
        ).json()
        assert_true(scoped_rule.get("ok"), f"product-scoped generator session should be ok: {scoped_rule}")
        scoped_session = scoped_rule["session"]
        created_session_ids.append(scoped_session["session_id"])
        assert_equal(scoped_session.get("category_id"), "product_rules", "generator should preserve product-scoped category")
        assert_equal(scoped_session.get("status"), "ready", "product-scoped rule should be ready")
        scoped_item_id = scoped_session["draft_item"]["id"]
        created_item_paths.append(tenant_product_item_knowledge_root() / "fl-920" / "rules" / f"{scoped_item_id}.json")
        scoped_saved = client.post(f"/api/generator/sessions/{scoped_session['session_id']}/confirm").json()
        assert_true(scoped_saved.get("ok"), f"product-scoped confirm should be ok: {scoped_saved}")
        scoped_items = client.get("/api/knowledge/categories/product_rules/items").json().get("items", [])
        assert_true(scoped_item_id in {item.get("id") for item in scoped_items}, "generated product-scoped rule should be visible")

        missing = client.post(
            "/api/generator/sessions",
            json={"message": "\u65b0\u589e\u5546\u54c1\uff1a\u795e\u79d8\u5546\u54c1", "use_llm": False},
        ).json()
        assert_true(missing.get("ok"), f"incomplete generator session should be ok: {missing}")
        created_session_ids.append(missing["session"]["session_id"])
        assert_equal(missing["session"].get("status"), "collecting", "incomplete generator input should ask follow-up")
        assert_equal(missing["session"].get("intake", {}).get("status"), "needs_more_info", "incomplete generator input should be temporarily stored")
        assert_true("price" in set(missing["session"].get("missing_fields", [])), "generator should ask for missing price")

        policy_message = (
            "\u5982\u679c\u7528\u6237\u8981\u6c42\u8f6c\u4eba\u5de5\u670d\u52a1\uff0c"
            "\u6216\u8005\u95ee\u4eba\u5de5\u5ba2\u670d\u5728\u4e0d\u5728\uff0c"
            "\u8981\u660e\u786e\u7684\u56de\u590d\uff1a\u5df2\u8f6c\u4eba\u5de5\u5ba2\u670d\uff0c"
            "\u7ebf\u8def\u5207\u6362\u4e2d\uff0c\u8bf7\u7a0d\u5019\u7247\u523b\u3002"
        )
        policy = client.post(
            "/api/generator/sessions",
            json={"message": policy_message, "preferred_category_id": "policies", "use_llm": False},
        ).json()
        assert_true(policy.get("ok"), f"policy generator session should be ok: {policy}")
        policy_session = policy["session"]
        created_session_ids.append(policy_session["session_id"])
        policy_data = policy_session["draft_item"]["data"]
        assert_equal(
            policy_data.get("answer"),
            "\u5df2\u8f6c\u4eba\u5de5\u5ba2\u670d\uff0c\u7ebf\u8def\u5207\u6362\u4e2d\uff0c\u8bf7\u7a0d\u5019\u7247\u523b\u3002",
            "policy generator should extract only the customer-facing reply",
        )
        assert_true(
            "trigger_conditions" in (policy_data.get("additional_details") or {}),
            "policy generator should preserve trigger conditions outside the reply",
        )
        edited_answer = "\u5df2\u4e3a\u60a8\u8f6c\u63a5\u4eba\u5de5\u5ba2\u670d\uff0c\u8bf7\u7a0d\u7b49\uff0c\u6211\u4f1a\u5e2e\u60a8\u8ddf\u8fdb\u3002"
        policy_data["answer"] = edited_answer
        patched = client.patch(f"/api/generator/sessions/{policy_session['session_id']}/draft", json={"data": policy_data}).json()
        assert_true(patched.get("ok"), f"generator draft edit should be ok: {patched}")
        assert_equal(
            patched["session"]["draft_item"]["data"].get("answer"),
            edited_answer,
            "generator draft edit should persist user-adjusted wording",
        )

        locked_faq = compile_faq(
            {
                "id": "unit_auto_disabled",
                "category_id": "policies",
                "data": {
                    "keywords": ["unit-test"],
                    "answer": "internal only",
                    "allow_auto_reply": False,
                    "requires_handoff": False,
                },
                "runtime": {"allow_auto_reply": True, "requires_handoff": False, "risk_level": "normal"},
            }
        )
        assert_true(bool(locked_faq.get("needs_handoff")), "allow_auto_reply=false should compile as a hard handoff gate")
        assert_equal(locked_faq.get("auto_reply_allowed"), False, "compiled FAQ should expose auto reply gate")

        folding = client.post(
            "/api/generator/sessions",
            json={
                "message": (
                    "新增商品：折叠床；\n"
                    "具体描述：带床垫单人可折叠便携式家用酒店加床记忆海绵午睡床；\n"
                    "售价：499\n"
                    "重量：13kg"
                ),
                "use_llm": False,
            },
        ).json()
        folding_session = folding["session"]
        created_session_ids.append(folding_session["session_id"])
        assert_equal(folding_session.get("status"), "ready", "folding-bed first message should be ready")
        followup = client.post(
            f"/api/generator/sessions/{folding_session['session_id']}/messages",
            json={"message": "阶梯价格：第一档1张，499元，第二档10张，450元；48小时发货", "use_llm": False},
        ).json()
        folding_data = followup["session"]["draft_item"]["data"]
        assert_equal(followup["session"].get("status"), "ready", "folding-bed tier follow-up should stay ready")
        assert_equal(folding_data.get("name"), "折叠床", "tier follow-up should not overwrite product name")
        tiers = folding_data.get("price_tiers", [])
        assert_equal(len(tiers), 2, "folding-bed tier follow-up should parse two tiers")
        assert_equal(tiers[0]["min_quantity"], 1.0, "first tier quantity")
        assert_equal(tiers[1]["unit_price"], 450.0, "second tier price")
    finally:
        for path in created_item_paths:
            if path.exists():
                path.unlink()
        cleanup_generator_sessions(created_session_ids)
        KnowledgeCompiler().compile_to_disk()


def check_upload_learning_candidate_apply_and_reject(client: TestClient) -> None:
    created_version_ids: list[str] = []
    cleanup_admin_check_artifacts()
    try:
        check_duplicate_candidate_detection_and_learning_skip()
        check_mixed_text_upload_candidate_generation()
        check_company_profile_classification_and_reclassify(client)
        check_llm_upload_hallucination_falls_back_to_local_parse()

        empty_job = client.post("/api/learning/jobs", json={"upload_ids": []}).json()
        assert_true(empty_job.get("ok"), f"empty learning job should be ok: {empty_job}")
        assert_equal(empty_job["job"]["candidate_count"], 0, "empty learning job should not relearn all uploads")
        missing_apply = client.post("/api/candidates/missing_candidate/apply")
        assert_equal(missing_apply.status_code, 404, "missing candidate apply should return 404")
        excel_upload = client.post(
            "/api/uploads",
            data={"kind": "products"},
            files={
                "file": (
                    "admin_excel_upload_test.xlsx",
                    build_admin_excel_upload(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        ).json()
        assert_true(excel_upload.get("ok"), f"xlsx upload should be ok: {excel_upload}")
        assert_equal(excel_upload["item"].get("stored_suffix"), ".txt", "xlsx upload should be normalized to text")
        batch_upload = client.post(
            "/api/uploads/batch",
            data={"kind": "products"},
            files=[
                ("files", ("admin_batch_upload_one.txt", "商品：批量上传测试A\n价格：11元".encode("utf-8"), "text/plain")),
                ("files", ("admin_batch_upload_two.txt", "商品：批量上传测试B\n价格：22元".encode("utf-8"), "text/plain")),
            ],
        ).json()
        assert_true(batch_upload.get("ok"), f"batch upload should be ok: {batch_upload}")
        assert_equal(batch_upload.get("count"), 2, "batch upload should accept multiple files")
        assert_equal(len(batch_upload.get("items", [])), 2, "batch upload should persist both files")
        delete_upload = client.post(
            "/api/uploads",
            data={"kind": "products"},
            files={"file": ("admin_delete_upload_test.txt", "商品：待删除测试资料\n价格：123元".encode("utf-8"), "text/plain")},
        ).json()
        assert_true(delete_upload.get("ok"), f"delete-test upload should be ok: {delete_upload}")
        delete_upload_id = delete_upload["item"]["upload_id"]
        delete_upload_path = Path(delete_upload["item"]["path"])
        assert_true(delete_upload_path.exists(), "uploaded raw file should exist before delete")
        deleted = client.delete(f"/api/uploads/{delete_upload_id}").json()
        assert_true(deleted.get("ok"), f"upload delete should be ok: {deleted}")
        assert_true(deleted.get("deleted_file") is True, f"upload delete should remove raw file: {deleted}")
        assert_true(not delete_upload_path.exists(), "uploaded raw file should be removed after delete")
        after_delete_uploads = client.get("/api/uploads").json().get("items", [])
        assert_true(delete_upload_id not in {item.get("upload_id") for item in after_delete_uploads}, "deleted upload should leave upload index")
        missing_upload_delete = client.delete(f"/api/uploads/{delete_upload_id}")
        assert_equal(missing_upload_delete.status_code, 404, "deleting missing upload should return 404")
        excel_job = client.post("/api/learning/jobs", json={"upload_ids": [excel_upload["item"]["upload_id"]]}).json()
        assert_true(excel_job.get("ok"), f"xlsx learning job should be ok: {excel_job}")
        product_candidates = [
            item for item in excel_job.get("candidates", []) if item.get("proposal", {}).get("formal_patch", {}).get("target_category") == "products"
        ]
        assert_true(len(product_candidates) >= 2, "xlsx learning should split multiple product rows into multiple candidates")
        product_candidate = product_candidates[0]
        assert_true(product_candidate.get("review", {}).get("rag_evidence", {}).get("enabled") is True, "upload learning should attach rag evidence")
        assert_true(product_candidate.get("source", {}).get("rag_hits"), "upload candidate should expose compact rag hits")
        product_id = product_candidate["proposal"]["formal_patch"]["item"]["id"]
        product_apply = client.post(f"/api/candidates/{product_candidate['candidate_id']}/apply").json()
        assert_true(product_apply.get("ok"), f"xlsx product candidate apply should be ok: {product_apply}")
        product_snapshot_id = product_apply["snapshot"]["version_id"]
        created_version_ids.append(product_snapshot_id)
        pending_after_product_apply = client.get("/api/candidates", params={"status": "pending"}).json().get("items", [])
        assert_true(
            product_candidate["candidate_id"] not in {item.get("candidate_id") for item in pending_after_product_apply},
            "applied product candidate should leave pending list",
        )
        category_products = client.get("/api/knowledge/categories/products/items").json().get("items", [])
        assert_true(product_id in {item.get("id") for item in category_products}, "applied xlsx product should be visible in product category")
        compiled_products = client.get("/api/knowledge/products").json().get("items", [])
        assert_true(product_id in {item.get("id") for item in compiled_products}, "applied xlsx product should be visible in compiled product API")
        saved_product = next(item for item in category_products if item.get("id") == product_id)
        assert_true(saved_product.get("data", {}).get("additional_details"), "applied xlsx product should preserve extra details")
        product_rollback = client.post(f"/api/versions/{product_snapshot_id}/rollback").json()
        assert_true(product_rollback.get("ok"), f"xlsx product rollback should be ok: {product_rollback}")
        backup_id = product_rollback.get("backup", {}).get("version_id")
        if backup_id:
            created_version_ids.append(backup_id)
        wrong_kind_policy = client.post(
            "/api/uploads",
            data={"kind": "products"},
            files={"file": ("admin_policy_under_products.txt", "开票规则：客户要求专票时，需要提供公司名称、税号、地址电话和开户行。".encode("utf-8"), "text/plain")},
        ).json()
        policy_job = client.post("/api/learning/jobs", json={"upload_ids": [wrong_kind_policy["item"]["upload_id"]]}).json()
        policy_candidate = policy_job["candidates"][0]
        assert_equal(policy_candidate["proposal"]["formal_patch"]["target_category"], "policies", "policy content uploaded under products should classify into policies")

        incomplete_upload = client.post(
            "/api/uploads",
            data={"kind": "products"},
            files={"file": ("admin_incomplete_product.txt", "商品：暂存缺价测试商品\n规格：超轻铝合金，支持定制颜色。".encode("utf-8"), "text/plain")},
        ).json()
        incomplete_job = client.post("/api/learning/jobs", json={"upload_ids": [incomplete_upload["item"]["upload_id"]]}).json()
        incomplete_candidate = incomplete_job["candidates"][0]
        assert_equal(incomplete_candidate.get("intake", {}).get("status"), "needs_more_info", "incomplete upload should be kept as needs-more-info candidate")
        assert_true("price" in set(incomplete_candidate.get("intake", {}).get("missing_fields", [])), "incomplete upload should ask for missing price")
        incomplete_apply_response = client.post(f"/api/candidates/{incomplete_candidate['candidate_id']}/apply")
        assert_equal(incomplete_apply_response.status_code, 400, "incomplete candidate apply should return 400")
        incomplete_apply = incomplete_apply_response.json().get("detail", {})
        assert_true(incomplete_apply.get("ok") is False, "incomplete candidate should not apply")
        supplement_data = dict(incomplete_candidate["proposal"]["formal_patch"]["item"]["data"])
        supplement_data.update({"price": 38, "unit": "件"})
        supplemented = client.post(
            f"/api/candidates/{incomplete_candidate['candidate_id']}/supplement",
            json={"data": supplement_data},
        ).json()
        assert_true(supplemented.get("ok"), f"incomplete candidate supplement should be ok: {supplemented}")
        assert_equal(supplemented["item"].get("intake", {}).get("status"), "ready", "supplemented candidate should become ready")
        completed_apply = client.post(f"/api/candidates/{incomplete_candidate['candidate_id']}/apply").json()
        assert_true(completed_apply.get("ok"), f"supplemented candidate apply should be ok: {completed_apply}")
        product_snapshot_id = completed_apply["snapshot"]["version_id"]
        created_version_ids.append(product_snapshot_id)
        product_rollback = client.post(f"/api/versions/{product_snapshot_id}/rollback").json()
        assert_true(product_rollback.get("ok"), f"supplemented product rollback should be ok: {product_rollback}")
        backup_id = product_rollback.get("backup", {}).get("version_id")
        if backup_id:
            created_version_ids.append(backup_id)
        style_content = "客户：你们客服还挺快的\n客服：哈哈谢谢，您需要查商品、报价或发货售后都可以直接发我。"
        upload = client.post(
            "/api/uploads",
            data={"kind": "chats"},
            files={"file": ("admin_style_sample.txt", style_content.encode("utf-8"), "text/plain")},
        ).json()
        assert_true(upload.get("ok"), f"upload should be ok: {upload}")
        upload_id = upload["item"]["upload_id"]
        job = client.post("/api/learning/jobs", json={"upload_ids": [upload_id]}).json()
        assert_true(job.get("ok"), f"learning job should be ok: {job}")
        candidate_ids = job["job"]["candidate_ids"]
        assert_true(bool(candidate_ids), "learning should create at least one candidate")
        candidate_id = candidate_ids[0]
        pending = client.get("/api/candidates", params={"status": "pending"}).json().get("items", [])
        assert_true(candidate_id in {item.get("candidate_id") for item in pending}, "candidate should appear in pending list")
        applied = client.post(f"/api/candidates/{candidate_id}/apply").json()
        assert_true(applied.get("ok"), f"candidate apply should be ok: {applied}")
        snapshot_id = applied["snapshot"]["version_id"]
        created_version_ids.append(snapshot_id)
        pending_after_apply = client.get("/api/candidates", params={"status": "pending"}).json().get("items", [])
        assert_true(candidate_id not in {item.get("candidate_id") for item in pending_after_apply}, "applied chat candidate should leave pending list")
        style_id = applied["item"]["proposal"]["formal_patch"]["item"]["id"]
        after_apply = client.get("/api/knowledge/styles").json().get("items", [])
        assert_true(style_id in {item.get("id") for item in after_apply}, "candidate style should be visible after apply")
        rollback = client.post(f"/api/versions/{snapshot_id}/rollback").json()
        assert_true(rollback.get("ok"), f"candidate rollback should be ok: {rollback}")
        backup_id = rollback.get("backup", {}).get("version_id")
        if backup_id:
            created_version_ids.append(backup_id)

        reject_content = "客户：能不能月底结账\n客服：账期需要人工审核，不能自动承诺。"
        reject_upload = client.post(
            "/api/uploads",
            data={"kind": "chats"},
            files={"file": ("admin_reject_sample.txt", reject_content.encode("utf-8"), "text/plain")},
        ).json()
        reject_job = client.post("/api/learning/jobs", json={"upload_ids": [reject_upload["item"]["upload_id"]]}).json()
        reject_id = reject_job["job"]["candidate_ids"][0]
        rejected = client.post(f"/api/candidates/{reject_id}/reject", json={"reason": "admin check reject"}).json()
        assert_true(rejected.get("ok"), "candidate reject should be ok")
        rejected_items = client.get("/api/candidates", params={"status": "rejected"}).json().get("items", [])
        assert_true(reject_id in {item.get("candidate_id") for item in rejected_items}, "candidate should appear in rejected list")
    finally:
        cleanup_admin_check_artifacts()
        for version_id in created_version_ids:
            remove_version_snapshot(version_id)


def check_duplicate_candidate_detection_and_learning_skip() -> None:
    check_knowledge_consistency_diagnostics()
    existing = json.loads((KNOWLEDGE_BASE_ROOT / "products" / "items" / "commercial_fridge_bx_200.json").read_text(encoding="utf-8"))
    candidate = {
        "schema_version": 1,
        "candidate_id": "admin_duplicate_candidate_probe",
        "proposal": {
            "summary": "重复商品探针",
            "formal_patch": {
                "target_category": "products",
                "operation": "upsert_item",
                "item": existing,
            },
        },
        "review": {"status": "pending"},
    }
    duplicate = KnowledgeDeduper().check_candidate(candidate)
    assert_true(duplicate.get("duplicate"), f"deduper should detect existing product duplicate: {duplicate}")

    existing_data = existing.get("data", {})
    partial_candidate = {
        "schema_version": 1,
        "candidate_id": "admin_partial_duplicate_candidate_probe",
        "proposal": {
            "summary": "partial tier duplicate probe",
            "formal_patch": {
                "target_category": "products",
                "operation": "upsert_item",
                "item": {
                    "schema_version": 1,
                    "category_id": "products",
                    "id": "commercial_fridge_bx_200-price-tiers",
                    "status": "active",
                    "data": {
                        "name": existing_data.get("name"),
                        "sku": existing_data.get("sku"),
                        "price_tiers": existing_data.get("price_tiers", [])[:1],
                    },
                    "runtime": {"allow_auto_reply": True, "requires_handoff": False, "risk_level": "normal"},
                },
            },
        },
        "review": {"status": "pending"},
    }
    partial_duplicate = KnowledgeDeduper().check_candidate(partial_candidate)
    assert_true(partial_duplicate.get("duplicate"), f"deduper should detect same-SKU partial tier duplicate: {partial_duplicate}")

    class FakeUploads:
        def __init__(self) -> None:
            self.marked: list[tuple[list[str], list[str]]] = []

        def list_uploads(self) -> list[dict[str, Any]]:
            return [{"upload_id": "admin_duplicate_upload", "path": str(TEST_ARTIFACTS / "admin_duplicate_upload.txt")}]

        def mark_learned(self, upload_ids: list[str], candidate_ids: list[str]) -> None:
            self.marked.append((upload_ids, candidate_ids))

    original_build = learning_service_module.build_candidates
    fake_uploads = FakeUploads()
    try:
        learning_service_module.build_candidates = lambda path, use_llm=False: [candidate]
        service = LearningService()
        service.uploads = fake_uploads
        result = service.create_job(["admin_duplicate_upload"], use_llm=False)
    finally:
        learning_service_module.build_candidates = original_build
    assert_true(result.get("ok"), f"duplicate learning job should complete: {result}")
    assert_equal(result["job"]["candidate_count"], 0, "duplicate candidate should not be written as pending")
    assert_equal(result["job"]["skipped_duplicate_count"], 1, "duplicate candidate should be counted as skipped")
    assert_true(not (APP_ROOT / "data" / "review_candidates" / "pending" / "admin_duplicate_candidate_probe.json").exists(), "duplicate pending candidate file should not be created")


def check_knowledge_consistency_diagnostics() -> None:
    base_item = {
        "schema_version": 1,
        "category_id": "products",
        "id": "admin_conflict_product_a",
        "status": "active",
        "data": {"name": "冲突检测测试商品", "sku": "admin-conflict-sku", "price": 100, "unit": "件"},
        "runtime": {"allow_auto_reply": True, "requires_handoff": False, "risk_level": "normal"},
    }
    conflict_item = {
        **base_item,
        "id": "admin_conflict_product_b",
        "data": {"name": "冲突检测测试商品", "sku": "admin-conflict-sku", "price": 120, "unit": "件"},
    }
    duplicate_item = {
        **base_item,
        "id": "admin_conflict_product_c",
    }
    service = DiagnosticsService()
    conflict_issues = service.detect_consistency_issues("products", [base_item, conflict_item])
    assert_true(
        any(issue.get("code") == "knowledge_potential_conflict" for issue in conflict_issues),
        f"diagnostics should flag same-SKU conflicting product fields: {conflict_issues}",
    )
    duplicate_issues = service.detect_consistency_issues("products", [base_item, duplicate_item])
    assert_true(
        any(issue.get("code") == "knowledge_potential_duplicate" for issue in duplicate_issues),
        f"diagnostics should flag duplicate product knowledge: {duplicate_issues}",
    )


def check_mixed_text_upload_candidate_generation() -> None:
    TEST_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = TEST_ARTIFACTS / "admin_mixed_sections_probe.txt"
    text = (
        "商品资料：防静电周转箱，蓝色，30L，PP材质。单价68元/个，10个起65元/个，24小时发货。\n"
        "政策规则：定制尺寸确认生产后不支持无理由退换；质量问题签收后48小时内拍照反馈。\n"
        "商品资料：仓储标签夹，100只装，适配货架横梁，暂时没有给价格。"
    )
    try:
        path.write_text(text, encoding="utf-8")
        candidates = review_candidate_generator.build_candidates(path, use_llm=False)
    finally:
        path.unlink(missing_ok=True)
    categories = [item["proposal"]["formal_patch"]["target_category"] for item in candidates]
    assert_equal(len(candidates), 3, "mixed text upload should split labeled sections into candidates")
    assert_equal(categories.count("products"), 2, "mixed text upload should create two product candidates")
    assert_equal(categories.count("policies"), 1, "mixed text upload should create one policy candidate")
    incomplete = [item for item in candidates if item.get("intake", {}).get("status") == "needs_more_info"]
    assert_true(bool(incomplete), "mixed text upload should keep incomplete product as pending candidate")
    assert_true("price" in set(incomplete[0].get("intake", {}).get("missing_fields", [])), "incomplete mixed product should ask for price")


def check_company_profile_classification_and_reclassify(client: TestClient) -> None:
    payload = {
        "name": "杭州云桥办公设备有限公司",
        "category": "办公设备",
        "additional_details": {
            "主营范围": "办公家具、智能门锁、空气净化设备、会议室配套设备",
            "对外客服人设": "耐心、简洁、专业，不主动夸大效果",
        },
    }
    TEST_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    source_path = TEST_ARTIFACTS / "admin_company_profile_probe.json"
    candidate_id = "admin_company_reclassify_probe"
    candidate_path = APP_ROOT / "data" / "review_candidates" / "pending" / f"{candidate_id}.json"
    try:
        source_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        candidates = review_candidate_generator.build_candidates(source_path, use_llm=False)
        assert_true(candidates, "company profile upload should create a candidate")
        generated = candidates[0]
        generated_patch = generated["proposal"]["formal_patch"]
        assert_equal(generated_patch["target_category"], "policies", "company profile should classify into policies")
        assert_equal(generated_patch["item"]["data"].get("policy_type"), "company", "company profile should use company policy type")
        assert_true("price" not in set(generated.get("intake", {}).get("missing_fields", [])), "company profile should not ask for product price")

        llm_record = {"category_id": "products", "summary": "company profile", "data": payload, "missing_fields": [], "warnings": []}
        llm_candidate = review_candidate_generator.candidate_from_llm_record(source_path, json.dumps(payload, ensure_ascii=False), ["company", "llm"], llm_record, 0)
        assert_true(llm_candidate is not None, "misclassified LLM company profile should still produce a candidate")
        assert_equal(llm_candidate["proposal"]["formal_patch"]["target_category"], "policies", "misclassified LLM company profile should be corrected to policies")

        wrong_candidate = {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "generated_at": "2026-04-27T00:00:00",
            "source": {"path": str(source_path), "suffix": ".json", "evidence_excerpt": json.dumps(payload, ensure_ascii=False)},
            "detected_tags": ["company"],
            "proposal": {
                "target_category": "products",
                "change_type": "llm_upsert_products",
                "summary": "公司名称和主营范围",
                "suggested_fields": payload,
                "formal_patch": {
                    "target_category": "products",
                    "operation": "upsert_item",
                    "item": {
                        "schema_version": 1,
                        "category_id": "products",
                        "id": "company-profile-probe",
                        "status": "active",
                        "source": {"type": "test"},
                        "data": payload,
                        "runtime": {"allow_auto_reply": True, "requires_handoff": False, "risk_level": "normal"},
                    },
                },
            },
            "intake": {"status": "needs_more_info", "missing_fields": ["price", "unit"], "missing_labels": ["基础价格", "计价单位"]},
            "review": {"status": "pending", "completeness_status": "needs_more_info", "missing_fields": ["price", "unit"]},
        }
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_text(json.dumps(wrong_candidate, ensure_ascii=False, indent=2), encoding="utf-8")
        changed = client.post(f"/api/candidates/{candidate_id}/category", json={"target_category": "policies"}).json()
        assert_true(changed.get("ok"), f"candidate category correction should be ok: {changed}")
        changed_item = changed["item"]
        changed_patch = changed_item["proposal"]["formal_patch"]
        assert_equal(changed_patch["target_category"], "policies", "candidate correction should update target category")
        assert_equal(changed_patch["item"]["data"].get("policy_type"), "company", "candidate correction should preserve company semantics")
        assert_equal(changed_item.get("intake", {}).get("status"), "ready", "corrected company candidate should be ready")
        assert_true("price" not in set(changed_item.get("intake", {}).get("missing_fields", [])), "corrected company candidate should not ask for price")
    finally:
        source_path.unlink(missing_ok=True)
        candidate_path.unlink(missing_ok=True)


def check_llm_upload_hallucination_falls_back_to_local_parse() -> None:
    TEST_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    path = TEST_ARTIFACTS / "admin_llm_hallucination_probe.txt"
    text = "商品资料：真实周转箱，30L，PP材质。单价10元/个。"
    original_call = review_candidate_generator.call_deepseek_json
    try:
        path.write_text(text, encoding="utf-8")
        review_candidate_generator.call_deepseek_json = lambda prompt: {
            "items": [
                {
                    "category_id": "products",
                    "summary": "模型幻觉商品",
                    "data": {"name": "不存在的塑料袋", "price": 1, "unit": "个"},
                }
            ]
        }
        candidates = review_candidate_generator.build_candidates(path, use_llm=True)
    finally:
        review_candidate_generator.call_deepseek_json = original_call
        path.unlink(missing_ok=True)
    assert_true(bool(candidates), "hallucinated LLM upload should fall back to local parsing")
    item = candidates[0]["proposal"]["formal_patch"]["item"]
    assert_equal(item.get("source", {}).get("type"), "raw_upload", "ungrounded LLM upload candidate should not be trusted")
    assert_equal(item.get("data", {}).get("name"), "真实周转箱", "fallback should preserve source-grounded product name")


def cleanup_admin_check_artifacts() -> None:
    cleanup_admin_rag_artifacts()
    admin_candidate_ids: set[str] = set()
    for path in (APP_ROOT / "data" / "review_candidates").glob("*/*.json"):
        try:
            text = path.read_text(encoding="utf-8")
            item = json.loads(text)
        except (OSError, json.JSONDecodeError):
            continue
        if (
            "admin_style_sample" in text
            or "admin_reject_sample" in text
            or "admin_excel_upload_test" in text
            or "admin_delete_upload_test" in text
            or "admin_batch_upload" in text
            or "admin_policy_under_products" in text
            or "admin_incomplete_product" in text
            or "自动化测试折叠床" in text
            or "自动化测试折叠椅" in text
            or "暂存缺价测试商品" in text
            or "admin check reject" in text
        ):
            admin_candidate_ids.add(str(item.get("candidate_id") or ""))
    if ADMIN_DRAFTS_ROOT.exists():
        for path in ADMIN_DRAFTS_ROOT.glob("*.json"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if "admin check style add" in text or "admin_check_style_example" in text:
                path.unlink()
    if ADMIN_JOBS_ROOT.exists():
        for path in ADMIN_JOBS_ROOT.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            candidate_ids = set(item.get("candidate_ids", []) or [])
            upload_ids = set(item.get("upload_ids", []) or [])
            if (
                not upload_ids
                or "admin_duplicate_upload" in upload_ids
                or candidate_ids & admin_candidate_ids
                or candidate_ids & {"raw_21a591e25fe6324c", "raw_0580a07da6023919"}
            ):
                path.unlink()
    for path in (APP_ROOT / "data" / "raw_inbox").glob("*/*admin_*sample*"):
        if path.is_file():
            path.unlink()
    for path in (APP_ROOT / "data" / "raw_inbox").glob("*/*admin_excel_upload_test*"):
        if path.is_file():
            path.unlink()
    for path in (APP_ROOT / "data" / "raw_inbox").glob("*/*admin_delete_upload_test*"):
        if path.is_file():
            path.unlink()
    for path in (APP_ROOT / "data" / "raw_inbox").glob("*/*admin_batch_upload*"):
        if path.is_file():
            path.unlink()
    for path in (APP_ROOT / "data" / "raw_inbox").glob("*/*admin_policy_under_products*"):
        if path.is_file():
            path.unlink()
    for path in (APP_ROOT / "data" / "raw_inbox").glob("*/*admin_incomplete_product*"):
        if path.is_file():
            path.unlink()
    for path in (KNOWLEDGE_BASE_ROOT / "products" / "items").glob("*.json"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "自动化测试折叠床" in text or "自动化测试折叠椅" in text or "批量上传测试" in text or "暂存缺价测试商品" in text:
            path.unlink()
    for path in (APP_ROOT / "data" / "review_candidates").glob("*/*.json"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "admin_style_sample" in text or "admin_reject_sample" in text or "admin_excel_upload_test" in text or "admin_delete_upload_test" in text or "admin_batch_upload" in text or "admin_policy_under_products" in text or "admin_incomplete_product" in text or "admin check reject" in text:
            path.unlink()
    if ADMIN_UPLOAD_INDEX.exists():
        records = json.loads(ADMIN_UPLOAD_INDEX.read_text(encoding="utf-8"))
        records = [item for item in records if not str(item.get("filename") or "").startswith("admin_")]
        ADMIN_UPLOAD_INDEX.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def cleanup_admin_rag_artifacts() -> None:
    rag = RagService()
    for source in list(rag.list_sources()):
        source_path = str(source.get("source_path") or "")
        if "\\admin_" in source_path or "/admin_" in source_path or "admin_" in Path(source_path).name:
            rag.delete_source_by_path(Path(source_path))


def build_admin_excel_upload() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "products"
    worksheet.append(["商品", "型号", "价格", "单位", "发货", "库存", "安装城市说明"])
    worksheet.append(["自动化测试折叠床", "ZDC-TEST", "499元", "张", "48小时发货", "20", "一线城市可预约上门安装"])
    worksheet.append(["自动化测试折叠椅", "ZDY-TEST", "199元", "把", "24小时发货", "35", "偏远地区安装另询"])
    tiers = workbook.create_sheet("price_tiers")
    tiers.append(["型号", "起订数量", "单价"])
    tiers.append(["ZDC-TEST", 1, "499元"])
    tiers.append(["ZDC-TEST", 10, "450元"])
    tiers.append(["ZDY-TEST", 1, "199元"])
    tiers.append(["ZDY-TEST", 20, "170元"])
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def cleanup_generator_sessions(session_ids: list[str]) -> None:
    if not ADMIN_GENERATOR_ROOT.exists():
        return
    for session_id in session_ids:
        path = ADMIN_GENERATOR_ROOT / f"{session_id}.json"
        if path.exists():
            path.unlink()


def remove_diagnostic_ignore(fingerprint: str) -> None:
    if not DIAGNOSTIC_IGNORES_PATH.exists():
        return
    try:
        payload = json.loads(DIAGNOSTIC_IGNORES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(payload, dict) and fingerprint in payload:
        payload.pop(fingerprint, None)
        DIAGNOSTIC_IGNORES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def remove_version_snapshot(version_id: str) -> None:
    target = (VERSIONS_ROOT / version_id).resolve()
    root = VERSIONS_ROOT.resolve()
    if root not in target.parents or not target.exists():
        return
    shutil.rmtree(target)


def check_diagnostics_and_system_status(client: TestClient) -> None:
    created_version_ids: list[str] = []
    test_fingerprint = "b" * 24
    try:
        backup = client.post("/api/versions", json={"reason": "admin check manual backup"}).json()
        assert_true(backup.get("ok"), f"manual backup should be ok: {backup}")
        created_version_ids.append(backup["item"]["version_id"])

        quick = client.post("/api/diagnostics/run", json={"mode": "quick"}).json()
        assert_true("run_id" in quick, "quick diagnostics should return run id")
        assert_true(quick.get("status") in {"ok", "warning", "error"}, "quick diagnostics should return status")
        run_id = quick["run_id"]
        runs = client.get("/api/diagnostics/runs").json().get("items", [])
        assert_true(run_id in {item.get("run_id") for item in runs}, "diagnostic run should be listed")
        fetched = client.get(f"/api/diagnostics/runs/{run_id}").json().get("item")
        assert_equal(fetched.get("run_id"), run_id, "diagnostic run should be retrievable")
        repair = client.post(f"/api/diagnostics/runs/{run_id}/apply-suggestion", json={"source": "admin check"}).json()
        assert_true(repair.get("ok"), f"diagnostic repair should be safe: {repair}")
        ignored = client.post("/api/diagnostics/ignore", json={"fingerprint": test_fingerprint, "reason": "admin check ignore"}).json()
        assert_true(ignored.get("ok"), f"diagnostic ignore should be ok: {ignored}")
        ignores = client.get("/api/diagnostics/ignores").json().get("items", [])
        assert_true(test_fingerprint in {item.get("fingerprint") for item in ignores}, "diagnostic ignore should be listed")

        full = client.post("/api/diagnostics/run", json={"mode": "full"}).json()
        assert_true(full.get("checks"), "full diagnostics should include checks")
        check_names = {item.get("name") for item in full.get("checks", [])}
        assert_true("offline_regression" in check_names, "full diagnostics should run offline regression")
        assert_true("workflow_logic" in check_names, "full diagnostics should run workflow logic")

        status = client.get("/api/system/status").json()
        assert_true(status.get("ok"), "system status should be ok")
        assert_true("knowledge" in status, "system status should include knowledge overview")
        locks = client.get("/api/system/runtime-locks").json()
        assert_true("items" in locks, "runtime locks should return items")
    finally:
        remove_diagnostic_ignore(test_fingerprint)
        for version_id in created_version_ids:
            remove_version_snapshot(version_id)


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
