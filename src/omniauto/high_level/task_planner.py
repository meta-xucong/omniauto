"""基于 Smolagents 的任务规划器.

将自然语言描述拆解为 AtomicStep 配置列表.
"""

from typing import Any, List

from ..utils.logger import get_logger

logger = get_logger("omniauto.task_planner")


class TaskPlanner:
    """任务规划器：将用户需求转换为可执行步骤配置."""

    def __init__(self, model: Any = None) -> None:
        self.model = model

    def plan(self, description: str) -> List[dict]:
        """基于规则 + 简单 LLM 规划任务步骤.

        当前版本提供基于关键词的规则解析，后续可扩展为 LLM 驱动.
        """
        steps = []
        desc = description.lower()

        import re

        # 1. 提取 URL 并生成导航步骤
        urls = re.findall(r'https?://[^\s\u3002\uff0c]+', description)
        if urls:
            steps.append({"type": "navigate", "url": urls[0]})
        elif any(k in desc for k in ("百度", "淘宝", "京东", "打开浏览器", "登录", "访问")):
            # 常见站点兜底
            if "百度" in desc:
                steps.append({"type": "navigate", "url": "https://www.baidu.com"})
            elif "淘宝" in desc:
                steps.append({"type": "navigate", "url": "https://www.taobao.com"})
            elif "京东" in desc:
                steps.append({"type": "navigate", "url": "https://www.jd.com"})

        # 2. 输入操作
        if any(k in desc for k in ("输入", "填写", "搜索")):
            steps.append({"type": "type", "selector": "input", "text": "sample"})

        # 3. 点击操作
        if any(k in desc for k in ("点击", "提交", "登录", "搜索", "确定")):
            steps.append({"type": "click", "selector": "button"})

        # 4. 截图
        if "截图" in desc or "保存" in desc:
            steps.append({"type": "screenshot"})

        # 5. 提取
        if any(k in desc for k in ("提取", "获取", "读取", "抓取")):
            steps.append({"type": "extract_text", "selector": "body"})

        if not steps:
            steps.append({"type": "navigate", "url": "https://example.com"})

        logger.info("task_planned", description=description, step_count=len(steps))
        return steps
