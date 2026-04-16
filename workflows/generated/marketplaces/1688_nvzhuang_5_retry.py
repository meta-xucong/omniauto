"""由 TemplateGenerator 自动生成的电商商品调研 Workflow.

任务: 女装 | 站点: 1688 | 页数: 5 | 排序: price_asc
"""

import asyncio
import json
import os
import random
import re
import shutil
from pathlib import Path
from urllib.parse import quote, urljoin

from omniauto.core.state_machine import Workflow, AtomicStep, TaskState
from omniauto.core.context import TaskContext
from omniauto.engines.browser import StealthBrowser
from omniauto.utils.auth_manager import is_login_page, is_captcha_page
from omniauto.utils.fingerprint import FingerprintRotator


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", "ignore").decode("gbk"))


# ------------------------------------------------------------------
# 配置常量
# ------------------------------------------------------------------
KEYWORD_GBK = quote("女装", encoding="gbk")
BASE_URL = (
    "https://s.1688.com/selloffer/offer_search.htm"
    f"?keywords={KEYWORD_GBK}"
    "&sortType=price_sort-asc"
)
MAX_PAGES = 5
SAMPLE_SIZE = 5
OUTPUT_DIR = Path("data/reports/1688_nvzhuang_5_retry")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_all_items: list = []
_enriched_items: list = []
_skip_count: int = 0
_profile_dir: str = "data/chrome_profile_1688"


def _profile_needs_rotate() -> bool:
    """判断当前固定 Profile 是否存在（若不存在说明已被轮换过）."""
    return Path(_profile_dir).exists()


async def _create_browser(user_data_dir: str) -> StealthBrowser:
    """创建 StealthBrowser 实例（固定 Profile 模式）."""
    return await StealthBrowser(
        headless=False,
        use_system_chrome=True,
        user_data_dir=user_data_dir,
        auto_handle_login=True,
        auth_storage_dir="data/auth",
        auto_login_timeout=60.0,
        rotate_fingerprint=False,
        proxy="http://127.0.0.1:7890",
    ).start()


async def _rotate_profile(ctx: TaskContext) -> StealthBrowser:
    """动态轮换：删除旧固定 Profile，生成全新 Profile 并重启浏览器+预热."""
    global _profile_dir
    old_browser: StealthBrowser = ctx.browser_state["browser"]
    await old_browser.close()

    # 删除旧固定 Profile
    if Path(_profile_dir).exists():
        shutil.rmtree(_profile_dir, ignore_errors=True)
        _safe_print(f"  [Rotate] 旧 Profile 疑似被标记，已删除: {_profile_dir}")

    # 生成全新临时 Profile 作为新的固定 Profile
    fp = FingerprintRotator()
    _profile_dir = fp.user_data_dir
    _safe_print(f"  [Rotate] 启用全新 Profile: {_profile_dir}")

    browser = await _create_browser(_profile_dir)
    ctx.browser_state["browser"] = browser

    # 新 Profile 必须先预热首页，否则直接搜索极易被拦截
    _safe_print("  [Rotate] 新 Profile 预热中...")
    await browser.goto("https://www.1688.com", wait_until="domcontentloaded", timeout=20000)
    await asyncio.sleep(random.uniform(3.0, 5.0))
    if not (await is_login_page(browser.page) or await is_captcha_page(browser.page)):
        await browser.simulate_human_viewing()
        _safe_print("  [Rotate] 预热完成")
    else:
        _safe_print("  [Rotate] 预热触发验证/登录，等待手动处理...")
        await asyncio.sleep(5)

    return browser


def _is_bad_url(url: str) -> bool:
    """检查当前 URL 是否为登录/验证/惩罚页."""
    lower = url.lower()
    bad = ["login", "signin", "passport", "auth", "logon", "punish", "identity", "verify", "captcha", "member.jump"]
    return any(sig in lower for sig in bad)


