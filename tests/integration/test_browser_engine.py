"""StealthBrowser 集成测试。

测试浏览器引擎的基本生命周期，访问一个公开页面并提取内容。
"""

from pathlib import Path

import pytest

from omniauto.engines.browser import StealthBrowser

ARTIFACT_DIR = Path("test_artifacts/pytest/browser")


@pytest.mark.asyncio
async def test_browser_goto_and_extract():
    browser = StealthBrowser(headless=True)
    await browser.start()
    try:
        await browser.goto("https://httpbin.org/html")
        text = await browser.extract_text("h1")
        assert "Herman Melville" in text
    finally:
        await browser.close()


@pytest.mark.asyncio
async def test_browser_screenshot():
    browser = StealthBrowser(headless=True)
    await browser.start()
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        await browser.goto("https://httpbin.org/html")
        path = await browser.screenshot(str(ARTIFACT_DIR / "test_browser_shot.png"))
        assert Path(path).exists()
    finally:
        await browser.close()
