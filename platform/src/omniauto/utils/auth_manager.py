"""登录态检测、提示与持久化管理."""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page


def get_site_key(url: str) -> str:
    """从 URL 中提取站点主域名作为 key."""
    netloc = urlparse(url).netloc.lower().split(":")[0]
    parts = netloc.split(".")
    # 移除 www 前缀
    if len(parts) > 2 and parts[0] == "www":
        parts = parts[1:]
    # 保留主域名，如 login.taobao.com -> taobao.com
    if len(parts) > 2:
        return ".".join(parts[-2:])
    return ".".join(parts)


async def is_login_page(page: Page) -> bool:
    """检测当前页面是否为登录/验证页."""
    url = page.url.lower()
    url_signals = [
        "login", "signin", "auth", "passport", "logon",
        "register", "dologin", "member", "jump",
    ]
    if any(sig in url for sig in url_signals):
        return True

    selectors = [
        'input[type="password"]',
        '#login-form',
        '.login-form',
        '.login-box',
        '.tmall-login-box',
        '[name="password"]',
        '[placeholder*="密码"]',
        '[placeholder*="password"]',
        '[placeholder*="手机号"]',
        '[placeholder*="mobile"]',
    ]
    visibility_script = """
        el => {
            if (!el) return false;
            const style = getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }
    """
    for sel in selectors:
        try:
            visible = await page.eval_on_selector(sel, visibility_script)
            if visible:
                return True
        except Exception:
            continue
    return False


async def is_captcha_page(page: Page) -> bool:
    """检测当前页面是否包含可见的滑块/验证码/人机验证元素."""
    # 精确 captcha 选择器（避免误匹配页面中的普通轮播/幻灯片组件）
    selectors = [
        '.nc_wrapper',
        '#nc_1_n1z',
        '.btn_slide',
        '.slide-box',
        '.captcha',
        '#captcha',
        '.verify',
        '#verify',
        '.geetest',
        '.yidun',
        '.sm-popup',
        '.tb-pass',
        '.nc-container',
        '.nc-mask',
        '.nc-lang-cnt',
        '#nc_1__bg',
        '#nc_1__scale_text',
        '.ncpt-mask',
        '.ncpt-challenge',
        '.ncpt-clickCaptcha',
        '[id^="nc_"]',
    ]
    visibility_script = """
        el => {
            if (!el) return false;
            const style = getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        }
    """
    for sel in selectors:
        try:
            visible = await page.eval_on_selector(sel, visibility_script)
            if visible:
                return True
        except Exception:
            continue

    # 通过页面文字检测（中文/英文验证码关键词）
    try:
        body_text = await page.evaluate(
            "() => document.body ? document.body.innerText.substring(0,3000) : ''"
        )
        text_lower = body_text.lower()
        keyword_signals = [
            "请拖动下方滑块", "拖动滑块", "滑块验证", "完成验证",
            "点击验证", "安全验证", "身份验证", "人机验证",
            "请按照说明拖动滑块", "拖动滑块出现", "完整的两个轮胎",
            "captcha", "verification", "slide to verify", "confirm you are human",
        ]
        if any(kw in text_lower for kw in keyword_signals):
            return True
    except Exception:
        pass

    return False