async def _is_normal_page(browser: StealthBrowser) -> bool:
    """页面健康检查：只有确认是正常商品详情页才返回 True."""
    url = browser.page.url
    if _is_bad_url(url):
        return False
    if await is_login_page(browser.page):
        return False
    if await is_captcha_page(browser.page):
        return False
    # 二次兜底：检测 body 文本中的异常关键词
    try:
        body_text = await browser.page.evaluate(
            "() => document.body ? document.body.innerText.substring(0, 2000) : ''"
        )
        body_lower = body_text.lower()
        bad_texts = ["拖动下方滑块", "完成验证", "亲，请拖动", "安全验证", "身份验证"]
        if any(bt in body_lower for bt in bad_texts):
            return False
    except Exception:
        pass
    # 检查是否存在商品详情页的核心元素（使用更宽的选择器兼容 1688 PC/H5 多种布局）
    try:
        has_core = await browser.page.evaluate(
            """() => !!document.querySelector(
                'h1, .d-title, .offer-title, .detail-title, .product-title, '
                + '#mod-detail, .detail-content, .description, .props-list, .offer-attr-list'
            )"""
        )
        return bool(has_core)
    except Exception:
        return False


async def _goto_search_page_with_recovery(
    browser: StealthBrowser,
    url: str,
    selector: str = ".search-offer-item, .offer-item",
    max_attempts: int = 3,
) -> bool:
    """访问搜索结果页，并在遇到验证码/惩罚页时尝试自动恢复."""
    for attempt in range(1, max_attempts + 1):
        await browser.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(random.uniform(2.0, 4.0))

        blocked = (
            _is_bad_url(browser.page.url)
            or await is_login_page(browser.page)
            or await is_captcha_page(browser.page)
        )
        if blocked:
            _safe_print(f"  [Recover] 第 {attempt} 次命中验证/惩罚页，尝试自动过滑块...")
            solved = await browser.try_solve_slider()
            await asyncio.sleep(random.uniform(2.0, 4.0))
            blocked = (
                _is_bad_url(browser.page.url)
                or await is_login_page(browser.page)
                or await is_captcha_page(browser.page)
            )
            if solved and not blocked:
                _safe_print("  [Recover] 滑块疑似通过，继续检查结果页。")
            elif blocked:
                _safe_print("  [Recover] 自动处理后仍被拦截。")

        if not blocked:
            try:
                await browser.wait_for_selector(selector, timeout=15000)
                return True
            except Exception:
                pass

        if attempt < max_attempts:
            await browser.cooldown(6.0, 10.0)

    return False


# ------------------------------------------------------------------
# Step 0: 预热——先访问 1688 首页建立真实浏览会话，降低风控概率
# ------------------------------------------------------------------
async def step_warmup(ctx: TaskContext):
    browser: StealthBrowser = ctx.browser_state["browser"]
    _safe_print("[Step 0] 预热：访问 1688 首页...")
    await browser.goto("https://www.1688.com", wait_until="domcontentloaded", timeout=20000)
    await asyncio.sleep(random.uniform(3.0, 5.0))

    # 若被拦截（登录/验证码），auto_handle_login 会自动弹窗等待用户处理
    if await is_login_page(browser.page) or await is_captcha_page(browser.page):
        _safe_print("[Step 0] 首页触发验证/登录，先尝试自动过滑块...")
        solved = await browser.try_solve_slider()
        await asyncio.sleep(random.uniform(2.0, 4.0))
        if solved and not (await is_login_page(browser.page) or await is_captcha_page(browser.page)):
            _safe_print("[Step 0] 自动验证通过，继续执行。")
        else:
            _safe_print("[Step 0] 自动处理未完全通过，等待手动处理...")
            # 给 auto_handle_login 留出处理时间（它会自己轮询），这里简单多等一会儿
            await asyncio.sleep(5)
    else:
        await browser.simulate_human_viewing()
        _safe_print("[Step 0] 预热完成")

    return {"success": True, "url": browser.page.url}


# ------------------------------------------------------------------
# Step 1: 访问搜索页
# ------------------------------------------------------------------
async def step_search(ctx: TaskContext):
    browser: StealthBrowser = ctx.browser_state["browser"]
    url = f"{BASE_URL}&beginPage=1"
    _safe_print(f"[Step 1] 访问搜索页: {url}")
    ok = await _goto_search_page_with_recovery(browser, url)
    if not ok:
        raise RuntimeError("1688 搜索结果页加载失败或仍被风控拦截")
    await browser.simulate_human_viewing()
    return {"success": True, "url": browser.page.url}


