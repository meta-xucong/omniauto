"""浏览器指纹轮换工具.

提供随机的 viewport、user-agent、临时 profile 路径，降低平台对固定指纹的标记概率.
"""

import random
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# 常见 Windows 桌面分辨率（轮换时优先使用与多数显示器匹配的尺寸，避免比例失调）
_VIEWPORT_POOL: List[Dict[str, int]] = [
    {"width": 1920, "height": 1080},
    {"width": 1920, "height": 1200},
    {"width": 1680, "height": 1050},
    {"width": 1600, "height": 900},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
]

# 常见 Windows Chrome UA（与 channel='chrome' 匹配）
_UA_POOL: List[str] = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]


def pick_viewport() -> Dict[str, int]:
    """随机选取一个常见桌面分辨率."""
    return random.choice(_VIEWPORT_POOL)


def pick_user_agent() -> str:
    """随机选取一个常见 Windows Chrome UA."""
    return random.choice(_UA_POOL)


def make_temp_profile() -> str:
    """创建一个新的临时 Chrome Profile 目录并返回路径."""
    return tempfile.mkdtemp(prefix="omniauto_profile_")


class FingerprintRotator:
    """管理浏览器指纹轮换与临时 Profile 生命周期."""

    def __init__(
        self,
        user_data_dir: Optional[str] = None,
        viewport: Optional[Dict[str, int]] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        self.user_data_dir = user_data_dir
        # 默认固定使用 1920x1080 以避免画面比例失调；仅当显式传入时才轮换
        self.viewport = viewport or {"width": 1920, "height": 1080}
        self.user_agent = user_agent or pick_user_agent()
        self._is_temp_profile = False

        if not self.user_data_dir:
            self.user_data_dir = make_temp_profile()
            self._is_temp_profile = True

    def cleanup(self) -> None:
        """清理临时 Profile 目录."""
        if self._is_temp_profile and self.user_data_dir:
            try:
                shutil.rmtree(self.user_data_dir, ignore_errors=True)
            except Exception:
                pass
