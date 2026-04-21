"""Task planner for converting natural language into deterministic step plans."""

from __future__ import annotations

import re
from typing import Any, List, Optional

from ..utils.logger import get_logger

logger = get_logger("omniauto.task_planner")


WINDOWS_PATH_RE = re.compile(r"([A-Za-z]:[\\/][^\"'\r\n]+?\.(?:json|xlsx))", re.IGNORECASE)


class TaskPlanner:
    """Plan user requests into a small deterministic step list."""

    def __init__(self, model: Any = None) -> None:
        self.model = model

    def plan(self, description: str) -> List[dict]:
        """Return a simple rule-based execution plan."""
        desc_lower = description.lower()

        if self._looks_like_local_excel_report_task(description, desc_lower):
            input_path = self._extract_file_path(description, ".json")
            output_path = self._extract_file_path(description, ".xlsx")
            steps = [
                {"type": "load_json_report", "path": input_path or ""},
                {
                    "type": "build_excel_report",
                    "output_path": output_path or "",
                    "sort_by": "price_num",
                    "sort_order": "asc",
                },
            ]
            logger.info("task_planned", description=description, step_count=len(steps), plan_type="local_excel_report")
            return steps

        steps: List[dict] = []

        urls = re.findall(r"https?://[^\s\u3002\uff0c]+", description)
        if urls:
            steps.append({"type": "navigate", "url": urls[0]})
        elif any(keyword in desc_lower for keyword in ("百度", "淘宝", "京东", "谷歌", "google", "打开浏览器", "登录", "访问")):
            if "百度" in desc_lower:
                steps.append({"type": "navigate", "url": "https://www.baidu.com"})
            elif "淘宝" in desc_lower:
                steps.append({"type": "navigate", "url": "https://www.taobao.com"})
            elif "京东" in desc_lower:
                steps.append({"type": "navigate", "url": "https://www.jd.com"})
            elif "谷歌" in desc_lower or "google" in desc_lower:
                steps.append({"type": "navigate", "url": "https://www.google.com"})

        if any(keyword in desc_lower for keyword in ("输入", "填写", "搜索")):
            steps.append({"type": "type", "selector": "input", "text": "sample"})

        if any(keyword in desc_lower for keyword in ("点击", "提交", "登录", "搜索", "确定")):
            if "google" in desc_lower or "谷歌" in desc_lower:
                steps.append({"type": "hotkey", "keys": ["Enter"]})
            else:
                steps.append({"type": "click", "selector": "button"})

        if "截图" in desc_lower or "保存" in desc_lower:
            steps.append({"type": "screenshot"})

        if any(keyword in desc_lower for keyword in ("提取", "获取", "读取", "抓取")):
            steps.append({"type": "extract_text", "selector": "body"})

        if not steps:
            steps.append({"type": "navigate", "url": "https://example.com"})

        logger.info("task_planned", description=description, step_count=len(steps), plan_type="generic")
        return steps

    def _looks_like_local_excel_report_task(self, description: str, desc_lower: str) -> bool:
        has_json = ".json" in desc_lower or "json" in desc_lower
        has_excel = any(keyword in desc_lower for keyword in ("excel", ".xlsx", "wps", "表格", "报表"))
        return has_json and has_excel

    def _extract_file_path(self, description: str, suffix: str) -> Optional[str]:
        suffix = suffix.lower()
        for match in WINDOWS_PATH_RE.findall(description):
            if match.lower().endswith(suffix):
                return match
        return None