# ------------------------------------------------------------------
# Step 2: 翻页抓取列表
# ------------------------------------------------------------------
async def step_scrape_pages(ctx: TaskContext):
    global _all_items
    browser: StealthBrowser = ctx.browser_state["browser"]

    actual_pages = 0
    for page_num in range(1, MAX_PAGES + 1):
        url = f"{BASE_URL}&beginPage={page_num}"
        if browser.page.url != url:
            _safe_print(f"[Step 2] 翻页 -> {url}")
            ok = await _goto_search_page_with_recovery(browser, url)
            if not ok:
                raise RuntimeError(f"第 {page_num} 页结果加载失败或仍被风控拦截")
            # 若被重定向（如超出总页数），提前结束
            if f"beginPage={page_num}" not in browser.page.url:
                _safe_print(f"  检测到重定向，实际已到达最后一页，提前结束翻页。")
                break

        await asyncio.sleep(1.5)
        items = await browser.page.evaluate(
            """
            () => {
                const results = [];
                document.querySelectorAll('.search-offer-item, .offer-item').forEach((card, i) => {
                    if (i >= 20) return;
                    // 标题提取：多重 fallback，避免命中"找相似"等按钮文字
                    let title = '';
                    const titleSelectors = [
                        '.offer-title-row .title-text',
                        '.offer-title-row [title]',
                        '.title a:not(.find-similar):not([title*="找相似"])',
                        'a[title]:not(.find-similar)',
                        '.main-img img[alt]',
                        'img[alt]'
                    ];
                    for (const sel of titleSelectors) {
                        const el = card.querySelector(sel);
                        if (el) {
                            const candidate = (el.getAttribute('title') || el.innerText || el.getAttribute('alt') || '').trim();
                            if (candidate && candidate !== '找相似' && !candidate.includes('找相似')) {
                                title = candidate;
                                break;
                            }
                        }
                    }
                    const priceEl = card.querySelector('.offer-price-row .price-item, .text-main, .price');
                    const imgEl   = card.querySelector('.main-img img, img');
                    const shopEl  = card.querySelector('.company-name, .shop-name, .offer-company');
                    // 1688 链接提取优先级：1) 卡片自身 href  2) data-renderkey 解析 offerId  3) data-offerid  4) 内部 a 标签
                    let link = (card.getAttribute('href') || '').trim();
                    let offerId = '';
                    if (!link) {
                        const renderKey = card.getAttribute('data-renderkey') || '';
                        const m = renderKey.match(/_(\\d+)$/);
                        if (m) offerId = m[1];
                    }
                    if (!link && !offerId) {
                        offerId = card.getAttribute('data-offerid') || card.getAttribute('offerid') || '';
                    }
                    if (!link && offerId) {
                        link = 'http://detail.m.1688.com/page/index.html?offerId=' + offerId;
                    }
                    if (!link) {
                        let linkEl = null;
                        card.querySelectorAll('a').forEach(a => {
                            const href = a.href || '';
                            if (!linkEl && (href.includes('/offer/') || href.includes('detail.'))) {
                                linkEl = a;
                            }
                        });
                        if (!linkEl) linkEl = card.querySelector('a');
                        link = linkEl ? linkEl.href : '';
                    }
                    // 如果标题仍为空，尝试用图片 alt 兜底
                    if ((!title || title === '找相似') && imgEl) {
                        const altTitle = (imgEl.getAttribute('alt') || '').trim();
                        if (altTitle && altTitle !== '找相似') title = altTitle;
                    }
                    const priceText = priceEl ? priceEl.innerText.trim() : '';
                    const numMatch = priceText.match(/\\d+(?:\\.\\d+)?/);
                    results.push({
                        title: title,
                        price_text: priceText,
                        price_num: numMatch ? parseFloat(numMatch[0]) : null,
                        image: imgEl ? (imgEl.getAttribute('data-src') || imgEl.getAttribute('src') || '') : '',
                        link: link,
                        shop_name: shopEl ? shopEl.innerText.trim() : '',
                    });
                });
                return results;
            }
            """
        )
        # 只保留有标题且链接为商品详情页的条目（过滤掉店铺首页等无效链接）
        valid = [it for it in items if it.get("title") and ("/offer/" in it.get("link", "") or "detail." in it.get("link", ""))]
        _safe_print(f"  Page {page_num}: {len(valid)} items")
        _all_items.extend(valid)
        actual_pages += 1

        if page_num < MAX_PAGES:
            await browser.simulate_human_viewing()
            await browser.throttle_request(8.0, 15.0)

    _safe_print(f"[Step 2] 列表抓取完成，总计 {len(_all_items)} 条（实际翻页 {actual_pages} / {MAX_PAGES}）")
    return {"success": True, "total": len(_all_items), "pages": actual_pages}


