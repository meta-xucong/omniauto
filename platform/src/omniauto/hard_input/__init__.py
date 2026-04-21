"""HardInput 硬输入模块.

基于 Interception 内核驱动实现的真实 HID 键鼠模拟，
作为 VisualEngine 的兜底方案，用于对抗 Qt/Chromium 架构
（如 WPS 文字）对合成输入的过滤。
"""

from .engine import HardInputEngine

__all__ = ["HardInputEngine"]
