"""OmniAuto 原子步骤库."""

from .navigate import NavigateStep
from .click import ClickStep
from .type import TypeStep
from .extract import ExtractTextStep, ExtractAttributeStep
from .screenshot import ScreenshotStep
from .wait import WaitStep
from .scroll import ScrollToBottomStep
from .hotkey import HotkeyStep
from .visual_click import VisualClickStep

__all__ = [
    "NavigateStep",
    "ClickStep",
    "TypeStep",
    "ExtractTextStep",
    "ExtractAttributeStep",
    "ScreenshotStep",
    "WaitStep",
    "ScrollToBottomStep",
    "HotkeyStep",
    "VisualClickStep",
]