# ------------------------------------------------------------------
# Step 3: 抽样进入详情页获取深度信息
# ------------------------------------------------------------------
async def step_enrich_details(ctx: TaskContext):
    global _enriched_items, _skip_count
    browser: StealthBrowser = ctx.browser_state["browser"]

    # 取价格最低的前 SAMPLE_SIZE 个，且按 link 去重
    sorted_items = sorted(_all_items, key=lambda x: (x["price_num"] is None, x["price_num"]))
    seen_links = set()
    sample = []
    for it in sorted_items:
        link = it.get("link", "")
        if link and link not in seen_links:
            seen_links.add(link)
            sample.append(it)
        if len(sample) >= SAMPLE_SIZE:
            break

    _safe_print(f"[Step 3] 进入 {len(sample)} 个详情页提取深度信息...")
    consecutive_skip = 0
    for idx, item in enumerate(sample, 1):
        detail_url = item.get("link")
        if not detail_url:
            continue

        _safe_print(f"  [{idx}/{len(sample)}] {detail_url}")
        try:
            await browser.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # 页面健康检查：只有正常详情页才提取+截图
            if not await _is_normal_page(browser):
                _safe_print(f"    ⚠️ 页面非正常详情页（登录/验证/无内容），跳过")
                item["detail_error"] = "page_not_normal"
                _enriched_items.append(item)
                _skip_count += 1
                consecutive_skip += 1
                if consecutive_skip >= 2:
                    _safe_print("    连续 2 个详情页被拦截，判断 Profile 可能已被标记，启动动态轮换...")
                    browser = await _rotate_profile(ctx)
                    consecutive_skip = 0
                continue
            consecutive_skip = 0

            await browser.simulate_human_viewing()

            detail = await browser.page.evaluate(
                """
                () => {
                    const shop = document.querySelector('.company-name, .shop-name, [data-spm="seller"], .s-companyName, .company-title');
                    const location = document.querySelector('.location, .address, .region');
                    const model = document.querySelector('.business-model, .business-type');
                    const params = [];
                    const propSelectors = [
                        '.props-list tr', '.props-list .prop-item',
                        '.offer-attr-item', '.props-item',
                        '#mod-detail .obj-leading', '.prop-item',
                        '#product table tr', '.region-screen-product table tr',
                        'table tr'
                    ];
                    for (const sel of propSelectors) {
                        const els = document.querySelectorAll(sel);
                        if (els.length) {
                            els.forEach(el => {
                                const text = (el.innerText || '').trim();
                                if (text && text.length < 100 && text.length > 0) params.push(text);
                            });
                            if (params.length) break;
                        }
                    }
                    const detailImgs = [];
                    const imgSelectors = [
                        '.detail-content img', '.description img',
                        '#desc-lazyload-container img', '.offer-desc-wrapper img', '.detail-img img',
                        '#content img', '#screen img', '#product img'
                    ];
                    for (const sel of imgSelectors) {
                        const els = document.querySelectorAll(sel);
                        if (els.length) {
                            els.forEach(img => { if (img.src) detailImgs.push(img.src); });
                            if (detailImgs.length) break;
                        }
                    }
                    return {
                        shop_name: shop ? shop.innerText.trim() : '',
                        location: location ? location.innerText.trim() : '',
                        business_model: model ? model.innerText.trim() : '',
                        params: params.slice(0, 20),
                        detail_images: detailImgs,
                    };
                }
                """
            )

            # 截图
            shot_path = OUTPUT_DIR / f"detail_{idx:03d}.png"
            await browser.screenshot(path=str(shot_path))

            item["detail"] = detail
            item["screenshot"] = shot_path.name
            _enriched_items.append(item)
        except Exception as exc:
            _safe_print(f"    ⚠️ 详情页异常: {exc}")
            item["detail_error"] = str(exc)
            _enriched_items.append(item)
            _skip_count += 1
            consecutive_skip += 1
            if consecutive_skip >= 2:
                _safe_print("    连续 2 个详情页异常，判断 Profile 可能已被标记，启动动态轮换...")
                browser = await _rotate_profile(ctx)
                consecutive_skip = 0
            continue

        if idx < len(sample):
            await browser.cooldown(20.0, 30.0)

    success_count = len(_enriched_items) - _skip_count
    _safe_print(f"[Step 3] 详情增强完成，成功 {success_count} / {len(sample)}，跳过 {_skip_count}")
    return {"success": True, "sample_size": len(_enriched_items)}


