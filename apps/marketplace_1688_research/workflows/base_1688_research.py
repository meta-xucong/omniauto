"""Low-disturbance ecommerce research workflow for 1688 单人摇椅."""

import asyncio
import base64
import json
import os
import random
import re
import shutil
import sqlite3
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

import win32crypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from omniauto.core.context import TaskContext
from omniauto.core.state_machine import AtomicStep, Workflow
from omniauto.engines.browser import StealthBrowser
from omniauto.recovery import RecoveryPolicy
from omniauto.utils.auth_manager import is_captcha_page, is_login_page

KEYWORD = "单人摇椅"
SITE_NAME = "1688"
TASK_NAME = "1688_single_rocking_chair_5"
SITE_HOME_URL = "https://www.1688.com"
KEYWORD_GBK = quote(KEYWORD, encoding="gbk")
BASE_URL = (
    "https://s.1688.com/selloffer/offer_search.htm"
    f"?keywords={KEYWORD_GBK}"
    "&sortType=price_sort-asc"
)
MAX_PAGES = 5
LIST_PAGE_LIMIT = 30
DETAIL_SAMPLE_SIZE = 0
OUTPUT_DIR = Path("runtime/apps/marketplace_1688_research/reports/1688_single_rocking_chair_5")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR = OUTPUT_DIR / "browser_artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
STATUS_PATH = OUTPUT_DIR / "run_status.json"
HANDOFF_PATH = OUTPUT_DIR / "manual_handoff.json"
MANUAL_BROWSER_LAUNCH_PATH = OUTPUT_DIR / "manual_browser_launch.json"
MANUAL_HANDOFF_BAR_SCRIPT = Path(__file__).resolve().parents[3] / "platform" / "src" / "omniauto" / "recovery" / "manual_handoff_bar.py"
REPORT_TEMPLATE = Path(__file__).resolve().parents[3] / "platform" / "src" / "omniauto" / "templates" / "reports" / "ecom_report.html.j2"
BROWSER_PROFILE_DIR = os.environ.get("OMNIAUTO_1688_PROFILE_DIR", "runtime/apps/marketplace_1688_research/chrome_profile_1688").strip() or "runtime/apps/marketplace_1688_research/chrome_profile_1688"
PROXY_SERVER = os.environ.get("OMNIAUTO_1688_PROXY", "").strip() or None
ENABLE_EXTERNAL_MANUAL_BROWSER = os.environ.get("OMNIAUTO_1688_EXTERNAL_MANUAL_BROWSER", "1").strip() != "0"
BROWSER_CONNECT_MODE = os.environ.get("OMNIAUTO_1688_BROWSER_MODE", "cdp_attach").strip() or "cdp_attach"
BROWSER_CDP_PORT = int((os.environ.get("OMNIAUTO_1688_CDP_PORT", "9232").strip() or "9232"))
REUSE_EXISTING_CDP = os.environ.get("OMNIAUTO_1688_REUSE_EXISTING_CDP", "1").strip() != "0"
PROFILE_COPY_EXCLUDED_DIRS = {
    "Crashpad",
    "GrShaderCache",
    "ShaderCache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "BrowserMetrics",
}
PROFILE_COPY_EXCLUDED_FILES = {
    "SingletonCookie",
    "SingletonLock",
    "SingletonSocket",
    "lockfile",
    "chrome_debug.log",
}
COOKIE_SOURCE_PATTERNS = ("%1688.com%", "%taobao.com%", "%alicdn.com%")
COOKIE_VALUE_TRAILING_RE = re.compile(r"([A-Za-z0-9%._+=&:/\\\\-]+)$")

RISK_URL_TOKENS = (
    "login",
    "signin",
    "passport",
    "auth",
    "logon",
    "punish",
    "identity",
    "verify",
    "captcha",
    "member.jump",
)
RISK_TEXT_TOKENS = (
    "滑动",
    "验证",
    "验证码",
    "安全验证",
    "身份验证",
    "请完成验证",
)
RESULT_SELECTOR = ".search-offer-item, .offer-item"

