from __future__ import annotations

from typing import Any


class BuiltinVisionPlugin:
    name = "builtin_customer_image_understanding"
    capability = "vision"

    def available(self) -> bool:
        return True

    def should_run(self, context: dict[str, Any]) -> dict[str, Any]:
        from .trigger import (
            customer_image_capture_trigger,
        )

        return customer_image_capture_trigger(
            payload=context.get("payload"),
            pending_signal=(
                context.get("pending_signal")
                if isinstance(context.get("pending_signal"), dict)
                else None
            ),
            pending_signal_kind=str(context.get("pending_signal_kind") or ""),
            target_state=(
                context.get("target_state")
                if isinstance(context.get("target_state"), dict)
                else None
            ),
            recent_message_limit=int(context.get("recent_message_limit") or 6),
        )

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        from apps.wechat_ai_customer_service.workflows.customer_image_turn_router import (
            maybe_route_customer_image_turn,
        )

        return maybe_route_customer_image_turn(
            connector=context.get("connector"),
            target=context.get("target"),
            config=context.get("config") if isinstance(context.get("config"), dict) else {},
            payload=context.get("payload") if isinstance(context.get("payload"), dict) else {},
            target_state=(
                context.get("target_state")
                if isinstance(context.get("target_state"), dict)
                else {}
            ),
            batch=[item for item in (context.get("batch") or []) if isinstance(item, dict)],
            combined=str(context.get("combined") or ""),
        )


def create_default_vision_plugin() -> BuiltinVisionPlugin:
    return BuiltinVisionPlugin()