class AuthManager:
    """通用登录态管理器."""

    def __init__(self, storage_dir: str = "runtime/data/auth"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _auth_file(self, site_key: str) -> Path:
        return self.storage_dir / f"{site_key}_auth.json"

    async def save(self, page: Page, site_key: str) -> None:
        """保存当前页面的 Cookie、LocalStorage 和 SessionStorage."""
        if page.context is None:
            return
        cookies = await page.context.cookies()
        local_storage = await page.evaluate("() => Object.assign({}, window.localStorage)")
        session_storage = await page.evaluate("() => Object.assign({}, window.sessionStorage)")
        data = {
            "url": page.url,
            "cookies": cookies,
            "local_storage": local_storage,
            "session_storage": session_storage,
        }
        file_path = self._auth_file(site_key)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[AuthManager] 登录态已保存到 {file_path}")

    async def load(self, page: Page, site_key: str) -> bool:
        """恢复登录态到当前页面上下文."""
        file_path = self._auth_file(site_key)
        if not file_path.exists():
            return False
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if page.context is None:
            return False

        cookies = data.get("cookies", [])
        if cookies:
            await page.context.add_cookies(cookies)

        local_storage = data.get("local_storage", {})
        session_storage = data.get("session_storage", {})
        for k, v in local_storage.items():
            await page.evaluate(
                f'() => {{ window.localStorage.setItem({json.dumps(k)}, {json.dumps(v)}); }}'
            )
        for k, v in session_storage.items():
            await page.evaluate(
                f'() => {{ window.sessionStorage.setItem({json.dumps(k)}, {json.dumps(v)}); }}'
            )
        print(f"[AuthManager] 登录态已从 {file_path} 恢复")
        return True

    async def inject_login_prompt(self, page, site_key: str) -> bool:
        """不再注入 DOM 提示条（避免干扰滑块验证），仅返回成功标志供日志使用."""
        # 为避免 DOM 注入干扰滑块/验证码交互，所有提示已通过系统弹窗 + 终端日志完成
        return True
        try:
            result = await page.evaluate(script)
            print(f"[AuthManager] 登录提示浮层注入结果: {result}")
            return result in ("injected", "already_exists")
        except Exception as e:
            print(f"[AuthManager] 登录提示浮层注入失败: {e}")
            return False

    async def update_login_prompt_timer(self, page, elapsed_seconds: int) -> None:
        """更新页面提示中的等待时间."""
        try:
            await page.evaluate(
                f"""
                var t = document.getElementById('omniauto-login-timer');
                if (t) t.textContent = '已等待 {elapsed_seconds} 秒';
                """
            )
        except Exception:
            pass

    async def remove_login_prompt(self, page) -> None:
        """移除页面中的登录提示浮层."""
        try:
            await page.evaluate("""
                var el = document.getElementById('omniauto-login-prompt');
                if (el) el.remove();
            """)
        except Exception:
            pass

    async def wait_for_intervention(
        self,
        page,
        site_key: str,
        timeout: float = 600.0,
        poll_interval: float = 3.0,
    ) -> bool:
        """轮询检测页面是否已离开登录/验证状态，返回是否处理成功.

        同时处理登录页和滑块/验证码页。提示信息会显示在终端和浏览器页面中。
        Windows 环境下还会触发系统弹窗与蜂鸣提示，防止用户忽略。
        """
        is_login = await is_login_page(page)
        is_captcha = await is_captcha_page(page)

        prompt_type = "登录"
        if is_captcha and not is_login:
            prompt_type = "验证（滑块/验证码）"

        print("\n" + "=" * 55)
        print(f" [OmniAuto] 当前站点需要处理: {site_key}")
        print(f" 请在弹出的浏览器窗口中手动完成{prompt_type}。")
        print(f" 程序将自动检测完成状态（最长等待 {int(timeout)} 秒）...")
        print("=" * 55 + "\n")
        await self.inject_login_prompt(page, site_key)

        # Windows 系统弹窗 + 蜂鸣提醒
        try:
            import ctypes
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            ctypes.windll.user32.MessageBoxW(
                0,
                f"当前站点: {site_key}\n请在浏览器窗口中手动完成{prompt_type}。\n程序将自动继续（最长等待 {int(timeout)} 秒）。",
                "OmniAuto 需要人工验证",
                0x40 | 0x1000  # MB_ICONINFORMATION | MB_TOPMOST
            )
        except Exception:
            pass

        elapsed = 0.0
        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            if int(elapsed) % 6 == 0:
                await self.update_login_prompt_timer(page, int(elapsed))

            still_login = await is_login_page(page)
            still_captcha = await is_captcha_page(page)
            if not still_login and not still_captcha:
                await self.remove_login_prompt(page)
                print(f"[AuthManager] 检测到 {site_key} {prompt_type}完成，继续执行。")
                return True
            print(f"  等待{prompt_type}中... {int(elapsed)}s")

        print(f"[AuthManager] 等待 {site_key} {prompt_type}超时。")
        return False
