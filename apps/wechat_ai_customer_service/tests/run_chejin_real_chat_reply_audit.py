"""Audit real historical customer questions against current reply pipeline.

This script:
1. extracts real customer questions from curated/raw chat sources;
2. simulates replies with the current runtime routing stack;
3. optionally probes LLM synthesis quality on a representative subset;
4. reports issue clusters and likely module ownership.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (PROJECT_ROOT, APP_ROOT, WORKFLOWS_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.knowledge_paths import tenant_context  # noqa: E402
from customer_service_loop import ReplyDecision  # noqa: E402
from knowledge_loader import build_evidence_pack  # noqa: E402
from llm_intent_router import IntentRouteResult, route_intent  # noqa: E402
from llm_reply_synthesis import maybe_synthesize_reply  # noqa: E402
from realtime_reply_router import decide_realtime_reply_route, maybe_build_realtime_reply  # noqa: E402
from listen_and_reply import (  # noqa: E402
    apply_local_customer_service_settings,
    handoff_acknowledgement_text,
    handoff_acknowledgement_is_low_information,
    load_config,
    maybe_match_product_knowledge,
)


DEFAULT_TENANT_ID = "chejin"
DEFAULT_CONFIG_PATH = APP_ROOT / "configs" / "jiangsu_chejin_xucong_live.example.json"
DEFAULT_RAW_INBOX_CHATS_DIR = APP_ROOT / "data" / "tenants" / "chejin_usedcar_regression" / "raw_inbox" / "chats"
DEFAULT_RUNTIME_MESSAGES_PATH = (
    APP_ROOT.parents[1] / "runtime" / "apps" / "wechat_ai_customer_service" / "tenants" / "chejin" / "raw_messages" / "messages.json"
)
DEFAULT_REPORT_PATH = (
    APP_ROOT.parents[1]
    / "runtime"
    / "apps"
    / "wechat_ai_customer_service"
    / "test_artifacts"
    / "chejin_real_chat_reply_audit_report.json"
)


USED_CAR_TERMS = (
    "车",
    "车型",
    "车源",
    "二手车",
    "预算",
    "自动挡",
    "手动挡",
    "省油",
    "油耗",
    "通勤",
    "家用",
    "试驾",
    "到店",
    "看车",
    "上牌",
    "过户",
    "贷款",
    "按揭",
    "首付",
    "月供",
    "置换",
    "收车",
    "估价",
    "车况",
    "公里",
    "检测",
)
HANDOFF_HINTS = ("转人工", "人工", "负责人", "确认后回复", "请负责人")
DIRECT_CHOICE_TERMS = ("哪个", "哪台", "哪款", "还是", "怎么选", "选一辆", "更推荐")
DIRECT_ANSWER_HINTS = ("建议", "优先", "更推荐", "先看", "我会先", "可以先")
VEHICLE_MODEL_TERMS = ("赛纳", "塞纳", "赛那", "凯美瑞", "雅阁", "奇骏", "途观", "gl8", "思域", "秦plus", "dm-i")
VEHICLE_CHOICE_CONTEXT_TERMS = USED_CAR_TERMS + ("suv", "mpv", "轿车", "越野", "纯电", "混动", "油车")
IDENTITY_OR_SYSTEM_TERMS = ("真人", "系统", "自动回", "机器人", "自动回复", "是不是ai", "是ai", "客服")


@dataclass(frozen=True)
class AuditSample:
    source: str
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--raw-inbox-chats", type=Path, default=DEFAULT_RAW_INBOX_CHATS_DIR)
    parser.add_argument("--runtime-messages", type=Path, default=DEFAULT_RUNTIME_MESSAGES_PATH)
    parser.add_argument("--max-total", type=int, default=220)
    parser.add_argument("--per-category", type=int, default=28)
    parser.add_argument("--llm-probe-limit", type=int, default=80)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # Offline audit should not be blocked by live/cloud safety rails.
    os.environ.setdefault("WECHAT_CLOUD_REQUIRED", "0")
    raw_config = load_config(args.config)
    config = load_audit_config(raw_config)
    samples = collect_samples(args.raw_inbox_chats, args.runtime_messages)
    selected = select_representative_samples(samples, max_total=max(20, args.max_total), per_category=max(3, args.per_category))

    results: list[dict[str, Any]] = []
    llm_probe_count = 0
    with tenant_context(args.tenant_id):
        for index, sample in enumerate(selected, start=1):
            result = simulate_one(sample=sample, config=config)
            if llm_probe_count < max(0, args.llm_probe_limit):
                probe = run_llm_probe(sample=sample, config=config, result=result)
                result["llm_probe"] = probe
                if probe.get("attempted"):
                    llm_probe_count += 1
            result["issues"] = detect_issues(sample.text, result)
            results.append(result)
            if index % 20 == 0:
                print(f"[audit] simulated {index}/{len(selected)}")

    report = build_report(samples=samples, selected=selected, results=results, config=args.config)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"[audit] report_path={args.report}")
    return 0


def load_audit_config(raw_config: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(raw_config if isinstance(raw_config, dict) else {})
    guard = cfg.get("live_safety_guard")
    if isinstance(guard, dict):
        guard["enabled"] = False
        cfg["live_safety_guard"] = guard
    intent_router = cfg.get("intent_router") if isinstance(cfg.get("intent_router"), dict) else {}
    llm_intent = intent_router.get("llm") if isinstance(intent_router.get("llm"), dict) else {}
    llm_intent["enabled"] = False
    intent_router["llm"] = llm_intent
    cfg["intent_router"] = intent_router

    llm_synthesis = cfg.get("llm_reply_synthesis") if isinstance(cfg.get("llm_reply_synthesis"), dict) else {}
    llm_synthesis["enabled"] = False
    cfg["llm_reply_synthesis"] = llm_synthesis
    return apply_local_customer_service_settings(cfg)


def collect_samples(raw_inbox_dir: Path, runtime_messages_path: Path) -> list[AuditSample]:
    samples: list[AuditSample] = []
    samples.extend(extract_from_raw_inbox(raw_inbox_dir))
    samples.extend(extract_from_runtime_messages(runtime_messages_path))
    return dedupe_samples(samples)


def extract_from_raw_inbox(raw_inbox_dir: Path) -> list[AuditSample]:
    if not raw_inbox_dir.exists():
        return []
    samples: list[AuditSample] = []
    for path in sorted(raw_inbox_dir.glob("*.txt")):
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in content.splitlines():
            text = line.strip()
            if not text:
                continue
            match = re.match(r"^(客户|顾客)\s*[：:]\s*(.+)$", text)
            if not match:
                continue
            question = sanitize_question(match.group(2))
            if question:
                samples.append(AuditSample(source=f"raw_inbox:{path.name}", text=question))
    return samples


def extract_from_runtime_messages(runtime_messages_path: Path) -> list[AuditSample]:
    if not runtime_messages_path.exists():
        return []
    try:
        payload = json.loads(runtime_messages_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    samples: list[AuditSample] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        text = sanitize_question(str(item.get("content") or ""))
        if not text:
            continue
        if is_obvious_bot_or_control_message(text):
            continue
        if is_likely_agent_reply_fragment(text):
            continue
        if not looks_like_customer_query(text):
            continue
        samples.append(AuditSample(source="runtime_messages", text=text))
    return samples


def sanitize_question(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    normalized = re.sub(r"^\[[A-Za-z0-9_:\- ]{6,80}\]\s*", "", normalized)
    normalized = re.sub(r"^\([A-Za-z0-9_:\- ]{6,80}\)\s*", "", normalized)
    normalized = normalized.strip("`'\"")
    if len(normalized) < 2:
        return ""
    if len(normalized) > 180:
        normalized = normalized[:180]
    return normalized


def is_obvious_bot_or_control_message(text: str) -> bool:
    lower = text.lower()
    blocked = (
        "[omniauto客服]",
        "[车金ai]",
        "[车金实盘]",
        "[omniauto自测]",
        "手动粘贴：",
        "演示批次：",
        "统一回复已经转接人工",
        "按f8",
        "已收到",
        "监听已停止",
        "实盘压测",
        "自动客服监听",
        "运行控制台",
        "商品资料：",
        "政策规则：",
        "聊天记录：",
        "测试批次：",
        "1条新消息",
        "无风险",
        "[l3可见锚点探针]",
    )
    if any(token in lower for token in blocked):
        return True
    return bool(re.match(r"^\s*(商品资料|政策规则|聊天记录)\s*[：:]", text))


def looks_like_customer_query(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    if re.search(r"[？?]", clean):
        return True
    return contains_any(
        clean,
        (
            "你好",
            "在吗",
            "想买",
            "想看",
            "预算",
            "推荐",
            "帮我",
            "麻烦",
            "请问",
            "咨询",
            "有没有",
            "多少",
            "怎么",
            "哪个",
            "哪台",
            "哪款",
            "可以",
            "能不能",
            "安排",
            "到店",
            "试驾",
            "置换",
            "贷款",
        ),
    )


def is_likely_agent_reply_fragment(text: str) -> bool:
    clean = str(text or "").strip()
    if not clean:
        return False
    stock_terms = ("上牌", "表显", "自动挡", "万公里", "检测报告", "看车城市", "到店时间", "贷款/置换")
    stock_hits = sum(1 for term in stock_terms if term in clean)
    if stock_hits >= 3 and len(clean) >= 56 and not re.search(r"[？?]", clean):
        return True
    if contains_any(clean, ("我再把优先级排细一点", "您把贷款/置换情况", "具体还是以检测报告为准")):
        return True
    if re.match(r"^[0-9一二三四五六七八九十]*\s*万[，,、；;）)]", clean) and len(clean) >= 24:
        return True
    if re.match(r"^(哥，按您|老板，按您|按您说的|如果先缩到两台)", clean):
        return True
    return False


def dedupe_samples(samples: list[AuditSample]) -> list[AuditSample]:
    seen: set[str] = set()
    result: list[AuditSample] = []
    for sample in samples:
        key = normalize_dedupe_key(sample.text)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(sample)
    return result


def normalize_dedupe_key(text: str) -> str:
    value = re.sub(r"\s+", "", str(text or ""))
    value = re.sub(r"[，。！？、,.!?；;:：~\-_=+（）()\[\]【】]", "", value)
    return value.lower().strip()


def select_representative_samples(samples: list[AuditSample], *, max_total: int, per_category: int) -> list[AuditSample]:
    grouped: dict[str, list[AuditSample]] = defaultdict(list)
    for sample in samples:
        grouped[classify_question(sample.text)].append(sample)
    selected: list[AuditSample] = []
    categories = sorted(grouped.keys(), key=lambda item: (0 if item == "used_car_core" else 1, item))
    for category in categories:
        selected.extend(grouped[category][:per_category])
    if len(selected) < max_total:
        selected_keys = {normalize_dedupe_key(item.text) for item in selected}
        for sample in samples:
            if len(selected) >= max_total:
                break
            key = normalize_dedupe_key(sample.text)
            if key in selected_keys:
                continue
            selected.append(sample)
            selected_keys.add(key)
    return selected[:max_total]


def classify_question(text: str) -> str:
    clean = str(text or "")
    if contains_any(clean, ("你好", "在吗", "哈喽", "嗨")) and len(clean) <= 12:
        return "greeting"
    if contains_any(clean, ("人工", "转人工", "投诉")):
        return "handoff"
    if contains_any(clean, ("置换", "收车", "估价", "卖车")):
        return "trade_in"
    if contains_any(clean, ("贷款", "按揭", "首付", "月供", "征信")):
        return "finance"
    if contains_any(clean, ("看车", "到店", "试驾", "周六", "周日", "预约")):
        return "appointment"
    if contains_any(clean, ("价格", "多少钱", "报价", "优惠", "最低")):
        return "price_discount"
    if contains_any(clean, ("哪个", "哪台", "还是", "怎么选", "更推荐")):
        return "compare_choice"
    if contains_any(clean, ("赛纳", "塞纳", "赛那", "凯美瑞", "雅阁", "奇骏", "途观", "gl8", "思域", "秦plus", "dm-i")):
        return "model_specific"
    if contains_any(clean, USED_CAR_TERMS):
        return "used_car_core"
    return "other"


def simulate_one(*, sample: AuditSample, config: dict[str, Any]) -> dict[str, Any]:
    message = sample.text
    evidence_pack = build_evidence_pack(message, context={"product_entity_resolution": config.get("product_entity_resolution", {}) or {}})
    intent_route = route_intent(
        combined=message,
        config=config,
        evidence_pack=evidence_pack,
        target_state={},
    )
    try:
        product_result = maybe_match_product_knowledge(config, {}, message, {})
    except Exception as exc:  # pragma: no cover - defensive guard for audit stability
        product_result = {"enabled": False, "matched": False, "reason": f"product_knowledge_probe_error:{exc!r}"}
    decision = build_initial_decision(product_result)
    intent_assist = {"intent": intent_route.intent, "evidence": {"safety": evidence_pack.get("safety", {}) or {}}}
    route = decide_realtime_reply_route(
        config=config,
        combined=message,
        decision=decision,
        intent_result=intent_route,
        intent_assist=intent_assist,
        rag_reply={},
        llm_reply={},
        product_knowledge=product_result,
        data_capture={},
        evidence_pack=evidence_pack,
        recent_reply_texts=[],
    )
    if (
        str(route.get("reason") or "") == "customer_data_or_contact_message"
        and handoff_acknowledgement_is_low_information(str(decision.reply_text or ""))
    ):
        decision = ReplyDecision(
            reply_text=handoff_acknowledgement_text(config, combined=message),
            rule_name=decision.rule_name,
            matched=decision.matched,
            need_handoff=True,
            reason=str(route.get("reason") or decision.reason),
        )
    realtime = maybe_build_realtime_reply(
        config=config,
        route=route,
        combined=message,
        evidence_pack=evidence_pack,
        current_reply_text=decision.reply_text,
        recent_reply_texts=[],
    )
    reply_text = str(realtime.get("reply_text") or decision.reply_text or "").strip()
    if (
        str(route.get("level") or "") == "L0"
        and str(route.get("reason") or "") == "deterministic_handoff_or_high_risk_boundary"
        and str(realtime.get("reason") or "") == "route_not_l1"
        and handoff_acknowledgement_is_low_information(reply_text)
    ):
        reply_text = handoff_acknowledgement_text(config, combined=message).strip()
        realtime = {**realtime, "applied": True, "rule_name": "simulated_l0_handoff_ack", "reason": "simulated_l0_handoff_ack"}
    return {
        "source": sample.source,
        "question": message,
        "category": classify_question(message),
        "intent_route": intent_route.to_dict(),
        "product_result": compact_mapping(product_result),
        "route": route,
        "realtime": compact_mapping(realtime),
        "reply_text": reply_text,
    }


def run_llm_probe(*, sample: AuditSample, config: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    batch = [{"id": "sim_msg_1", "sender": "customer", "content": sample.text, "time": ""}]
    product_result = result.get("product_result") if isinstance(result.get("product_result"), dict) else {}
    decision = build_initial_decision(product_result)
    route = result.get("route") if isinstance(result.get("route"), dict) else {}
    llm_config = copy.deepcopy(config)
    llm_synthesis = llm_config.get("llm_reply_synthesis") if isinstance(llm_config.get("llm_reply_synthesis"), dict) else {}
    llm_synthesis["enabled"] = True
    llm_synthesis.setdefault("provider", "openai")
    llm_synthesis.setdefault("retry_count", 0)
    llm_synthesis.setdefault("timeout_seconds", 8)
    llm_synthesis.setdefault("max_reply_chars", int(llm_synthesis.get("max_reply_chars") or 150))
    if route.get("foreground_llm_allowed"):
        llm_synthesis["foreground_realtime"] = True
    llm_config["llm_reply_synthesis"] = llm_synthesis

    attempted = bool(route.get("foreground_llm_allowed")) or route.get("level") in {"L2"} or not result.get("realtime", {}).get("applied", False)
    if not attempted:
        return {"attempted": False, "reason": "route_prefers_local_reply"}

    llm_result = maybe_synthesize_reply(
        config=llm_config,
        target_name="模拟客户",
        target_state={"conversation_context": {}},
        batch=batch,
        combined=sample.text,
        decision=decision,
        reply_text=str(result.get("reply_text") or ""),
        intent_assist={"intent": str((result.get("intent_route") or {}).get("intent") or "product_inquiry"), "evidence": {"safety": ((result.get("route") or {}).get("safety") or {})}},
        rag_reply={},
        llm_reply={},
        product_knowledge=product_result,
        data_capture={},
        raw_capture={},
        customer_profile=None,
    )
    return {
        "attempted": True,
        "applied": bool(llm_result.get("applied")),
        "rule_name": str(llm_result.get("rule_name") or ""),
        "reason": str(llm_result.get("reason") or ""),
        "model": str(llm_result.get("model") or ""),
        "model_tier": str(llm_result.get("model_tier") or ""),
        "reply_text": str(llm_result.get("reply_text") or ""),
        "needs_handoff": bool(llm_result.get("needs_handoff", False)),
        "llm_status": compact_mapping(llm_result.get("llm_status") or {}),
    }


def build_initial_decision(product_result: dict[str, Any]) -> ReplyDecision:
    if product_result.get("matched") and str(product_result.get("reply_text") or "").strip():
        return ReplyDecision(
            reply_text=str(product_result.get("reply_text") or ""),
            rule_name="product_knowledge",
            matched=True,
            need_handoff=bool(product_result.get("needs_handoff")),
            reason=str(product_result.get("reason") or "product_knowledge_matched"),
        )
    return ReplyDecision(
        reply_text="收到，我先看一下。",
        rule_name="no_rule",
        matched=False,
        need_handoff=False,
        reason="no_rule_matched",
    )


def detect_issues(question: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    reply = str(result.get("reply_text") or "").strip()
    route = result.get("route") if isinstance(result.get("route"), dict) else {}
    realtime = result.get("realtime") if isinstance(result.get("realtime"), dict) else {}
    llm_probe = result.get("llm_probe") if isinstance(result.get("llm_probe"), dict) else {}
    route_level = str(route.get("level") or "")
    route_reason = str(route.get("reason") or "")
    expected_l0_reasons = {
        "deterministic_handoff_or_high_risk_boundary",
        "customer_data_or_contact_message",
        "structured_product_fact_available",
    }
    expected_l0 = route_level == "L0" and route_reason in expected_l0_reasons

    if not reply:
        issues.append(issue("empty_reply", "回复为空", "listen_and_reply / realtime_reply_router"))
        return issues
    if len(reply) > 180:
        issues.append(issue("reply_too_long", f"回复偏长({len(reply)}字)", owner_from_result(route, realtime, llm_probe)))
    if is_vehicle_choice_question(question) and not contains_any(reply, DIRECT_ANSWER_HINTS) and not expected_l0:
        issues.append(issue("no_clear_recommendation", "明确选择题未给出清晰建议", "realtime_reply_router"))
    budget_issue = detect_budget_deviation(question, reply)
    if budget_issue:
        issues.append(issue("budget_deviation", budget_issue, "realtime_reply_router.rank_product_candidates"))
    if contains_any(question, USED_CAR_TERMS) and not contains_any(reply, USED_CAR_TERMS) and not expected_l0:
        issues.append(issue("weak_domain_alignment", "二手车问题回复缺少行业语义锚点", owner_from_result(route, realtime, llm_probe)))
    if not looks_high_risk(question) and contains_any(reply, HANDOFF_HINTS) and not expected_l0:
        issues.append(issue("possible_over_handoff", "非高风险问题出现转人工倾向", "realtime_reply_router / llm_reply_synthesis"))
    if contains_any(question, ("赛纳", "塞纳", "赛那")) and not contains_any(reply, ("赛那", "塞纳", "赛纳", "sienna")):
        issues.append(issue("entity_resolution_miss", "同义/同音车型识别后回复未显式对齐实体", "product_name_matcher / llm_product_name_matcher"))
    if str(route.get("reason") or "") == "uncertain_message_light_synthesis_allowed" and not llm_probe.get("attempted"):
        issues.append(issue("llm_not_triggered_when_uncertain", "不确定问题未触发LLM探针", "listen_and_reply / realtime_reply_router"))
    if str(realtime.get("reason") or "") == "route_not_l1":
        if expected_l0:
            return issues
        issues.append(issue("route_not_l1", "实时路由未进入L1回复分支", "realtime_reply_router"))
    return issues


def issue(code: str, detail: str, owner: str) -> dict[str, Any]:
    return {"code": code, "detail": detail, "owner": owner}


def owner_from_result(route: dict[str, Any], realtime: dict[str, Any], llm_probe: dict[str, Any]) -> str:
    if llm_probe.get("applied"):
        return "llm_reply_synthesis"
    if realtime.get("applied"):
        return "realtime_reply_router"
    if route.get("foreground_llm_allowed"):
        return "realtime_reply_router -> llm_reply_synthesis"
    return "listen_and_reply / realtime_reply_router"


def detect_budget_deviation(question: str, reply: str) -> str:
    if is_likely_agent_reply_fragment(question):
        return ""
    budget = extract_budget(question)
    if not budget:
        return ""
    prices = extract_prices(reply)
    if not prices:
        return ""
    lower, upper = budget
    if upper <= 0:
        return ""
    floor = max(0.0, lower * 0.6)
    ceil = upper * 1.4
    outlier = [price for price in prices if price < floor or price > ceil]
    if not outlier:
        return ""
    return f"预算[{lower:.2f},{upper:.2f}]万，回复价格存在偏离值: {', '.join(f'{item:.2f}' for item in outlier)}万"


def is_vehicle_choice_question(question: str) -> bool:
    clean = str(question or "")
    if contains_any(clean, ("哪个", "哪台", "哪款", "怎么选", "选一辆", "更推荐")):
        return True
    if "还是" not in clean:
        return False
    if contains_any(clean, IDENTITY_OR_SYSTEM_TERMS):
        return False
    if contains_any(clean, VEHICLE_CHOICE_CONTEXT_TERMS):
        return True
    return contains_any(clean, VEHICLE_MODEL_TERMS)


def extract_budget(text: str) -> tuple[float, float] | None:
    clean = str(text or "")
    match_range = re.search(r"(\d+(?:\.\d+)?)\s*[-到~]\s*(\d+(?:\.\d+)?)\s*万", clean)
    if match_range:
        left = float(match_range.group(1))
        right = float(match_range.group(2))
        return (min(left, right), max(left, right))
    match_cap = re.search(r"(\d+(?:\.\d+)?)\s*万\s*(以内|以下|内|上限|封顶)", clean)
    if match_cap:
        upper = float(match_cap.group(1))
        return (0.0, upper)
    match_around = re.search(r"(\d+(?:\.\d+)?)\s*万\s*左右", clean)
    if match_around:
        center = float(match_around.group(1))
        return (max(0.0, center - 1.5), center + 1.5)
    return None


def extract_prices(text: str) -> list[float]:
    prices: list[float] = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*万", str(text or "")):
        try:
            prices.append(float(match.group(1)))
        except (TypeError, ValueError):
            continue
    return prices


def looks_high_risk(question: str) -> bool:
    return contains_any(
        question,
        (
            "最低价",
            "底价",
            "保证",
            "包过",
            "赔偿",
            "合同",
            "定金",
            "订金",
            "征信",
            "审批",
            "发票",
            "退款",
        ),
    )


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    clean = str(text or "").lower()
    return any(term.lower() in clean for term in terms)


def compact_mapping(value: Any, *, max_text: int = 600) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, raw in value.items():
            if isinstance(raw, str):
                result[str(key)] = raw[:max_text]
            elif isinstance(raw, (int, float, bool)) or raw is None:
                result[str(key)] = raw
            elif isinstance(raw, list):
                result[str(key)] = raw[:8]
            elif isinstance(raw, dict):
                result[str(key)] = compact_mapping(raw, max_text=max_text)
        return result
    return value


def build_report(
    *,
    samples: list[AuditSample],
    selected: list[AuditSample],
    results: list[dict[str, Any]],
    config: Path,
) -> dict[str, Any]:
    issue_counter: Counter[str] = Counter()
    owner_counter: Counter[str] = Counter()
    category_counter: Counter[str] = Counter()
    reply_template_counter: Counter[str] = Counter()
    examples_by_issue: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in results:
        category = str(item.get("category") or "unknown")
        category_counter[category] += 1
        reply_key = normalize_dedupe_key(str(item.get("reply_text") or ""))
        if reply_key:
            reply_template_counter[reply_key] += 1
        for issue_item in item.get("issues", []) or []:
            code = str(issue_item.get("code") or "")
            owner = str(issue_item.get("owner") or "")
            issue_counter[code] += 1
            owner_counter[owner] += 1
            if len(examples_by_issue[code]) < 6:
                examples_by_issue[code].append(
                    {
                        "question": item.get("question"),
                        "reply": item.get("reply_text"),
                        "route_reason": (item.get("route") or {}).get("reason"),
                        "issue_detail": issue_item.get("detail"),
                        "owner": owner,
                    }
                )

    repeated_templates = [
        {"reply_key": key, "count": count}
        for key, count in reply_template_counter.most_common(12)
        if count >= 4
    ]

    return {
        "summary": {
            "source_question_count": len(samples),
            "selected_question_count": len(selected),
            "simulated_count": len(results),
            "issue_count": int(sum(issue_counter.values())),
            "issue_types": dict(issue_counter.most_common()),
            "module_owner_hotspots": dict(owner_counter.most_common()),
            "category_coverage": dict(category_counter.most_common()),
            "repeated_reply_templates": repeated_templates,
            "config_path": str(config),
        },
        "examples_by_issue": dict(examples_by_issue),
        "results": results,
    }


if __name__ == "__main__":
    raise SystemExit(main())
