"""闅愬舰娴忚鍣ㄥ紩鎿?

鍩轰簬 Playwright + browser-use 鐞嗗康灏佽锛屾彁渚涚畝娲佺殑 Pythonic API.
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

from ..recovery import (
    BrowserRecoveryFallback,
    BrowserRecoveryManager,
    BrowserRecoveryRegistry,
    ChainedRecoveryFallback,
    ConstrainedAIRecoveryFallback,
    HeuristicRecoveryFallback,
    RecoveryAttemptResult,
    RecoveryPolicy,
    RecoveryRule,
)
from ..utils.stealth import STEALTH_CONFIG
from ..utils.mouse import bezier_curve
from ..utils.auth_manager import AuthManager, get_site_key, is_login_page, is_captcha_page
from ..utils.fingerprint import FingerprintRotator


def _find_system_chrome() -> Optional[str]:
    """鑷姩鎺㈡祴绯荤粺涓畨瑁呯殑 Google Chrome 鍙墽琛屾枃浠惰矾寰?"""
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
    """鍩轰簬 Playwright 鐨勯殣褰㈡祻瑙堝櫒灏佽.

    鏀寔鍙嶆娴嬪惎鍔ㄥ弬鏁般€佺湡瀹?Chrome Profile銆佸鏍囩椤点€乮frame 鍒囨崲.
    鏂板锛氳嚜鍔ㄤ紭鍏堜娇鐢ㄧ郴缁熷畨瑁呯殑 Google Chrome锛坈hannel="chrome"锛夛紝
          浠ュ強鏀寔閫氳繃 CDP 杩炴帴鐢ㄦ埛宸茶繍琛岀殑 Chrome 瀹炰緥.
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
        auth_storage_dir: str = "runtime/data/auth",
        auto_login_timeout: float = 300.0,
        rotate_fingerprint: bool = False,
        auto_recover_interruptions: bool = True,
        recovery_registry: Optional[BrowserRecoveryRegistry] = None,
        recovery_policy: Optional[RecoveryPolicy] = None,
        recovery_fallback: Optional[BrowserRecoveryFallback] = None,
        ai_recovery_decider: Optional[Any] = None,
        recovery_artifact_dir: Optional[str] = None,
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
        self.auto_recover_interruptions = auto_recover_interruptions
        self._recovery_artifact_dir = recovery_artifact_dir
        fallback_chain: BrowserRecoveryFallback
        if ai_recovery_decider is not None:
            fallback_chain = ChainedRecoveryFallback(
                [
                    recovery_fallback or HeuristicRecoveryFallback(),
                    ConstrainedAIRecoveryFallback(ai_recovery_decider),
                ]
            )
        else:
            fallback_chain = recovery_fallback or HeuristicRecoveryFallback()
        self._recovery_manager = BrowserRecoveryManager(
            page_getter=lambda: self._page,
            registry=recovery_registry,
            policy=recovery_policy,
            fallback=fallback_chain,
            artifact_dir_getter=lambda: self._recovery_artifact_dir,
        )

        # 鎸囩汗杞崲
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
        """鍚姩娴忚鍣ㄥ疄渚?"""
        self._playwright = await async_playwright().start()

        # 妯″紡 A: 閫氳繃 CDP 杩炴帴宸茶繍琛岀殑 Chrome
        if self.cdp_url:
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
            contexts = list(self._browser.contexts)
            preferred_page = None
            for context in contexts:
                for page in context.pages:
                    if not page.url.startswith("chrome://"):
                        preferred_page = page
                        break
                if preferred_page is not None:
                    break
            if preferred_page is not None:
                self._context = preferred_page.context
                self._page = preferred_page
            else:
                self._context = contexts[0] if contexts else await self._browser.new_context()
                self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            await self._inject_stealth_scripts()
            return self

        # Mode B: use a persistent browser profile.
        # Keep window size aligned with viewport to avoid coordinate drift.
        dynamic_args = list(STEALTH_CONFIG["args"]) + self.args
        dynamic_args = [a for a in dynamic_args if not a.startswith("--window-size")]
        dynamic_args.append(f"--window-size={self.viewport['width']},{self.viewport['height']}")
        if "--test-type" not in dynamic_args:
            dynamic_args.append("--test-type")
        if "--disable-session-crashed-bubble" not in dynamic_args:
            dynamic_args.append("--disable-session-crashed-bubble")

        launch_args: Dict[str, Any] = {
            "headless": self.headless,
            "args": dynamic_args,
            "ignore_default_args": ["--enable-automation"],
        }
        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}

        system_chrome = _find_system_chrome() if self.use_system_chrome else None
        if system_chrome:
            # Playwright 鎺ㄨ崘浠?channel="chrome" 杩炴帴绯荤粺瀹夎鐨?Chrome
            launch_args["channel"] = "chrome"

        # Context configuration aligned with a typical China-based browser profile.
        # In headful mode we prefer viewport=None and rely on the explicit window-size arg.
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

    def register_recovery_rule(self, rule: RecoveryRule) -> "StealthBrowser":
        self._recovery_manager.registry.register(rule)
        return self

    def set_recovery_artifact_dir(self, path: Optional[str]) -> "StealthBrowser":
        self._recovery_artifact_dir = path
        return self

    async def recover_from_interruptions(
        self,
        trigger: str = "manual",
        error: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> RecoveryAttemptResult:
        if not self.auto_recover_interruptions:
            return RecoveryAttemptResult(
                handled=False,
                trigger=trigger,
                error="recovery_disabled",
            )
        return await self._recovery_manager.recover(trigger=trigger, error=error, step_id=step_id)

    async def _inject_stealth_scripts(self) -> None:
        """Inject stealth scripts into the browser context."""
        if self._context is None:
            return
        for script in STEALTH_CONFIG.get("scripts", []):
            await self._context.add_init_script(script)

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: Optional[int] = None) -> None:
        """Navigate to a URL and optionally wait for login or verification handling."""

        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩锛岃鍏堣皟鐢?start()")

        await self.recover_from_interruptions("before_goto")

        goto_kwargs = {"wait_until": wait_until}
        if timeout is not None:
            goto_kwargs["timeout"] = timeout
        await self._page.goto(url, **goto_kwargs)

        if not self.auto_handle_login:
            return

        # 蹇€熻矾寰勶細URL 涓庡厓绱犲潎鏃犵櫥褰曠壒寰佹椂鐩存帴璺宠繃
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

        # If the URL smells like login, give the page a moment to settle before checking auth state.
        await asyncio.sleep(2)
        site_key = get_site_key(self._page.url)

        if await is_login_page(self._page) or await is_captcha_page(self._page):
            auth_file = self._auth_manager._auth_file(site_key)

            if await is_login_page(self._page) and auth_file.exists():
                await self._auth_manager.load(self._page, site_key)
                # 鍒锋柊鎴栭噸鏂板鑸互搴旂敤 Cookie
                await self._page.goto(url, wait_until=wait_until)
                await asyncio.sleep(2)

                if not await is_login_page(self._page) and not await is_captcha_page(self._page):
                    print(f"[StealthBrowser] Restored login state for {site_key}.")
                    return
                else:
                    print(f"[StealthBrowser] Stored login state for {site_key} is no longer valid.")

            intervention_success = await self._auth_manager.wait_for_intervention(
                self._page, site_key, timeout=self.auto_login_timeout, poll_interval=3.0
            )
            if intervention_success:
                if await is_login_page(self._page) is False:
                    await self._auth_manager.save(self._page, site_key)
            else:
                raise RuntimeError(
                    f"Manual login or verification timed out for site {site_key}."
                )
        await self.recover_from_interruptions("after_goto")

    async def simulate_human_viewing(self) -> None:
        """Simulate light human-like reading and scrolling."""
        if self._page is None:
            return
        mode = random.choice(["scroll_down_up", "double_down", "scroll_top_then_down", "no_scroll"])

        if mode == "no_scroll":
            await asyncio.sleep(random.uniform(2.0, 4.5))
        # 鍏堝仠鐣欙紝璁╅〉闈㈢ǔ瀹?
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
        """Move the pointer before navigation to avoid a fixed starting point."""
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

    async def _click_impl(self, selector: str, delay: Optional[tuple[float, float]] = None) -> None:
        # 鎿嶄綔鍓嶉殢鏈哄欢杩燂紙妯℃嫙浜虹被鍙嶅簲鏃堕棿锛?        await asyncio.sleep(random.uniform(0.5, 1.5))
        if delay:
            await asyncio.sleep(random.uniform(*delay))

        # 1. 鑾峰彇鐩爣鍏冪礌涓績鍧愭爣
        box = await self._page.locator(selector).bounding_box()
        if box:
            target_x = box["x"] + box["width"] / 2
            target_y = box["y"] + box["height"] / 2

            # 2. 鑾峰彇褰撳墠榧犳爣浣嶇疆锛堝鏋滄棤娉曡幏鍙栧垯榛樿宸︿笂瑙掗檮杩戯級
            current_pos = await self._page.evaluate("() => { try { return {x: window.__lastMouseX || 0, y: window.__lastMouseY || 0}; } catch(e) { return {x:0,y:0}; } }")
            start_x, start_y = current_pos.get("x", 0), current_pos.get("y", 0)

            # 3. 鍏堢Щ鍔ㄥ埌涓€涓殢鏈轰腑闂寸偣锛堟ā鎷熶汉绫讳笉浼氬畬鍏ㄧ洿绾跨Щ鍔級
            mid_x = random.uniform(100, self.viewport["width"] - 100)
            mid_y = random.uniform(100, self.viewport["height"] - 100)
            mid_points = bezier_curve((start_x, start_y), (mid_x, mid_y), num_points=15, spread=120)
            for px, py in mid_points:
                await self._page.mouse.move(px, py)
                await asyncio.sleep(random.uniform(0.005, 0.015))

            await asyncio.sleep(random.uniform(0.2, 0.5))

            # 4. 鍐嶄粠涓棿鐐规部璐濆灏旀洸绾跨Щ鍔ㄥ埌鐩爣鍏冪礌
            end_points = bezier_curve((mid_x, mid_y), (target_x, target_y), num_points=20, spread=80)
            for px, py in end_points:
                await self._page.mouse.move(px, py)
                await asyncio.sleep(random.uniform(0.005, 0.015))

            # 璁板綍鏈€鍚庨紶鏍囦綅缃?            await self._page.evaluate(f"() => {{ window.__lastMouseX = {target_x}; window.__lastMouseY = {target_y}; }}")

            # 5. 鍦ㄧ洰鏍囦笂鏂规偓鍋滀竴灏忎細鍎垮啀鐐瑰嚮
            await asyncio.sleep(random.uniform(0.2, 0.6))
            await self._page.mouse.down()
            await asyncio.sleep(random.uniform(0.05, 0.15))
            await self._page.mouse.up()
        else:
            # 鍏冪礌涓嶅彲瑙佹椂鍥為€€鍒版爣鍑?click
            await self._page.click(selector)

    async def click(self, selector: str, delay: Optional[tuple[float, float]] = None) -> None:
        """Click an element with a human-like fallback path."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")

        await self.recover_from_interruptions("before_click")

        try:
            await self._click_impl(selector, delay)
        except Exception as exc:
            recovery = await self.recover_from_interruptions("error_click", error=str(exc))
            if recovery.handled:
                try:
                    await self._click_impl(selector, delay)
                    await self.recover_from_interruptions("after_click")
                    return
                except Exception:
                    pass
            await self._page.evaluate(f'''
                const el = document.querySelector("{selector.replace('"', '\\"')}");
                if (el) el.click();
            ''')
        await self.recover_from_interruptions("after_click")

    async def _type_text_impl(
        self,
        selector: str,
        text: str,
        interval: tuple[float, float] = (0.05, 0.25),
        clear: bool = True,
    ) -> None:
        # 鑱氱劍鍓嶇殑鑷劧鍋滈】
        await asyncio.sleep(random.uniform(0.3, 0.8))

        if clear:
            await self._page.fill(selector, "")
            await asyncio.sleep(random.uniform(0.2, 0.5))

        # 浣跨敤 Playwright 鐨?type锛屽苟浼犻€掗殢鏈哄欢杩燂紙姣忓瓧 50~250ms锛?        delay_ms = random.uniform(interval[0] * 1000, interval[1] * 1000)
        await self._page.type(selector, text, delay=delay_ms)

        # 杈撳叆瀹屾垚鍚庣殑闅忔満鍋滈】锛堟ā鎷熺敤鎴锋鏌ヨ緭鍏ュ唴瀹癸級
        await asyncio.sleep(random.uniform(0.5, 1.2))

    async def type_text(
        self,
        selector: str,
        text: str,
        interval: tuple[float, float] = (0.05, 0.25),
        clear: bool = True,
    ) -> None:
        """Type text into an element with recovery-aware fallbacks."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")

        await self.recover_from_interruptions("before_type_text")

        try:
            await self._type_text_impl(selector, text, interval=interval, clear=clear)
        except Exception as exc:
            recovery = await self.recover_from_interruptions("error_type_text", error=str(exc))
            if recovery.handled:
                try:
                    await self._type_text_impl(selector, text, interval=interval, clear=clear)
                    await self.recover_from_interruptions("after_type_text")
                    return
                except Exception:
                    pass
            safe_text = text.replace('\\', '\\\\').replace('"', '\\"').replace("\n", '\\n')
            await self._page.evaluate(f'''
                const el = document.querySelector("{selector.replace('"', '\\"')}");
                if (el) {{ el.value = "{safe_text}"; el.dispatchEvent(new Event('input', {{ bubbles: true }})); }}
            ''')
        await self.recover_from_interruptions("after_type_text")

    async def cooldown(self, min_sec: float = 1.5, max_sec: float = 4.0) -> None:
        """Sleep for a human-like cooldown window."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def throttle_request(self, min_sec: float = 3.0, max_sec: float = 8.0) -> None:
        """Throttle requests between high-frequency browser actions."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def extract_text(self, selector: str) -> str:
        """Extract inner text for a selector."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        await self.recover_from_interruptions("before_extract_text")
        element = await self._page.query_selector(selector)
        if element is None:
            return ""
        return await element.inner_text() or ""

    async def extract_attribute(self, selector: str, attribute: str) -> str:
        """Extract an attribute value for a selector."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        await self.recover_from_interruptions("before_extract_attribute")
        return await self._page.get_attribute(selector, attribute) or ""

    async def screenshot(self, path: Optional[str] = None) -> str:
        """Capture a screenshot and return its path."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        if path is None:
            artifact_dir = Path("runtime/test_artifacts/screenshots/browser")
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = str(artifact_dir / f"screenshot_{random.randint(1000,9999)}.png")
        await self._page.screenshot(path=path, full_page=True)
        return path

    async def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript in the page context."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        return await self._page.evaluate(expression)

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        """Wait for a selector to appear."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        await self.recover_from_interruptions("before_wait_for_selector")
        try:
            await self._page.wait_for_selector(selector, timeout=timeout)
        except Exception as exc:
            recovery = await self.recover_from_interruptions("error_wait_for_selector", error=str(exc))
            if recovery.handled:
                await self._page.wait_for_selector(selector, timeout=timeout)
            else:
                raise

    async def scroll_to_bottom(self) -> None:
        """Scroll to the bottom of the page."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    @property
    def page(self) -> Optional[Page]:
        """Return the active Playwright page object."""
        return self._page

    async def try_solve_slider(self) -> bool:
        return False

    async def close(self) -> None:
        """Close the browser and related resources."""
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

