"""Runtime containment for the byte-immutable WeChat PR #28 integration.

This module is deliberately outside every PR-owned file.  It preserves the
original connector method names and payload shapes while applying host-side
identity and process-environment policy before the immutable connector enters
the physical RPA layer.

It must not contain customer-service reply logic or optional Vision logic.
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass
from typing import Any


PR28_HEAD = "e6a53bd012564d05ad009f29c8921e11bc67c812"
PR28_BLOBS = {
    "apps/wechat_ai_customer_service/adapters/wechat_connector.py": "f25d605ee6baff4b935f4339a6183d5446d97c33",
    "apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/text_normalization.py": "7a09c6ddd2d218ee941686f4985cc2f184f03a4d",
    "apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py": "050e29d5669a63c691883788df4b69a19720e107",
    "apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py": "66900f31efa4ef1cffc0a0745195c4019aad1de4",
    "apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_sender_role_screenshot_replay.py": "0832a0be250093ef3c8384d6c0296b50f9d2b4c8",
    "apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_window_action_planning_checks.py": "a0efe8031f79165654b97185e0ed94d84919033b",
    "apps/wechat_ai_customer_service/wechat_message_envelope.py": "3c81ea47717b67ea3b82d9224fc7d83941eed722",
}


def physical_rpa_identity_kwargs(values: dict[str, Any]) -> dict[str, Any]:
    """Project a semantic identity onto the immutable PR physical boundary.

    ``session_key`` and the exact title remain the hard physical identity.  A
    conversation type learned later from message structure is useful semantic
    metadata, but must not invalidate the already-issued opaque key.  Omitting
    only that optional physical filter lets PR #28 reacquire the exact key while
    keeping every caller-visible field unchanged.
    """

    projected = dict(values or {})
    if str(projected.get("session_key") or "").strip():
        projected["conversation_type"] = ""
    return projected


def _install_sidecar_environment_containment(connector: Any) -> None:
    original = getattr(connector, "call_compat_sidecar", None)
    if not callable(original):
        return
    if bool(getattr(original, "_omniauto_pr28_environment_containment", False)):
        return

    @functools.wraps(original)
    def contained_call(
        args: list[str],
        *,
        allow_failure: bool = False,
        primary_payload: dict[str, Any] | None = None,
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        overrides = dict(env_overrides or {})
        if "WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN" not in os.environ:
            overrides.setdefault("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN", "1")
        return original(
            args,
            allow_failure=allow_failure,
            primary_payload=primary_payload,
            env_overrides=overrides or None,
        )

    contained_call._omniauto_pr28_environment_containment = True
    try:
        connector.call_compat_sidecar = contained_call
    except (AttributeError, TypeError):
        # Frozen test doubles and custom third-party connectors remain valid.
        # They do not spawn the immutable PR Sidecar and therefore need no
        # process-environment containment.
        return


@dataclass
class WeChatPr28RuntimeAdapter:
    """Transparent internal proxy around the immutable PR connector."""

    delegate: Any

    def __post_init__(self) -> None:
        _install_sidecar_environment_containment(self.delegate)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def get_messages(self, target: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        return self.delegate.get_messages(
            target,
            exact=exact,
            **physical_rpa_identity_kwargs(kwargs),
        )

    def send_text(self, target: str, text: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        return self.delegate.send_text(
            target,
            text,
            exact=exact,
            **physical_rpa_identity_kwargs(kwargs),
        )

    def send_text_and_verify(
        self,
        target: str,
        text: str,
        exact: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.delegate.send_text_and_verify(
            target,
            text,
            exact=exact,
            **physical_rpa_identity_kwargs(kwargs),
        )

def adapt_wechat_pr28_connector(connector: Any) -> Any:
    if isinstance(connector, WeChatPr28RuntimeAdapter):
        return connector
    return WeChatPr28RuntimeAdapter(connector)


__all__ = [
    "PR28_BLOBS",
    "PR28_HEAD",
    "WeChatPr28RuntimeAdapter",
    "adapt_wechat_pr28_connector",
    "physical_rpa_identity_kwargs",
]
