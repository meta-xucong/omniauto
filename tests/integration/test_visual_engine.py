"""VisualEngine 集成测试.

在 Windows 环境下测试视觉引擎的基础能力（截图、坐标计算）.
"""

import pytest
import sys

from omniauto.engines.visual import VisualEngine


@pytest.mark.skipif(sys.platform != "win32", reason="pyauto-desktop 主要支持 Windows")
def test_visual_screenshot():
    engine = VisualEngine().start()
    path = engine.screenshot("/tmp/test_visual_shot.png")
    from pathlib import Path
    assert Path(path).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="pyauto-desktop 主要支持 Windows")
def test_visual_locate_missing_image():
    engine = VisualEngine().start()
    result = engine.locate_center("/tmp/nonexistent_image.png")
    assert result is None
