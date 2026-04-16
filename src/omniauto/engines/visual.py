"""视觉自动化引擎.

基于 pyauto-desktop（PyAutoGUI 增强替代）封装，提供跨分辨率图像识别与物理级操作.
"""

import ctypes
import random
import time
from pathlib import Path
from typing import Optional, Tuple

import pyauto_desktop

from ..utils.input_method import InputMethodController
from ..utils.mouse import bezier_curve


class VisualEngine:
    """视觉自动化引擎，用于桌面软件自动化与浏览器降级兜底.

    基于 pyauto-desktop 实现跨分辨率自动缩放、图像定位和人类化鼠标移动.
    """

    def __init__(
        self,
        screen: int = 1,
        source_resolution: Optional[Tuple[int, int]] = None,
        source_dpr: float = 1.0,
    ) -> None:
        self.screen = screen
        self.source_resolution = source_resolution
        self.source_dpr = source_dpr
        self._session: Optional[pyauto_desktop.Session] = None

    def start(self) -> "VisualEngine":
        """初始化视觉会话."""
        kwargs: dict = {"screen": self.screen}
        if self.source_resolution:
            kwargs["source_resolution"] = self.source_resolution
            kwargs["source_dpr"] = self.source_dpr
            kwargs["scaling_type"] = "dpr"
        self._session = pyauto_desktop.Session(**kwargs)
        return self

    def _locate(self, image_path: str, confidence: float = 0.9) -> Optional[Tuple[int, int, int, int]]:
        """内部方法：定位图像并返回边界框 `(left, top, width, height)`。"""
        if not Path(image_path).exists():
            return None
        if self._session is None:
            raise RuntimeError("VisualEngine 尚未启动，请先调用 start()")
        result = self._session.locateOnScreen(image_path, grayscale=True, confidence=confidence)
        if result is not None:
            return (result.left, result.top, result.width, result.height)
        return None

    def locate_center(self, image_path: str, confidence: float = 0.9) -> Optional[Tuple[int, int]]:
        """定位图像中心坐标."""
        box = self._locate(image_path, confidence)
        if box is None:
            return None
        left, top, width, height = box
        return (left + width // 2, top + height // 2)

    def click(
        self,
        image_path: Optional[str] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        confidence: float = 0.9,
        pre_delay: Tuple[float, float] = (0.1, 0.3),
        duration: float = 0.5,
    ) -> bool:
        """点击图像或指定坐标.

        Args:
            image_path: 模板图像路径.
            x, y: 直接指定的屏幕坐标（与 `image_path` 二选一）。
            confidence: 图像匹配置信度.
            pre_delay: 点击前随机延迟范围.
            duration: 鼠标移动耗时.

        Returns:
            是否成功点击.
        """
        if self._session is None:
            raise RuntimeError("VisualEngine 尚未启动，请先调用 start()")

        if pre_delay:
            time.sleep(random.uniform(*pre_delay))

        if image_path is not None:
            center = self.locate_center(image_path, confidence)
            if center is None:
                return False
            x, y = center

        if x is None or y is None:
            return False

        self._human_like_move(x, y, duration=duration)
        self._session.click()
        return True

    def type_text(
        self,
        text: str,
        interval: Tuple[float, float] = (0.05, 0.15),
        ensure_english: bool = False,
    ) -> None:
        """模拟键盘输入，支持随机间隔.

        Args:
            text: 要输入的文本.
            interval: 每个字符之间的随机延迟范围.
            ensure_english: 是否在输入前强制切换到英文输入法状态，
                避免中文输入法拦截 ASCII 字符.
        """
        if self._session is None:
            raise RuntimeError("VisualEngine 尚未启动，请先调用 start()")
        if ensure_english:
            InputMethodController.ensure_english_input()
        # pyauto-desktop Session.write 支持 interval，但为了更精细的随机间隔，这里逐字符写入
        for char in text:
            self._session.write(char, interval=0)
            time.sleep(random.uniform(*interval))

    def screenshot(self, path: Optional[str] = None) -> str:
        """截取全屏并保存."""
        if self._session is None:
            raise RuntimeError("VisualEngine 尚未启动，请先调用 start()")
        if path is None:
            artifact_dir = Path("test_artifacts/screenshots/visual")
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = str(artifact_dir / f"visual_screenshot_{int(time.time()*1000)}.png")
        img = self._session.screenshot()
        img.save(path)
        return path

    def _human_like_move(self, x: int, y: int, duration: float = 0.5) -> None:
        """使用贝塞尔曲线移动鼠标."""
        if self._session is None:
            raise RuntimeError("VisualEngine 尚未启动，请先调用 start()")
        current_x, current_y = _get_cursor_pos()
        points = bezier_curve((current_x, current_y), (x, y), num_points=20)
        step_duration = duration / len(points)
        for px, py in points:
            self._session.moveTo(px, py, duration=0)
            time.sleep(step_duration)

    def press(self, key: str) -> None:
        """按下单个按键."""
        if self._session is None:
            raise RuntimeError("VisualEngine 尚未启动，请先调用 start()")
        self._session.press(key)

    def hotkey(self, *keys: str) -> None:
        """按下组合键."""
        if self._session is None:
            raise RuntimeError("VisualEngine 尚未启动，请先调用 start()")
        for k in keys:
            self._session.keyDown(k)
        for k in reversed(keys):
            self._session.keyUp(k)

    @staticmethod
    def inspector() -> None:
        """打开 pyauto-desktop 内置 GUI Inspector（用于录制或生成代码）。"""
        pyauto_desktop.inspector()

    @staticmethod
    def ensure_english_input(
        detection_method: str = "auto",
        use_shift: bool = True,
        use_ctrl_space: bool = False,
        cooldown: float = 0.3,
    ) -> bool:
        """确保当前输入法处于英文输入状态.

        在输入英文或 ASCII 内容前调用，可避免中文输入法（如微软拼音）
        拦截按键导致乱码或输入失败。

        Args:
            detection_method: 检测方式，`"auto"`、`"layout"` 或 `"ime"`。
            use_shift: 检测到中文模式时是否发送 Shift 键切换。
            use_ctrl_space: Shift 无效时是否进一步发送 Ctrl+Space。
            cooldown: 每次按键后的冷却时间（秒）。

        Returns:
            True 表示已确保英文状态，或已执行切换动作。
        """
        return InputMethodController.ensure_english_input(
            detection_method=detection_method,
            use_shift=use_shift,
            use_ctrl_space=use_ctrl_space,
            cooldown=cooldown,
        )


def _get_cursor_pos() -> Tuple[int, int]:
    """通过 Windows API 获取当前鼠标坐标."""
    from ctypes import wintypes

    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y
