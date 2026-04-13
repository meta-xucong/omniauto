"""隐形浏览器引擎.

基于 Playwright + browser-use 理念封装，提供简洁的 Pythonic API.
"""

import asyncio
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ..utils.stealth import STEALTH_CONFIG
from ..utils.mouse import human_like_move


class StealthBrowser:
    """基于 Playwright 的隐形浏览器封装.

    支持反检测启动参数、真实 Chrome Profile、多标签页、iframe 切换.
    """

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        proxy: Optional[str] = None,
        args: Optional[List[str]] = None,
        viewport: Optional[Dict[str, int]] = None,
    ) -> None:
        self.headless = headless
        self.user_data_dir = user_data_dir
        self.proxy = proxy
        self.args = args or []
        self.viewport = viewport or {"width": 1920, "height": 1080}
        self._playwright: Optional[Any] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def start(self) -> "StealthBrowser":
        """启动浏览器实例."""
        self._playwright = await async_playwright().start()
        launch_args = {
            "headless": self.headless,
            "args": STEALTH_CONFIG["args"] + self.args,
        }
        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}

        if self.user_data_dir:
            # 使用 persistent context 连接真实 Profile
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                **launch_args,
                viewport=self.viewport,
            )
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        else:
            self._browser = await self._playwright.chromium.launch(**launch_args)
            self._context = await self._browser.new_context(viewport=self.viewport)
            self._page = await self._context.new_page()

        # 注入反检测脚本
        await self._inject_stealth_scripts()
        return self

    async def _inject_stealth_scripts(self) -> None:
        """注入 Stealth 脚本覆盖检测属性."""
        if self._page is None:
            return
        for script in STEALTH_CONFIG.get("scripts", []):
            await self._page.add_init_script(script)

    async def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        """导航到指定 URL."""
        if self._page is None:
            raise RuntimeError("浏览器未启动，请先调用 start()")
        await self._page.goto(url, wait_until=wait_until)

    async def click(self, selector: str, delay: Optional[tuple[float, float]] = None) -> None:
        """点击元素，支持随机延迟。若标准 API 因可见性失败，降级到 DOM 操作."""
        if self._page is None:
            raise RuntimeError("浏览器未启动")
        if delay:
            await asyncio.sleep(random.uniform(*delay))
        try:
            await self._page.click(selector)
        except Exception:
            await self._page.evaluate(f'''
                const el = document.querySelector("{selector.replace('"', '\\"')}");
                if (el) el.click();
            ''')

    async def type_text(
        self,
        selector: str,
        text: str,
        interval: tuple[float, float] = (0.05, 0.15),
        clear: bool = True,
    ) -> None:
        """在元素中输入文本，模拟人类打字节奏。若标准 API 因可见性失败，降级到 DOM 操作."""
        if self._page is None:
            raise RuntimeError("浏览器未启动")
        try:
            if clear:
                await self._page.fill(selector, "")
            avg_delay = (interval[0] + interval[1]) * 1000 / 2
            await self._page.type(selector, text, delay=avg_delay)
        except Exception:
            safe_text = text.replace('\\', '\\\\').replace('"', '\\"').replace("\n", '\\n')
            await self._page.evaluate(f'''
                const el = document.querySelector("{selector.replace('"', '\\"')}");
                if (el) {{ el.value = "{safe_text}"; el.dispatchEvent(new Event('input', {{ bubbles: true }})); }}
            ''')

    async def extract_text(self, selector: str) -> str:
        """提取元素的文本内容."""
        if self._page is None:
            raise RuntimeError("浏览器未启动")
        element = await self._page.query_selector(selector)
        if element is None:
            return ""
        return await element.inner_text() or ""

    async def extract_attribute(self, selector: str, attribute: str) -> str:
        """提取元素的指定属性."""
        if self._page is None:
            raise RuntimeError("浏览器未启动")
        return await self._page.get_attribute(selector, attribute) or ""

    async def screenshot(self, path: Optional[str] = None) -> str:
        """截图并保存，返回文件路径."""
        if self._page is None:
            raise RuntimeError("浏览器未启动")
        if path is None:
            path = f"screenshot_{random.randint(1000,9999)}.png"
        await self._page.screenshot(path=path, full_page=True)
        return path

    async def evaluate(self, expression: str) -> Any:
        """在页面上下文中执行 JavaScript."""
        if self._page is None:
            raise RuntimeError("浏览器未启动")
        return await self._page.evaluate(expression)

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        """等待元素出现."""
        if self._page is None:
            raise RuntimeError("浏览器未启动")
        await self._page.wait_for_selector(selector, timeout=timeout)

    async def scroll_to_bottom(self) -> None:
        """滚动到页面底部."""
        if self._page is None:
            raise RuntimeError("浏览器未启动")
        await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    @property
    def page(self) -> Optional[Page]:
        """获取当前 Page 对象（高级用法）."""
        return self._page

    async def close(self) -> None:
        """关闭浏览器."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
