"""Real-world Taobao verification workflow.

Flow:
1. Open Taobao with a persistent Chrome profile.
2. Reuse login if available; otherwise switch to SMS login and wait for human code entry.
3. Search by keyword.
4. Open the selected shop candidate from the search results.

This script is intentionally deterministic and keeps all task-specific choices in config.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from omniauto.core.context import StepResult, TaskContext
from omniauto.core.state_machine import AtomicStep, TaskState, Workflow
from omniauto.engines.browser import StealthBrowser


TASK_ID = "verification_taobao_login_top_shop"

TAOBAO_HOME_URL = "https://www.taobao.com"
TAOBAO_ACCOUNT_URL = "https://buyertrade.taobao.com/trade/itemlist/list_bought_items.htm"
TAOBAO_LOGIN_URL = (
    "https://login.taobao.com/member/login.jhtml"
    "?redirectURL=https%3A%2F%2Fwww.taobao.com%2F"
)

TEXT_SMS_LOGIN = "\u77ed\u4fe1\u767b\u5f55"
TEXT_PHONE_LOGIN = "\u624b\u673a\u767b\u5f55"
TEXT_SMS_CODE_LOGIN = "\u9a8c\u8bc1\u7801\u767b\u5f55"
TEXT_PHONE_CODE_LOGIN = "\u624b\u673a\u9a8c\u8bc1\u7801\u767b\u5f55"
TEXT_SEND_SMS = "\u53d1\u9001\u9a8c\u8bc1\u7801"
TEXT_GET_CODE = "\u83b7\u53d6\u9a8c\u8bc1\u7801"
TEXT_GET_SMS_CODE = "\u83b7\u53d6\u77ed\u4fe1\u9a8c\u8bc1\u7801"
TEXT_CODE_SENT = "\u9a8c\u8bc1\u7801\u5df2\u53d1\u9001"
TEXT_RESEND = "\u91cd\u65b0\u53d1\u9001"
TEXT_REACQUIRE = "\u91cd\u65b0\u83b7\u53d6"
TEXT_ALREADY_READ = "\u5df2\u9605\u8bfb\u5e76\u540c\u610f"
TEXT_SERVICE_AGREEMENT = "\u670d\u52a1\u534f\u8bae"
TEXT_PRIVACY = "\u9690\u79c1"
TEXT_LOGOUT = "\u9000\u51fa\u767b\u5f55"
TEXT_ACCOUNT_SETTINGS = "\u8d26\u6237\u8bbe\u7f6e"
TEXT_SEARCH = "\u641c\u7d22"
TEXT_SEARCH_THIS_SHOP = "\u641c\u7d22\u672c\u5e97"
TEXT_ALL_PRODUCTS = "\u5168\u90e8\u5b9d\u8d1d"
TEXT_SHOP_CATEGORY = "\u5e97\u94fa\u5206\u7c7b"
TEXT_FOLLOW = "\u5173\u6ce8"
TEXT_FANS = "\u7c89\u4e1d"
TEXT_ENTER_SHOP = "\u8fdb\u5e97"
TEXT_TMALL = "\u5929\u732b"
TEXT_TAOBAO = "\u6dd8\u5b9d"
TEXT_SORT_PRICE = "\u4ef7\u683c"
TEXT_SORT_COMPREHENSIVE = "\u7efc\u5408\u6392\u5e8f"

ARTIFACT_DIR = Path("runtime/test_artifacts/verification/browser/taobao_login_top_shop")
PROFILE_DIR = ARTIFACT_DIR / "profile"
STATUS_PATH = ARTIFACT_DIR / "status.json"
LOGIN_STATE_PATH = ARTIFACT_DIR / "login_state.json"
HANDOFF_PATH = ARTIFACT_DIR / "handoff.json"
FINAL_SCREENSHOT_PATH = ARTIFACT_DIR / "final_page.png"
WAITING_SCREENSHOT_PATH = ARTIFACT_DIR / "waiting_for_sms.png"
SEARCH_SCREENSHOT_PATH = ARTIFACT_DIR / "search_results.png"


def _split_tokens(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,\n|;，；]+", text) if item.strip()]


def _as_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: object, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _load_runtime_config() -> dict[str, Any]:
    raw: dict[str, Any] = {}
    config_path = os.environ.get("OMNIAUTO_TAOBAO_CONFIG_PATH", "").strip()
    if config_path:
        path = Path(config_path)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))

    def pick(key: str, env_name: str, default: object) -> object:
        env_value = os.environ.get(env_name)
        if env_value is not None and str(env_value).strip() != "":
            return env_value
        value = raw.get(key)
        return default if value in (None, "") else value

    keyword = str(pick("keyword", "OMNIAUTO_TAOBAO_KEYWORD", "\u6c49\u670d")).strip()
    if not keyword:
        keyword = "\u6c49\u670d"

    return {
        "config_path": config_path,
        "phone": str(pick("phone", "OMNIAUTO_TAOBAO_PHONE", "13813809690")).strip(),
        "keyword": keyword,
        "force_sms_login": _as_bool(pick("force_sms_login", "OMNIAUTO_TAOBAO_FORCE_SMS_LOGIN", False)),
        "keep_browser_seconds": _as_int(pick("keep_browser_seconds", "OMNIAUTO_TAOBAO_KEEP_BROWSER_SECONDS", 600), 600),
        "result_rank": max(1, _as_int(pick("result_rank", "OMNIAUTO_TAOBAO_RESULT_RANK", 1), 1)),
        "scan_limit": max(1, _as_int(pick("scan_limit", "OMNIAUTO_TAOBAO_SCAN_LIMIT", 20), 20)),
        "preferred_platform": str(pick("preferred_platform", "OMNIAUTO_TAOBAO_PREFERRED_PLATFORM", "any")).strip().lower() or "any",
        "enter_mode": str(pick("enter_mode", "OMNIAUTO_TAOBAO_ENTER_MODE", "auto")).strip().lower() or "auto",
        "title_include": _split_tokens(pick("title_include", "OMNIAUTO_TAOBAO_TITLE_INCLUDE", "")),
        "title_exclude": _split_tokens(pick("title_exclude", "OMNIAUTO_TAOBAO_TITLE_EXCLUDE", "")),
        "shop_include": _split_tokens(pick("shop_include", "OMNIAUTO_TAOBAO_SHOP_INCLUDE", "")),
        "shop_exclude": _split_tokens(pick("shop_exclude", "OMNIAUTO_TAOBAO_SHOP_EXCLUDE", "")),
    }


RUNTIME_CONFIG = _load_runtime_config()
PHONE_NUMBER = RUNTIME_CONFIG["phone"]
SEARCH_KEYWORD = RUNTIME_CONFIG["keyword"]
FORCE_SMS_LOGIN = RUNTIME_CONFIG["force_sms_login"]
KEEP_BROWSER_SECONDS = RUNTIME_CONFIG["keep_browser_seconds"]
RESULT_RANK = RUNTIME_CONFIG["result_rank"]
SCAN_LIMIT = RUNTIME_CONFIG["scan_limit"]
PREFERRED_PLATFORM = RUNTIME_CONFIG["preferred_platform"]
ENTER_MODE = RUNTIME_CONFIG["enter_mode"]
TITLE_INCLUDE = RUNTIME_CONFIG["title_include"]
TITLE_EXCLUDE = RUNTIME_CONFIG["title_exclude"]
SHOP_INCLUDE = RUNTIME_CONFIG["shop_include"]
SHOP_EXCLUDE = RUNTIME_CONFIG["shop_exclude"]
TAOBAO_SEARCH_URL = f"https://s.taobao.com/search?q={quote(SEARCH_KEYWORD)}"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_status(status: str, message: str, **extra: object) -> None:
    payload = {
        "task_id": TASK_ID,
        "status": status,
        "message": message,
        "keyword": SEARCH_KEYWORD,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    payload.update(extra)
    _write_json(STATUS_PATH, payload)


def _write_login_state(mode: str, **extra: object) -> None:
    payload = {
        "task_id": TASK_ID,
        "mode": mode,
        "phone": PHONE_NUMBER,
        "keyword": SEARCH_KEYWORD,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    payload.update(extra)
    _write_json(LOGIN_STATE_PATH, payload)


def _write_handoff(status: str, reason: str, **extra: object) -> None:
    payload = {
        "task_id": TASK_ID,
        "status": status,
        "reason": reason,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    payload.update(extra)
    _write_json(HANDOFF_PATH, payload)


def _clear_handoff() -> None:
    if HANDOFF_PATH.exists():
        HANDOFF_PATH.unlink()


def _contains_any(text: str, tokens: list[str]) -> bool:
    lower = (text or "").lower()
    return any(token.lower() in lower for token in tokens)


def _match_text_rules(text: str, include_tokens: list[str], exclude_tokens: list[str]) -> bool:
    if include_tokens and not _contains_any(text, include_tokens):
        return False
    if exclude_tokens and _contains_any(text, exclude_tokens):
        return False
    return True


def _platform_penalty(platform: str) -> int:
    normalized = (platform or "unknown").strip().lower()
    if PREFERRED_PLATFORM == "any":
        return 0
    if normalized == PREFERRED_PLATFORM:
        return 0
    if normalized == "unknown":
        return 1
    return 2


def _choose_search_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    filtered: list[dict[str, Any]] = []
    for item in candidates[: max(SCAN_LIMIT, RESULT_RANK) * 3]:
        title = str(item.get("title") or "")
        shop_text = " ".join([str(item.get("shopName") or ""), str(item.get("cardText") or "")]).strip()
        if not _match_text_rules(title, TITLE_INCLUDE, TITLE_EXCLUDE):
            continue
        if not _match_text_rules(shop_text, SHOP_INCLUDE, SHOP_EXCLUDE):
            continue
        if ENTER_MODE == "shop_only" and not item.get("shopHref"):
            continue
        if ENTER_MODE == "product_then_shop" and not item.get("productHref"):
            continue
        filtered.append(item)

    pool = filtered or candidates
    if not pool:
        raise RuntimeError("No usable Taobao search candidate was found.")

    pool = sorted(
        pool,
        key=lambda item: (
            _platform_penalty(str(item.get("platform") or "unknown")),
            int(item.get("index") or 999999),
        ),
    )
    return pool[min(len(pool), RESULT_RANK) - 1]


async def _find_locator(page, selectors: list[str], timeout_ms: int = 1500):
    for frame in list(page.frames):
        for selector in selectors:
            locator = frame.locator(selector).first
            try:
                await locator.wait_for(state="visible", timeout=timeout_ms)
                return frame, locator
            except Exception:
                continue
    return None, None


async def _click_first(page, selectors: list[str], timeout_ms: int = 1500) -> bool:
    _, locator = await _find_locator(page, selectors, timeout_ms)
    if locator is None:
        return False
    await locator.click()
    return True


async def _fill_first(page, selectors: list[str], text: str, timeout_ms: int = 1500) -> bool:
    _, locator = await _find_locator(page, selectors, timeout_ms)
    if locator is None:
        return False
    await locator.fill("")
    await locator.type(text, delay=100)
    return True


async def _looks_logged_in(page) -> bool:
    if "login.taobao.com" in page.url:
        return False
    selectors = [
        f"text=\u5df2\u4e70\u5230\u7684\u5b9d\u8d1d",
        f"text=\u6536\u85cf\u5939",
        f"text={TEXT_LOGOUT}",
        f"text={TEXT_ACCOUNT_SETTINGS}",
    ]
    _, locator = await _find_locator(page, selectors, timeout_ms=1000)
    return locator is not None


async def _looks_waiting_for_sms(page) -> bool:
    selectors = [
        "input[placeholder*='\u9a8c\u8bc1\u7801']",
        "input[aria-label*='\u9a8c\u8bc1\u7801']",
        f"text={TEXT_CODE_SENT}",
        f"text={TEXT_RESEND}",
        f"text={TEXT_REACQUIRE}",
        "text=\u79d2\u540e\u91cd\u53d1",
    ]
    _, locator = await _find_locator(page, selectors, timeout_ms=1000)
    return locator is not None


async def _dismiss_common_overlays(page) -> None:
    selectors = [
        "text=\u77e5\u9053\u4e86",
        "text=\u7a0d\u540e\u518d\u8bf4",
        "text=\u6682\u4e0d",
        "text=\u5173\u95ed",
        "text=\u4e0d\u611f\u5174\u8da3",
        "text=\u8df3\u8fc7",
        "button:has-text('\u5173\u95ed')",
    ]
    for _ in range(3):
        clicked = await _click_first(page, selectors, timeout_ms=500)
        if not clicked:
            break
        await asyncio.sleep(0.8)


async def _confirm_logged_in_via_account_page(browser: StealthBrowser) -> bool:
    await browser.goto(TAOBAO_ACCOUNT_URL)
    await asyncio.sleep(4)
    page = browser.page
    return bool(page and "login.taobao.com" not in page.url and await _looks_logged_in(page))


async def _wait_for_login_success(browser: StealthBrowser, timeout_sec: int = 600) -> bool:
    page = browser.page
    if page is None:
        return False
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while asyncio.get_running_loop().time() < deadline:
        if await _looks_logged_in(page):
            return True
        if "login.taobao.com" not in page.url:
            _, login_marker = await _find_locator(
                page,
                [
                    "input[placeholder*='\u624b\u673a\u53f7']",
                    "input[placeholder*='\u767b\u5f55\u5bc6\u7801']",
                    "input[type='password']",
                    f"text={TEXT_SMS_LOGIN}",
                    f"text=\u5bc6\u7801\u767b\u5f55",
                ],
                timeout_ms=800,
            )
            if login_marker is None:
                return True
        await asyncio.sleep(2)
    return False


async def _looks_shop_page(page) -> bool:
    selectors = [
        f"text={TEXT_SEARCH_THIS_SHOP}",
        f"text={TEXT_ALL_PRODUCTS}",
        f"text={TEXT_SHOP_CATEGORY}",
        f"text={TEXT_FOLLOW}",
        f"text={TEXT_FANS}",
    ]
    _, locator = await _find_locator(page, selectors, timeout_ms=1000)
    return locator is not None


async def step_open_taobao(ctx: TaskContext) -> StepResult:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _write_status("starting", "Launching Chrome and opening Taobao home.")

    browser = await StealthBrowser(
        headless=False,
        use_system_chrome=True,
        user_data_dir=str(PROFILE_DIR),
        auto_handle_login=False,
    ).start()
    browser.set_recovery_artifact_dir(str(ARTIFACT_DIR))
    ctx.browser_state["browser"] = browser

    await browser.goto(TAOBAO_HOME_URL)
    await asyncio.sleep(3)
    if browser.page is not None:
        await _dismiss_common_overlays(browser.page)
    _write_status("opened_home", "Taobao home page is open.", url=browser.page.url if browser.page else TAOBAO_HOME_URL)
    return StepResult(success=True, data={"url": browser.page.url if browser.page else TAOBAO_HOME_URL})


async def step_login_with_sms(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None or browser.page is None:
        raise RuntimeError("Browser engine is not initialized.")

    page = browser.page

    if not FORCE_SMS_LOGIN and await _confirm_logged_in_via_account_page(browser):
        _write_status("logged_in", "Persistent Chrome profile is already logged in.", url=page.url)
        _write_login_state("reused_profile", url=page.url)
        _clear_handoff()
        return StepResult(success=True, data={"logged_in": True, "skipped": True})

    _write_status("opening_login", "Opening Taobao login page.")
    await browser.goto(TAOBAO_LOGIN_URL)
    await asyncio.sleep(4)

    await _click_first(
        page,
        [
            f"text={TEXT_SMS_LOGIN}",
            f"text={TEXT_PHONE_CODE_LOGIN}",
            f"text={TEXT_SMS_CODE_LOGIN}",
            f"text={TEXT_PHONE_LOGIN}",
        ],
        timeout_ms=1200,
    )
    await asyncio.sleep(1)

    phone_filled = await _fill_first(
        page,
        [
            "input[placeholder*='\u624b\u673a\u53f7']",
            "input[aria-label*='\u624b\u673a\u53f7']",
            "input[name*='loginId']",
            "input[name*='fm-login-id']",
            "input[id*='fm-login-id']",
            "input[type='tel']",
            "input[inputmode='numeric']",
        ],
        PHONE_NUMBER,
        timeout_ms=2500,
    )
    if not phone_filled:
        raise RuntimeError("Taobao phone number input was not found.")

    sent = False
    for _ in range(2):
        clicked = await _click_first(
            page,
            [
                f"text={TEXT_SEND_SMS}",
                f"text={TEXT_GET_CODE}",
                f"text={TEXT_GET_SMS_CODE}",
                f"button:has-text('{TEXT_SEND_SMS}')",
                f"button:has-text('{TEXT_GET_CODE}')",
            ],
            timeout_ms=1800,
        )
        await asyncio.sleep(1.5)
        if clicked and await _looks_waiting_for_sms(page):
            sent = True
            break

    waiting_url = page.url
    try:
        await browser.screenshot(str(WAITING_SCREENSHOT_PATH))
    except Exception:
        pass

    handoff_message = (
        "Please enter the Taobao SMS code in Chrome to continue."
        if sent
        else "SMS send button was not confirmed automatically. Please complete the login step manually in Chrome."
    )
    _write_handoff(
        "waiting_for_sms",
        handoff_message,
        phone=PHONE_NUMBER,
        sent_code_button_clicked=sent,
        url=waiting_url,
    )
    _write_status(
        "waiting_for_sms",
        handoff_message,
        phone=PHONE_NUMBER,
        sent_code_button_clicked=sent,
        url=waiting_url,
    )

    logged_in = await _wait_for_login_success(browser, timeout_sec=600)
    if not logged_in:
        raise RuntimeError("Timed out while waiting for Taobao SMS login completion.")

    _write_login_state("sms_login_success", url=page.url)
    _write_status("logged_in", "Taobao login is complete.", url=page.url)
    _clear_handoff()
    return StepResult(success=True, data={"logged_in": True, "skipped": False})


async def step_search_and_open_top_shop(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None or browser.page is None:
        raise RuntimeError("Browser engine is not initialized.")

    page = browser.page
    _write_status(
        "searching",
        f"Opening Taobao search results for '{SEARCH_KEYWORD}'.",
        selection_rules={
            "result_rank": RESULT_RANK,
            "scan_limit": SCAN_LIMIT,
            "preferred_platform": PREFERRED_PLATFORM,
            "enter_mode": ENTER_MODE,
            "title_include": TITLE_INCLUDE,
            "title_exclude": TITLE_EXCLUDE,
            "shop_include": SHOP_INCLUDE,
            "shop_exclude": SHOP_EXCLUDE,
        },
    )

    await browser.goto(TAOBAO_SEARCH_URL)
    await asyncio.sleep(5)
    await _dismiss_common_overlays(page)

    if "login.taobao.com" in page.url:
        raise RuntimeError("Search results redirected back to login, so the login state is not usable.")

    try:
        await browser.screenshot(str(SEARCH_SCREENSHOT_PATH))
    except Exception:
        pass

    page_marker = await page.evaluate(
        """(args) => {
            const keyword = args.keyword || '';
            const bodyText = document.body ? (document.body.innerText || '') : '';
            const searchInput = document.querySelector("input[name='q'], #q, input[placeholder*='搜索']");
            const searchValue = searchInput ? (searchInput.value || searchInput.getAttribute('value') || '') : '';
            return {
                url: location.href,
                bodyHasKeyword: bodyText.includes(keyword),
                searchValue,
                hasResultsLikeText: /价格|发货地|综合排序/.test(bodyText),
            };
        }""",
        {"keyword": SEARCH_KEYWORD},
    )
    if not (
        page_marker.get("bodyHasKeyword")
        or SEARCH_KEYWORD in (page_marker.get("searchValue") or "")
        or page_marker.get("hasResultsLikeText")
    ):
        raise RuntimeError(f"Did not reach the expected Taobao search results page for '{SEARCH_KEYWORD}'.")

    candidates = await page.evaluate(
        """(args) => {
            const limit = args.limit || 20;
            const textTmall = args.textTmall || '天猫';
            const textTaobao = args.textTaobao || '淘宝';

            const isVisible = (el) => {
                if (!el) return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };

            const nearestCard = (anchor) => {
                return anchor.closest('[data-index], .doubleCardWrapperAdapt, .Card--doubleCardWrapper, li, .tbpc-col');
            };

            const parseIndex = (anchor, fallbackIndex, card) => {
                const spmMatch = (anchor.href || '').match(/item\\.(\\d+)/);
                if (spmMatch) return Number(spmMatch[1]);
                const dataIndex = card ? card.getAttribute('data-index') : '';
                if (dataIndex !== null && dataIndex !== undefined && dataIndex !== '' && !Number.isNaN(Number(dataIndex))) {
                    return Number(dataIndex);
                }
                return fallbackIndex;
            };

            const shopAnchors = Array.from(
                document.querySelectorAll("a[href*='store.taobao.com/shop/view_shop'], a.shopName--hdF527QA[href]")
            ).filter((anchor) => {
                if (!isVisible(anchor)) return false;
                const href = anchor.href || '';
                if (!/store\\.taobao\\.com/.test(href)) return false;
                if (/openshop/.test(href)) return false;
                return true;
            });

            const normalized = shopAnchors
                .map((shopAnchor, order) => {
                    const card = nearestCard(shopAnchor);
                    const anchors = card ? Array.from(card.querySelectorAll('a[href]')).filter(isVisible) : [];
                    const productAnchor = anchors.find((a) => {
                        const href = a.href || '';
                        return /item\\.taobao\\.com|detail\\.tmall\\.com/.test(href);
                    });
                    const cardText = card ? (card.innerText || '').trim() : ((shopAnchor.innerText || '').trim());
                    const platform = cardText.includes(textTmall)
                        ? 'tmall'
                        : (cardText.includes(textTaobao) ? 'taobao' : 'unknown');
                    return {
                        index: parseIndex(shopAnchor, order, card),
                        title: ((productAnchor && productAnchor.innerText) || cardText).trim().slice(0, 120),
                        shopName: (shopAnchor.innerText || '').trim(),
                        cardText: cardText.slice(0, 300),
                        platform,
                        shopHref: shopAnchor.href || '',
                        productHref: productAnchor ? productAnchor.href : '',
                    };
                })
                .filter((item) => item.shopHref || item.productHref)
                .sort((a, b) => a.index - b.index);

            return normalized.slice(0, limit);
        }""",
        {
            "limit": max(SCAN_LIMIT * 3, RESULT_RANK + 5),
            "textEnterShop": TEXT_ENTER_SHOP,
            "textShop": "\u5e97\u94fa",
            "textTmall": TEXT_TMALL,
            "textTaobao": TEXT_TAOBAO,
        },
    )

    shop_target = _choose_search_candidate(candidates or [])
    context = page.context
    target_url = shop_target.get("shopHref") or shop_target.get("productHref")
    if not target_url:
        raise RuntimeError("The selected Taobao search candidate does not have a usable URL.")

    await browser.goto(target_url)
    await asyncio.sleep(5)
    await _dismiss_common_overlays(page)

    if any(flag in page.url for flag in ["item.taobao.com", "detail.tmall.com"]):
        pages_before = len(context.pages)
        clicked_shop = await _click_first(
            page,
            [
                f"a:has-text('{TEXT_ENTER_SHOP}')",
                f"button:has-text('{TEXT_ENTER_SHOP}')",
                f"text={TEXT_ENTER_SHOP}",
            ],
            timeout_ms=2500,
        )
        await asyncio.sleep(4)
        if len(context.pages) > pages_before:
            new_page = context.pages[-1]
            await new_page.bring_to_front()
            ctx.browser_state["browser"]._page = new_page
            page = new_page
        elif not clicked_shop:
            raise RuntimeError("Reached a product detail page, but no shop entry point was found.")
        await asyncio.sleep(3)
        await _dismiss_common_overlays(page)

    if not await _looks_shop_page(page):
        raise RuntimeError("Navigation finished, but the final page does not look like a shop homepage.")

    final_url = page.url
    try:
        await browser.screenshot(str(FINAL_SCREENSHOT_PATH))
    except Exception:
        pass

    _write_status(
        "opened_top_shop",
        f"Opened a Taobao shop from search results for '{SEARCH_KEYWORD}'.",
        keyword=SEARCH_KEYWORD,
        shop_title=shop_target.get("title"),
        shop_name=shop_target.get("shopName"),
        platform=shop_target.get("platform"),
        matched_rank=RESULT_RANK,
        url=final_url,
        screenshot=str(FINAL_SCREENSHOT_PATH),
    )
    return StepResult(
        success=True,
        data={
            "url": final_url,
            "keyword": SEARCH_KEYWORD,
            "shop_title": shop_target.get("title"),
            "shop_name": shop_target.get("shopName"),
        },
    )


workflow = Workflow(task_id=TASK_ID, inter_step_delay=(1.0, 2.0))
workflow.add_step(AtomicStep("open_taobao", step_open_taobao, lambda r: r.success))
workflow.add_step(AtomicStep("login_with_sms", step_login_with_sms, lambda r: r.success))
workflow.add_step(AtomicStep("open_top_shop", step_search_and_open_top_shop, lambda r: r.success))


async def _main() -> int:
    ctx = TaskContext(task_id=TASK_ID)
    browser: Optional[StealthBrowser] = None
    try:
        final_state = await workflow.run(ctx)
        browser = ctx.browser_state.get("browser")
        status_name = "completed" if final_state == TaskState.COMPLETED else "failed"
        message = (
            "Workflow finished successfully. Chrome will stay open for manual verification."
            if final_state == TaskState.COMPLETED
            else "Workflow ended without completion. Chrome will stay open briefly for debugging."
        )
        _write_status(status_name, message, final_state=final_state.name, output_keys=list(ctx.outputs.keys()))
        await asyncio.sleep(KEEP_BROWSER_SECONDS)
        return 0 if final_state == TaskState.COMPLETED else 1
    except Exception as exc:
        _write_status("failed", f"{type(exc).__name__}: {exc}")
        await asyncio.sleep(120)
        return 1
    finally:
        browser = browser or ctx.browser_state.get("browser")
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
