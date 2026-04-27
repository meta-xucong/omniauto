"""Generate review-only candidates from raw WeChat customer-service materials.

This workflow never edits formal structured business data directly. It scans raw
inbox files and produces evidence-bound candidates. Candidates are promoted only
after an operator approves/applies them in the admin console.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

try:  # pragma: no cover - supports package and script imports.
    from .knowledge_intake import evaluate_intake_item
except ImportError:  # pragma: no cover
    from knowledge_intake import evaluate_intake_item


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.knowledge_paths import default_admin_knowledge_base_root  # noqa: E402
from apps.wechat_ai_customer_service.workflows.knowledge_runtime import PRODUCT_SCOPED_SCHEMAS  # noqa: E402

RAW_INBOX_ROOT = APP_ROOT / "data" / "raw_inbox"
PENDING_ROOT = APP_ROOT / "data" / "review_candidates" / "pending"
SUPPORTED_SUFFIXES = {".txt", ".md", ".json", ".csv"}
DEFAULT_KINDS = {"products", "chats", "policies", "erp_exports", "product_faq", "product_rules", "product_explanations"}
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"

TAG_KEYWORDS: dict[str, list[str]] = {
    "product": ["产品", "商品", "型号", "规格", "库存", "现货", "sku"],
    "quote": ["价格", "报价", "多少钱", "单价", "元", "费用", "售价"],
    "discount": ["优惠", "折扣", "最低价", "便宜", "议价", "阶梯价"],
    "company": ["公司名称", "主营范围", "主营业务", "公司信息", "开票信息", "生产方", "厂家", "对外客服人设", "客服人设"],
    "invoice": ["发票", "开票", "专票", "普票", "税号"],
    "shipping": ["物流", "快递", "运费", "包邮", "发货", "到货"],
    "payment": ["付款", "支付", "对公", "转账", "账户"],
    "after_sales": ["售后", "保修", "质保", "退换", "退款"],
    "style": ["客户：", "客服：", "用户：", "回复："],
}

HEADER_ALIASES: dict[str, str] = {
    "商品": "name",
    "商品名称": "name",
    "产品": "name",
    "产品名称": "name",
    "名称": "name",
    "name": "name",
    "型号": "sku",
    "型号/sku": "sku",
    "sku": "sku",
    "商品类别": "category",
    "产品类别": "category",
    "类别": "category",
    "类目": "category",
    "category": "category",
    "别名": "aliases",
    "别名关键词": "aliases",
    "客户常用叫法": "aliases",
    "关键词": "aliases",
    "规格": "specs",
    "规格参数": "specs",
    "具体描述": "specs",
    "描述": "specs",
    "基础价格": "price",
    "价格": "price",
    "售价": "price",
    "单价": "unit_price",
    "计价单位": "unit",
    "单位": "unit",
    "库存": "inventory",
    "发货": "shipping_policy",
    "发货物流": "shipping_policy",
    "物流": "shipping_policy",
    "发货/物流": "shipping_policy",
    "售后": "warranty_policy",
    "保修": "warranty_policy",
    "售后保修": "warranty_policy",
    "售后/保修": "warranty_policy",
    "自动回复注意事项": "reply_note",
    "标准回复": "reply_note",
    "回复模板": "reply_note",
    "起订数量": "min_quantity",
    "起订量": "min_quantity",
    "数量": "min_quantity",
    "备注": "note",
    "客户问题": "customer_message",
    "客户": "customer_message",
    "用户问题": "customer_message",
    "客服回复": "service_reply",
    "客服": "service_reply",
    "回复": "service_reply",
    "意图标签": "intent_tags",
    "语气标签": "tone_tags",
    "规则名称": "title",
    "标题": "title",
    "规则类型": "policy_type",
    "类型": "policy_type",
    "触发关键词": "keywords",
    "答案": "answer",
    "回答": "answer",
    "允许自动回复": "allow_auto_reply",
    "必须转人工": "requires_handoff",
    "转人工原因": "handoff_reason",
    "提醒人工客服": "operator_alert",
    "风险等级": "risk_level",
    "来源系统": "source_system",
    "source_system": "source_system",
    "记录类型": "record_type",
    "record_type": "record_type",
    "外部编号": "external_id",
    "external_id": "external_id",
}

POLICY_TAG_TO_TYPE = {
    "company": "company",
    "invoice": "invoice",
    "shipping": "logistics",
    "payment": "payment",
    "after_sales": "after_sales",
    "discount": "discount",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=RAW_INBOX_ROOT)
    parser.add_argument("--pending-root", type=Path, default=PENDING_ROOT)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true", help="Preview candidates without writing files.")
    parser.add_argument("--write", action="store_true", help="Write candidates to the pending review directory.")
    args = parser.parse_args()

    result = generate_candidates(
        raw_root=args.raw_root,
        pending_root=args.pending_root,
        limit=args.limit,
        write=bool(args.write and not args.dry_run),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def generate_candidates(raw_root: Path, pending_root: Path, limit: int, write: bool) -> dict[str, Any]:
    files = list(iter_raw_files(raw_root))[: max(1, limit)]
    candidates: list[dict[str, Any]] = []
    for path in files:
        candidates.extend(build_candidates(path))
    written = []
    if write:
        pending_root.mkdir(parents=True, exist_ok=True)
        for candidate in candidates:
            output_path = pending_root / f"{candidate['candidate_id']}.json"
            output_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written.append(str(output_path))

    return {
        "ok": True,
        "dry_run": not write,
        "raw_root": str(raw_root),
        "pending_root": str(pending_root),
        "files_seen": len(files),
        "candidate_count": len(candidates),
        "written": written,
        "candidates": candidates,
    }


def iter_raw_files(raw_root: Path) -> list[Path]:
    if not raw_root.exists():
        return []
    files = []
    for path in raw_root.rglob("*"):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(path)
    return sorted(files)


def candidate_build_order(raw_kind: str, tags: list[str], text: str) -> list[str]:
    scores = {
        "products": 0,
        "chats": 0,
        "policies": 0,
        "erp_exports": 0,
    }
    tag_set = set(tags)
    if tag_set & {"product", "quote"}:
        scores["products"] += 3
    if "style" in tag_set:
        scores["chats"] += 4
    if tag_set & {"invoice", "shipping", "payment", "after_sales", "discount"}:
        scores["policies"] += 4
    if "company" in tag_set or looks_like_company_profile_text(text):
        scores["policies"] += 6
        scores["products"] -= 4
    if any(keyword in text.lower() for keyword in ["erp", "订单", "外部编号", "同步状态", "source_system"]):
        scores["erp_exports"] += 4
    if raw_kind in scores:
        scores[raw_kind] += 1
    if raw_kind == "products" and not has_product_signal(text):
        scores["products"] -= 2
    ordered = sorted(scores, key=lambda kind: (scores[kind], kind == raw_kind), reverse=True)
    return [kind for kind in ordered if scores[kind] > 0] or [raw_kind or "policies"]


def has_product_signal(text: str) -> bool:
    return bool(re.search(r"(商品|产品|型号|sku|SKU|规格|售价|单价|库存)", text))


def looks_like_company_profile_text(text: str) -> bool:
    normalized = str(text or "")
    company_signals = ["公司名称", "主营范围", "主营业务", "公司信息", "对外客服人设", "客服人设", "生产方", "厂家", "开票信息"]
    return any(signal in normalized for signal in company_signals) or bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9（）()]+(?:有限公司|有限责任公司|股份有限公司)", normalized))


def build_candidate(path: Path, *, use_llm: bool = False) -> dict[str, Any] | None:
    candidates = build_candidates(path, use_llm=use_llm)
    return candidates[0] if candidates else None


def build_candidates(path: Path, *, use_llm: bool = False) -> list[dict[str, Any]]:
    text = read_text(path)
    if not text.strip():
        return []
    raw_kind = infer_raw_kind(path)
    tags = detect_tags(text) or ["unknown"]
    if use_llm:
        llm_candidates = build_llm_candidates(path, text, tags, raw_kind)
        if llm_candidates:
            return llm_candidates

    section_candidates = build_labeled_section_candidates(path, text, tags)
    if section_candidates:
        return section_candidates

    builders = {
        "products": build_product_candidates,
        "chats": build_chat_candidates,
        "policies": build_policy_candidates,
        "erp_exports": build_erp_candidates,
    }
    for kind in candidate_build_order(raw_kind, tags, text):
        candidates = builders[kind](path, text, tags)
        if candidates:
            return candidates

    if "style" in tags:
        candidates = build_chat_candidates(path, text, tags)
        if candidates:
            return candidates
    if set(tags) & {"invoice", "shipping", "payment", "after_sales", "discount"}:
        candidates = build_policy_candidates(path, text, tags)
        if candidates:
            return candidates
    if set(tags) & {"product", "quote"}:
        candidates = build_product_candidates(path, text, tags)
        if candidates:
            return candidates
    return [build_manual_policy_candidate(path, text, tags)]


def build_labeled_section_candidates(path: Path, text: str, tags: list[str]) -> list[dict[str, Any]]:
    builders = {
        "products": build_product_candidates,
        "chats": build_chat_candidates,
        "policies": build_policy_candidates,
        "erp_exports": build_erp_candidates,
    }
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for section in split_labeled_sections(text):
        builder = builders.get(section["kind"])
        if not builder:
            continue
        section_tags = sorted(set([*tags, section["kind"].removesuffix("s")]))
        for candidate in builder(path, section["text"], section_tags):
            candidate_id = str(candidate.get("candidate_id") or "")
            if candidate_id and candidate_id in seen_ids:
                continue
            seen_ids.add(candidate_id)
            candidates.append(candidate)
    return candidates


def split_labeled_sections(text: str) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    current_kind = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_kind, current_lines
        body = "\n".join(line for line in current_lines if line.strip()).strip()
        if current_kind and body:
            sections.append({"kind": current_kind, "text": body})
        current_kind = ""
        current_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        kind = labeled_section_kind(line)
        if kind:
            flush()
            current_kind = kind
            current_lines = [line]
        elif current_kind:
            current_lines.append(line)
    flush()
    return sections if len(sections) > 1 else []


def labeled_section_kind(line: str) -> str:
    patterns = [
        ("products", r"^(?:商品资料|产品资料|新增商品|商品|产品)\s*[:：]"),
        ("policies", r"^(?:政策规则|规则|政策|售后规则|发货规则|物流政策|开票政策|付款政策|退换规则)\s*[:：]"),
        ("chats", r"^(?:话术|客服话术|聊天记录|客户问|客服回复)\s*[:：]"),
        ("erp_exports", r"^(?:ERP导出|ERP记录|订单记录|客户记录)\s*[:：]"),
    ]
    for kind, pattern in patterns:
        if re.search(pattern, line, flags=re.IGNORECASE):
            return kind
    return ""


def build_product_candidates(path: Path, text: str, tags: list[str]) -> list[dict[str, Any]]:
    rows = product_rows_from_content(path, text)
    tier_rows = tier_rows_from_content(path, text)
    candidates = []
    for index, row in enumerate(rows):
        data = product_data_from_row(row)
        if not data.get("name"):
            continue
        tiers = tiers_for_product(data, tier_rows)
        tiers.extend(inline_price_tiers_from_text(str(row.get("raw_text") or row_to_evidence(row))))
        if data.get("price") is not None:
            tiers.append({"min_quantity": 1.0, "unit_price": data["price"]})
        tiers = unique_price_tiers(tiers)
        if tiers:
            data["price_tiers"] = tiers
        item_id = safe_item_id(str(data.get("sku") or data.get("name") or ""), fallback_seed=f"{path}:{index}:{data}")
        item = {
            "schema_version": 1,
            "category_id": "products",
            "id": item_id,
            "status": "active",
            "source": {"type": "raw_upload", "path": str(path)},
            "data": data,
            "runtime": product_runtime_flags_from_data(data),
        }
        candidates.append(
            make_native_candidate(
                path=path,
                text=text,
                tags=sorted(set([*tags, "product"])),
                category_id="products",
                item=item,
                discriminator=f"products:{item_id}:{index}",
                summary=f"建议新增/更新商品：{data.get('name')}",
                change_type="upsert_product",
                evidence_excerpt=compact_excerpt(row_to_evidence(row), 360),
                suggested_tests=[{"scenario": "product_quote", "assertion": "入库后应能按商品名称、别名或 SKU 回答报价、规格和发货信息。"}],
            )
        )
    return candidates


def product_rows_from_content(path: Path, text: str) -> list[dict[str, Any]]:
    json_rows = rows_from_json(path, text)
    if json_rows:
        return [canonicalize_row(row) for row in json_rows if row and not looks_like_company_profile_row(canonicalize_row(row), text)]
    tables = parse_tables(text)
    product_rows: list[dict[str, Any]] = []
    for table in tables:
        name = table["name"].lower()
        rows = [canonicalize_row(row) for row in table["rows"]]
        rows = [row for row in rows if not looks_like_company_profile_row(row, text)]
        if "tier" in name or "阶梯" in name or "价格档" in name:
            continue
        if any(token in name for token in ("product", "products", "商品", "产品")):
            product_rows.extend(rows)
            continue
        if any(row.get("name") for row in rows):
            product_rows.extend(rows)
    if product_rows:
        return product_rows
    product = free_text_product_row(text)
    return [product] if product.get("name") else []


def tier_rows_from_content(path: Path, text: str) -> list[dict[str, Any]]:
    rows = []
    for table in parse_tables(text):
        name = table["name"].lower()
        canonical_rows = [canonicalize_row(row) for row in table["rows"]]
        if any(token in name for token in ("tier", "price", "价格", "阶梯")):
            rows.extend(canonical_rows)
            continue
        if any("min_quantity" in row and ("unit_price" in row or "price" in row) for row in canonical_rows):
            rows.extend(canonical_rows)
    return rows


def product_data_from_row(row: dict[str, Any]) -> dict[str, Any]:
    price = number_from_text(row.get("price")) if row.get("price") is not None else number_from_text(row.get("unit_price"))
    inventory = number_from_text(row.get("inventory"))
    reply_note = clean_text(row.get("reply_note"))
    risk_rules = split_tags(row.get("risk_rules"))
    if reply_note and any(word in reply_note for word in ["人工", "上级", "不能", "不可", "禁止", "确认", "承诺"]):
        risk_rules.append(reply_note)
    data = compact_dict(
        {
            "name": clean_text(row.get("name")),
            "sku": clean_text(row.get("sku")),
            "category": clean_text(row.get("category")),
            "aliases": split_tags(row.get("aliases")),
            "specs": clean_text(row.get("specs")),
            "price": price,
            "unit": clean_text(row.get("unit")) or infer_unit(row),
            "inventory": inventory,
            "shipping_policy": clean_text(row.get("shipping_policy")),
            "warranty_policy": clean_text(row.get("warranty_policy")),
            "risk_rules": unique_list(risk_rules),
        }
    )
    if reply_note:
        data["reply_templates"] = {"default": reply_note}
    if isinstance(row.get("extra_fields"), dict):
        data["extra_fields"] = row["extra_fields"]
    return data


def tiers_for_product(data: dict[str, Any], tier_rows: list[dict[str, Any]]) -> list[dict[str, float]]:
    sku = str(data.get("sku") or "").strip().lower()
    tiers = []
    for row in tier_rows:
        row_sku = str(row.get("sku") or "").strip().lower()
        if sku and row_sku and row_sku != sku:
            continue
        quantity = number_from_text(row.get("min_quantity"))
        unit_price = number_from_text(row.get("unit_price"))
        if unit_price is None:
            unit_price = number_from_text(row.get("price"))
        if quantity is None or unit_price is None:
            continue
        tiers.append({"min_quantity": float(quantity), "unit_price": float(unit_price)})
    unique: dict[float, dict[str, float]] = {}
    for tier in sorted(tiers, key=lambda item: item["min_quantity"]):
        unique[tier["min_quantity"]] = tier
    return list(unique.values())


def inline_price_tiers_from_text(text: str) -> list[dict[str, float]]:
    tiers = []
    for match in re.finditer(
        r"(\d+(?:\.\d+)?)\s*(?:个|件|台|张|只|套|箱|条|支)?\s*(?:起|以上|及以上|起订|起批)\D{0,10}?(\d+(?:\.\d+)?)\s*元",
        text,
    ):
        quantity = number_from_text(match.group(1))
        unit_price = number_from_text(match.group(2))
        if quantity is None or unit_price is None:
            continue
        tiers.append({"min_quantity": float(quantity), "unit_price": float(unit_price)})
    return unique_price_tiers(tiers)


def unique_price_tiers(tiers: list[dict[str, float]]) -> list[dict[str, float]]:
    unique: dict[float, dict[str, float]] = {}
    for tier in sorted(tiers, key=lambda item: item.get("min_quantity", 0)):
        quantity = number_from_text(tier.get("min_quantity"))
        unit_price = number_from_text(tier.get("unit_price"))
        if quantity is None or unit_price is None:
            continue
        unique[quantity] = {"min_quantity": float(quantity), "unit_price": float(unit_price)}
    return list(unique.values())


def build_chat_candidates(path: Path, text: str, tags: list[str]) -> list[dict[str, Any]]:
    pairs = chat_pairs_from_content(path, text)
    candidates = []
    for index, pair in enumerate(pairs):
        service_reply = clean_text(pair.get("service_reply"))
        if not service_reply:
            continue
        data = {
            "customer_message": clean_text(pair.get("customer_message")),
            "service_reply": service_reply,
            "intent_tags": split_tags(pair.get("intent_tags")) or sorted(tag for tag in tags if tag != "style") or ["general"],
            "tone_tags": split_tags(pair.get("tone_tags")) or ["真实客服话术"],
            "linked_categories": split_tags(pair.get("linked_categories")),
            "linked_item_ids": split_tags(pair.get("linked_item_ids")),
            "usable_as_template": True,
        }
        if isinstance(pair.get("extra_fields"), dict):
            data["extra_fields"] = pair["extra_fields"]
        item_id = safe_item_id(f"chat_{stable_digest(str(pair), 10)}", fallback_seed=f"{path}:{index}:{pair}")
        item = {
            "schema_version": 1,
            "category_id": "chats",
            "id": item_id,
            "status": "active",
            "source": {"type": "raw_upload", "path": str(path)},
            "data": compact_dict(data),
            "runtime": runtime_flags_from_text(service_reply),
        }
        candidates.append(
            make_native_candidate(
                path=path,
                text=text,
                tags=sorted(set([*tags, "style"])),
                category_id="chats",
                item=item,
                discriminator=f"chats:{item_id}:{index}",
                summary="建议沉淀一条客服话术样例",
                change_type="upsert_chat_example",
                evidence_excerpt=compact_excerpt(row_to_evidence(pair), 360),
                suggested_tests=[{"scenario": "style", "assertion": "入库后应只影响回复风格或类似场景表达，不改变事实依据。"}],
            )
        )
    return candidates


def chat_pairs_from_content(path: Path, text: str) -> list[dict[str, Any]]:
    json_rows = rows_from_json(path, text)
    if json_rows:
        rows = [canonicalize_row(row) for row in json_rows]
        return [row for row in rows if row.get("service_reply")]
    tables = parse_tables(text)
    table_pairs = []
    for table in tables:
        rows = [canonicalize_row(row) for row in table["rows"]]
        table_pairs.extend(row for row in rows if row.get("service_reply"))
    if table_pairs:
        return table_pairs

    pairs = []
    last_customer = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        customer_match = re.match(r"^(?:客户|用户|买家)[:：]\s*(.+)$", line)
        if customer_match:
            last_customer = customer_match.group(1).strip()
            continue
        service_match = re.match(r"^(?:客服|回复)[:：]\s*(.+)$", line)
        if service_match:
            pairs.append({"customer_message": last_customer, "service_reply": service_match.group(1).strip()})
            last_customer = ""
    if pairs:
        return pairs
    excerpt = compact_excerpt(text)
    return [{"customer_message": "", "service_reply": excerpt}] if excerpt else []


def build_policy_candidates(path: Path, text: str, tags: list[str]) -> list[dict[str, Any]]:
    rows = policy_rows_from_content(path, text, tags)
    candidates = []
    for index, row in enumerate(rows):
        answer = clean_text(row.get("answer")) or clean_text(row.get("reply_note")) or compact_excerpt(row_to_evidence(row), 360)
        title = clean_text(row.get("title")) or policy_title_from_tags(tags, answer)
        if not title or not answer:
            continue
        policy_type = clean_policy_type(row.get("policy_type")) or policy_type_from_tags(tags)
        keywords = split_tags(row.get("keywords")) or [tag for tag in tags if tag != "unknown"]
        requires_handoff = bool_from_text(row.get("requires_handoff")) or any(word in answer for word in ["人工", "上级", "不能自动", "审核"])
        data = {
            "title": title,
            "policy_type": policy_type,
            "keywords": keywords,
            "answer": answer,
            "allow_auto_reply": not requires_handoff,
            "requires_handoff": requires_handoff,
            "handoff_reason": clean_text(row.get("handoff_reason")),
            "operator_alert": bool_from_text(row.get("operator_alert")) or requires_handoff,
            "risk_level": clean_text(row.get("risk_level")) or ("warning" if requires_handoff else "normal"),
        }
        if isinstance(row.get("extra_fields"), dict):
            data["extra_fields"] = row["extra_fields"]
        item_id = safe_item_id(clean_text(row.get("id")) or title, fallback_seed=f"{path}:{index}:{data}")
        item = {
            "schema_version": 1,
            "category_id": "policies",
            "id": item_id,
            "status": "active",
            "source": {"type": "raw_upload", "path": str(path)},
            "data": compact_dict(data),
            "runtime": runtime_flags_from_text(answer),
        }
        candidates.append(
            make_native_candidate(
                path=path,
                text=text,
                tags=tags,
                category_id="policies",
                item=item,
                discriminator=f"policies:{item_id}:{index}",
                summary=f"建议新增/更新政策规则：{title}",
                change_type="upsert_policy",
                evidence_excerpt=compact_excerpt(row_to_evidence(row), 360),
                suggested_tests=[{"scenario": policy_type, "assertion": "入库后应能按关键词回答该政策；高风险内容必须转人工。"}],
            )
        )
    return candidates


def policy_rows_from_content(path: Path, text: str, tags: list[str]) -> list[dict[str, Any]]:
    json_rows = rows_from_json(path, text)
    if json_rows:
        rows = [canonicalize_row(row) for row in json_rows]
        company_rows = [company_policy_row_from_data(row, text) for row in rows if looks_like_company_profile_row(row, text)]
        if company_rows:
            return company_rows
        if any(row.get("answer") or row.get("title") for row in rows):
            return rows
    rows = []
    for table in parse_tables(text):
        canonical_rows = [canonicalize_row(row) for row in table["rows"]]
        if any(row.get("answer") or row.get("title") or row.get("policy_type") for row in canonical_rows):
            rows.extend(canonical_rows)
    if rows:
        return rows
    return [{"title": policy_title_from_tags(tags, text), "answer": compact_excerpt(text, 520), "keywords": tags}]


def looks_like_company_profile_row(row: dict[str, Any], text: str = "") -> bool:
    payload = json.dumps(row, ensure_ascii=False) + "\n" + str(text or "")
    if not looks_like_company_profile_text(payload):
        return False
    product_specific = any(not is_blank(row.get(key)) for key in ("sku", "price", "unit_price", "inventory", "specs"))
    return not product_specific


def company_policy_row_from_data(data: dict[str, Any], source_text: str = "") -> dict[str, Any]:
    details = data.get("additional_details") if isinstance(data.get("additional_details"), dict) else {}
    company_name = clean_text(data.get("name")) or clean_text(details.get("公司名称"))
    business_scope = clean_text(details.get("主营范围") or details.get("主营业务") or data.get("category"))
    persona = clean_text(details.get("对外客服人设") or details.get("客服人设"))
    answer_parts = []
    if company_name:
        answer_parts.append(f"公司名称：{company_name}")
    if business_scope:
        answer_parts.append(f"主营范围：{business_scope}")
    if persona:
        answer_parts.append(f"对外客服风格：{persona}")
    for key, value in details.items():
        if key in {"公司名称", "主营范围", "主营业务", "对外客服人设", "客服人设"} or is_blank(value):
            continue
        answer_parts.append(f"{key}：{value}")
    answer = "；".join(answer_parts) or compact_excerpt(source_text or row_to_evidence(data), 520)
    keywords = unique_list(
        [
            "公司名称",
            "公司信息",
            "主营范围",
            "主营业务",
            "生产方",
            "厂家",
            "开票信息",
            company_name,
            business_scope,
        ]
    )
    return compact_dict(
        {
            "title": company_name or "公司信息",
            "policy_type": "company",
            "keywords": keywords,
            "answer": answer,
            "allow_auto_reply": True,
            "requires_handoff": False,
            "operator_alert": False,
            "risk_level": "normal",
            "extra_fields": {key: value for key, value in data.items() if key not in {"name", "category", "additional_details"}},
        }
    )


def build_erp_candidates(path: Path, text: str, tags: list[str]) -> list[dict[str, Any]]:
    rows = erp_rows_from_content(path, text)
    candidates = []
    for index, row in enumerate(rows):
        external_id = clean_text(row.get("external_id")) or clean_text(row.get("sku")) or f"record_{index + 1}"
        source_system = clean_text(row.get("source_system")) or "uploaded_file"
        record_type = clean_erp_record_type(row.get("record_type")) or infer_erp_record_type(row)
        data = {
            "source_system": source_system,
            "record_type": record_type,
            "external_id": external_id,
            "fields": {key: value for key, value in row.items() if key not in {"source_system", "record_type", "external_id"}},
            "sync_status": clean_text(row.get("sync_status")) or "imported",
        }
        item_id = safe_item_id(f"{source_system}_{external_id}", fallback_seed=f"{path}:{index}:{data}")
        item = {
            "schema_version": 1,
            "category_id": "erp_exports",
            "id": item_id,
            "status": "active",
            "source": {"type": "raw_upload", "path": str(path)},
            "data": compact_dict(data),
            "runtime": {"allow_auto_reply": False, "requires_handoff": False, "risk_level": "normal"},
        }
        candidates.append(
            make_native_candidate(
                path=path,
                text=text,
                tags=sorted(set([*tags, "erp"])),
                category_id="erp_exports",
                item=item,
                discriminator=f"erp:{item_id}:{index}",
                summary=f"建议导入 ERP 记录：{external_id}",
                change_type="upsert_erp_record",
                evidence_excerpt=compact_excerpt(row_to_evidence(row), 360),
                suggested_tests=[{"scenario": "erp_export", "assertion": "入库后应作为后台数据参考，不直接承诺给客户。"}],
            )
        )
    return candidates


def erp_rows_from_content(path: Path, text: str) -> list[dict[str, Any]]:
    json_rows = rows_from_json(path, text)
    if json_rows:
        return [canonicalize_row(row) for row in json_rows]
    rows = []
    for table in parse_tables(text):
        rows.extend(canonicalize_row(row) for row in table["rows"])
    return rows or [{"external_id": path.stem, "record_type": "other", "raw_text": compact_excerpt(text, 1000)}]


def build_manual_policy_candidate(path: Path, text: str, tags: list[str]) -> dict[str, Any]:
    return build_policy_candidates(path, text, tags or ["unknown"])[0]


def build_llm_candidates(path: Path, text: str, tags: list[str], raw_kind: str) -> list[dict[str, Any]]:
    api_key = read_secret("DEEPSEEK_API_KEY")
    if not api_key:
        return []
    prompt = {
        "task": "把上传资料拆成多个可审核的知识候选。必须只输出 JSON 对象。",
        "raw_kind_from_upload": raw_kind,
        "detected_tags": tags,
        "product_scoped_storage_rule": "If knowledge only applies to one concrete product, use product_faq/product_rules/product_explanations and fill data.product_id.",
        "rules": [
            "根据内容判断 category_id，不要盲从 raw_kind_from_upload。",
            "一个商品/一条政策/一段话术/一条 ERP 记录生成一个 item。",
            "公司名称、主营范围、开票主体、生产方、厂家、客服人设等公司主体信息必须归入 policies，policy_type 使用 company；不要归入 products。",
            "缺失关键字段时不要编造，保留已有信息并写入 missing_fields。",
            "无法放入既有字段的内容必须写入 data.additional_details。",
            "高风险承诺写入 warnings。",
        ],
        "categories": category_prompt_summary(),
        "response_shape": {
            "items": [
                {
                    "category_id": "products|policies|chats|erp_exports|product_faq|product_rules|product_explanations",
                    "confidence": 0.0,
                    "item_id_hint": "safe english id if possible",
                    "summary": "short Chinese review summary",
                    "data": {"additional_details": {}},
                    "missing_fields": [],
                    "warnings": [],
                }
            ]
        },
        "content": compact_excerpt(text, 10000),
    }
    result = call_deepseek_json(prompt)
    records = result.get("items") if isinstance(result, dict) else None
    if not isinstance(records, list):
        return []
    candidates = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        candidate = candidate_from_llm_record(path, text, tags, record, index)
        if candidate:
            candidates.append(candidate)
    return candidates


def candidate_from_llm_record(path: Path, text: str, tags: list[str], record: dict[str, Any], index: int) -> dict[str, Any] | None:
    category_id = str(record.get("category_id") or "").strip()
    if category_id not in DEFAULT_KINDS:
        return None
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    if category_id == "products" and looks_like_company_profile_row(data, text):
        category_id = "policies"
        data = company_policy_row_from_data(data, text)
    if category_id in PRODUCT_SCOPED_SCHEMAS:
        data = normalize_product_scoped_llm_record_data(category_id, data)
    data = normalize_llm_record_data(category_id, data)
    if not llm_record_is_source_grounded(category_id, data, text):
        return None
    item_id_source = str(record.get("item_id_hint") or data.get("sku") or data.get("name") or data.get("title") or data.get("external_id") or data.get("product_id") or "")
    item_id = safe_item_id(item_id_source, fallback_seed=f"{path}:llm:{index}:{record}")
    item = {
        "schema_version": 1,
        "category_id": category_id,
        "id": item_id,
        "status": "active",
        "source": {"type": "deepseek_upload_learning", "path": str(path)},
        "data": data,
        "runtime": product_runtime_flags_from_data(data) if category_id == "products" else runtime_flags_from_text(json.dumps(data, ensure_ascii=False)),
    }
    summary = str(record.get("summary") or f"建议新增/更新 {category_id} 知识")
    return make_native_candidate(
        path=path,
        text=text,
        tags=sorted(set([*tags, "llm"])),
        category_id=category_id,
        item=item,
        discriminator=f"llm:{category_id}:{item_id}:{index}",
        summary=summary,
        change_type=f"llm_upsert_{category_id}",
        evidence_excerpt=compact_excerpt(json.dumps(data, ensure_ascii=False), 360),
        suggested_tests=[{"scenario": "llm_upload_learning", "assertion": "人工确认候选字段、缺失项和额外信息后再入库。"}],
    )


def normalize_llm_record_data(category_id: str, data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    if category_id != "products":
        return normalized
    raw_tiers = normalized.get("price_tiers")
    tiers: list[dict[str, float]] = []
    if isinstance(raw_tiers, list):
        for tier in raw_tiers:
            if not isinstance(tier, dict):
                continue
            quantity = (
                number_from_text(tier.get("min_quantity"))
                or number_from_text(tier.get("min_qty"))
                or number_from_text(tier.get("quantity"))
                or number_from_text(tier.get("数量"))
            )
            unit_price = (
                number_from_text(tier.get("unit_price"))
                or number_from_text(tier.get("price"))
                or number_from_text(tier.get("价格"))
            )
            if quantity is None or unit_price is None:
                continue
            tiers.append({"min_quantity": float(quantity), "unit_price": float(unit_price)})
    price = number_from_text(normalized.get("price"))
    if price is not None:
        normalized["price"] = price
        tiers.append({"min_quantity": 1.0, "unit_price": price})
    tiers = unique_price_tiers(tiers)
    if tiers:
        normalized["price_tiers"] = tiers
    return normalized


def normalize_product_scoped_llm_record_data(category_id: str, data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    product_id = normalized.get("product_id") or normalized.get("sku") or normalized.get("product_sku")
    normalized["product_id"] = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(product_id or "").strip()).strip("_.-").lower()
    if category_id == "product_explanations" and not normalized.get("content"):
        normalized["content"] = normalized.get("answer") or normalized.get("description") or ""
    if category_id in {"product_faq", "product_rules"} and not normalized.get("answer"):
        normalized["answer"] = normalized.get("content") or normalized.get("description") or ""
    return normalized


def llm_record_is_source_grounded(category_id: str, data: dict[str, Any], source_text: str) -> bool:
    if not data:
        return False
    if category_id == "products":
        anchors = [
            data.get("name"),
            data.get("sku"),
            *(data.get("aliases") or [] if isinstance(data.get("aliases"), list) else []),
        ]
    elif category_id == "policies":
        anchors = [data.get("title"), data.get("answer")]
    elif category_id == "chats":
        anchors = [data.get("customer_message"), data.get("service_reply")]
    elif category_id == "erp_exports":
        anchors = [data.get("external_id"), data.get("source_system"), json.dumps(data.get("fields", {}), ensure_ascii=False)]
    elif category_id in PRODUCT_SCOPED_SCHEMAS:
        anchors = [data.get("product_id"), data.get("title"), data.get("question"), data.get("answer"), data.get("content")]
    else:
        anchors = []
    return any(anchor_is_in_source(str(anchor or ""), source_text) for anchor in anchors)


def anchor_is_in_source(anchor: str, source_text: str) -> bool:
    anchor = clean_text(anchor)
    if len(anchor) < 2:
        return False
    source = normalize_grounding_text(source_text)
    normalized_anchor = normalize_grounding_text(anchor)
    if normalized_anchor and normalized_anchor in source:
        return True
    chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", anchor)
    if any(normalize_grounding_text(token) in source for token in chinese_tokens):
        return True
    if not chinese_tokens:
        alpha_tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", anchor)
        if any(token.lower() in source for token in alpha_tokens):
            return True
    return False


def normalize_grounding_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").lower())


def category_prompt_summary() -> list[dict[str, Any]]:
    registry_path = default_admin_knowledge_base_root() / "registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    categories = []
    for category in registry.get("categories", []) or []:
        category_id = str(category.get("id") or "")
        if category_id not in DEFAULT_KINDS:
            continue
        schema = load_category_schema(category_id)
        categories.append(
            {
                "id": category_id,
                "name": category.get("name") or schema.get("display_name") or category_id,
                "description": schema.get("description") or "",
                "fields": [
                    {
                        "id": field.get("id"),
                        "label": field.get("label"),
                        "type": field.get("type"),
                        "required": bool(field.get("required")),
                    }
                    for field in schema.get("fields", []) or []
                ],
            }
        )
    for category_id, schema in PRODUCT_SCOPED_SCHEMAS.items():
        categories.append(
            {
                "id": category_id,
                "name": schema.get("display_name") or category_id,
                "description": "Product-scoped knowledge. Requires data.product_id and is stored under that product folder.",
                "fields": [
                    {
                        "id": field.get("id"),
                        "label": field.get("label"),
                        "type": field.get("type"),
                        "required": bool(field.get("required")),
                    }
                    for field in schema.get("fields", []) or []
                ],
            }
        )
    return categories


def call_deepseek_json(prompt: dict[str, Any]) -> dict[str, Any]:
    api_key = read_secret("DEEPSEEK_API_KEY")
    if not api_key:
        return {}
    base_url = read_secret("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL
    model = read_secret("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是微信 AI 客服知识库的数据整理员。你只做分类和结构化，不代表客服回复客户。"
                    "必须只输出 JSON 对象。禁止引入 content 中没有出现的商品、价格、库存、政策、数量或承诺。"
                    "商品名、政策答案和话术必须可从原文直接找到依据；不确定就放进 missing_fields 或 additional_details。"
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "max_tokens": 2200,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url=base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {}
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return parse_json_object(str(content or "")) or {}


def read_secret(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            registry_value, _ = winreg.QueryValueEx(key, name)
            return str(registry_value)
    except Exception:
        return ""


def parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def make_native_candidate(
    *,
    path: Path,
    text: str,
    tags: list[str],
    category_id: str,
    item: dict[str, Any],
    discriminator: str,
    summary: str,
    change_type: str,
    evidence_excerpt: str,
    suggested_tests: list[dict[str, str]],
) -> dict[str, Any]:
    candidate_id = stable_candidate_id(path, text, tags, discriminator)
    patch_item = dict(item)
    intake_result = evaluate_intake_item(
        category_id=category_id,
        schema=load_category_schema(category_id),
        item=patch_item,
        raw_text=evidence_excerpt,
        confidence=0.72,
        source_label="原始资料摘录",
    )
    patch_item = intake_result["item"]
    intake = intake_result["intake"]
    patch_item["source"] = {**(patch_item.get("source") or {}), "candidate_id": candidate_id}
    return {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "path": str(path),
            "suffix": path.suffix.lower(),
            "evidence_excerpt": evidence_excerpt,
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
        "detected_tags": sorted(set(tags)),
        "proposal": {
            "target_category": category_id,
            "change_type": change_type,
            "summary": summary,
            "suggested_fields": patch_item.get("data", {}),
            "missing_fields": intake.get("missing_fields", []),
            "warnings": intake.get("warnings", []),
            "formal_patch": {
                "target_category": category_id,
                "operation": "upsert_item",
                "item": patch_item,
            },
        },
        "intake": intake,
        "review": {
            "status": "pending",
            "completeness_status": intake.get("status", "ready"),
            "missing_fields": intake.get("missing_fields", []),
            "requires_human_approval": True,
            "allowed_auto_apply": False,
        },
        "suggested_tests": suggested_tests,
    }


def rows_from_json(path: Path, text: str) -> list[dict[str, Any]]:
    if path.suffix.lower() != ".json":
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("products", "items", "records", "rows", "policies", "chats"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def parse_tables(text: str) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    current_name = "raw"
    current_lines: list[str] = []

    def flush() -> None:
        if current_lines:
            rows = parse_csv_lines(current_lines)
            if rows:
                tables.append({"name": current_name, "rows": rows})

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# Sheet:"):
            flush()
            current_name = line.replace("# Sheet:", "", 1).strip() or "sheet"
            current_lines = []
        else:
            current_lines.append(line)
    flush()
    return tables


def parse_csv_lines(lines: list[str]) -> list[dict[str, str]]:
    if len(lines) < 2 or "," not in lines[0]:
        return []
    reader = csv.DictReader(lines)
    rows = []
    for row in reader:
        normalized = {str(key or "").strip(): str(value or "").strip() for key, value in row.items() if key}
        if any(normalized.values()):
            rows.append(normalized)
    return rows


def canonicalize_row(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    extras: dict[str, Any] = {}
    for key, value in row.items():
        clean_key = str(key or "").strip()
        normalized_key = HEADER_ALIASES.get(clean_key.lower(), HEADER_ALIASES.get(clean_key, clean_key))
        if normalized_key == clean_key and normalized_key not in set(HEADER_ALIASES.values()):
            extras[clean_key] = value
        result[normalized_key] = value
    if extras:
        result.setdefault("extra_fields", extras)
    return result


def free_text_product_row(text: str) -> dict[str, Any]:
    name = extract_after_labels(text, ["商品资料", "产品资料", "商品", "产品", "新增商品", "商品名称"])
    sku = extract_after_labels(text, ["型号", "SKU", "sku"])
    price = extract_price(text)
    specs = extract_after_labels(text, ["具体描述", "描述", "规格"])
    shipping = extract_after_labels(text, ["发货", "物流"])
    warranty = extract_after_labels(text, ["售后", "保修"])
    return compact_dict(
        {
            "name": name,
            "sku": sku,
            "specs": specs,
            "price": price,
            "unit": infer_unit({"price": text}),
            "shipping_policy": shipping,
            "warranty_policy": warranty,
            "raw_text": text,
        }
    )


def infer_raw_kind(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    for kind in DEFAULT_KINDS:
        if kind in parts:
            return kind
    return ""


def detect_tags(text: str) -> list[str]:
    normalized = text.lower()
    tags = [
        tag
        for tag, keywords in TAG_KEYWORDS.items()
        if any(keyword.lower() in normalized for keyword in keywords)
    ]
    return sorted(set(tags))


def extract_price(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|块钱)", text)
    return float(match.group(1)) if match else None


def extract_after_labels(text: str, labels: list[str]) -> str:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*[:：]\s*([^\n；;，,]+)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def number_from_text(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def split_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    text = str(value).strip()
    if not text:
        return []
    parts = re.split(r"[,，;；、|/\n]+", text)
    return [part.strip() for part in parts if part.strip()]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def bool_from_text(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "是", "需要", "必须", "转人工"}


def clean_policy_type(value: Any) -> str:
    text = clean_text(value).lower()
    mapping = {
        "开票": "invoice",
        "发票": "invoice",
        "付款": "payment",
        "支付": "payment",
        "物流": "logistics",
        "发货": "logistics",
        "售后": "after_sales",
        "保修": "after_sales",
        "折扣": "discount",
        "优惠": "discount",
        "人工": "manual_required",
    }
    if text in {"company", "invoice", "payment", "logistics", "after_sales", "discount", "sample", "installation", "contract", "manual_required", "other"}:
        return text
    return mapping.get(text, "")


def policy_type_from_tags(tags: list[str]) -> str:
    for tag in tags:
        if tag in POLICY_TAG_TO_TYPE:
            return POLICY_TAG_TO_TYPE[tag]
    return "other"


def policy_title_from_tags(tags: list[str], text: str) -> str:
    policy_type = policy_type_from_tags(tags)
    titles = {
        "invoice": "开票规则",
        "logistics": "物流发货规则",
        "payment": "付款规则",
        "after_sales": "售后规则",
        "discount": "优惠议价规则",
        "other": "待分类规则",
    }
    return titles.get(policy_type) or compact_excerpt(text, 24) or "待分类规则"


def clean_erp_record_type(value: Any) -> str:
    text = clean_text(value).lower()
    allowed = {"product", "inventory", "price", "customer", "order", "other"}
    return text if text in allowed else ""


def infer_erp_record_type(row: dict[str, Any]) -> str:
    keys = {str(key).lower() for key in row}
    if {"inventory", "库存"} & keys:
        return "inventory"
    if {"price", "unit_price", "价格"} & keys:
        return "price"
    if {"customer", "客户"} & keys:
        return "customer"
    if {"order", "订单"} & keys:
        return "order"
    if {"sku", "name"} & keys:
        return "product"
    return "other"


def infer_unit(row: dict[str, Any]) -> str:
    text = " ".join(str(value or "") for value in row.values())
    match = re.search(r"元\s*/\s*([^\s,，;；]+)", text)
    if match:
        return match.group(1).strip()
    match = re.search(r"\d+(?:\.\d+)?\s*(个|件|台|张|只|套|箱|条|支|瓶|包|米|kg|公斤)\s*(?:装|起|以上|及以上|/|每)?", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def runtime_flags_from_text(text: str) -> dict[str, Any]:
    high_risk_words = ["最低价", "赔偿", "退款", "账期", "合同", "保证", "一定", "必须"]
    requires_handoff = any(word in text for word in ["请示", "上级", "人工", "不能自动", "审核"])
    risk_level = "warning" if requires_handoff or any(word in text for word in high_risk_words) else "normal"
    return {"allow_auto_reply": not requires_handoff, "requires_handoff": requires_handoff, "risk_level": risk_level}


def product_runtime_flags_from_data(data: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(data, ensure_ascii=False)
    hard_handoff_words = ["禁止自动回复", "不可自动回复", "不能自动回复", "全部转人工", "整单转人工"]
    warning_words = ["最低价", "赔偿", "退款", "账期", "合同", "保证", "必须", "人工", "确认", "承诺"]
    requires_handoff = any(word in text for word in hard_handoff_words)
    risk_level = "warning" if requires_handoff or any(word in text for word in warning_words) else "normal"
    return {"allow_auto_reply": not requires_handoff, "requires_handoff": requires_handoff, "risk_level": risk_level}


def unique_list(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def compact_excerpt(text: str, limit: int = 260) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit]


def row_to_evidence(row: dict[str, Any]) -> str:
    return "；".join(f"{key}: {value}" for key, value in row.items() if value not in (None, "", [], {}))


def stable_candidate_id(path: Path, text: str, tags: list[str], discriminator: str = "") -> str:
    digest = hashlib.sha256()
    digest.update(str(path).encode("utf-8"))
    digest.update(b"\0")
    digest.update(text.encode("utf-8"))
    digest.update(b"\0")
    digest.update(",".join(tags).encode("utf-8"))
    digest.update(b"\0")
    digest.update(discriminator.encode("utf-8"))
    return "raw_" + digest.hexdigest()[:16]


def stable_digest(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def safe_item_id(value: str, fallback_seed: str) -> str:
    text = value.strip().lower()
    text = re.sub(r"[^a-z0-9_.-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    if not text or not re.match(r"^[a-z0-9]", text):
        text = "item_" + stable_digest(fallback_seed, 12)
    return text[:120]


def compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def load_category_schema(category_id: str) -> dict[str, Any]:
    if category_id in PRODUCT_SCOPED_SCHEMAS:
        return dict(PRODUCT_SCOPED_SCHEMAS[category_id])
    path = default_admin_knowledge_base_root() / category_id / "schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
