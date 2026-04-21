"""VisualEngine 集成测试。

在 Windows 环境下测试视觉引擎的基础能力。
"""

from pathlib import Path
import sys

import pytest

from omniauto.engines.visual import VisualEngine

ARTIFACT_DIR = Path("runtime/test_artifacts/pytest/visual")


@pytest.mark.skipif(sys.platform != "win32", reason="pyauto-desktop 主要支持 Windows")
def test_visual_screenshot():
    engine = VisualEngine().start()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = engine.screenshot(str(ARTIFACT_DIR / "test_visual_shot.png"))
    assert Path(path).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="pyauto-desktop 主要支持 Windows")
def test_visual_locate_missing_image():
    engine = VisualEngine().start()
    result = engine.locate_center(str(ARTIFACT_DIR / "nonexistent_image.png"))
    assert result is None
