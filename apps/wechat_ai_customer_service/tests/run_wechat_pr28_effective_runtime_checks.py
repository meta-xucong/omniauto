from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]


def _run_pr_suite(module_name: str) -> dict[str, Any]:
    code = (
        "import os; "
        "from apps.wechat_ai_customer_service.adapters import wechat_win32_ocr_sidecar as sidecar; "
        "original=sidecar.env_flag; "
        "sidecar.env_flag=lambda name,*,default: "
        "(True if name=='WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN' and name not in os.environ "
        "else original(name,default=default)); "
        f"import {module_name} as suite; "
        "raise SystemExit(suite.main())"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    lines = [line.strip() for line in str(completed.stdout or "").splitlines() if line.strip()]
    return {
        "ok": completed.returncode == 0,
        "module": module_name,
        "returncode": int(completed.returncode),
        "summary": lines[-1] if lines else "",
        "stderr_tail": str(completed.stderr or "").strip()[-1000:],
    }


def main() -> int:
    results = [
        _run_pr_suite(
            "apps.wechat_ai_customer_service.tests.run_wechat_win32_ocr_compat_checks"
        ),
        _run_pr_suite(
            "apps.wechat_ai_customer_service.tests.run_wechat_win32_ocr_window_action_planning_checks"
        ),
    ]
    failures = [item for item in results if not item.get("ok")]
    print(
        json.dumps(
            {"ok": not failures, "count": len(results), "failures": failures, "results": results},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