_all_items: list[dict] = []
_top_cheapest: list[dict] = []
_enriched_items: list[dict] = []
_skip_count = 0


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", "ignore").decode("gbk"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_status(state: str, **extra: object) -> None:
    payload = {"task_id": TASK_NAME, "state": state, "updated_at": datetime.now().isoformat()}
    payload.update(extra)
    _write_json(STATUS_PATH, payload)


def _canonical_1688_link(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    offer_id = query.get("offerId", [""])[0]
    sku_id = query.get("skuId", [""])[0] or query.get("hotSaleSkuId", [""])[0]
    if offer_id:
        clean_query = {"offerId": offer_id}
        if sku_id:
            clean_query["skuId"] = sku_id
        return f"http://detail.m.1688.com/page/index.html?{urlencode(clean_query)}"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


async def _write_manual_handoff(browser: StealthBrowser, reason: str, ctx: TaskContext) -> None:
    ctx.metadata["manual_handoff_url"] = browser.page.url if browser.page else ""
    ctx.metadata["manual_handoff_reason"] = reason
    payload = {
        "task_id": TASK_NAME,
        "reason": reason,
        "url": browser.page.url if browser.page else "",
        "target_url": ctx.metadata.get("manual_handoff_target_url"),
        "updated_at": datetime.now().isoformat(),
        "stopped_reason": ctx.metadata.get("stopped_reason"),
        "external_manual_browser_enabled": ENABLE_EXTERNAL_MANUAL_BROWSER,
        "proxy_enabled": bool(PROXY_SERVER),
    }
    _write_json(HANDOFF_PATH, payload)
    try:
        await browser.screenshot(path=str(ARTIFACT_DIR / "manual_handoff.png"))
    except Exception:
        pass


def _stop_profile_chrome_processes(user_data_dir: str) -> None:
    profile_path = str(Path(user_data_dir).resolve()).replace("'", "''")
    powershell = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*"
        f"{profile_path}"
        "*' } | "
        "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", powershell],
        check=False,
        capture_output=True,
        text=True,
    )


def _stop_profile_automation_chrome_processes(user_data_dir: str) -> None:
    profile_path = str(Path(user_data_dir).resolve()).replace("'", "''")
    powershell = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq 'chrome.exe' -and $_.CommandLine -like '*"
        f"{profile_path}"
        "*' -and ($_.CommandLine -like '*--remote-debugging-port*' -or $_.CommandLine -like '*--disable-extensions*') } | "
        "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", powershell],
        check=False,
        capture_output=True,
        text=True,
    )


