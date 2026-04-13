"""OmniAuto Agent Runtime.

实现 ReAct 风格的决策循环：观测 -> 思考 -> 行动 -> 反馈.
将用户的自然语言指令自动转化为对 OmniAutoService 的调用链.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .service import OmniAutoService
from .utils.logger import get_logger

logger = get_logger("omniauto.agent_runtime")


@dataclass
class AgentResult:
    """Agent 执行结果."""

    success: bool
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    screenshots: List[str] = field(default_factory=list)


class OmniAutoAgent:
    """OmniAuto 智能体运行时.

    负责把用户自然语言指令自动拆解为：
    plan -> generate -> validate -> run -> (observe -> fix) -> feedback
    """

    def __init__(
        self,
        service: Optional[OmniAutoService] = None,
        max_fix_rounds: int = 3,
        headless: bool = True,
        trust_mode: str = "normal",  # normal | high
    ) -> None:
        self.service = service or OmniAutoService()
        self.max_fix_rounds = max_fix_rounds
        self.headless = headless
        self.trust_mode = trust_mode

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------
    async def process(self, user_text: str) -> AgentResult:
        """处理用户自然语言指令，返回最终结果."""
        logger.info("agent_process_start", user_text=user_text)

        # 1. 意图识别
        intent = self._classify_intent(user_text)

        if intent == "query_status":
            return await self._handle_query(user_text)
        if intent == "schedule":
            return await self._handle_schedule(user_text)
        if intent == "list_schedules":
            return self._handle_list_schedules()
        if intent == "list_steps":
            return self._handle_list_steps()

        # 默认当作一次性任务或修复任务处理
        return await self._handle_task(user_text)

    # ------------------------------------------------------------------
    # 意图分类
    # ------------------------------------------------------------------
    def _classify_intent(self, text: str) -> str:
        t = text.lower()
        if any(k in t for k in ("状态", "结果", "怎么样", "失败了吗", "完成了吗", "队列")):
            return "query_status"
        if any(k in t for k in ("列出定时任务", "有哪些定时", "list scheduled")):
            return "list_schedules"
        if any(k in t for k in ("有哪些步骤", "支持什么操作", "list steps", "list available")):
            return "list_steps"
        if any(k in t for k in ("每天", "每周", "每隔", "schedule", "cron")):
            return "schedule"
        # "定时任务"单独出现时若无创建关键词，则视为查询（已在上面 list_schedules 处理）
        if any(k in t for k in ("创建定时", "新建定时", "添加定时", "安排定时")):
            return "schedule"
        return "task"

    # ------------------------------------------------------------------
    # 任务执行主循环
    # ------------------------------------------------------------------
    async def _handle_task(self, description: str) -> AgentResult:
        # 步骤1: 规划
        plan = self.service.plan_task(description)
        if not plan.get("steps"):
            return AgentResult(success=False, message="无法理解任务，请尝试更具体的描述")

        # 步骤2: 生成脚本
        script_dir = Path("./scripts")
        script_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", description)[:30]
        script_path = str(script_dir / f"agent_{safe_name}.py")
        gen_info = self.service.generate_script(description, script_path)

        # 步骤3: 校验
        validation = self.service.validate_script(script_path)
        if not validation["valid"]:
            return AgentResult(
                success=False,
                message=f"脚本校验未通过: {validation['report']}",
                data={"issues": validation["issues"]},
            )

        # 步骤4: Guardian 预确认（非高信任模式）
        if plan.get("needs_guardian") and self.trust_mode != "high":
            # 在纯 Agent 运行时中，若无人机交互通道，默认放行并记录日志
            logger.warning(
                "guardian_auto_passed",
                description=description,
                reason="AgentRuntime 无交互通道，默认放行",
            )

        # 步骤5: 执行 + 自修复循环
        round_num = 0
        current_script = script_path
        last_result: Optional[Dict[str, Any]] = None
        screenshots: List[str] = []

        while round_num <= self.max_fix_rounds:
            round_num += 1
            result = await self.service.run_workflow(
                script_path=current_script,
                headless=self.headless,
            )
            last_result = result

            if result.get("final_state") == "COMPLETED":
                return AgentResult(
                    success=True,
                    message=f"任务执行成功（共尝试 {round_num} 次）",
                    data=result.get("outputs", {}),
                    screenshots=screenshots,
                )

            # 失败：获取截图和状态
            shot = await self.service.get_screenshot("browser")
            if shot.get("image_base64"):
                screenshots.append(shot["image_base64"])

            # 达到最大修复轮数则退出
            if round_num > self.max_fix_rounds:
                break

            # 尝试自我修复：基于失败原因修改脚本
            fixed_script = await self._fix_script(
                description=description,
                script_path=current_script,
                failure_result=result,
                screenshot_b64=shot.get("image_base64", ""),
            )
            if fixed_script is None:
                break
            current_script = fixed_script
            logger.info("agent_fix_retry", round=round_num, script=current_script)

        # 最终失败反馈
        error_msg = last_result.get("error", "未知错误") if last_result else "执行失败"
        return AgentResult(
            success=False,
            message=f"任务执行失败（已尝试 {round_num} 次）: {error_msg}",
            data=last_result or {},
            screenshots=screenshots,
        )

    # ------------------------------------------------------------------
    # 自修复逻辑（基于规则 + 简单 LLM 预留）
    # ------------------------------------------------------------------
    async def _fix_script(
        self,
        description: str,
        script_path: str,
        failure_result: Dict[str, Any],
        screenshot_b64: str,
    ) -> Optional[str]:
        """分析失败原因并生成修正后的脚本路径."""
        error = failure_result.get("error", "")
        error_lower = error.lower()

        # 规则化修复：超时/元素未找到 -> 增加 WaitStep
        if "timeout" in error_lower or "未找到" in error or "not found" in error_lower:
            original = Path(script_path).read_text(encoding="utf-8")
            # 简单启发：在 navigate 后插入 WaitStep
            if "WaitStep" not in original:
                lines = original.splitlines()
                new_lines = []
                for line in lines:
                    new_lines.append(line)
                    if "workflow.add_step(NavigateStep" in line:
                        indent = len(line) - len(line.lstrip())
                        new_lines.append(" " * indent + "workflow.add_step(WaitStep(3.0))")
                fixed_path = script_path.replace(".py", "_fix_wait.py")
                Path(fixed_path).write_text("\n".join(new_lines), encoding="utf-8")
                return fixed_path

        # 规则化修复：导航后无数据 -> 修改提取选择器
        if "validationerror" in error_lower:
            original = Path(script_path).read_text(encoding="utf-8")
            if "ExtractTextStep" in original and "body" not in original:
                fixed = original.replace("ExtractTextStep(\"h1\")", "ExtractTextStep(\"body\")")
                fixed_path = script_path.replace(".py", "_fix_selector.py")
                Path(fixed_path).write_text(fixed, encoding="utf-8")
                return fixed_path

        # 若无法规则修复，返回 None（由上层终止并转人工）
        logger.warning("agent_fix_failed", error=error)
        return None

    # ------------------------------------------------------------------
    # 查询类意图处理
    # ------------------------------------------------------------------
    async def _handle_query(self, text: str) -> AgentResult:
        # 尝试从文本中提取 task_id
        import re
        matches = re.findall(r"[a-f0-9\-]{36}", text)
        if matches:
            task_id = matches[0]
            status = self.service.get_task_status(task_id)
            return AgentResult(
                success=True,
                message=f"任务 {task_id} 当前状态: {status['state']}",
                data=status,
            )
        # 若无 task_id，返回队列概览
        queue = self.service.get_queue()
        count = len(queue.get("pending_tasks", []))
        return AgentResult(
            success=True,
            message=f"当前有 {count} 个待处理/异常任务",
            data=queue,
        )

    # ------------------------------------------------------------------
    # 定时任务处理
    # ------------------------------------------------------------------
    async def _handle_schedule(self, text: str) -> AgentResult:
        # 先当作普通任务预执行一次
        task_result = await self._handle_task(text)
        if not task_result.success:
            return AgentResult(
                success=False,
                message=f"预执行失败，无法创建定时任务: {task_result.message}",
            )

        # 提取 cron 表达式（简单规则解析）
        cron = self._extract_cron(text)
        if not cron:
            return AgentResult(
                success=False,
                message="未能从指令中解析出定时规则，请使用'每天X点'或'每周一X点'等明确描述",
            )

        # 复用最近一次生成的脚本
        script_dir = Path("./scripts")
        scripts = sorted(script_dir.glob("agent_*.py"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not scripts:
            return AgentResult(success=False, message="未找到可定时执行的脚本")

        script_path = str(scripts[0])
        task_name = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", text)[:30]
        sched = self.service.schedule_task(script_path, task_name, cron, self.headless)
        return AgentResult(
            success=True,
            message=f"定时任务已创建: {task_name}，执行规则: {cron}，下次执行: {sched.get('next_run', '')}",
            data=sched,
        )

    def _extract_cron(self, text: str) -> Optional[str]:
        """从中文描述中提取简化版 Cron 表达式."""
        import re
        t = text.lower()

        def _parse_hour(text: str) -> int:
            m = re.search(r"([0-9]{1,2})\s*点", text)
            if not m:
                return 0
            hour = int(m.group(1))
            if "下午" in text or "晚上" in text:
                if hour != 12:
                    hour += 12
            elif "上午" in text and hour == 12:
                hour = 0
            return hour

        # 每天 X 点
        m = re.search(r"每天.*?(上午|下午|晚上)?\s*([0-9]{1,2})\s*点", t)
        if m:
            hour = _parse_hour(t)
            return f"0 {hour} * * *"

        # 每周一 X 点
        weekdays = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 0, "天": 0}
        m = re.search(r"每周([一二三四五六日天]).*?(上午|下午|晚上)?\s*([0-9]{1,2})\s*点", t)
        if m:
            day = weekdays.get(m.group(1), 1)
            hour = _parse_hour(t)
            return f"0 {hour} * * {day}"

        # 每隔 X 小时
        m = re.search(r"每隔\s*([0-9]+)\s*小时", t)
        if m:
            interval = int(m.group(1))
            return f"0 */{interval} * * *"

        return None

    def _handle_list_schedules(self) -> AgentResult:
        result = self.service.list_scheduled_tasks()
        count = len(result.get("schedules", []))
        return AgentResult(
            success=True,
            message=f"当前共有 {count} 个定时任务",
            data=result,
        )

    def _handle_list_steps(self) -> AgentResult:
        result = self.service.list_available_steps()
        names = [s["name"] for s in result.get("steps", [])]
        return AgentResult(
            success=True,
            message=f"系统支持 {len(names)} 种原子步骤: {', '.join(names)}",
            data=result,
        )
