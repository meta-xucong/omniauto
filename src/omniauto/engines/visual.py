"""瑙嗚鑷姩鍖栧紩鎿?

鍩轰簬 pyauto-desktop锛圥yAutoGUI 澧炲己鏇夸唬锛夊皝瑁咃紝鎻愪緵璺ㄥ垎杈ㄧ巼鍥惧儚璇嗗埆涓庣墿鐞嗙骇鎿嶄綔.
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
    """瑙嗚鑷姩鍖栧紩鎿庯紝鐢ㄤ簬妗岄潰杞欢鑷姩鍖栦笌娴忚鍣ㄩ檷绾у厹搴?

    鍩轰簬 pyauto-desktop 瀹炵幇璺ㄥ垎杈ㄧ巼鑷姩缂╂斁銆佸浘鍍忓畾浣嶃€佷汉绫诲寲榧犳爣绉诲姩.
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
        """鍒濆鍖栬瑙変細璇?"""
        kwargs: dict = {"screen": self.screen}
        if self.source_resolution:
            kwargs["source_resolution"] = self.source_resolution
            kwargs["source_dpr"] = self.source_dpr
            kwargs["scaling_type"] = "dpr"
        self._session = pyauto_desktop.Session(**kwargs)
        return self

    def _locate(self, image_path: str, confidence: float = 0.9) -> Optional[Tuple[int, int, int, int]]:
        """鍐呴儴鏂规硶锛氬畾浣嶅浘鍍忓苟杩斿洖杈圭晫妗?(left, top, width, height)."""
        if not Path(image_path).exists():
            return None
        if self._session is None:
            raise RuntimeError("VisualEngine 灏氭湭鍚姩锛岃鍏堣皟鐢?start()")
        result = self._session.locateOnScreen(image_path, grayscale=True, confidence=confidence)
        if result is not None:
            return (result.left, result.top, result.width, result.height)
        return None

    def locate_center(self, image_path: str, confidence: float = 0.9) -> Optional[Tuple[int, int]]:
        """瀹氫綅鍥惧儚涓績鍧愭爣."""
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
        """鐐瑰嚮鍥惧儚鎴栨寚瀹氬潗鏍?

        Args:
            image_path: 妯℃澘鍥惧儚璺緞.
            x, y: 鐩存帴鎸囧畾鐨勫睆骞曞潗鏍囷紙涓?image_path 浜岄€変竴锛?
            confidence: 鍥惧儚鍖归厤缃俊搴?
            pre_delay: 鐐瑰嚮鍓嶉殢鏈哄欢杩熻寖鍥?
            duration: 榧犳爣绉诲姩鑰楁椂.

        Returns:
            鏄惁鎴愬姛鐐瑰嚮.
        """
        if self._session is None:
            raise RuntimeError("VisualEngine 灏氭湭鍚姩锛岃鍏堣皟鐢?start()")

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
        """妯℃嫙閿洏杈撳叆锛屾敮鎸侀殢鏈洪棿闅?

        Args:
            text: 瑕佽緭鍏ョ殑鏂囨湰.
            interval: 姣忎釜瀛楃涔嬮棿鐨勯殢鏈哄欢杩熻寖鍥?
            ensure_english: 鏄惁鍦ㄨ緭鍏ュ墠寮哄埗鍒囨崲鍒拌嫳鏂囪緭鍏ユ硶鐘舵€侊紝
                閬垮厤涓枃杈撳叆娉曟嫤鎴?ASCII 瀛楃.
        """
        if self._session is None:
            raise RuntimeError("VisualEngine 灏氭湭鍚姩锛岃鍏堣皟鐢?start()")
        if ensure_english:
            InputMethodController.ensure_english_input()
        # pyauto-desktop Session.write 鏀寔 interval锛屼絾涓轰簡鏇寸簿缁嗙殑闅忔満闂撮殧锛岄€愬瓧绗﹀啓鍏?        for char in text:
            self._session.write(char, interval=0)
            time.sleep(random.uniform(*interval))

    def screenshot(self, path: Optional[str] = None) -> str:
        """鎴彇鍏ㄥ睆骞朵繚瀛?"""
        if self._session is None:
            raise RuntimeError("VisualEngine 灏氭湭鍚姩锛岃鍏堣皟鐢?start()")
        if path is None:
            artifact_dir = Path("test_artifacts/screenshots/visual")
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = str(artifact_dir / f"visual_screenshot_{int(time.time()*1000)}.png")
        img = self._session.screenshot()
        img.save(path)
        return path

    def _human_like_move(self, x: int, y: int, duration: float = 0.5) -> None:
        """浣跨敤璐濆灏旀洸绾跨Щ鍔ㄩ紶鏍?"""
        if self._session is None:
            raise RuntimeError("VisualEngine 灏氭湭鍚姩锛岃鍏堣皟鐢?start()")
        current_x, current_y = _get_cursor_pos()
        points = bezier_curve((current_x, current_y), (x, y), num_points=20)
        step_duration = duration / len(points)
        for px, py in points:
            self._session.moveTo(px, py, duration=0)
            time.sleep(step_duration)

    def press(self, key: str) -> None:
        """鎸変笅鍗曚釜鎸夐敭."""
        if self._session is None:
            raise RuntimeError("VisualEngine 灏氭湭鍚姩锛岃鍏堣皟鐢?start()")
        self._session.press(key)

    def hotkey(self, *keys: str) -> None:
        """鎸変笅缁勫悎閿?"""
        if self._session is None:
            raise RuntimeError("VisualEngine 灏氭湭鍚姩锛岃鍏堣皟鐢?start()")
        for k in keys:
            self._session.keyDown(k)
        for k in reversed(keys):
            self._session.keyUp(k)

    @staticmethod
    def inspector() -> None:
        """鎵撳紑 pyauto-desktop 鍐呯疆 GUI Inspector锛堢敤浜庡綍鍒?鐢熸垚浠ｇ爜锛?"""
        pyauto_desktop.inspector()

    @staticmethod
    def ensure_english_input(
        detection_method: str = "auto",
        use_shift: bool = True,
        use_ctrl_space: bool = False,
        cooldown: float = 0.3,
    ) -> bool:
        """纭繚褰撳墠杈撳叆娉曞浜庤嫳鏂囪緭鍏ョ姸鎬?

        鍦ㄨ緭鍏ヨ嫳鏂囨垨 ASCII 鍐呭鍓嶈皟鐢紝鍙伩鍏嶄腑鏂囪緭鍏ユ硶锛堝寰蒋鎷奸煶锛?        鎷︽埅鎸夐敭瀵艰嚧涔辩爜鎴栬緭鍏ュけ璐?

        Args:
            detection_method: 妫€娴嬫柟寮忥紝"auto" | "layout" | "ime".
            use_shift: 妫€娴嬪埌涓枃妯″紡鏃舵槸鍚﹀彂閫?Shift 閿垏鎹?
            use_ctrl_space: Shift 鏃犳晥鏃舵槸鍚﹁繘涓€姝ュ彂閫?Ctrl+Space.
            cooldown: 姣忔鎸夐敭鍚庣殑鍐峰嵈鏃堕棿锛堢锛?

        Returns:
            True 琛ㄧず宸茬‘淇濊嫳鏂囩姸鎬侊紙鎴栨墽琛屼簡鍒囨崲鍔ㄤ綔锛?
        """
        return InputMethodController.ensure_english_input(
            detection_method=detection_method,
            use_shift=use_shift,
            use_ctrl_space=use_ctrl_space,
            cooldown=cooldown,
        )


def _get_cursor_pos() -> Tuple[int, int]:
    """閫氳繃 Windows API 鑾峰彇褰撳墠榧犳爣鍧愭爣."""
    from ctypes import wintypes
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

