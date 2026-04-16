"""隐形浏览器引擎.

基于 Playwright + browser-use 理念封装，提供简洁的 Pythonic API.
"""

import asyncio
import os
import random
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from ..utils.stealth import STEALTH_CONFIG
from ..utils.mouse import bezier_curve
from ..utils.auth_manager import AuthManager, get_site_key, is_login_page, is_captcha_page
from ..utils.fingerprint import FingerprintRotator


def _find_system_chrome() -> Optional[str]:
    """自动探测系统中安装的 Google Chrome 可执行文件路径."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


class StealthBrowser:
    """基于 Playwright 的隐形浏览器封装.

    支持反检测启动参数、真实 Chrome Profile、多标签页、iframe 切换.
    新增：自动优先使用系统安装的 Google Chrome（channel="chrome"），
          以及支持通过 CDP 连接用户已运行的 Chrome 实例.
    """

    def __init__(
        self,
        headless: bool = False,
        user_data_dir: Optional[str] = None,
        proxy: Optional[str] = None,
        args: Optional[List[str]] = None,
        viewport: Optional[Dict[str, int]] = None,
        use_system_chrome: bool = True,
        cdp_url: Optional[str] = None,
        auto_handle_login: bool = True,
        auth_storage_dir: str = "data/auth",
        auto_login_timeout: float = 300.0,
        rotate_fingerprint: bool = False,
    ) -> None:
        self.headless = headless
        self.proxy = proxy
        self.args = args or []
        self.use_system_chrome = use_system_chrome
        self.cdp_url = cdp_url
        self.auto_handle_login = auto_handle_login
        self.auto_login_timeout = auto_login_timeout
        self._auth_manager = AuthManager(storage_dir=auth_storage_dir)
        self._playwright: Optional[Any] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._cdp_proc: Optional[subprocess.Popen] = None

        # 指纹轮换
        if rotate_fingerprint:
            self._fp = FingerprintRotator(user_data_dir=user_data_dir, viewport=viewport)
        else:
            from ..utils.fingerprint import pick_viewport, pick_user_agent
            self._fp = None
            self.user_data_dir = user_data_dir
            self.viewport = viewport or pick_viewport()
            self.user_agent = pick_user_agent()

    @property
    def user_data_dir(self) -> Optional[str]:
        if self._fp is not None:
            return self._fp.user_data_dir
        return self._user_data_dir

    @user_data_dir.setter
    def user_data_dir(self, value: Optional[str]) -> None:
        self._user_data_dir = value

    @property
    def viewport(self) -> Dict[str, int]:
        if self._fp is not None:
            return self._fp.viewport
        return self._viewport

    @viewport.setter
    def viewport(self, value: Dict[str, int]) -> None:
        self._viewport = value

    @property
    def user_agent(self) -> str:
        if self._fp is not None:
            return self._fp.user_agent
        return self._user_agent

    @user_agent.setter
    def user_agent(self, value: str) -> None:
        self._user_agent = value

    async def start(self) -> "StealthBrowser":
        """启动浏览器实例."""
        self._playwright = await async_playwright().start()

        # 模式 A: 通过 CDP 连接已运行的 Chrome
        if self.cdp_url:
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
            self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            await self._inject_stealth_scripts()
            return self

        # 模式 B: 使用 persistent context（真实 Profile）
        # 动态 window-size 必须与 viewport 严格一致，否则页面会错位
        dynamic_args = list(STEALTH_CONFIG["args"]) + self.args
        dynamic_args = [a for a in dynamic_args if not a.startswith("--window-size")]
        dynamic_args.append(f"--window-size={self.viewport['width']},{self.viewport['height']}")
        if "--test-type" not in dynamic_args:
            dynamic_args.append("--test-type")

        launch_args: Dict[str, Any] = {
            "headless": self.headless,
            "args": dynamic_args,
            "ignore_default_args": ["--enable-automation"],
        }
        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}

        system_chrome = _find_system_chrome() if self.use_system_chrome else None
        if system_chrome:
            # Playwright 推荐以 channel="chrome" 连接系统安装的 Chrome
            launch_args["channel"] = "chrome"

        # 上下文配置：统一指纹、时区、地理位置以匹配中国用户环境
        # headful 模式下使用 viewport=None 并配合精确的 --window-size，
        # 可避免 Windows DPI 缩放导致的画面比例失真
        context_kwargs: Dict[str, Any] = {
            "viewport": None if not self.headless else self.viewport,
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "geolocation": {"latitude": 31.2304, "longitude": 121.4737},
            "permissions": ["geolocation"],
            "user_agent": self.user_agent,
        }

        if self.user_data_dir:
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                **launch_args,
                **context_kwargs,
            )
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        else:
            self._browser = await self._playwright.chromium.launch(**launch_args)
            self._context = await self._browser.new_context(**context_kwargs)
            self._page = await self._context.new_page()

        await self._inject_stealth_scripts()
        return self

    async def _inject_stealth_scripts(self) -> None:
        """注入 Stealth 脚本，覆盖检测属性（在 context 级别注入，确保新页面和 iframe 均生效）。"""
        if self._context is None:
            return
        for script in STEALTH_CONFIG.get("scripts", []):
            await self._context.add_init_script(script)

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: Optional[int] = None) -> None:
        """导航到指定 URL.

        若检测到登录页且启用了 auto_handle_login，会自动处理登录。
        注意：本方法不再执行任何滚动或鼠标预热行为，避免干扰延迟出现的滑块验证页。
        行为模拟应由调用方在确认页面正常后显式调用 simulate_human_viewing() / cooldown()。
        """


        if self._page is None:
            raise RuntimeError("浏览器未启动，请先调用 start()")

        goto_kwargs = {"wait_until": wait_until}
        if timeout is not None:
            goto_kwargs["timeout"] = timeout
        await self._page.goto(url, **goto_kwargs)

        if not self.auto_handle_login:
            return

        # 快速路径：URL 与元素均无登录特征时直接跳过
        url_lower = self._page.url.lower()
        quick_signals = [
            "login", "signin", "auth", "passport", "logon",
            "register", "dologin", "member", "jump",
        ]
        has_login_signal = any(sig in url_lower for sig in quick_signals)
        has_password_input = False
        if not has_login_signal:
            try:
                has_password_input = await self._page.eval_on_selector(
                    'input[type="password"]', "el => !!el"
                )
            except Exception:
                pass
            if not has_password_input:
                return

        # 存在登录迹象时，给页面留足时间完成重定向或渲染
        await asyncio.sleep(2)
        site_key = get_site_key(self._page.url)

        if await is_login_page(self._page) or await is_captcha_page(self._page):
            auth_file = self._auth_manager._auth_file(site_key)

            # 尝试加载已有登录态（仅针对登录页）
            if await is_login_page(self._page) and auth_file.exists():
                print(f"[StealthBrowser] 检测到登录页，尝试恢复 {site_key} 登录态...")
                await self._auth_manager.load(self._page, site_key)
                # 刷新或重新导航以应用 Cookie
                await self._page.goto(url, wait_until=wait_until)
                await asyncio.sleep(2)

                if not await is_login_page(self._page) and not await is_captcha_page(self._page):
                    print(f"[StealthBrowser] {site_key} 登录态恢复成功，继续执行")
                    return
                else:
                    print(f"[StealthBrowser] {site_key} 登录态已过期或仍需验证，需要手动处理")

            # 自动轮询等待用户手动完成登录或验证
            intervention_success = await self._auth_manager.wait_for_intervention(
                self._page, site_key, timeout=self.auto_login_timeout, poll_interval=3.0
            )
            if intervention_success:
                # 仅登录成功后保存状态；验证码过后当前页面状态即为正常
                if await is_login_page(self._page) is False:
                    await self._auth_manager.save(self._page, site_key)
            else:
                raise RuntimeError(
                    f"站点 {site_key} 手动处理超时，请确保在弹出的浏览器窗口中完成登录或验证"
                )

    async def simulate_human_viewing(self) -> None:
        """模拟真人浏览行为：多种随机滚动模式加随机停留."""
        if self._page is None:
            return
        mode = random.choice(["scroll_down_up", "double_down", "scroll_top_then_down", "no_scroll"])

        if mode == "no_scroll":
            await asyncio.sleep(random.uniform(2.0, 4.5))
        # 先停留，让页面稳定

        await asyncio.sleep(random.uniform(1.0, 2.5))

        if mode == "scroll_down_up":
            scroll_down = random.randint(150, 500)
            scroll_up = random.randint(40, 150)
            await self._page.evaluate(f"window.scrollBy(0, {scroll_down})")
            await asyncio.sleep(random.uniform(0.8, 2.0))
            await self._page.evaluate(f"window.scrollBy(0, -{scroll_up})")
            await asyncio.sleep(random.uniform(0.8, 2.0))
        elif mode == "double_down":
            await self._page.evaluate(f"window.scrollBy(0, {random.randint(100, 300)})")
            await asyncio.sleep(random.uniform(0.5, 1.2))
            await self._page.evaluate(f"window.scrollBy(0, {random.randint(80, 250)})")
            await asyncio.sleep(random.uniform(1.0, 2.5))
        elif mode == "scroll_top_then_down":
            await self._page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(random.uniform(0.5, 1.0))
            await self._page.evaluate(f"window.scrollBy(0, {random.randint(200, 600)})")
            await asyncio.sleep(random.uniform(1.0, 2.5))

    async def _mouse_preheat(self) -> None:
        """导航前随机移动鼠标到页面某处，避免每次轨迹起点都在 (0, 0)。"""
        if self._page is None:
            return
        try:
            target_x = random.uniform(150, self.viewport["width"] - 150)
            target_y = random.uniform(150, self.viewport["height"] - 150)
            current_pos = await self._page.evaluate(
                "() => { try { return {x: window.__lastMouseX || 0, y: window.__lastMouseY || 0}; } catch(e) { return {x:0,y:0}; } }"
            )
            start_x, start_y = current_pos.get("x", 0), current_pos.get("y", 0)
            points = bezier_curve((start_x, start_y), (target_x, target_y), num_points=random.randint(12, 20), spread=random.randint(80, 150))
            for px, py in points:
                await self._page.mouse.move(px, py)
                await asyncio.sleep(random.uniform(0.005, 0.015))
            await self._page.evaluate(f"() => {{ window.__lastMouseX = {target_x}; window.__lastMouseY = {target_y}; }}")
            await asyncio.sleep(random.uniform(0.3, 0.8))
        except Exception:
            pass

    async def click(self, selector: str, delay: Optional[tuple[float, float]] = None) -> None:
        """点击元素，模拟人类鼠标轨迹和随机延迟。若标准 API 因可见性失败，则降级到 DOM 操作。"""
        if self._page is None:
            raise RuntimeError("浏览器未启动")

        # 操作前随机延迟（模拟人类反应时间）
        await asyncio.sleep(random.uniform(0.5, 1.5))
        if delay:
            await asyncio.sleep(random.uniform(*delay))

        try:
            # 1. 获取目标元素中心坐标
            box = await self._page.locator(selector).bounding_box()
            if box:
                target_x = box["x"] + box["width"] / 2
                target_y = box["y"] + box["height"] / 2

                # 2. 获取当前鼠标位置（如果无法获取则默认左上角附近）
                current_pos = await self._page.evaluate("() => { try { return {x: window.__lastMouseX || 0, y: window.__lastMouseY || 0}; } catch(e) { return {x:0,y:0}; } }")
                start_x, start_y = current_pos.get("x", 0), current_pos.get("y", 0)

                # 3. 先移动到一个随机中间点（模拟人类不会完全直线移动）
                mid_x = random.uniform(100, self.viewport["width"] - 100)
                mid_y = random.uniform(100, self.viewport["height"] - 100)
                mid_points = bezier_curve((start_x, start_y), (mid_x, mid_y), num_points=15, spread=120)
                for px, py in mid_points:
                    await self._page.mouse.move(px, py)
                    await asyncio.sleep(random.uniform(0.005, 0.015))

                await asyncio.sleep(random.uniform(0.2, 0.5))

                # 4. 再从中间点沿贝塞尔曲线移动到目标元素
                end_points = bezier_curve((mid_x, mid_y), (target_x, target_y), num_points=20, spread=80)
                for px, py in end_points:
                    await self._page.mouse.move(px, py)
                    await asyncio.sleep(random.uniform(0.005, 0.015))

                # 记录最后鼠标位置
                await self._page.evaluate(f"() => {{ window.__lastMouseX = {target_x}; window.__lastMouseY = {target_y}; }}")

                # 5. 在目标上方悬停一小会儿再点击
                await asyncio.sleep(random.uniform(0.2, 0.6))
                await self._page.mouse.down()
                await asyncio.sleep(random.uniform(0.05, 0.15))
                await self._page.mouse.up()
            else:
                # 元素不可见时回退到标准 click
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
        interval: tuple[float, float] = (0.05, 0.25),
        clear: bool = True,
    ) -> None:
        """在元素中输入文本，模拟人类打字节奏。若标准 API 因可见性失败，则降级到 DOM 操作。"""
        if self._page is None:
            raise RuntimeError("浏览器未启动")

        # 聚焦前的自然停顿
        await asyncio.sleep(random.uniform(0.3, 0.8))

        try:
            if clear:
                await self._page.fill(selector, "")
                await asyncio.sleep(random.uniform(0.2, 0.5))

            # 使用 Playwright 的 type，并传递随机延迟（每字 50~250ms）
            delay_ms = random.uniform(interval[0] * 1000, interval[1] * 1000)
            await self._page.type(selector, text, delay=delay_ms)

            # 输入完成后的随机停顿（模拟用户检查输入内容）
            await asyncio.sleep(random.uniform(0.5, 1.2))
        except Exception:
            safe_text = text.replace('\\', '\\\\').replace('"', '\\"').replace("\n", '\\n')
            await self._page.evaluate(f'''
                const el = document.querySelector("{selector.replace('"', '\\"')}");
                if (el) {{ el.value = "{safe_text}"; el.dispatchEvent(new Event('input', {{ bubbles: true }})); }}
            ''')

    async def cooldown(self, min_sec: float = 1.5, max_sec: float = 4.0) -> None:
        """通用冷却：模拟人类在操作后的阅读和思考时间."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def throttle_request(self, min_sec: float = 3.0, max_sec: float = 8.0) -> None:
        """显式请求限速：用于批量抓取、翻页等连续请求场景，降低被风控概率."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

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
            artifact_dir = Path("test_artifacts/screenshots/browser")
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = str(artifact_dir / f"screenshot_{random.randint(1000,9999)}.png")
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

    async def try_solve_slider(self) -> bool:
        """实验性：尝试自动解决简单的滑块验证码（如 1688 NC 滑块）。

        仅尝试一次，失败后应由调用方转人工处理。

        Returns:
            True 表示疑似成功，False 表示失败或未检测到滑块。
        """



        if self._page is None:
            return False
        try:
            # 检测滑块轨道和滑块按钮
            slider = await self._page.query_selector('.nc_wrapper .nc_iconfont.btn_slide, #nc_1_n1z, .btn_slide')
            track = await self._page.query_selector('.nc_wrapper .nc_scale, .slide-box, .nc-container')
            if not slider or not track:
                return False
            # 移动到滑块上
            slider_box = await slider.bounding_box()
            track_box = await track.bounding_box()
            if not slider_box or not track_box:
                return False
            start_x = slider_box["x"] + slider_box["width"] / 2
            start_y = slider_box["y"] + slider_box["height"] / 2
            end_x = track_box["x"] + track_box["width"] - slider_box["width"] / 2
            end_y = start_y + random.uniform(-3, 3)
            # 移动到滑块上
            for px, py in bezier_curve((start_x - 50, start_y + random.uniform(-20, 20)), (start_x, start_y), num_points=12, spread=40):
                await self._page.mouse.move(px, py)
                await asyncio.sleep(random.uniform(0.008, 0.018))
            await asyncio.sleep(random.uniform(0.2, 0.5))
            await self._page.mouse.down()
            # 两段贝塞尔曲线拖动：先快后慢，并带小幅抖动
            mid_x = (start_x + end_x) / 2 + random.uniform(-20, 20)
            mid_y = start_y + random.uniform(-5, 5)
            for px, py in bezier_curve((start_x, start_y), (mid_x, mid_y), num_points=25, spread=random.randint(30, 80)):
                await self._page.mouse.move(px, py)
                await asyncio.sleep(random.uniform(0.003, 0.012))
            await asyncio.sleep(random.uniform(0.05, 0.2))
            for px, py in bezier_curve((mid_x, mid_y), (end_x, end_y), num_points=20, spread=random.randint(20, 60)):
                await self._page.mouse.move(px, py)
                await asyncio.sleep(random.uniform(0.005, 0.015))
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await self._page.mouse.up()
            await asyncio.sleep(1.5)
            # 简单校验：滑块是否还在
            still = await self._page.query_selector('.nc_wrapper .nc_iconfont.btn_slide, #nc_1_n1z')
            return still is None
        except Exception:
            return False

    async def close(self) -> None:
        """关闭浏览器."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._cdp_proc:
            self._cdp_proc.terminate()
            try:
                self._cdp_proc.wait(timeout=5)
            except Exception:
                self._cdp_proc.kill()
        if self._playwright:
            await self._playwright.stop()
        if self._fp is not None:
            self._fp.cleanup()
