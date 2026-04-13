"""StealthBrowser 集成测试.

测试浏览器引擎的基本生命周期，访问一个本地页面并提取内容.
"""

import pytest

from omniauto.engines.browser import StealthBrowser


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
        await browser.goto("https://httpbin.org/html")
        path = await browser.screenshot("/tmp/test_browser_shot.png")
        from pathlib import Path
        assert Path(path).exists()
    finally:
        await browser.close()
