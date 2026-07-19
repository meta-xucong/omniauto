"""Compatibility alias for the host-side neutral visual bridge."""

import importlib as _importlib
import sys as _sys

_impl = _importlib.import_module("apps.wechat_ai_customer_service.internal.vision_bridge")
_sys.modules[__name__] = _impl
