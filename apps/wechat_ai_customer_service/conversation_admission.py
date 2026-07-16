"""Pure admission policy for customer-service conversation candidates.

The session-list OCR surface also contains service-account containers, WeChat
system notices and local utility surfaces.  A dynamic "all conversations"
listener must mean all *customer* conversations, never every visible sidebar
row.  This module deliberately stays free of RPA, scheduler and Brain imports
so the same decision is made before a foreground click and again by every
later dispatch guard.
"""

from __future__ import annotations

from typing import Any


CUSTOMER_CONVERSATION_TYPES = frozenset({"private", "group"})
NON_CUSTOMER_CONVERSATION_TYPES = frozenset({"file_transfer", "system", "service_account", "utility"})

# These are WeChat-owned containers or one-way/system surfaces, not customer
# display names.  Keep the matching deliberately exact (apart from the OCR
# back-header form) so a legitimate customer whose name happens to contain a
# similar word is never excluded by substring matching.
NON_CUSTOMER_SESSION_TITLES = frozenset(
    {
        "服务号",
        "服务通知",
        "订阅号",
        "订阅号消息",
        "公众号",
        "系统消息",
        "微信团队",
        "微信支付",
        "微信安全中心",
        "腾讯客服",
        "微信运动",
    }
)


def normalized_session_title(value: Any) -> str:
    """Return a compact sidebar title suitable for exact surface checks."""

    return "".join(str(value or "").strip().split())


def non_customer_title_reason(value: Any) -> str:
    """Classify known non-customer sidebar containers without fuzzy matching."""

    title = normalized_session_title(value)
    if not title:
        return ""
    if title in NON_CUSTOMER_SESSION_TITLES:
        return "service_or_system_session"
    # OCR may retain the service-container back marker as "<服务号".  This is
    # still the container page, never a customer chat title.
    stripped = title.lstrip("<〈‹＜")
    if stripped in {"服务号", "订阅号", "公众号"}:
        return "service_container_subview"
    return ""

def inferred_non_customer_conversation_type(value: Any) -> str:
    """Return the canonical type for a known non-customer title, if any."""

    return "system" if non_customer_title_reason(value) else ""


def customer_session_admission_reason(
    *,
    name: Any,
    conversation_type: Any,
    session_key: Any,
) -> str:
    """Return why a dynamic customer-service candidate must not be dispatched.

    A blank/unknown identity is intentionally rejected before any ``open_chat``
    action.  Static, operator-configured test targets are not evaluated here;
    callers use this only for dynamic all-customer monitoring.
    """

    title_reason = non_customer_title_reason(name)
    if title_reason:
        return title_reason
    clean_type = str(conversation_type or "").strip().lower()
    if clean_type in NON_CUSTOMER_CONVERSATION_TYPES:
        return f"non_customer_conversation_type:{clean_type}"
    if clean_type not in CUSTOMER_CONVERSATION_TYPES:
        return "conversation_type_unconfirmed"
    if not str(session_key or "").strip():
        return "session_identity_missing"
    return ""
