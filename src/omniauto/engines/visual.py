"""视觉自动化引擎.

基于 pyauto-desktop（PyAutoGUI 增强替代）封装，提供跨分辨率图像识别与物理级操作.
"""

import random
from pathlib import Path
from typing import Optional, Tuple

import pyauto_desktop

from ..utils.mouse import bezier_curve


class VisualEngine:
    """视觉自动化引擎，用于桌面软件自动化与浏览器降级兜底.

    基于 pyauto-desktop 实现跨分辨率自动缩放、图像定位、人类化鼠标移动.
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
        if self.source_resolution:
            self._session = pyauto_desktop.Session(
                screen=self.screen,
                source_resolution=self.source_resolution,
                source_dpr=self.source_dpr,
                scaling_type="dpr",
            )
        else:
            # 若未指定源分辨率，则直接使用当前屏幕（不启用自动缩放）
            self._session = None
        return self

    def _locate(self, image_path: str, confidence: float = 0.9) -> Optional[Tuple[int, int, int, int]]:
        """内部方法：定位图像并返回边界框 (left, top, width, height)."""
        if not Path(image_path).exists():
            return None
        if self._session is not None:
            result = self._session.locateOnScreen(image_path, grayscale=True, confidence=confidence)
            if result is not None:
                return (result.left, result.top, result.width, result.height)
            return None
        # 降级到标准 pyauto-desktop API
        result = pyauto_desktop.locateOnScreen(image_path, grayscale=True, confidence=confidence)
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
            x, y: 直接指定的屏幕坐标（与 image_path 二选一）.
            confidence: 图像匹配置信度.
            pre_delay: 点击前随机延迟范围.
            duration: 鼠标移动耗时.

        Returns:
            是否成功点击.
        """
        if pre_delay:
            import time
            time.sleep(random.uniform(*pre_delay))

        if image_path is not None:
            center = self.locate_center(image_path, confidence)
            if center is None:
                return False
            x, y = center

        if x is None or y is None:
            return False

        if self._session is not None:
            self._session.moveTo(x, y, duration=duration)
            self._session.click()
        else:
            self._human_like_move(x, y, duration=duration)
            pyauto_desktop.click()
        return True

    def type_text(
        self,
        text: str,
        interval: Tuple[float, float] = (0.05, 0.15),
    ) -> None:
        """模拟键盘输入，支持随机间隔."""
        for char in text:
            pyauto_desktop.typewrite(char, interval=0)
            import time
            time.sleep(random.uniform(*interval))

    def screenshot(self, path: Optional[str] = None) -> str:
        """截取全屏并保存."""
        import time
        if path is None:
            path = f"visual_screenshot_{int(time.time()*1000)}.png"
        if self._session is not None:
            img = self._session.screenshot()
        else:
            # 降级到 mss + Pillow
            from mss import mss
            from PIL import Image
            with mss() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                img = Image.frombytes("RGB", (monitor["width"], monitor["height"]), sct.grab(monitor).rgb)
        img.save(path)
        return path

    def _human_like_move(self, x: int, y: int, duration: float = 0.5) -> None:
        """使用贝塞尔曲线移动鼠标（无 Session 时的降级方案）."""
        import time
        current_x, current_y = pyauto_desktop.position()
        points = bezier_curve((current_x, current_y), (x, y), num_points=20)
        step_duration = duration / len(points)
        for px, py in points:
            pyauto_desktop.moveTo(px, py)
            time.sleep(step_duration)

    def press(self, key: str) -> None:
        """按下单个按键."""
        pyauto_desktop.press(key)

    def hotkey(self, *keys: str) -> None:
        """按下组合键."""
        pyauto_desktop.hotkey(*keys)

    @staticmethod
    def inspector() -> None:
        """打开 pyauto-desktop 内置 GUI Inspector（用于录制/生成代码）."""
        pyauto_desktop.inspector()
