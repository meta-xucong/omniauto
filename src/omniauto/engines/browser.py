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
            self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            await self._inject_stealth_scripts()
            return self

        # 妯″紡 B: 浣跨敤 persistent context锛堢湡瀹?Profile锛?        # 鍔ㄦ€?window-size 蹇呴』涓?viewport 涓ユ牸涓€鑷达紝鍚﹀垯椤甸潰浼氶敊浣?        dynamic_args = list(STEALTH_CONFIG["args"]) + self.args
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
            # Playwright 鎺ㄨ崘鐢?channel='chrome' 杩炴帴绯荤粺瀹夎鐨?Chrome
            launch_args["channel"] = "chrome"

        # 涓婁笅鏂囬厤缃細缁熶竴鎸囩汗銆佹椂鍖恒€佸湴鐞嗕綅缃互鍖归厤涓浗鐢ㄦ埛鐜
        # headful 妯″紡涓?viewport=None 閰嶅悎绮剧‘鐨?--window-size锛屽彲閬垮厤 Windows DPI 缂╂斁瀵艰嚧鐨勭敾闈㈡瘮渚嬪け璋?        context_kwargs: Dict[str, Any] = {
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
        """娉ㄥ叆 Stealth 鑴氭湰瑕嗙洊妫€娴嬪睘鎬э紙鍦?context 绾у埆娉ㄥ叆锛岀‘淇濇柊椤甸潰/iframe 鍧囩敓鏁堬級."""
        if self._context is None:
            return
        for script in STEALTH_CONFIG.get("scripts", []):
            await self._context.add_init_script(script)

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: Optional[int] = None) -> None:
        """瀵艰埅鍒版寚瀹?URL. 鑻ユ娴嬪埌鐧诲綍椤典笖寮€鍚簡 auto_handle_login, 浼氳嚜鍔ㄥ鐞嗙櫥褰曟€?

        娉ㄦ剰锛氭湰鏂规硶涓嶅啀鎵ц浠讳綍婊氬姩鎴栭紶鏍囬鐑涓猴紝閬垮厤骞叉壈寤惰繜鍑虹幇鐨勬粦鍧楅獙璇侀〉銆?        琛屼负妯℃嫙搴旂敱璋冪敤鏂瑰湪纭椤甸潰姝ｅ父鍚庢樉寮忚皟鐢?simulate_human_viewing() / cooldown()銆?        """
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩锛岃鍏堣皟鐢?start()")

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

        # 瀛樺湪鐧诲綍杩硅薄鏃讹紝缁欓〉闈㈢暀瓒虫椂闂村畬鎴愰噸瀹氬悜/娓叉煋
        await asyncio.sleep(2)
        site_key = get_site_key(self._page.url)

        if await is_login_page(self._page) or await is_captcha_page(self._page):
            auth_file = self._auth_manager._auth_file(site_key)

            # 灏濊瘯鍔犺浇宸叉湁鐧诲綍鎬侊紙浠呴拡瀵圭櫥褰曢〉锛?            if await is_login_page(self._page) and auth_file.exists():
                print(f"[StealthBrowser] 妫€娴嬪埌鐧诲綍椤碉紝灏濊瘯鎭㈠ {site_key} 鐧诲綍鎬?..")
                await self._auth_manager.load(self._page, site_key)
                # 鍒锋柊鎴栭噸鏂板鑸互搴旂敤 Cookie
                await self._page.goto(url, wait_until=wait_until)
                await asyncio.sleep(2)

                if not await is_login_page(self._page) and not await is_captcha_page(self._page):
                    print(f"[StealthBrowser] {site_key} 鐧诲綍鎬佹仮澶嶆垚鍔燂紝缁х画鎵ц銆?)
                    return
                else:
                    print(f"[StealthBrowser] {site_key} 鐧诲綍鎬佸凡杩囨湡鎴栦粛闇€楠岃瘉锛岄渶瑕佹墜鍔ㄥ鐞嗐€?)

            # 鑷姩杞绛夊緟鐢ㄦ埛鎵嬪姩瀹屾垚鐧诲綍鎴栭獙璇?            intervention_success = await self._auth_manager.wait_for_intervention(
                self._page, site_key, timeout=self.auto_login_timeout, poll_interval=3.0
            )
            if intervention_success:
                # 浠呯櫥褰曟垚鍔熷悗淇濆瓨鐘舵€侊紱楠岃瘉鐮侀€氳繃鍚庡綋鍓嶉〉闈㈢姸鎬佸嵆涓烘甯?                if await is_login_page(self._page) is False:
                    await self._auth_manager.save(self._page, site_key)
            else:
                raise RuntimeError(
                    f"绔欑偣 {site_key} 鎵嬪姩澶勭悊瓒呮椂锛岃纭繚鍦ㄥ脊鍑虹殑娴忚鍣ㄧ獥鍙ｄ腑瀹屾垚鐧诲綍鎴栭獙璇併€?
                )

    async def simulate_human_viewing(self) -> None:
        """妯℃嫙鐪熶汉娴忚琛屼负锛氬绉嶉殢鏈烘粴鍔ㄦā寮?+ 闅忔満鍋滅暀."""
        if self._page is None:
            return
        mode = random.choice(["scroll_down_up", "double_down", "scroll_top_then_down", "no_scroll"])

        if mode == "no_scroll":
            await asyncio.sleep(random.uniform(2.0, 4.5))
            return

        # 鍏堝仠鐣欒椤甸潰绋冲畾
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
        """瀵艰埅鍓嶉殢鏈虹Щ鍔ㄩ紶鏍囧埌椤甸潰鏌愬锛岄伩鍏嶆瘡娆¤建杩硅捣鐐归兘鏄?(0,0)."""
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
        """鐐瑰嚮鍏冪礌锛屾ā鎷熶汉绫婚紶鏍囩Щ鍔ㄨ建杩瑰拰闅忔満寤惰繜銆傝嫢鏍囧噯 API 鍥犲彲瑙佹€уけ璐ワ紝闄嶇骇鍒?DOM 鎿嶄綔."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")

        # 鎿嶄綔鍓嶉殢鏈哄欢杩燂紙妯℃嫙浜虹被鍙嶅簲鏃堕棿锛?        await asyncio.sleep(random.uniform(0.5, 1.5))
        if delay:
            await asyncio.sleep(random.uniform(*delay))

        try:
            # 1. 鑾峰彇鐩爣鍏冪礌涓績鍧愭爣
            box = await self._page.locator(selector).bounding_box()
            if box:
                target_x = box["x"] + box["width"] / 2
                target_y = box["y"] + box["height"] / 2

                # 2. 鑾峰彇褰撳墠榧犳爣浣嶇疆锛堝鏋滄棤娉曡幏鍙栧垯榛樿宸︿笂瑙掗檮杩戯級
                current_pos = await self._page.evaluate("() => { try { return {x: window.__lastMouseX || 0, y: window.__lastMouseY || 0}; } catch(e) { return {x:0,y:0}; } }")
                start_x, start_y = current_pos.get("x", 0), current_pos.get("y", 0)

                # 3. 鍏堢Щ鍔ㄥ埌涓€涓殢鏈轰腑闂寸偣锛堟ā鎷熶汉绫讳笉浼氱洿鐩村湴绉诲姩锛?                mid_x = random.uniform(100, self.viewport["width"] - 100)
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

                # 璁板綍鏈€鍚庨紶鏍囦綅缃?                await self._page.evaluate(f"() => {{ window.__lastMouseX = {target_x}; window.__lastMouseY = {target_y}; }}")

                # 5. 鍦ㄧ洰鏍囦笂鏂规偓鍋滀竴灏忎細鍎垮啀鐐瑰嚮
                await asyncio.sleep(random.uniform(0.2, 0.6))
                await self._page.mouse.down()
                await asyncio.sleep(random.uniform(0.05, 0.15))
                await self._page.mouse.up()
            else:
                # 鍏冪礌涓嶅彲瑙佹椂鍥為€€鍒版爣鍑?click
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
        """鍦ㄥ厓绱犱腑杈撳叆鏂囨湰锛屾ā鎷熶汉绫绘墦瀛楄妭濂忋€傝嫢鏍囧噯 API 鍥犲彲瑙佹€уけ璐ワ紝闄嶇骇鍒?DOM 鎿嶄綔."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")

        # 鑱氱劍鍓嶇殑鑷劧鍋滈】
        await asyncio.sleep(random.uniform(0.3, 0.8))

        try:
            if clear:
                await self._page.fill(selector, "")
                await asyncio.sleep(random.uniform(0.2, 0.5))

            # 浣跨敤 Playwright 鐨?type 浣嗕紶閫掗殢鏈哄欢杩燂紙姣忓瓧绗?50~250ms锛?            delay_ms = random.uniform(interval[0] * 1000, interval[1] * 1000)
            await self._page.type(selector, text, delay=delay_ms)

            # 杈撳叆瀹屾垚鍚庣殑闅忔満鍋滈】锛堟ā鎷熺敤鎴锋鏌ヨ緭鍏ュ唴瀹癸級
            await asyncio.sleep(random.uniform(0.5, 1.2))
        except Exception:
            safe_text = text.replace('\\', '\\\\').replace('"', '\\"').replace("\n", '\\n')
            await self._page.evaluate(f'''
                const el = document.querySelector("{selector.replace('"', '\\"')}");
                if (el) {{ el.value = "{safe_text}"; el.dispatchEvent(new Event('input', {{ bubbles: true }})); }}
            ''')

    async def cooldown(self, min_sec: float = 1.5, max_sec: float = 4.0) -> None:
        """閫氱敤鍐峰嵈锛氭ā鎷熶汉绫诲湪鎿嶄綔鍚庣殑闃呰/鎬濊€冩椂闂?"""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def throttle_request(self, min_sec: float = 3.0, max_sec: float = 8.0) -> None:
        """鏄惧紡璇锋眰闄愰€燂細鐢ㄤ簬鎵归噺鎶撳彇銆佺炕椤电瓑杩炵画璇锋眰鍦烘櫙锛岄檷浣庤椋庢帶姒傜巼."""
        await asyncio.sleep(random.uniform(min_sec, max_sec))

    async def extract_text(self, selector: str) -> str:
        """鎻愬彇鍏冪礌鐨勬枃鏈唴瀹?"""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        element = await self._page.query_selector(selector)
        if element is None:
            return ""
        return await element.inner_text() or ""

    async def extract_attribute(self, selector: str, attribute: str) -> str:
        """鎻愬彇鍏冪礌鐨勬寚瀹氬睘鎬?"""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        return await self._page.get_attribute(selector, attribute) or ""

    async def screenshot(self, path: Optional[str] = None) -> str:
        """鎴浘骞朵繚瀛橈紝杩斿洖鏂囦欢璺緞."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        if path is None:
            artifact_dir = Path("test_artifacts/screenshots/browser")
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = str(artifact_dir / f"screenshot_{random.randint(1000,9999)}.png")
        await self._page.screenshot(path=path, full_page=True)
        return path

    async def evaluate(self, expression: str) -> Any:
        """鍦ㄩ〉闈笂涓嬫枃涓墽琛?JavaScript."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        return await self._page.evaluate(expression)

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        """绛夊緟鍏冪礌鍑虹幇."""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        await self._page.wait_for_selector(selector, timeout=timeout)

    async def scroll_to_bottom(self) -> None:
        """婊氬姩鍒伴〉闈㈠簳閮?"""
        if self._page is None:
            raise RuntimeError("娴忚鍣ㄦ湭鍚姩")
        await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    @property
    def page(self) -> Optional[Page]:
        """鑾峰彇褰撳墠 Page 瀵硅薄锛堥珮绾х敤娉曪級."""
        return self._page

    async def try_solve_slider(self) -> bool:
        """瀹為獙鎬э細灏濊瘯鑷姩瑙ｅ喅绠€鍗曠殑婊戝潡楠岃瘉鐮侊紙濡?1688 NC 婊戝潡锛?

        浠呭皾璇曚竴娆★紝澶辫触鍚庡簲鐢辫皟鐢ㄦ柟杞汉宸ュ鐞嗐€?        Returns:
            True 琛ㄧず鐤戜技鎴愬姛锛孎alse 琛ㄧず澶辫触鎴栨湭妫€娴嬪埌婊戝潡銆?        """
        if self._page is None:
            return False
        try:
            # 妫€娴嬫粦鍧楄建閬撳拰婊戝潡鎸夐挳
            slider = await self._page.query_selector('.nc_wrapper .nc_iconfont.btn_slide, #nc_1_n1z, .btn_slide')
            track = await self._page.query_selector('.nc_wrapper .nc_scale, .slide-box, .nc-container')
            if not slider or not track:
                return False
            slider_box = await slider.bounding_box()
            track_box = await track.bounding_box()
            if not slider_box or not track_box:
                return False
            start_x = slider_box["x"] + slider_box["width"] / 2
            start_y = slider_box["y"] + slider_box["height"] / 2
            end_x = track_box["x"] + track_box["width"] - slider_box["width"] / 2
            end_y = start_y + random.uniform(-3, 3)
            # 绉诲姩鍒版粦鍧椾笂
            for px, py in bezier_curve((start_x - 50, start_y + random.uniform(-20, 20)), (start_x, start_y), num_points=12, spread=40):
                await self._page.mouse.move(px, py)
                await asyncio.sleep(random.uniform(0.008, 0.018))
            await asyncio.sleep(random.uniform(0.2, 0.5))
            await self._page.mouse.down()
            # 涓ゆ璐濆灏旀洸绾挎嫋鍔細鍏堝揩鍚庢參甯﹀皬骞呮姈鍔?            mid_x = (start_x + end_x) / 2 + random.uniform(-20, 20)
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
            # 绠€鍗曟牎楠岋細婊戝潡鏄惁杩樺湪
            still = await self._page.query_selector('.nc_wrapper .nc_iconfont.btn_slide, #nc_1_n1z')
            return still is None
        except Exception:
            return False

    async def close(self) -> None:
        """鍏抽棴娴忚鍣?"""
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

