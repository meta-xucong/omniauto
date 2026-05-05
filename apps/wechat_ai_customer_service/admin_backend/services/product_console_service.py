"""Product-centric admin helpers for merchant-friendly product operations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .knowledge_base_store import KnowledgeBaseStore
from .knowledge_compiler import KnowledgeCompiler
from .knowledge_generator import KnowledgeGenerator
from .upload_store import UploadStore


PRODUCT_SCOPED_CATEGORIES = {
    "product_faq": "商品专属问答",
    "product_rules": "商品专属规则",
    "product_explanations": "商品专属解释",
}


class ProductConsoleService:
    def __init__(self) -> None:
        self.store = KnowledgeBaseStore()
        self.compiler = KnowledgeCompiler()

    def catalog(self, *, include_archived: bool = False) -> dict[str, Any]:
        scoped_counts = self.product_scoped_counts()
        products = [
            self.enrich_product(
                item,
                scoped_counts=scoped_counts.get(str(item.get("id") or ""), {}),
            )
            for item in self.store.list_items("products", include_archived=include_archived)
        ]
        active_count = sum(1 for item in products if item.get("status") == "active")
        in_stock_count = sum(1 for item in products if item.get("stock_state") == "in_stock")
        sold_out_count = sum(1 for item in products if item.get("stock_state") == "sold_out")
        runtime_usable_count = sum(1 for item in products if item.get("runtime_usable"))
        unread_count = sum(1 for item in products if item.get("is_unread"))
        return {
            "ok": True,
            "items": products,
            "counts": {
                "total": len(products),
                "active": active_count,
                "in_stock": in_stock_count,
                "sold_out": sold_out_count,
                "archived": sum(1 for item in products if item.get("status") == "archived"),
                "runtime_usable": runtime_usable_count,
                "unread": unread_count,
            },
        }

    def detail(self, product_id: str) -> dict[str, Any]:
        item = self.get_product_item(product_id, include_archived=True)
        if not item:
            raise FileNotFoundError(product_id)
        scoped = self.product_scoped_knowledge(product_id)
        return {"ok": True, "item": self.enrich_product(item, scoped=scoped), "scoped_knowledge": scoped}

    def product_scoped_knowledge(self, product_id: str) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for category_id in PRODUCT_SCOPED_CATEGORIES:
            result[category_id] = [
                item
                for item in self.store.list_items(category_id, include_archived=False)
                if str((item.get("data") or {}).get("product_id") or "") == product_id
            ]
        return result

    def product_scoped_counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for category_id in PRODUCT_SCOPED_CATEGORIES:
            for item in self.store.list_items(category_id, include_archived=False):
                product_id = str((item.get("data") or {}).get("product_id") or "")
                if not product_id:
                    continue
                product_counts = counts.setdefault(product_id, {key: 0 for key in PRODUCT_SCOPED_CATEGORIES})
                product_counts[category_id] = product_counts.get(category_id, 0) + 1
        return counts

    def adjust_inventory(self, product_id: str, *, operation: str, quantity: int | None = None) -> dict[str, Any]:
        item = self.get_product_item(product_id, include_archived=True)
        if not item:
            raise FileNotFoundError(product_id)
        data = dict(item.get("data") or {})
        operation = str(operation or "").strip()
        current = to_int(data.get("inventory"), default=0)
        if operation == "set":
            data["inventory"] = max(0, int(quantity or 0))
            item["status"] = "active"
        elif operation == "increase":
            data["inventory"] = max(0, current + int(quantity or 1))
            item["status"] = "active"
        elif operation in {"decrease", "sell"}:
            data["inventory"] = max(0, current - int(quantity or 1))
            item["status"] = "active"
        elif operation == "archive":
            item["status"] = "archived"
        elif operation == "activate":
            item["status"] = "active"
        else:
            raise ValueError(f"unsupported operation: {operation}")
        item["data"] = data
        return self.save_product_item(item, operation=operation)

    def update_product(self, product_id: str, data_patch: dict[str, Any]) -> dict[str, Any]:
        item = self.get_product_item(product_id, include_archived=True)
        if not item:
            raise FileNotFoundError(product_id)
        data = dict(item.get("data") or {})
        data.update({key: value for key, value in data_patch.items() if value not in (None, "", [], {})})
        item["data"] = data
        return self.save_product_item(item, operation="update_product")

    def save_product_item(self, item: dict[str, Any], *, operation: str) -> dict[str, Any]:
        saved = self.store.save_item("products", item)
        if not saved.get("ok"):
            raise ValueError(saved)
        self.compiler.compile_to_disk()
        return {"ok": True, "item": self.enrich_product(saved["item"]), "operation": operation}

    def command(self, message: str, *, use_llm: bool = True) -> dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            raise ValueError("message is required")
        products = self.store.list_items("products", include_archived=True)
        matched = match_product(text, products)
        quantity = parse_quantity(text)
        if matched and means_archived_status(text):
            return {"ok": True, "action": "archive", **self.adjust_inventory(str(matched.get("id") or ""), operation="archive")}
        if matched and has_any(text, "卖掉", "卖出", "售出", "成交", "减少", "扣减"):
            return {
                "ok": True,
                "action": "decrease_inventory",
                **self.adjust_inventory(str(matched.get("id") or ""), operation="sell", quantity=quantity or 1),
            }
        if matched and means_inventory_zero(text):
            return {"ok": True, "action": "set_inventory", **self.adjust_inventory(str(matched.get("id") or ""), operation="set", quantity=0)}
        if matched and has_any(text, "库存改", "库存设", "库存为", "还有", "现货"):
            if quantity is None:
                raise ValueError("请写清楚库存数量，例如：凯美瑞库存改成 2 台")
            return {
                "ok": True,
                "action": "set_inventory",
                **self.adjust_inventory(str(matched.get("id") or ""), operation="set", quantity=quantity),
            }
        if matched and has_any(text, "增加", "补货", "到货", "入库"):
            if quantity is None:
                raise ValueError("请写清楚增加数量，例如：凯美瑞补货 2 台")
            return {
                "ok": True,
                "action": "increase_inventory",
                **self.adjust_inventory(str(matched.get("id") or ""), operation="increase", quantity=quantity),
            }
        if matched:
            data_patch = extract_product_patch(text)
            if data_patch:
                return {
                    "ok": True,
                    "action": "update_product",
                    **self.update_product(str(matched.get("id") or ""), data_patch),
                    "updated_fields": sorted(data_patch),
                }
        if has_any(text, "新增", "添加", "上架", "新商品", "新车源"):
            session = KnowledgeGenerator().create_session(text, preferred_category_id="products", use_llm=use_llm)
            return {
                "ok": True,
                "action": "draft_product",
                "message": "已整理成商品草稿，请在商品库确认或修改后直接入库。",
                "session": session.get("session"),
            }
        raise ValueError("没有识别到可执行的商品操作。可以试试：凯美瑞卖出 1 台、凯美瑞库存改成 2 台、新增商品……")

    def upload_product_draft(self, *, filename: str, content: bytes, use_llm: bool = True) -> dict[str, Any]:
        upload = UploadStore().save_upload(filename=filename or "product_upload.txt", content=content, kind="products")
        if not upload.get("ok"):
            raise ValueError(upload.get("message") or upload)
        item = upload.get("item") if isinstance(upload.get("item"), dict) else {}
        path = Path(str(item.get("path") or ""))
        text = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
        if not text.strip():
            raise ValueError("商品资料没有可读取的文字内容")
        prompt = "\n".join(
            [
                "请把下面资料只整理成商品库主数据。不要生成客服话术、政策规则或候选知识。",
                "如果商品名称、价格、库存、类目、单位等主字段不完整，请保留草稿并提示用户补充。",
                text[:12000],
            ]
        )
        session = KnowledgeGenerator().create_session(prompt, preferred_category_id="products", use_llm=use_llm).get("session", {})
        return {
            "ok": True,
            "action": "product_upload_draft",
            "upload": item,
            "session": session,
            "ai_advice": product_draft_advice(session),
            "direct_apply_allowed": str(session.get("category_id") or "") == "products" and str(session.get("status") or "") == "ready",
        }

    def get_product_item(self, product_id: str, *, include_archived: bool = False) -> dict[str, Any] | None:
        for item in self.store.list_items("products", include_archived=include_archived):
            if str(item.get("id") or "") == product_id:
                return item
        return None

    def enrich_product(
        self,
        item: dict[str, Any],
        *,
        scoped: dict[str, list[dict[str, Any]]] | None = None,
        scoped_counts: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        product_id = str(item.get("id") or "")
        scoped = scoped if scoped is not None else None
        if scoped_counts is None:
            scoped = scoped if scoped is not None else self.product_scoped_knowledge(product_id)
            scoped_counts = {category_id: len(items) for category_id, items in scoped.items()}
        else:
            scoped_counts = {category_id: int(scoped_counts.get(category_id, 0) or 0) for category_id in PRODUCT_SCOPED_CATEGORIES}
        inventory = data.get("inventory")
        stock_state = product_stock_state(item, inventory)
        review_state = item.get("review_state") if isinstance(item.get("review_state"), dict) else {}
        is_unread = bool(review_state.get("is_new"))
        runtime_usable = str(item.get("status") or "active") != "archived" and not is_unread
        return {
            **item,
            "is_unread": is_unread,
            "runtime_usable": runtime_usable,
            "display": {
                "name": data.get("name") or product_id,
                "sku": data.get("sku") or product_id,
                "category": data.get("category") or "未分类",
                "price": data.get("price"),
                "unit": data.get("unit") or "",
                "inventory": inventory,
                "stock_state": stock_state,
                "stock_label": stock_label(stock_state, inventory),
                "runtime_label": runtime_label(item, is_unread=is_unread),
            },
            "stock_state": stock_state,
            "scoped_counts": scoped_counts,
        }


def match_product(text: str, products: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized = text.lower()
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in products:
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        values = [item.get("id"), data.get("name"), data.get("sku"), *(data.get("aliases") or [])]
        score = 0
        for value in values:
            value_text = str(value or "").strip()
            if value_text and value_text.lower() in normalized:
                score = max(score, len(value_text))
        if score:
            scored.append((score, item))
    if not scored:
        return None
    return sorted(scored, key=lambda pair: pair[0], reverse=True)[0][1]


def parse_quantity(text: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:台|个|件|辆|套|只|箱|库存)?", text)
    if match:
        return int(match.group(1))
    chinese_digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    for char, value in chinese_digits.items():
        if re.search(fr"{char}\s*(?:台|个|件|辆|套|只|箱)", text):
            return value
    return None


def extract_product_patch(text: str) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if has_any(text, "价格", "售价", "报价", "标价"):
        price = parse_decimal_after_keywords(text, "价格", "售价", "报价", "标价")
        if price is not None:
            patch["price"] = price
    category = extract_text_after_keywords(text, "类目", "分类")
    if category:
        patch["category"] = category
    shipping = extract_text_after_keywords(text, "发货", "物流")
    if shipping:
        patch["shipping_policy"] = shipping
    warranty = extract_text_after_keywords(text, "售后", "保修")
    if warranty:
        patch["warranty_policy"] = warranty
    details = extract_text_after_keywords(text, "备注", "说明")
    if details:
        patch["additional_details"] = details
    aliases = extract_text_after_keywords(text, "别名", "叫法", "也叫")
    if aliases:
        patch["aliases"] = split_aliases(aliases)
    return patch


def parse_decimal_after_keywords(text: str, *keywords: str) -> float | int | None:
    for keyword in keywords:
        match = re.search(fr"{re.escape(keyword)}\s*(?:改成|改为|设为|调整为|是|为|:|：)?\s*(\d+(?:\.\d+)?)", text)
        if not match:
            continue
        value = float(match.group(1))
        return int(value) if value.is_integer() else value
    return None


def extract_text_after_keywords(text: str, *keywords: str) -> str:
    for keyword in keywords:
        match = re.search(fr"{re.escape(keyword)}\s*(?:改成|改为|设为|调整为|是|为|:|：)?\s*(.+)$", text)
        if match:
            return cleanup_value_text(match.group(1))
    return ""


def cleanup_value_text(value: str) -> str:
    return str(value or "").strip(" ：:，,。；; \t\r\n")


def split_aliases(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，、/]\s*|\s+", value) if item.strip()]


def product_draft_advice(session: dict[str, Any]) -> dict[str, Any]:
    status = str(session.get("status") or "")
    missing = [str(item) for item in session.get("missing_fields", []) or [] if str(item)]
    if str(session.get("category_id") or "") != "products":
        return {
            "label": "需要人工检查",
            "message": "AI 没有把这份资料稳定识别为商品主数据，请修改草稿或换一份商品资料。",
            "missing_fields": missing,
        }
    if status == "ready":
        return {
            "label": "结构完整，可确认入库",
            "message": "AI 判断这份商品资料已满足商品库主字段要求。确认前仍建议核对价格、库存、单位和售后说明。",
            "missing_fields": [],
        }
    return {
        "label": "资料还不完整",
        "message": str(session.get("question") or "请补充缺失字段后再确认入库。"),
        "missing_fields": missing,
    }


def has_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def means_archived_status(text: str) -> bool:
    """Map merchant status wording to the only non-active state we support."""
    if has_any(text, "下架", "归档", "不卖", "停售", "停止销售", "不再销售"):
        return True
    if has_any(text, "已售罄", "售罄", "已售完", "售完", "卖完了", "卖光", "售空"):
        return True
    return False


def means_inventory_zero(text: str) -> bool:
    if has_any(text, "库存归零", "库存清零", "没有库存", "库存为0", "库存改成0", "库存设为0"):
        return True
    return False


def to_int(value: Any, *, default: int) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def product_stock_state(item: dict[str, Any], inventory: Any) -> str:
    if item.get("status") == "archived":
        return "archived"
    if inventory in (None, ""):
        return "unknown"
    try:
        return "sold_out" if int(float(str(inventory))) <= 0 else "in_stock"
    except (TypeError, ValueError):
        return "unknown"


def stock_label(stock_state: str, inventory: Any) -> str:
    if stock_state == "archived":
        return "已归档"
    if stock_state == "sold_out":
        return "无库存"
    if stock_state == "in_stock":
        return f"库存 {inventory}"
    return "库存未填写"


def runtime_label(item: dict[str, Any], *, is_unread: bool) -> str:
    if str(item.get("status") or "active") == "archived":
        return "已归档，不参与客服回复"
    if is_unread:
        return "新加入未已阅，暂不参与客服回复"
    return "已阅，可参与客服回复"
