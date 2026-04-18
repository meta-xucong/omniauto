import pytest
from playwright.async_api import async_playwright

from omniauto.recovery.manager import BrowserRecoveryManager


AGREEMENT_TEXT = "\u5df2\u9605\u8bfb\u5e76\u540c\u610f\u670d\u52a1\u534f\u8bae\u53ca\u9690\u79c1\u4fdd\u62a4"
SEND_SMS_TEXT = "\u53d1\u9001\u9a8c\u8bc1\u7801"
RECOVERY_ERROR_TEXT = "\u9a8c\u8bc1\u7801\u8f93\u5165\u6846\u672a\u51fa\u73b0"


HTML = """
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>recovery smoke</title>
  </head>
  <body>
    <div id="agreement-panel">
      <label for="agree">""" + AGREEMENT_TEXT + """</label>
      <input id="agree" type="checkbox" />
      <button id="send">""" + SEND_SMS_TEXT + """</button>
      <div id="status">idle</div>
    </div>
    <script>
      document.getElementById("send").addEventListener("click", () => {
        const agreed = document.getElementById("agree").checked;
        document.getElementById("status").textContent = agreed ? "sent" : "blocked";
      });
    </script>
  </body>
</html>
"""


@pytest.mark.asyncio
async def test_browser_recovery_manager_clears_agreement_blocker():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(HTML)

        manager = BrowserRecoveryManager(page_getter=lambda: page)
        result = await manager.recover(
            trigger="error_click",
            error=RECOVERY_ERROR_TEXT,
            step_id="send_sms",
        )

        status_text = await page.locator("#status").text_content()
        checkbox_state = await page.locator("#agree").is_checked()

        await browser.close()

    assert result.handled is True
    assert "agreement_checkbox_required" in result.matched_rules
    assert checkbox_state is True
    assert status_text == "sent"
