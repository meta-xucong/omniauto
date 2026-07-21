from __future__ import annotations

from typing import Any


class BuiltinVisionPlugin:
    name = "builtin_customer_image_understanding"
    capability = "vision"

    def available(self) -> bool:
        from .service import create_vision_service

        return create_vision_service().available()

    def should_run(self, context: dict[str, Any]) -> dict[str, Any]:
        from .service import create_vision_service

        return create_vision_service().should_run(context)

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        from .service import create_vision_service

        return create_vision_service().inspect_current_conversation(context)

    def observe_current_surface(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return structural message envelopes without understanding pixels."""

        from .service import create_vision_service

        return create_vision_service().observe_current_surface(context)

    def capture_self_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return a text-only self-image context result; never a reply plan."""

        from .service import create_vision_service

        return create_vision_service().inspect_self_context(context)

    def invoke(self, operation: str, context: dict[str, Any]) -> Any:
        """Dispatch implementation-owned supplemental operations lazily."""

        from .operations import invoke_vision_operation

        return invoke_vision_operation(operation, context)


def create_default_vision_plugin() -> BuiltinVisionPlugin:
    return BuiltinVisionPlugin()