# ------------------------------------------------------------------
# Step 4: 生成报告
# ------------------------------------------------------------------
async def step_generate_report(ctx: TaskContext):
    _safe_print("[Step 4] 生成报告...")

    report_data = {
        "keyword": "女装",
        "site": "1688",
        "total_items": len(_all_items),
        "sample_size": len(_enriched_items),
        "skip_count": _skip_count,
        "all_items": _all_items,
        "items": _enriched_items,
        "generated_at": __import__('datetime').datetime.now().isoformat(),
    }

    # JSON 数据备份
    json_path = OUTPUT_DIR / "report_data.json"
    json_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 如果配置了 report_template_path，渲染 HTML
    report_template = "D:/AI/AI_RPA/src/omniauto/templates/reports/ecom_report.html.j2"
    html_path = OUTPUT_DIR / "report.html"
    if report_template and Path(report_template).exists():
        from jinja2 import Template
        tpl = Template(Path(report_template).read_text(encoding="utf-8"))
        html = tpl.render(**report_data)
        html_path.write_text(html, encoding="utf-8")
    else:
        # fallback 简单 HTML
        lines = [
            "<html><head><meta charset='utf-8'><title>Report</title></head><body>",
            f"<h1>女装 — 1688 调研报告</h1>",
            f"<p>总商品数: {len(_all_items)} | 抽样详情数: {len(_enriched_items)} | 跳过: {_skip_count}</p>",
            "<table border='1' cellpadding='6'><tr><th>标题</th><th>价格</th><th>店铺</th></tr>",
        ]
        for it in _enriched_items:
            lines.append(f"<tr><td>{it['title']}</td><td>{it['price_text']}</td><td>{it.get('shop_name','')}</td></tr>")
        lines.append("</table></body></html>")
        html_path.write_text("\n".join(lines), encoding="utf-8")

    _safe_print(f"  报告已保存: {html_path}")
    _safe_print(f"  数据已保存: {json_path}")
    return {"success": True, "html_path": str(html_path), "json_path": str(json_path)}


# ------------------------------------------------------------------
# 组装 Workflow
# ------------------------------------------------------------------
workflow = Workflow(
    task_id="1688_nvzhuang_5_retry",
    steps=[
        AtomicStep("s0_warmup", step_warmup, lambda r: r.get("success"), retry=2, description="1688 首页预热"),
        AtomicStep("s1_search", step_search, lambda r: r.get("success"), retry=3, description="访问 1688 搜索页"),
        AtomicStep("s2_scrape", step_scrape_pages, lambda r: 1 <= r.get("pages", 0) <= MAX_PAGES, retry=2, description="翻页抓取列表"),
        AtomicStep("s3_enrich", step_enrich_details, lambda r: r.get("sample_size", 0) > 0, retry=2, description="详情页抽样增强"),
        AtomicStep("s4_report", step_generate_report, lambda r: bool(r.get("html_path")), retry=2, description="生成图文报告"),
    ],
    inter_step_delay=(4.0, 7.0),
)


# ------------------------------------------------------------------
# 执行入口
# ------------------------------------------------------------------
async def main():
    browser = await _create_browser(_profile_dir)

    ctx = TaskContext(task_id="1688_nvzhuang_5_retry", browser_state={"browser": browser})
    final_state = await workflow.run(context=ctx)
    _safe_print(f"Workflow finished: {final_state.name}")
    await ctx.browser_state["browser"].close()


if __name__ == "__main__":
    asyncio.run(main())