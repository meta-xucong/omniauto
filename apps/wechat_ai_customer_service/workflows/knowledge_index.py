"""Search helpers for category knowledge items."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover - supports both package and script imports.
    from .knowledge_runtime import KnowledgeRuntime
except ImportError:  # pragma: no cover
    from knowledge_runtime import KnowledgeRuntime


PRODUCT_SCOPED_CATEGORY_IDS = {"product_faq", "product_rules", "product_explanations"}

INTENT_KEYWORDS: dict[str, list[str]] = {
    "greeting": ["你好", "您好", "hello", "在吗"],
    "catalog": ["有哪些商品", "有什么商品", "商品列表", "产品列表", "产品介绍", "商品介绍", "主营产品", "卖什么"],
    "quote": ["价格", "报价", "多少钱", "费用", "单价", "总价", "一共", "合计", "共多少钱"],
    "discount": ["优惠", "便宜", "最低", "折扣", "能少", "少点", "还价", "议价", "贵", "能按"],
    "stock": ["库存", "现货", "有货"],
    "shipping": ["物流", "快递", "运费", "包邮", "发货", "发到", "发往", "送到", "寄到", "到货", "送货", "上楼", "几天到", "几天", "多久"],
    "warranty": ["售后", "保修", "质保", "坏了", "退换"],
    "spec": ["规格", "型号", "参数", "尺寸"],
    "invoice": ["发票", "开票", "专票", "普票", "税号", "电子发票"],
    "payment": ["付款", "支付", "对公", "转账", "收款", "银行账号", "账户"],
    "company": ["你们公司", "公司名称", "公司叫什么", "公司信息", "公司地址", "你们地址", "在哪里", "营业时间", "客服电话"],
    "after_sales": ["退换", "退货", "换货", "破损", "退款", "赔偿", "投诉"],
    "customer_data": ["姓名", "电话", "手机", "地址", "收件", "联系人"],
    "small_talk": ["哈哈", "随便看看", "先看看", "靠谱不", "可靠", "辛苦", "谢谢", "客服", "小姐姐", "小哥"],
    "scene_product": [
        "小店",
        "便利店",
        "餐饮店",
        "饮料",
        "冷藏",
        "保鲜",
        "冷柜",
        "办公室",
        "员工",
        "久坐",
        "腰疼",
        "净水",
        "滤瓶",
        "耗材",
        "仓库",
        "快递",
        "打包",
        "包装",
        "搬家",
    ],
    "handoff": [
        "人工",
        "转人工",
        "投诉",
        "退款",
        "赔偿",
        "法务",
        "律师",
        "合同",
        "月结",
        "账期",
        "赊账",
        "安装",
        "上门",
        "免单",
        "白送",
        "先发货",
        "月底结",
        "虚开",
        "伪造",
        "假发票",
    ],
}

POLICY_TYPE_TO_INTENT = {
    "company_profile": "company",
    "company": "company",
    "invoice_policy": "invoice",
    "invoice": "invoice",
    "payment_policy": "payment",
    "payment": "payment",
    "logistics_policy": "shipping",
    "logistics": "shipping",
    "after_sales_policy": "after_sales",
    "after_sales": "after_sales",
    "discount": "discount",
    "contract": "handoff",
    "manual_required": "handoff",
}

BUSINESS_INTENTS = {
    "catalog",
    "quote",
    "discount",
    "stock",
    "shipping",
    "warranty",
    "spec",
    "invoice",
    "payment",
    "company",
    "after_sales",
    "scene_product",
    "handoff",
}

PRODUCT_CONTEXT_INTENTS = {"quote", "discount", "shipping", "stock", "warranty", "spec"}


@dataclass(frozen=True)
class KnowledgeHit:
    category_id: str
    item_id: str
    title: str
    matched_fields: tuple[str, ...]
    match_reason: str
    confidence: float
    category: dict[str, Any]
    schema: dict[str, Any]
    resolver: dict[str, Any]
    item: dict[str, Any]


class KnowledgeIndex:
    """A small in-memory index built from resolver-defined match fields."""

    def __init__(self, runtime: KnowledgeRuntime | None = None) -> None:
        self.runtime = runtime or KnowledgeRuntime()

    def search(
        self,
        text: str,
        *,
        context: dict[str, Any] | None = None,
        intent_tags: list[str] | None = None,
        limit: int = 12,
    ) -> list[KnowledgeHit]:
        context = context or {}
        intent_tags = intent_tags or detect_intent_tags(text)
        normalized_text = normalize_text(text)
        hits: list[KnowledgeHit] = []
        for category, schema, resolver, item in self.runtime.iter_reply_items():
            category_id = str(category.get("id") or "")
            hit = self._match_item(category, schema, resolver, item, normalized_text, intent_tags)
            if hit:
                hits.append(hit)

            context_hit = self._context_product_hit(category, schema, resolver, item, context, intent_tags)
            if context_hit:
                hits.append(context_hit)

        product_ids = {hit.item_id for hit in hits if hit.category_id == "products"}
        if context.get("last_product_id"):
            product_ids.add(str(context.get("last_product_id")))
        for category, schema, resolver, item in self.runtime.iter_product_scoped_items(product_ids):
            hit = self._match_item(category, schema, resolver, item, normalized_text, intent_tags)
            if hit:
                hits.append(hit)

        hits = dedupe_hits(hits)
        hits.sort(key=lambda hit: (hit.confidence, -category_rank(hit.category_id)), reverse=True)
        return hits[:limit]

    def _match_item(
        self,
        category: dict[str, Any],
        schema: dict[str, Any],
        resolver: dict[str, Any],
        item: dict[str, Any],
        normalized_text: str,
        intent_tags: list[str],
    ) -> KnowledgeHit | None:
        category_id = str(category.get("id") or "")
        data = item.get("data", {}) or {}
        matched_fields: list[str] = []
        exact_matches = 0
        intent_matches = 0
        if category_id == "global_guidelines" and data.get("always_include", False):
            matched_fields.append("always_include")
            intent_matches += 1
        if category_id in PRODUCT_SCOPED_CATEGORY_IDS and data.get("always_include", False):
            matched_fields.append("always_include")
            intent_matches += 1
        for field_id in resolver.get("match_fields", []) or []:
            values = flatten_values(data.get(field_id))
            field_matched, field_exact, field_intent = field_matches(field_id, values, normalized_text, intent_tags, data)
            if field_matched:
                matched_fields.append(str(field_id))
                exact_matches += field_exact
                intent_matches += field_intent

        if category_id == "products" and "catalog" in intent_tags:
            matched_fields.append("catalog")
            intent_matches += 1

        if category_id == "policies":
            policy_intent = POLICY_TYPE_TO_INTENT.get(str(data.get("policy_type") or ""))
            if policy_intent and policy_intent in intent_tags:
                matched_fields.append("policy_type")
                intent_matches += 1

        if not matched_fields:
            return None
        if category_id == "policies" and item_blocks_auto_reply(data, item.get("runtime", {}) or {}) and exact_matches <= 0:
            return None

        confidence = score_hit(category_id, matched_fields, exact_matches, intent_matches)
        minimum = float(resolver.get("minimum_confidence", 0.4) or 0.4)
        if confidence < minimum:
            return None
        return KnowledgeHit(
            category_id=category_id,
            item_id=str(item.get("id") or ""),
            title=item_title(schema, item),
            matched_fields=tuple(sorted(set(matched_fields))),
            match_reason=match_reason(category_id, matched_fields, intent_matches),
            confidence=round(confidence, 3),
            category=category,
            schema=schema,
            resolver=resolver,
            item=item,
        )

    def _context_product_hit(
        self,
        category: dict[str, Any],
        schema: dict[str, Any],
        resolver: dict[str, Any],
        item: dict[str, Any],
        context: dict[str, Any],
        intent_tags: list[str],
    ) -> KnowledgeHit | None:
        if str(category.get("id") or "") != "products":
            return None
        last_product_id = str(context.get("last_product_id") or "")
        if not last_product_id or str(item.get("id") or "") != last_product_id:
            return None
        if not (set(intent_tags) & PRODUCT_CONTEXT_INTENTS):
            return None
        return KnowledgeHit(
            category_id="products",
            item_id=str(item.get("id") or ""),
            title=item_title(schema, item),
            matched_fields=("conversation_context",),
            match_reason="conversation_context_product",
            confidence=0.7,
            category=category,
            schema=schema,
            resolver=resolver,
            item=item,
        )


def detect_intent_tags(text: str) -> list[str]:
    normalized = normalize_text(text)
    tags = {
        tag
        for tag, keywords in INTENT_KEYWORDS.items()
        if any(normalize_text(keyword) in normalized for keyword in keywords)
    }
    if re.search(r"\d+\s*(台|个|件|只|箱|套|张|kg|公斤|千克)", normalized, re.IGNORECASE):
        tags.add("quote")
        tags.add("product")
    if tags & {"quote", "discount", "stock", "shipping", "warranty", "spec", "scene_product"}:
        tags.add("product")
    if not tags:
        tags.add("unknown")
    return sorted(tags)


def normalize_text(text: Any) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).lower().strip()


def flatten_values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (str, int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(flatten_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(flatten_values(item))
        return values
    return [str(value)]


def field_matches(
    field_id: str,
    values: list[str],
    normalized_text: str,
    intent_tags: list[str],
    data: dict[str, Any],
) -> tuple[bool, int, int]:
    exact_matches = 0
    intent_matches = 0
    for value in values:
        normalized_value = normalize_text(value)
        if not normalized_value:
            continue
        if field_id in {"intent_tags", "tone_tags"}:
            if normalized_value in intent_tags:
                intent_matches += 1
                continue
        if field_id == "policy_type":
            mapped = POLICY_TYPE_TO_INTENT.get(normalized_value, normalized_value)
            if mapped in intent_tags:
                intent_matches += 1
                continue
        if len(normalized_value) >= 2 and normalized_value in normalized_text:
            exact_matches += 1
            continue
        if len(normalized_text) >= 4 and normalized_text in normalized_value:
            exact_matches += 1
            continue
        if field_id in {"answer", "content", "question"} and has_shared_fragment(normalized_value, normalized_text):
            exact_matches += 1
            continue

    return exact_matches + intent_matches > 0, exact_matches, intent_matches


def has_shared_fragment(value: str, text: str, *, min_size: int = 4) -> bool:
    if len(value) < min_size or len(text) < min_size:
        return False
    for start in range(0, len(value) - min_size + 1):
        fragment = value[start : start + min_size]
        if fragment and fragment in text:
            return True
    return False


def score_hit(category_id: str, matched_fields: list[str], exact_matches: int, intent_matches: int) -> float:
    base = 0.32 + min(0.32, 0.08 * len(set(matched_fields)))
    exact_score = min(0.36, 0.1 * exact_matches)
    intent_score = min(0.2, 0.07 * intent_matches)
    category_boost = 0.0
    if category_id == "products" and any(field in matched_fields for field in ("name", "aliases", "sku")):
        category_boost = 0.12
    if category_id == "policies" and any(field in matched_fields for field in ("keywords", "policy_type")):
        category_boost = 0.1
    if category_id == "chats" and "intent_tags" in matched_fields:
        category_boost = 0.08
    if category_id == "global_guidelines":
        category_boost = 0.04
    if category_id in PRODUCT_SCOPED_CATEGORY_IDS:
        category_boost = 0.1
    return min(0.98, base + exact_score + intent_score + category_boost)


def item_blocks_auto_reply(data: dict[str, Any], runtime: dict[str, Any]) -> bool:
    data_has_auto_reply = "allow_auto_reply" in data
    data_has_handoff = "requires_handoff" in data
    allow_auto_reply = data.get("allow_auto_reply") if data_has_auto_reply else runtime.get("allow_auto_reply", True)
    requires_handoff = data.get("requires_handoff") if data_has_handoff else runtime.get("requires_handoff", False)
    return bool(allow_auto_reply is False or requires_handoff)


def match_reason(category_id: str, matched_fields: list[str], intent_matches: int) -> str:
    if "conversation_context" in matched_fields:
        return "conversation_context_product"
    if category_id == "products" and any(field in matched_fields for field in ("name", "aliases", "sku")):
        return "product_alias_or_identifier"
    if category_id == "policies" and intent_matches:
        return "policy_keyword_or_intent"
    if category_id == "chats":
        return "chat_style_or_intent"
    if category_id == "global_guidelines":
        return "global_style_guideline"
    if category_id in PRODUCT_SCOPED_CATEGORY_IDS:
        return "product_scoped_knowledge"
    return "resolver_match_fields"


def item_title(schema: dict[str, Any], item: dict[str, Any]) -> str:
    data = item.get("data", {}) or {}
    title_field = str(schema.get("item_title_field") or "title")
    return str(data.get(title_field) or item.get("id") or "")


def category_rank(category_id: str) -> int:
    order = {"products": 10, "product_rules": 18, "product_faq": 19, "product_explanations": 20, "policies": 30, "chats": 40, "global_guidelines": 80}
    return order.get(category_id, 90)


def dedupe_hits(hits: list[KnowledgeHit]) -> list[KnowledgeHit]:
    best: dict[tuple[str, str], KnowledgeHit] = {}
    for hit in hits:
        key = (hit.category_id, hit.item_id)
        existing = best.get(key)
        if not existing or hit.confidence > existing.confidence:
            best[key] = hit
    return list(best.values())
