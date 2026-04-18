"""HardInput 引擎：基于 Interception 内核驱动的真实 HID 键鼠模拟.

这是 VisualEngine 的"硬兜底"版本，能够绕过用户态对 LLKHF_INJECTED 的检测，
对 Qt/Chromium 架构的应用（如 WPS 文字）同样生效.
"""

import random
import time
from typing import Optional, Tuple

import pyperclip

from ..utils.input_method import InputMethodController


class HardInputEngine:
    """基于 Interception 驱动的高仿真键鼠自动化引擎.

    与 VisualEngine 保持接口兼容，上层脚本无需修改即可切换.
    """

    def __init__(self) -> None:
        self._interception = None

    def start(self) -> "HardInputEngine":
        """初始化 Interception 设备捕获."""
        try:
            import interception

            interception.auto_capture_devices()
            self._interception = interception
        except Exception as exc:
            raise RuntimeError(
                "Interception 驱动未安装或初始化失败。"
                "请先以管理员身份运行 install-interception.exe /install 并重启系统。"
            ) from exc
        return self

    def click(
        self,
        x: Optional[int] = None,
        y: Optional[int] = None,
        button: str = "left",
        pre_delay: Tuple[float, float] = (0.1, 0.3),
        duration: float = 0.5,
    ) -> bool:
        """点击指定坐标.

        Args:
            x, y: 屏幕绝对坐标.
            button: 鼠标按钮，支持 left/right/middle/mouse4/mouse5.
            pre_delay: 点击前随机延迟.
            duration: 鼠标移动耗时（当前版本由 interception 内部控制，此参数保留兼容）.
        """
        if self._interception is None:
            raise RuntimeError("HardInputEngine 尚未启动，请先调用 start()")
        if pre_delay:
            time.sleep(random.uniform(*pre_delay))
        if x is not None and y is not None:
            self._interception.move_to(x, y)
        self._interception.click(button=button)
        return True

    def move_to(self, x: int, y: int, duration: float = 0.5) -> None:
        """移动鼠标到指定坐标."""
        if self._interception is None:
            raise RuntimeError("HardInputEngine 尚未启动，请先调用 start()")
        # interception.move_to 本身已经比较平滑；若需要更精细的贝塞尔控制，可后续扩展
        self._interception.move_to(x, y)

    def type_text(
        self,
        text: str,
        interval: Tuple[float, float] = (0.05, 0.15),
        ensure_english: bool = False,
        use_clipboard: bool = False,
    ) -> None:
        """模拟键盘输入.

        Args:
            text: 要输入的文本.
            interval: 每个字符之间的随机延迟范围.
            ensure_english: 是否在输入前强制切换到英文输入法状态.
            use_clipboard: 是否通过系统剪贴板+Ctrl+V 的方式输入文本。
                对于拦截直接键盘输入的应用（如 WPS 文字编辑区），
                剪贴板粘贴是唯一可靠的方式。
        """
        if self._interception is None:
            raise RuntimeError("HardInputEngine 尚未启动，请先调用 start()")
        if ensure_english:
            InputMethodController.ensure_english_input()

        if use_clipboard:
            self._type_text_via_clipboard(text)
            return

        # interception.write 不支持大写和特殊字符（仅支持小写字母和数字），
        # 因此我们对每个字符做自定义处理：
        # - 小写字母、数字：直接 press
        # - 大写字母：hold shift + press 对应小写
        # - 常见标点/符号：映射到对应键位
        for char in text:
            self._send_char(char)
            time.sleep(random.uniform(*interval))

    def _type_text_via_clipboard(self, text: str) -> None:
        """通过剪贴板粘贴输入文本."""
        # 保存当前剪贴板内容（简单实现：只保存文本）
        original = ""
        try:
            original = pyperclip.paste()
        except Exception:
            pass

        pyperclip.copy(text)
        time.sleep(0.2)
        self.hotkey("ctrl", "v")
        paste_settle = min(2.0, max(0.8, len(text) / 200.0))
        time.sleep(paste_settle)

        # 恢复剪贴板
        try:
            pyperclip.copy(original)
        except Exception:
            pass

    def _send_char(self, char: str) -> None:
        """发送单个字符."""
        import interception

        # 换行
        if char == "\n":
            interception.press("return")
            return

        # 空格
        if char == " ":
            interception.press("space")
            return

        # 小写英文字母或数字
        if char.isascii() and char.isalnum() and char.islower():
            interception.press(char)
            return

        # 大写英文字母
        if char.isascii() and char.isalpha() and char.isupper():
            with interception.hold_key("shift"):
                interception.press(char.lower())
            return

        # 常见中文标点与符号映射（基于标准 US 键盘布局）
        symbol_map = {
            "!": ("1", True),
            "@": ("2", True),
            "#": ("3", True),
            "$": ("4", True),
            "%": ("5", True),
            "^": ("6", True),
            "&": ("7", True),
            "*": ("8", True),
            "(": ("9", True),
            ")": ("0", True),
            "-": ("minus", False),
            "_": ("minus", True),
            "=": ("equals", False),
            "+": ("equals", True),
            "[": ("leftbracket", False),
            "{": ("leftbracket", True),
            "]": ("rightbracket", False),
            "}": ("rightbracket", True),
            "\\": ("backslash", False),
            "|": ("backslash", True),
            ";": ("semicolon", False),
            ":": ("semicolon", True),
            "'": ("quote", False),
            '"': ("quote", True),
            ",": ("comma", False),
            "<": ("comma", True),
            ".": ("period", False),
            ">": ("period", True),
            "/": ("slash", False),
            "?": ("slash", True),
            "`": ("grave", False),
            "~": ("grave", True),
        }

        mapped = symbol_map.get(char)
        if mapped:
            key_name, need_shift = mapped
            if need_shift:
                with interception.hold_key("shift"):
                    interception.press(key_name)
            else:
                interception.press(key_name)
            return

        # 对于无法映射的字符，不再回退到 interception.write()，
        # 因为该函数在 WPS/Qt+Chromium 等环境下已被证实会被过滤。
        # 建议调用方使用 use_clipboard=True 输入中文及特殊字符。
        raise ValueError(
            f"字符 {char!r} 无法通过当前键盘布局直接输入，"
            f"请使用 use_clipboard=True 或通过剪贴板方式输入。"
        )

    def press(self, key: str) -> None:
        """按下单个按键."""
        if self._interception is None:
            raise RuntimeError("HardInputEngine 尚未启动，请先调用 start()")
        self._interception.press(key)

    def hotkey(self, *keys: str) -> None:
        """按下组合键."""
        if self._interception is None:
            raise RuntimeError("HardInputEngine 尚未启动，请先调用 start()")
        import interception

        if not keys:
            return
        if len(keys) == 1:
            self._interception.press(keys[0])
            return
        # 多个键：逐个 keyDown 所有键，再反向 keyUp
        # 在按键之间加入拟人化随机延迟（10~50ms），避免被应用层
        # 通过"组合键时序一致性"检测出来并丢弃。
        for k in keys[:-1]:
            interception.key_down(k)
            time.sleep(random.uniform(0.01, 0.05))
        interception.key_down(keys[-1])
        time.sleep(random.uniform(0.03, 0.08))
        interception.key_up(keys[-1])
        for k in reversed(keys[:-1]):
            interception.key_up(k)
            time.sleep(random.uniform(0.01, 0.05))

    def scroll(self, amount: int) -> None:
        """滚动鼠标滚轮."""
        if self._interception is None:
            raise RuntimeError("HardInputEngine 尚未启动，请先调用 start()")
        self._interception.scroll(amount)

    @staticmethod
    def ensure_english_input(
        detection_method: str = "auto",
        use_shift: bool = True,
        use_ctrl_space: bool = False,
        cooldown: float = 0.3,
    ) -> bool:
        """确保当前输入法处于英文输入状态."""
        return InputMethodController.ensure_english_input(
            detection_method=detection_method,
            use_shift=use_shift,
            use_ctrl_space=use_ctrl_space,
            cooldown=cooldown,
        )