def _wait_for_cdp_port(port: int, timeout_seconds: float = 20.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _is_cdp_port_ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def _launch_profile_cdp_browser(user_data_dir: str, target_url: str, port: int) -> None:
    chrome_path = _find_system_chrome()
    if not chrome_path:
        raise RuntimeError("System Chrome not found")
    _stop_profile_chrome_processes(user_data_dir)
    profile_path = str(Path(user_data_dir).resolve())
    subprocess.Popen(
        [
            chrome_path,
            f"--user-data-dir={profile_path}",
            f"--remote-debugging-port={port}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--new-window",
            target_url,
        ],
        close_fds=True,
    )
    if not _wait_for_cdp_port(port, timeout_seconds=20.0):
        raise RuntimeError(f"CDP port {port} did not become ready")


async def _create_browser(user_data_dir: str, *, start_url: str | None = None) -> StealthBrowser:
    if BROWSER_CONNECT_MODE == "cdp_attach":
        target_url = start_url or SITE_HOME_URL
        if not (REUSE_EXISTING_CDP and _is_cdp_port_ready(BROWSER_CDP_PORT)):
            _launch_profile_cdp_browser(user_data_dir, target_url, BROWSER_CDP_PORT)
        return await StealthBrowser(
            headless=False,
            use_system_chrome=False,
            cdp_url=f"http://127.0.0.1:{BROWSER_CDP_PORT}",
            auto_handle_login=False,
            auth_storage_dir="runtime/data/auth",
            auto_login_timeout=15.0,
            rotate_fingerprint=False,
            recovery_policy=RecoveryPolicy(
                max_total_cycles=4,
                manual_handoff_timeout_sec=1800.0,
                manual_handoff_poll_interval_sec=2.0,
                sensitive_site_mode=True,
                stop_on_risk_pages=True,
                wait_for_manual_handoff=False,
            ),
            recovery_artifact_dir=str(ARTIFACT_DIR),
        ).start()
    return await StealthBrowser(
        headless=False,
        use_system_chrome=True,
        user_data_dir=user_data_dir,
        auto_handle_login=False,
        auth_storage_dir="runtime/data/auth",
        auto_login_timeout=15.0,
        rotate_fingerprint=False,
        proxy=PROXY_SERVER,
        recovery_policy=RecoveryPolicy(
            max_total_cycles=4,
            manual_handoff_timeout_sec=1800.0,
            manual_handoff_poll_interval_sec=2.0,
            sensitive_site_mode=True,
            stop_on_risk_pages=True,
            wait_for_manual_handoff=False,
        ),
        recovery_artifact_dir=str(ARTIFACT_DIR),
    ).start()


def _looks_like_verification_stop(reason: str | None) -> bool:
    return bool(reason and "verification_required" in reason)


def _find_system_chrome() -> str | None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    return None


def _pythonw_path() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "python.exe":
        candidate = executable.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return str(executable)


def _prepare_playwright_profile(user_data_dir: str) -> str:
    source = Path(user_data_dir).resolve()
    if source.name.endswith("_playwright"):
        destination = source
    else:
        destination = source.with_name(f"{source.name}_playwright")
    shutil.rmtree(destination, ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    return str(destination)


def _clean_cookie_value(value: str) -> str:
    value = value.replace("\x00", "")
    match = COOKIE_VALUE_TRAILING_RE.search(value)
    if match:
        return match.group(1)
    return value


def _load_profile_cookies(user_data_dir: str) -> list[dict]:
    profile_dir = Path(user_data_dir).resolve()
    local_state_path = profile_dir / "Local State"
    cookies_db_path = profile_dir / "Default" / "Network" / "Cookies"
    if not local_state_path.is_file() or not cookies_db_path.is_file():
        return []

    try:
        local_state = json.loads(local_state_path.read_text(encoding="utf-8"))
        encrypted_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
        if encrypted_key.startswith(b"DPAPI"):
            encrypted_key = encrypted_key[5:]
        cookie_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
    except Exception:
        return []

    def decrypt_cookie(blob: bytes) -> str:
        if not blob:
            return ""
        if blob.startswith((b"v10", b"v11")):
            nonce = blob[3:15]
            ciphertext = blob[15:-16]
            tag = blob[-16:]
            plain = AESGCM(cookie_key).decrypt(nonce, ciphertext + tag, None).decode("utf-8", "ignore")
        else:
            plain = win32crypt.CryptUnprotectData(blob, None, None, None, 0)[1].decode("utf-8", "ignore")
        return _clean_cookie_value(plain)

    copy_db_path = cookies_db_path.with_name("Cookies.omniauto.readcopy")
    try:
        shutil.copy2(cookies_db_path, copy_db_path)
        connection = sqlite3.connect(copy_db_path)
        try:
            where_clause = " or ".join(["host_key like ?"] * len(COOKIE_SOURCE_PATTERNS))
            rows = connection.execute(
                f"""
                select host_key, name, path, expires_utc, is_secure, is_httponly, encrypted_value
                from cookies
                where {where_clause}
                """,
                COOKIE_SOURCE_PATTERNS,
            ).fetchall()
        finally:
            connection.close()
    except Exception:
        return []
    finally:
        copy_db_path.unlink(missing_ok=True)

    cookies: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for host_key, name, path, expires_utc, is_secure, is_httponly, encrypted_value in rows:
        value = decrypt_cookie(encrypted_value)
        if not host_key or not name or not value:
            continue
        cookie = {
            "name": name,
            "value": value,
            "domain": host_key.lstrip("."),
            "path": path or "/",
            "secure": bool(is_secure),
            "httpOnly": bool(is_httponly),
        }
        if expires_utc and expires_utc > 11644473600000000:
            expires = int(expires_utc / 1_000_000 - 11644473600)
            if expires > 0:
                cookie["expires"] = expires
        dedupe_key = (cookie["domain"], cookie["name"], cookie["path"])
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        cookies.append(cookie)
    return cookies


async def _prime_browser_session_from_profile(browser: StealthBrowser, user_data_dir: str, ctx: TaskContext | None = None) -> int:
    cookies = _load_profile_cookies(user_data_dir)
    applied = 0
    if not cookies or browser.page is None:
        if ctx is not None:
            ctx.metadata["seeded_cookie_count"] = 0
        return 0
    for cookie in cookies:
        try:
            await browser.page.context.add_cookies([cookie])
            applied += 1
        except Exception:
            continue
    if ctx is not None:
        ctx.metadata["seeded_cookie_count"] = applied
    return applied


def _launch_external_manual_browser(url: str, user_data_dir: str, reason: str | None) -> dict | None:
    if not ENABLE_EXTERNAL_MANUAL_BROWSER or not url:
        return None
    chrome_path = _find_system_chrome()
    if not chrome_path:
        return None

    profile_path = str(Path(user_data_dir).resolve())
    _stop_profile_automation_chrome_processes(profile_path)
    command = [
        chrome_path,
        f"--user-data-dir={profile_path}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        url,
    ]
    subprocess.Popen(command, close_fds=True)
    payload = {
        "task_id": TASK_NAME,
        "launched_at": datetime.now().isoformat(),
        "reason": reason,
        "url": url,
        "chrome_path": chrome_path,
        "user_data_dir": profile_path,
        "command": command,
    }
    _write_json(MANUAL_BROWSER_LAUNCH_PATH, payload)
    if MANUAL_HANDOFF_BAR_SCRIPT.is_file():
        bar_message = (
            "\u68c0\u6d4b\u5230 1688 \u9700\u8981\u4eba\u5de5\u63a5\u7ba1\u3002"
            "\u82e5\u9875\u9762\u5df2\u6b63\u5e38\u663e\u793a\u641c\u7d22\u7ed3\u679c\uff0c\u8bf7\u4fdd\u6301\u5f53\u524d\u767b\u5f55\u72b6\u6001\uff1b"
            "\u82e5\u4ecd\u8df3\u8f6c\u5230\u767b\u5f55\u6216\u9a8c\u8bc1\uff0c\u8bf7\u624b\u52a8\u5b8c\u6210\u540e\u518d\u56de\u6765\u7ee7\u7eed\u4efb\u52a1\u3002"
        )
        subprocess.Popen(
            [
                _pythonw_path(),
                str(MANUAL_HANDOFF_BAR_SCRIPT),
                "--title",
                "1688 \u4eba\u5de5\u63a5\u7ba1",
                "--message",
                bar_message,
                "--subtitle",
                (reason or "manual_handoff"),
                "--timeout-seconds",
                "1800",
            ],
            close_fds=True,
        )
    return payload


async def _gentle_page_pause(
    browser: StealthBrowser,
    *,
    min_idle: float = 6.0,
    max_idle: float = 12.0,
    with_viewing: bool = True,
) -> None:
    if with_viewing:
        await browser.simulate_human_viewing()
    await browser.cooldown(min_idle, max_idle)


async def _page_text(browser: StealthBrowser) -> str:
    try:
        return await browser.page.evaluate("() => document.body ? document.body.innerText.slice(0, 3000) : ''")
    except Exception:
        return ""


async def _is_risk_page(browser: StealthBrowser) -> bool:
    page = browser.page
    url = (page.url or "").lower()
    if any(token in url for token in RISK_URL_TOKENS):
        return True
    if await is_login_page(page) or await is_captcha_page(page):
        return True
    text = (await _page_text(browser)).lower()
    return any(token.lower() in text for token in RISK_TEXT_TOKENS)


async def _post_verify_settle(browser: StealthBrowser) -> None:
    await asyncio.sleep(random.uniform(10.0, 16.0))
    try:
        await browser.simulate_human_viewing()
    except Exception:
        pass
    await asyncio.sleep(random.uniform(5.0, 8.0))


async def _prepare_list_page(browser: StealthBrowser) -> None:
    try:
        await asyncio.sleep(random.uniform(2.0, 4.0))
        last_count = -1
        stable_rounds = 0
        for _ in range(5):
            count = await browser.page.locator(RESULT_SELECTOR).count()
            if count == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
                last_count = count
            if count >= LIST_PAGE_LIMIT or stable_rounds >= 2:
                break
            await browser.page.mouse.wheel(0, random.randint(520, 880))
            await asyncio.sleep(random.uniform(1.5, 3.0))
        await browser.page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
        await asyncio.sleep(random.uniform(1.0, 2.0))
    except Exception:
        return


async def _goto_once(browser: StealthBrowser, url: str, *, selector: str | None, ctx: TaskContext, risk_reason: str) -> bool:
    ctx.metadata["last_requested_url"] = url
    await browser.goto(url, wait_until="domcontentloaded", timeout=20000)
    await asyncio.sleep(random.uniform(2.5, 4.0))
    if await _is_risk_page(browser):
        ctx.metadata["stopped_reason"] = risk_reason
        ctx.metadata["manual_handoff_target_url"] = url
        await _write_manual_handoff(browser, risk_reason, ctx)
        return False
    if selector:
        try:
            await browser.wait_for_selector(selector, timeout=12000)
        except Exception:
            ctx.metadata["stopped_reason"] = f"selector_timeout:{risk_reason}"
            return False
    return True


async def _extract_list_items(browser: StealthBrowser) -> list[dict]:
    items = await browser.page.evaluate(
        """
        () => {{
            const results = [];
            const cards = Array.from(document.querySelectorAll('{result_selector}')).slice(0, {list_page_limit});
            for (const card of cards) {{
                let title = '';
                const titleSelectors = [
                    '.offer-title-row .title-text',
                    '.offer-title-row [title]',
                    '.title a:not(.find-similar)',
                    'a[title]:not(.find-similar)',
                    '.main-img img[alt]',
                    'img[alt]'
                ];
                for (const sel of titleSelectors) {{
                    const el = card.querySelector(sel);
                    if (!el) continue;
                    const candidate = (el.getAttribute('title') || el.innerText || el.getAttribute('alt') || '').trim();
                    if (candidate && !candidate.includes('找相似')) {{
                        title = candidate;
                        break;
                    }}
                }}
                const priceEl = card.querySelector('.offer-price-row .price-item, .text-main, .price');
                const imgEl = card.querySelector('.main-img img, img');
                const shopEl = card.querySelector('.company-name, .shop-name, .offer-company');
                let link = (card.getAttribute('href') || '').trim();
                let offerId = '';
                if (!link) {{
                    const renderKey = card.getAttribute('data-renderkey') || '';
                    const match = renderKey.match(/_(\\d+)$/);
                    if (match) offerId = match[1];
                }}
                if (!link && !offerId) {{
                    offerId = card.getAttribute('data-offerid') || card.getAttribute('offerid') || '';
                }}
                if (!link && offerId) {{
                    link = 'http://detail.m.1688.com/page/index.html?offerId=' + offerId;
                }}
                if (!link) {{
                    let anchor = null;
                    for (const a of card.querySelectorAll('a')) {{
                        const href = a.href || '';
                        if (!anchor && (href.includes('/offer/') || href.includes('detail.'))) {{
                            anchor = a;
                        }}
                    }}
                    if (!anchor) anchor = card.querySelector('a');
                    link = anchor ? anchor.href : '';
                }}
                if ((!title || title === '找相似') && imgEl) {{
                    const altTitle = (imgEl.getAttribute('alt') || '').trim();
                    if (altTitle && altTitle !== '找相似') title = altTitle;
                }}
                const priceText = priceEl ? priceEl.innerText.trim() : '';
                const numMatch = priceText.match(/\\d+(?:\\.\\d+)?/);
                results.push({{
                    title: title,
                    price_text: priceText,
                    price_num: numMatch ? parseFloat(numMatch[0]) : null,
                    image: imgEl ? (imgEl.getAttribute('data-src') || imgEl.getAttribute('src') || '') : '',
                    link: link,
                    shop_name: shopEl ? shopEl.innerText.trim() : '',
                }});
            }}
            return results;
        }}
        """.format(result_selector=RESULT_SELECTOR, list_page_limit=LIST_PAGE_LIMIT)
    )
    valid = []
    seen_links: set[str] = set()
    for item in items:
        link = _canonical_1688_link(item.get("link", ""))
        item["link"] = link
        if not item.get("title"):
            continue
        if "/offer/" not in link and "detail." not in link:
            continue
        if not link or link in seen_links:
            continue
        seen_links.add(link)
        valid.append(item)
    return valid


def _pick_top_cheapest(items: list[dict], limit: int) -> list[dict]:
    deduped: dict[str, dict] = {}
    for item in items:
        link = _canonical_1688_link(item.get("link", ""))
        if not link:
            continue
        item["link"] = link
        existing = deduped.get(link)
        if existing is None:
            deduped[link] = item
            continue
        old_price = existing.get("price_num")
        new_price = item.get("price_num")
        if old_price is None or (new_price is not None and new_price < old_price):
            deduped[link] = item
    candidates = [item for item in deduped.values() if item.get("price_num") is not None]
    candidates.sort(key=lambda item: (item.get("price_num") is None, item.get("price_num"), item.get("title", "")))
    return candidates[:limit]


async def _extract_detail(browser: StealthBrowser) -> dict:
    return await browser.page.evaluate(
        """
        () => {
            const shop = document.querySelector('.company-name, .shop-name, [data-spm="seller"], .s-companyName, .company-title');
            const location = document.querySelector('.location, .address, .region');
            const model = document.querySelector('.business-model, .business-type');
            const params = [];
            const propSelectors = [
                '.props-list tr', '.props-list .prop-item', '.offer-attr-item', '.props-item',
                '#mod-detail .obj-leading', '.prop-item', '#product table tr', '.region-screen-product table tr', 'table tr'
            ];
            for (const sel of propSelectors) {
                const els = document.querySelectorAll(sel);
                if (!els.length) continue;
                els.forEach((el) => {
                    const text = (el.innerText || '').trim();
                    if (text && text.length < 120) params.push(text);
                });
                if (params.length) break;
            }
            return {
                shop_name: shop ? shop.innerText.trim() : '',
                location: location ? location.innerText.trim() : '',
                business_model: model ? model.innerText.trim() : '',
                params: params.slice(0, 30),
            };
        }
        """
    )


async def step_warmup(ctx: TaskContext):
    browser: StealthBrowser = ctx.browser_state["browser"]
    if BROWSER_CONNECT_MODE == "cdp_attach":
        ctx.metadata["seeded_cookie_count"] = 0
        _safe_print("[Step 0] Warmup: attached to dedicated Chrome profile via CDP")
        await _gentle_page_pause(browser, min_idle=2.0, max_idle=4.0, with_viewing=False)
        return {"success": True, "url": browser.page.url}
    seeded_cookie_count = await _prime_browser_session_from_profile(browser, BROWSER_PROFILE_DIR, ctx)
    _safe_print(f"[Step 0] Warmup: seeded {seeded_cookie_count} session cookies and skip home-page risk")
    await _gentle_page_pause(browser, min_idle=3.0, max_idle=6.0, with_viewing=False)
    return {"success": True, "url": browser.page.url}


async def step_search(ctx: TaskContext):
    browser: StealthBrowser = ctx.browser_state["browser"]
    url = f"{BASE_URL}&beginPage=1"
    _safe_print(f"[Step 1] Open search page: {url}")
    ok = await _goto_once(browser, url, selector=RESULT_SELECTOR, ctx=ctx, risk_reason=f"{SITE_NAME}_search_verification_required")
    if not ok:
        raise RuntimeError(f"{SITE_NAME} search page requires manual verification")
    await _post_verify_settle(browser)
    await _gentle_page_pause(browser, min_idle=7.0, max_idle=12.0, with_viewing=True)
    return {"success": True, "url": browser.page.url}


async def step_scrape_pages(ctx: TaskContext):
    global _all_items, _top_cheapest
    browser: StealthBrowser = ctx.browser_state["browser"]
    actual_pages = 0

    for page_num in range(1, MAX_PAGES + 1):
        url = f"{BASE_URL}&beginPage={page_num}"
        if page_num > 1 or f"beginPage={page_num}" not in browser.page.url:
            _safe_print(f"[Step 2] List page {page_num}: {url}")
            ok = await _goto_once(browser, url, selector=RESULT_SELECTOR, ctx=ctx, risk_reason=f"{SITE_NAME}_list_verification_required_page_{page_num}")
            if not ok:
                break
        await _prepare_list_page(browser)
        items = await _extract_list_items(browser)
        for item in items:
            item["source_page"] = page_num
        _all_items.extend(items)
        actual_pages += 1
        _safe_print(f"  Page {page_num}: {len(items)} items")
        await _gentle_page_pause(browser, min_idle=8.0, max_idle=14.0, with_viewing=True)
        if page_num < MAX_PAGES:
            await browser.cooldown(28.0, 42.0)

    _top_cheapest = _pick_top_cheapest(_all_items, DETAIL_SAMPLE_SIZE) if DETAIL_SAMPLE_SIZE > 0 else []
    ctx.metadata["list_pages_completed"] = actual_pages
    ctx.metadata["list_items_total"] = len(_all_items)
    ctx.metadata["top_cheapest_count"] = len(_top_cheapest)
    scrape_success = actual_pages > 0 and len(_all_items) > 0
    if DETAIL_SAMPLE_SIZE > 0:
        scrape_success = scrape_success and len(_top_cheapest) > 0
    return {"success": scrape_success, "pages": actual_pages, "total": len(_all_items), "top_count": len(_top_cheapest)}


async def step_enrich_details(ctx: TaskContext):
    global _enriched_items, _skip_count
    browser: StealthBrowser = ctx.browser_state["browser"]

    if not _top_cheapest:
        return {"success": True, "sample_size": 0, "target": 0}

    _safe_print(f"[Step 3] Enrich top {len(_top_cheapest)} cheapest detail pages")
    for index, item in enumerate(_top_cheapest, 1):
        detail_url = item.get("link")
        if not detail_url:
            continue
        await browser.cooldown(18.0, 28.0)
        ok = await _goto_once(browser, detail_url, selector=None, ctx=ctx, risk_reason=f"{SITE_NAME}_detail_verification_required")
        if not ok:
            item["detail_error"] = "risk_page"
            _enriched_items.append(item)
            _skip_count += 1
            break
        detail = await _extract_detail(browser)
        if not detail.get("shop_name") and not detail.get("params"):
            item["detail_error"] = "page_not_normal"
            _enriched_items.append(item)
            _skip_count += 1
            continue
        screenshot_name = f"detail_{index:03d}.png"
        item["detail"] = detail
        try:
            await browser.screenshot(path=str(OUTPUT_DIR / screenshot_name))
            item["screenshot"] = screenshot_name
        except Exception as exc:
            item["screenshot_error"] = str(exc)
            _safe_print(f"[Step 3] Screenshot failed for sample {index}: {exc}")
        _enriched_items.append(item)
        await _gentle_page_pause(browser, min_idle=4.0, max_idle=9.0, with_viewing=True)

    ctx.metadata["detail_sample_target"] = len(_top_cheapest)
    ctx.metadata["detail_sample_completed"] = len([item for item in _enriched_items if item.get("detail")])
    return {"success": True, "sample_size": len(_enriched_items), "target": len(_top_cheapest)}


async def step_generate_report(ctx: TaskContext):
    report_data = {
        "task_id": TASK_NAME,
        "keyword": KEYWORD,
        "site": SITE_NAME,
        "safe_mode": True,
        "total_items": len(_all_items),
        "top_cheapest_count": len(_top_cheapest),
        "sample_size": len(_enriched_items),
        "skip_count": _skip_count,
        "list_pages_completed": ctx.metadata.get("list_pages_completed", 0),
        "detail_sample_target": ctx.metadata.get("detail_sample_target", 0),
        "detail_sample_completed": ctx.metadata.get("detail_sample_completed", 0),
        "stopped_reason": ctx.metadata.get("stopped_reason"),
        "all_items": _all_items,
        "top_cheapest_items": _top_cheapest,
        "items": _enriched_items,
        "generated_at": datetime.now().isoformat(),
    }
    json_path = OUTPUT_DIR / "report_data.json"
    _write_json(json_path, report_data)

    html_path = OUTPUT_DIR / "report.html"
    def _fallback_html() -> str:
        lines = [
            "<html><head><meta charset='utf-8'><title>Report</title></head><body>",
            f"<h1>{KEYWORD} - {SITE_NAME} report</h1>",
            f"<p>List items: {len(_all_items)} | Top cheapest: {len(_top_cheapest)} | Detail enriched: {len(_enriched_items)} | Skipped: {_skip_count}</p>",
            f"<p>Stopped reason: {ctx.metadata.get('stopped_reason') or 'none'}</p>",
            "<h2>Top 10 cheapest</h2>",
            "<table border='1' cellpadding='6'><tr><th>Title</th><th>Price</th><th>Page</th><th>Link</th></tr>",
        ]
        for item in _top_cheapest:
            lines.append(
                f"<tr><td>{item.get('title','')}</td><td>{item.get('price_text','')}</td><td>{item.get('source_page','')}</td><td>{item.get('link','')}</td></tr>"
            )
        lines.append("</table></body></html>")
        return "\n".join(lines)

    if REPORT_TEMPLATE.exists():
        try:
            from jinja2 import Template

            tpl = Template(REPORT_TEMPLATE.read_text(encoding="utf-8"))
            html = tpl.render(**report_data)
        except Exception:
            html = _fallback_html()
    else:
        html = _fallback_html()
    html_path.write_text(html, encoding="utf-8")

    _write_status(
        "report_ready",
        final_state="report_ready",
        total_items=len(_all_items),
        top_cheapest_count=len(_top_cheapest),
        detail_sample_completed=ctx.metadata.get("detail_sample_completed", 0),
        stopped_reason=ctx.metadata.get("stopped_reason"),
    )
    return {"success": True, "json_path": str(json_path), "html_path": str(html_path)}


workflow = Workflow(
    task_id=TASK_NAME,
    steps=[
        AtomicStep("s0_warmup", step_warmup, lambda r: r.get("success"), retry=0, description="site warmup"),
        AtomicStep("s1_search", step_search, lambda r: r.get("success"), retry=0, description="open search page"),
        AtomicStep("s2_scrape", step_scrape_pages, lambda r: r.get("success"), retry=0, description="scrape list pages"),
        AtomicStep("s3_enrich", step_enrich_details, lambda r: r.get("success"), retry=0, description="enrich detail pages"),
        AtomicStep("s4_report", step_generate_report, lambda r: bool(r.get("json_path")) and bool(r.get("html_path")), retry=0, description="generate report"),
    ],
    inter_step_delay=(4.0, 7.0),
)


async def main():
    browser = await _create_browser(BROWSER_PROFILE_DIR)
    ctx = TaskContext(task_id=TASK_NAME, browser_state={"browser": browser})
    try:
        final_state = await workflow.run(context=ctx)
        _write_status(
            "completed",
            final_state=final_state.name,
            outputs=list(ctx.outputs.keys()),
            stopped_reason=ctx.metadata.get("stopped_reason"),
        )
        _safe_print(f"Workflow finished: {final_state.name}")
    except Exception as exc:
        _write_status("error", final_state="ERROR", error=str(exc), stopped_reason=ctx.metadata.get("stopped_reason"))
        raise
    finally:
        await ctx.browser_state["browser"].close()


if __name__ == "__main__":
    asyncio.run(main())

