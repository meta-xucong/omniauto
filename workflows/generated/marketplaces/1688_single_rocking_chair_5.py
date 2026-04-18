"""Low-disturbance ecommerce research workflow for 1688 单人摇椅."""

import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

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
OUTPUT_DIR = Path("data/reports/1688_single_rocking_chair_5")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_DIR = OUTPUT_DIR / "browser_artifacts"
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
STATUS_PATH = OUTPUT_DIR / "run_status.json"
HANDOFF_PATH = OUTPUT_DIR / "manual_handoff.json"

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
    payload = {
        "task_id": TASK_NAME,
        "reason": reason,
        "url": browser.page.url if browser.page else "",
        "updated_at": datetime.now().isoformat(),
        "stopped_reason": ctx.metadata.get("stopped_reason"),
    }
    _write_json(HANDOFF_PATH, payload)
    try:
        await browser.screenshot(path=str(ARTIFACT_DIR / "manual_handoff.png"))
    except Exception:
        pass


async def _create_browser(user_data_dir: str) -> StealthBrowser:
    return await StealthBrowser(
        headless=False,
        use_system_chrome=True,
        user_data_dir=user_data_dir,
        auto_handle_login=False,
        auth_storage_dir="data/auth",
        auto_login_timeout=15.0,
        rotate_fingerprint=False,
        proxy="http://127.0.0.1:7890",
        recovery_policy=RecoveryPolicy(
            max_total_cycles=4,
            manual_handoff_timeout_sec=1800.0,
            manual_handoff_poll_interval_sec=2.0,
            sensitive_site_mode=True,
            stop_on_risk_pages=True,
            wait_for_manual_handoff=True,
        ),
        recovery_artifact_dir=str(ARTIFACT_DIR),
    ).start()


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
    await asyncio.sleep(random.uniform(8.0, 12.0))
    for _ in range(2):
        try:
            await browser.page.evaluate("(distance) => window.scrollBy(0, distance)", random.randint(400, 900))
        except Exception:
            pass
        await asyncio.sleep(random.uniform(4.0, 6.0))


async def _goto_once(browser: StealthBrowser, url: str, *, selector: str | None, ctx: TaskContext, risk_reason: str) -> bool:
    await browser.goto(url, wait_until="domcontentloaded", timeout=20000)
    await asyncio.sleep(random.uniform(2.5, 4.0))
    if await _is_risk_page(browser):
        ctx.metadata["stopped_reason"] = risk_reason
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
    _safe_print("[Step 0] Warmup: visit 1688 home page")
    ok = await _goto_once(browser, SITE_HOME_URL, selector=None, ctx=ctx, risk_reason=f"{SITE_NAME}_home_verification_required")
    if not ok:
        raise RuntimeError(f"{SITE_NAME} home page requires manual verification or login")
    await browser.simulate_human_viewing()
    return {"success": True, "url": browser.page.url}


async def step_search(ctx: TaskContext):
    browser: StealthBrowser = ctx.browser_state["browser"]
    url = f"{BASE_URL}&beginPage=1"
    _safe_print(f"[Step 1] Open search page: {url}")
    ok = await _goto_once(browser, url, selector=RESULT_SELECTOR, ctx=ctx, risk_reason=f"{SITE_NAME}_search_verification_required")
    if not ok:
        raise RuntimeError(f"{SITE_NAME} search page requires manual verification")
    await _post_verify_settle(browser)
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
        items = await _extract_list_items(browser)
        for item in items:
            item["source_page"] = page_num
        _all_items.extend(items)
        actual_pages += 1
        _safe_print(f"  Page {page_num}: {len(items)} items")
        if page_num < MAX_PAGES:
            await browser.simulate_human_viewing()
            await browser.cooldown(12.0, 18.0)

    _top_cheapest = _pick_top_cheapest(_all_items, max(len(_all_items), 500))
    ctx.metadata["list_pages_completed"] = actual_pages
    ctx.metadata["list_items_total"] = len(_all_items)
    ctx.metadata["top_cheapest_count"] = len(_top_cheapest)
    return {"success": actual_pages > 0 and len(_all_items) > 0 and len(_top_cheapest) > 0, "pages": actual_pages, "total": len(_all_items), "top_count": len(_top_cheapest)}


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
        await browser.cooldown(14.0, 20.0)
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
        await browser.screenshot(path=str(OUTPUT_DIR / screenshot_name))
        item["detail"] = detail
        item["screenshot"] = screenshot_name
        _enriched_items.append(item)

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

    report_template = "D:/AI/AI_RPA/src/omniauto/templates/reports/ecom_report.html.j2"
    html_path = OUTPUT_DIR / "report.html"
    if report_template and Path(report_template).exists():
        from jinja2 import Template
        tpl = Template(Path(report_template).read_text(encoding="utf-8"))
        html = tpl.render(**report_data)
        html_path.write_text(html, encoding="utf-8")
    else:
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
        html_path.write_text("\n".join(lines), encoding="utf-8")

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
    browser = await _create_browser("data/chrome_profile_1688")
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

