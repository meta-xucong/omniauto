"""OmniAuto 核心业务服务封装.

将 CLI 中的核心逻辑解耦为可复用的 Service 层，供 MCP Server 和 FastAPI 调用.
"""

import asyncio
import base64
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .core.state_machine import StateStore, Workflow, TaskState
from .core.context import TaskContext
from .engines.browser import StealthBrowser
from .orchestration.generator import ScriptGenerator
from .orchestration.validator import ScriptValidator
from .orchestration.guardian import GuardianNode
from .utils.logger import get_logger
from .high_level.task_planner import TaskPlanner

logger = get_logger("omniauto.service")


class OmniAutoService:
    """OmniAuto 统一服务入口."""

    def __init__(self, state_store: Optional[StateStore] = None) -> None:
        self.store = state_store or StateStore()
        self.generator = ScriptGenerator()
        self.validator = ScriptValidator()
        self.planner = TaskPlanner()
        self._active_browser: Optional[StealthBrowser] = None

    # ------------------------------------------------------------------
    # 1. 任务规划
    # ------------------------------------------------------------------
    def plan_task(self, description: str) -> Dict[str, Any]:
        steps = self.planner.plan(description)
        needs_guardian = any(
            s.get("type") in ("click", "type") for s in steps
        )
        return {
            "plan_id": f"plan_{hash(description) & 0xFFFFFFFF}",
            "steps": steps,
            "estimated_risk": "low" if not needs_guardian else "medium",
            "needs_guardian": needs_guardian,
        }

    # ------------------------------------------------------------------
    # 2. 脚本生成
    # ------------------------------------------------------------------
    def generate_script(self, description: str, output_path: str) -> Dict[str, Any]:
        path = self.generator.generate(description, output_path)
        lines = Path(path).read_text(encoding="utf-8").count("\n") + 1
        return {
            "script_path": path,
            "generated_at": str(Path(path).stat().st_mtime),
            "lines_of_code": lines,
        }

    # ------------------------------------------------------------------
    # 3. 脚本校验
    # ------------------------------------------------------------------
    def validate_script(self, script_path: str) -> Dict[str, Any]:
        ok = self.validator.validate(script_path)
        return {
            "valid": ok,
            "issues": self.validator.issues,
            "report": self.validator.report()
                .replace("✅", "[OK]")
                .replace("❌", "[ERR]"),
        }

    # ------------------------------------------------------------------
    # 4. 工作流执行
    # ------------------------------------------------------------------
    async def run_workflow(
        self,
        script_path: str,
        headless: bool = True,
        task_id: Optional[str] = None,
        guardian_callback=None,
    ) -> Dict[str, Any]:
        script_path_resolved = str(Path(script_path).resolve())
        if not Path(script_path_resolved).exists():
            raise FileNotFoundError(f"脚本不存在: {script_path}")

        # 安全校验
        validation = self.validate_script(script_path_resolved)
        if not validation["valid"]:
            return {
                "task_id": task_id or "",
                "final_state": "VALIDATION_FAILED",
                "outputs": {},
                "validation_report": validation["report"],
                "duration_seconds": 0.0,
            }

        # 动态加载脚本模块
        import importlib.util
        spec = importlib.util.spec_from_file_location("atomic_script", script_path_resolved)
        module = importlib.util.module_from_spec(spec)
        sys.modules["atomic_script"] = module
        spec.loader.exec_module(module)

        if not hasattr(module, "workflow"):
            raise RuntimeError("脚本中未找到 'workflow' 变量")

        workflow: Workflow = module.workflow
        if task_id:
            workflow.task_id = task_id

        # 启动浏览器
        browser = await StealthBrowser(headless=headless).start()
        self._active_browser = browser
        context = TaskContext(task_id=workflow.task_id, browser_state={"browser": browser})

        guardian = GuardianNode(callback=guardian_callback)
        start = asyncio.get_event_loop().time()

        try:
            final_state = await workflow.run(
                context=context,
                guardian_callback=guardian.check,
            )
            duration = asyncio.get_event_loop().time() - start
            logger.info(
                "workflow_finished",
                task_id=workflow.task_id,
                state=final_state.name,
            )
            return {
                "task_id": workflow.task_id,
                "final_state": final_state.name,
                "outputs": context.outputs,
                "duration_seconds": round(duration, 2),
            }
        except Exception as exc:
            duration = asyncio.get_event_loop().time() - start
            logger.error("workflow_error", task_id=workflow.task_id, error=str(exc))
            return {
                "task_id": workflow.task_id,
                "final_state": "ERROR",
                "outputs": context.outputs,
                "error": str(exc),
                "duration_seconds": round(duration, 2),
            }
        finally:
            await browser.close()
            self._active_browser = None

    # ------------------------------------------------------------------
    # 5. 截图
    # ------------------------------------------------------------------
    async def get_screenshot(self, engine: str = "browser") -> Dict[str, Any]:
        if engine == "browser":
            if self._active_browser is None:
                return {
                    "image_base64": "",
                    "format": "png",
                    "timestamp": "",
                    "error": "浏览器未启动，请先执行工作流",
                }
            path = await self._active_browser.screenshot()
        else:
            from .engines.visual import VisualEngine
            vis = VisualEngine().start()
            path = vis.screenshot()

        data = Path(path).read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")
        return {
            "image_base64": b64,
            "format": "png",
            "timestamp": str(Path(path).stat().st_mtime),
        }

    # ------------------------------------------------------------------
    # 6. 任务状态查询
    # ------------------------------------------------------------------
    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        info = self.store.load_workflow(task_id)
        if info is None:
            return {"task_id": task_id, "state": "NOT_FOUND", "current_step": 0, "outputs": {}, "error": ""}
        return {
            "task_id": task_id,
            "state": info["state"].name,
            "current_step": info["current_step"],
            "outputs": info.get("outputs", {}),
            "error": "",
        }

    # ------------------------------------------------------------------
    # 7. 异常队列
    # ------------------------------------------------------------------
    def get_queue(self) -> Dict[str, Any]:
        import sqlite3
        conn = sqlite3.connect(self.store.db_path)
        rows = conn.execute(
            "SELECT task_id, state, current_step, updated_at FROM workflow_state WHERE state IN ('PAUSED', 'ESCALATED', 'FAILED') ORDER BY updated_at DESC"
        ).fetchall()
        conn.close()
        return {
            "pending_tasks": [
                {
                    "task_id": row[0],
                    "state": row[1],
                    "current_step": row[2],
                    "updated_at": row[3],
                }
                for row in rows
            ]
        }

    # ------------------------------------------------------------------
    # 8. 定时任务
    # ------------------------------------------------------------------
    def schedule_task(
        self,
        script_path: str,
        task_name: str,
        cron_expr: str,
        headless: bool = True,
    ) -> Dict[str, Any]:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError as exc:
            raise RuntimeError("请安装 APScheduler: uv add apscheduler") from exc

        # 使用模块级单例调度器（简化版）
        sched = _ensure_scheduler()
        job_id = f"sch_{task_name}"

        async def _job():
            await self.run_workflow(script_path, headless=headless, task_id=f"{task_name}_{asyncio.get_event_loop().time()}")

        # APScheduler 默认不直接支持 async，用 asyncio.run 包装
        def _sync_job():
            try:
                asyncio.get_running_loop().create_task(_job())
            except RuntimeError:
                asyncio.run(_job())

        trigger = CronTrigger.from_crontab(cron_expr)
        job = sched.add_job(_sync_job, trigger=trigger, id=job_id, replace_existing=True)
        return {
            "schedule_id": job.id,
            "task_name": task_name,
            "cron_expr": cron_expr,
            "next_run": str(job.next_run_time) if job.next_run_time else "",
        }

    def list_scheduled_tasks(self) -> Dict[str, Any]:
        sched = _ensure_scheduler()
        return {
            "schedules": [
                {
                    "schedule_id": j.id,
                    "task_name": j.id.replace("sch_", ""),
                    "cron_expr": str(j.trigger),
                    "active": j.next_run_time is not None,
                }
                for j in sched.get_jobs()
            ]
        }

    # ------------------------------------------------------------------
    # 9. 步骤列表
    # ------------------------------------------------------------------
    def list_available_steps(self) -> Dict[str, Any]:
        return {
            "steps": [
                {"name": "NavigateStep", "params": ["url"], "description": "导航到指定URL"},
                {"name": "ClickStep", "params": ["selector"], "description": "点击CSS选择器匹配的元素"},
                {"name": "TypeStep", "params": ["selector", "text"], "description": "在输入框中模拟人类打字输入"},
                {"name": "ExtractTextStep", "params": ["selector"], "description": "提取元素的文本内容"},
                {"name": "ExtractAttributeStep", "params": ["selector", "attribute"], "description": "提取元素的指定属性值"},
                {"name": "ScreenshotStep", "params": ["output_dir"], "description": "截取当前页面或桌面截图"},
                {"name": "WaitStep", "params": ["seconds"], "description": "固定等待指定秒数"},
                {"name": "ScrollToBottomStep", "params": [], "description": "滚动到页面底部"},
                {"name": "HotkeyStep", "params": ["*keys"], "description": "按下浏览器热键组合"},
                {"name": "VisualClickStep", "params": ["image_path"], "description": "基于图像识别在桌面点击"},
            ]
        }


# ----------------------------------------------------------------------
# APScheduler 单例
# ----------------------------------------------------------------------
_scheduler = None


def _ensure_scheduler():
    global _scheduler
    if _scheduler is None:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler()
        _scheduler.start()
    return _scheduler
