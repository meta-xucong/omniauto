"""Low-disturbance ecommerce research workflow for 1688 sepuzhu."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from urllib.parse import quote

from omniauto.core.context import TaskContext
from omniauto.core.state_machine import AtomicStep, Workflow


REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_SCRIPT_PATH = REPO_ROOT / "workflows" / "generated" / "marketplaces" / "1688_single_rocking_chair_5.py"
MODULE_NAME = "marketplaces_1688_base_single_rocking_chair_sepuzhu"


def _load_base_module():
    spec = importlib.util.spec_from_file_location(MODULE_NAME, BASE_SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load base workflow: {BASE_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


base = _load_base_module()

base.KEYWORD = "\u8272\u8c31\u67f1"
base.TASK_NAME = "1688_sepuzhu_3"
base.KEYWORD_GBK = quote(base.KEYWORD, encoding="gbk")
base.BASE_URL = (
    "https://s.1688.com/selloffer/offer_search.htm"
    f"?keywords={base.KEYWORD_GBK}"
    "&sortType=price_sort-asc"
)
base.MAX_PAGES = 3
base.LIST_PAGE_LIMIT = 30
base.DETAIL_SAMPLE_SIZE = 27
base.OUTPUT_DIR = Path("runtime/data/reports/1688_sepuzhu_3")
base.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
base.ARTIFACT_DIR = base.OUTPUT_DIR / "browser_artifacts"
base.ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
base.STATUS_PATH = base.OUTPUT_DIR / "run_status.json"
base.HANDOFF_PATH = base.OUTPUT_DIR / "manual_handoff.json"
base.MANUAL_BROWSER_LAUNCH_PATH = base.OUTPUT_DIR / "manual_browser_launch.json"
base._all_items = []
base._top_cheapest = []
base._enriched_items = []
base._skip_count = 0

requires_browser = True

workflow = Workflow(
    task_id=base.TASK_NAME,
    steps=[
        AtomicStep("s0_warmup", base.step_warmup, lambda r: r.get("success"), retry=0, description="site warmup"),
        AtomicStep("s1_search", base.step_search, lambda r: r.get("success"), retry=0, description="open search page"),
        AtomicStep("s2_scrape", base.step_scrape_pages, lambda r: r.get("success"), retry=0, description="scrape list pages"),
        AtomicStep("s3_enrich", base.step_enrich_details, lambda r: r.get("success"), retry=0, description="enrich detail pages"),
        AtomicStep("s4_report", base.step_generate_report, lambda r: bool(r.get("json_path")) and bool(r.get("html_path")), retry=0, description="generate report"),
    ],
    inter_step_delay=(4.0, 7.0),
)


async def main():
    start_url = f"{base.BASE_URL}&beginPage=1"
    if base.BROWSER_CONNECT_MODE == "cdp_attach":
        playwright_profile_dir = f"cdp://127.0.0.1:{base.BROWSER_CDP_PORT}"
        browser = await base._create_browser(base.BROWSER_PROFILE_DIR, start_url=start_url)
    else:
        playwright_profile_dir = base._prepare_playwright_profile(base.BROWSER_PROFILE_DIR)
        browser = await base._create_browser(playwright_profile_dir, start_url=start_url)
    ctx = TaskContext(task_id=base.TASK_NAME, browser_state={"browser": browser})
    final_state = None
    try:
        final_state = await workflow.run(context=ctx)
        reason = ctx.metadata.get("stopped_reason")
        status_state = "completed"
        if final_state is not None and final_state.name == "ESCALATED" and base._looks_like_verification_stop(reason):
            status_state = "manual_handoff_ready"
        base._write_status(
            status_state,
            final_state=final_state.name,
            outputs=list(ctx.outputs.keys()),
            stopped_reason=reason,
            browser_profile_dir=base.BROWSER_PROFILE_DIR,
            playwright_profile_dir=playwright_profile_dir,
            seeded_cookie_count=ctx.metadata.get("seeded_cookie_count", 0),
        )
        base._safe_print(f"Workflow finished: {final_state.name}")
    except Exception as exc:
        base._write_status(
            "error",
            final_state="ERROR",
            error=str(exc),
            stopped_reason=ctx.metadata.get("stopped_reason"),
            browser_profile_dir=base.BROWSER_PROFILE_DIR,
            playwright_profile_dir=playwright_profile_dir,
            seeded_cookie_count=ctx.metadata.get("seeded_cookie_count", 0),
        )
        raise
    finally:
        handoff_reason = ctx.metadata.get("stopped_reason")
        handoff_url = (
            ctx.metadata.get("manual_handoff_target_url")
            or ctx.metadata.get("manual_handoff_url")
            or (browser.page.url if browser.page else "")
        )
        await ctx.browser_state["browser"].close()
        if base._looks_like_verification_stop(handoff_reason):
            payload = base._launch_external_manual_browser(handoff_url, base.BROWSER_PROFILE_DIR, handoff_reason)
            if payload:
                base._write_status(
                    "manual_browser_launched",
                    final_state=final_state.name if final_state is not None else "UNKNOWN",
                    stopped_reason=handoff_reason,
                    manual_browser_url=payload.get("url"),
                    manual_browser_user_data_dir=payload.get("user_data_dir"),
                    browser_profile_dir=base.BROWSER_PROFILE_DIR,
                    playwright_profile_dir=playwright_profile_dir,
                    seeded_cookie_count=ctx.metadata.get("seeded_cookie_count", 0),
                )


if __name__ == "__main__":
    asyncio.run(main())
