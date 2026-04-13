"""OmniAuto MCP Server.

基于 mcp.server.fastmcp.FastMCP 实现，为 Kimi Code / Codex / Claude 提供 Tools.
"""

import asyncio
import json
import os
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from .service import OmniAutoService

mcp = FastMCP("omniauto")
service = OmniAutoService()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _text(data: Any) -> list:
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]


# ----------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------
@mcp.tool()
def omni_plan_task(description: str) -> list:
    """根据用户自然语言描述，生成 OmniAuto 原子步骤计划."""
    result = service.plan_task(description)
    return _text(result)


@mcp.tool()
def omni_generate_script(description: str, output_path: str) -> list:
    """根据任务描述生成 OmniAuto 原子脚本."""
    result = service.generate_script(description, output_path)
    return _text(result)


@mcp.tool()
def omni_validate_script(script_path: str) -> list:
    """校验脚本是否包含危险操作或硬编码敏感信息."""
    result = service.validate_script(script_path)
    return _text(result)


@mcp.tool()
async def omni_run_workflow(script_path: str, headless: bool = True, task_id: str = "") -> list:
    """执行 OmniAuto 工作流脚本."""
    result = await service.run_workflow(
        script_path=script_path,
        headless=headless,
        task_id=task_id or None,
    )
    return _text(result)


@mcp.tool()
async def omni_get_screenshot(engine: str = "browser") -> list:
    """获取当前浏览器或桌面截图（base64格式）."""
    result = await service.get_screenshot(engine)
    return _text(result)


@mcp.tool()
def omni_get_task_status(task_id: str) -> list:
    """查询任务当前状态."""
    result = service.get_task_status(task_id)
    return _text(result)


@mcp.tool()
def omni_get_queue() -> list:
    """查看异常和待处理任务队列."""
    result = service.get_queue()
    return _text(result)


@mcp.tool()
def omni_schedule_task(script_path: str, task_name: str, cron_expr: str, headless: bool = True) -> list:
    """创建定时重复执行的自动化任务."""
    result = service.schedule_task(script_path, task_name, cron_expr, headless)
    return _text(result)


@mcp.tool()
def omni_list_scheduled_tasks() -> list:
    """列出所有已注册的定时任务."""
    result = service.list_scheduled_tasks()
    return _text(result)


@mcp.tool()
def omni_list_available_steps() -> list:
    """返回系统支持的所有原子步骤类型及使用说明."""
    result = service.list_available_steps()
    return _text(result)


# ----------------------------------------------------------------------
# Entrypoints
# ----------------------------------------------------------------------
def main() -> None:
    transport = os.environ.get("OMNIAUTO_MCP_TRANSPORT", "stdio")
    if transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
