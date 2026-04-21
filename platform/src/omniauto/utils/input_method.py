"""输入法检测与切换工具.

Windows 桌面自动化中，输入法状态（尤其是中文输入法的中/英文模式）
经常导致键鼠模拟输入被拦截或乱码。本模块提供检测与强制切换能力.
"""

import ctypes
import time
from ctypes import wintypes
from typing import Optional, Tuple

# 常见中文键盘布局低位字 (LANGID)
_CHINESE_LANGIDS = {
    0x0804,  # zh-CN
    0x0404,  # zh-TW
    0x0C04,  # zh-HK
    0x1404,  # zh-MO
    0x1004,  # zh-SG
}

# 常见英文键盘布局低位字
_ENGLISH_LANGIDS = {
    0x0409,  # en-US
    0x0809,  # en-GB
    0x0C09,  # en-AU
    0x1009,  # en-CA
    0x1409,  # en-NZ
    0x1809,  # en-IE
    0x1C09,  # en-ZA
    0x2009,  # en-JM
    0x2409,  # en-CB
    0x2809,  # en-BZ
    0x2C09,  # en-TT
    0x3009,  # en-ZW
    0x3409,  # en-PH
}


class InputMethodController:
    """基于 Windows API 的输入法状态检测与切换控制器."""

    @staticmethod
    def get_foreground_window_info() -> Tuple[int, int, int]:
        """获取前台窗口句柄、线程 ID 和键盘布局 HKL.

        Returns:
            (hwnd, tid, hkl) 元组.
        """
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        hkl = user32.GetKeyboardLayout(tid)
        return hwnd, tid, hkl

    @classmethod
    def get_keyboard_layout_langid(cls) -> int:
        """获取当前前台窗口线程的键盘布局 LANGID（低位字）."""
        _, _, hkl = cls.get_foreground_window_info()
        return hkl & 0xFFFF

    @classmethod
    def is_chinese_layout(cls) -> bool:
        """当前键盘布局是否为中文键盘布局."""
        return cls.get_keyboard_layout_langid() in _CHINESE_LANGIDS

    @classmethod
    def is_english_layout(cls) -> bool:
        """当前键盘布局是否为英文键盘布局."""
        return cls.get_keyboard_layout_langid() in _ENGLISH_LANGIDS

    @classmethod
    def try_get_ime_conversion_status(cls, hwnd: Optional[int] = None) -> Optional[bool]:
        """尝试通过 IMM32 获取 IME 转换状态（中文模式/英文模式）.

        Args:
            hwnd: 目标窗口句柄，若为 None 则使用前台窗口.

        Returns:
            True  表示 IME 处于中文（原生）输入模式；
            False 表示 IME 处于英文输入模式或已关闭；
            None  表示无法获取（当前环境/API 不支持）.
        """
        user32 = ctypes.windll.user32
        imm32 = ctypes.windll.imm32

        if hwnd is None:
            hwnd = user32.GetForegroundWindow()

        hIMC = imm32.ImmGetContext(hwnd)
        if not hIMC:
            # 若窗口本身无 IME 上下文，尝试其默认 IME 窗口
            ime_hwnd = imm32.ImmGetDefaultIMEWnd(hwnd)
            if ime_hwnd:
                hIMC = imm32.ImmGetContext(ime_hwnd)
            if not hIMC:
                return None

        try:
            conversion = wintypes.DWORD()
            sentence = wintypes.DWORD()
            ret = imm32.ImmGetConversionStatus(hIMC, ctypes.byref(conversion), ctypes.byref(sentence))
            imm32.ImmReleaseContext(hwnd, hIMC)
            if ret:
                # IME_CMODE_NATIVE = 0x0001，若置位通常表示中文/日文/韩文原生输入模式
                return bool(conversion.value & 0x0001)
        except Exception:
            imm32.ImmReleaseContext(hwnd, hIMC)
        return None

    @classmethod
    def is_chinese_input_mode(cls) -> bool:
        """综合判断当前是否处于中文输入模式.

        优先使用 IME 转换状态检测；若 API 不可用，则回退到键盘布局判断.
        """
        ime_status = cls.try_get_ime_conversion_status()
        if ime_status is not None:
            return ime_status
        return cls.is_chinese_layout()

    @classmethod
    def _send_key(cls, vk_code: int) -> None:
        """底层发送单个按键."""
        user32 = ctypes.windll.user32
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(vk_code, 0, 0, 0)
        user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)

    @classmethod
    def press_shift(cls) -> None:
        """发送 Shift 键（用于微软拼音等输入法的中/英文模式切换）."""
        cls._send_key(0x10)

    @classmethod
    def press_ctrl_space(cls) -> None:
        """发送 Ctrl+Space（用于打开/关闭中文输入法）."""
        user32 = ctypes.windll.user32
        KEYEVENTF_KEYUP = 0x0002
        VK_CONTROL = 0x11
        VK_SPACE = 0x20
        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_SPACE, 0, 0, 0)
        user32.keybd_event(VK_SPACE, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

    @classmethod
    def ensure_english_input(
        cls,
        detection_method: str = "auto",
        use_shift: bool = True,
        use_ctrl_space: bool = False,
        cooldown: float = 0.3,
    ) -> bool:
        """确保当前输入法处于英文输入状态.

        Args:
            detection_method: 检测方式，"auto" | "layout" | "ime".
            use_shift: 当检测到中文模式时，是否发送 Shift 键切换.
            use_ctrl_space: 若发送 Shift 后仍为中文，是否进一步发送 Ctrl+Space.
            cooldown: 每次按键后的冷却时间（秒）.

        Returns:
            True 表示执行了切换动作（或原本就是英文）；
            False 表示尝试后仍无法确认.
        """
        is_chinese = False

        if detection_method in ("auto", "ime"):
            ime_status = cls.try_get_ime_conversion_status()
            if ime_status is not None:
                is_chinese = ime_status
            elif detection_method == "ime":
                is_chinese = False  # 无法获取时保守处理
            else:
                is_chinese = cls.is_chinese_layout()
        else:
            is_chinese = cls.is_chinese_layout()

        if not is_chinese:
            return True

        if use_shift:
            cls.press_shift()
            time.sleep(cooldown)

            # 再次检测
            if detection_method in ("auto", "ime"):
                ime_status = cls.try_get_ime_conversion_status()
                if ime_status is not None:
                    is_chinese = ime_status
                else:
                    is_chinese = cls.is_chinese_layout()
            else:
                is_chinese = cls.is_chinese_layout()

        if is_chinese and use_ctrl_space:
            cls.press_ctrl_space()
            time.sleep(cooldown)
            return True

        return True


# 兼容旧式调用
def ensure_english_input(**kwargs) -> bool:
    return InputMethodController.ensure_english_input(**kwargs)
