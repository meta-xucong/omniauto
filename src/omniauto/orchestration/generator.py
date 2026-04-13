"""AI 脚本生成器.

基于 TaskPlanner + 模板生成原子化 Python 脚本.
"""

from pathlib import Path
from typing import Any, List

from ..high_level.task_planner import TaskPlanner

SYSTEM_PROMPT = """你是一位自动化脚本生成专家。请生成 Python 原子脚本，要求：
1. 所有浏览器操作必须使用提供的 StealthBrowser 类，禁止直接使用 selenium / webdriver。
2. 所有桌面操作必须优先使用 VisualEngine（pyauto-desktop 封装），禁止直接使用裸 pyautogui。
3. 所有点击操作必须包含 random_delay(0.1, 0.5)。
4. 鼠标移动必须使用 human_like_move() 或 VisualEngine 的 Session 移动方法，禁止瞬时移动。
5. 禁止生成 eval()、exec()、subprocess、os.system 等危险代码。
6. 函数签名：async def atomic_task_XXX(context: TaskContext) -> StepResult
7. 导入路径统一使用：from omniauto.core.context import TaskContext, StepResult
"""


class ScriptGenerator:
    """原子脚本生成器.

    支持两种模式：
    1. 模板模式：根据自然语言描述快速生成标准结构（无需 LLM）。
    2. LLM 模式：调用本地模型生成高灵活度脚本（预留接口）。
    """

    def __init__(self, model: Any = None) -> None:
        self.planner = TaskPlanner(model)
        self.model = model

    def generate(
        self,
        task_description: str,
        output_path: str,
    ) -> str:
        """生成原子脚本.

        当前默认使用模板模式，快速可用.
        """
        steps = self.planner.plan(task_description)
        return self._write_template(task_description, steps, output_path)

    def _write_template(
        self,
        task_description: str,
        steps: List[dict],
        output_path: str,
    ) -> str:
        lines = [
            "# Auto-generated OmniAuto atomic script",
            f'# Task: {task_description}',
            "",
            "import asyncio",
            "from omniauto.core.context import TaskContext, StepResult",
            "from omniauto.core.state_machine import AtomicStep, Workflow",
            "from omniauto.core.exceptions import GuardianBlockedError",
            "",
            "async def run_task(ctx: TaskContext) -> StepResult:",
            '    browser = ctx.browser_state.get("browser")',
            '    if browser is None:',
            '        raise RuntimeError("浏览器引擎未初始化")',
            "",
        ]

        for step in steps:
            stype = step.get("type")
            if stype == "navigate":
                lines.append(f'    await browser.goto("{step.get("url")}")')
            elif stype == "click":
                lines.append(f'    await browser.click("{step.get("selector")}")')
            elif stype == "hotkey":
                keys = step.get("keys", [])
                key_args = ', '.join(f'"{k}"' for k in keys)
                lines.append(f'    page = browser.page')
                lines.append(f'    await page.keyboard.press({key_args})')
            elif stype == "type":
                lines.append(
                    f'    await browser.type_text("{step.get("selector")}", '
                    f'"{step.get("text")}", interval=(0.05, 0.15))'
                )
            elif stype == "extract_text":
                lines.append(f'    data = await browser.extract_text("{step.get("selector")}")')
                lines.append('    return StepResult(success=True, data=data)')
            elif stype == "screenshot":
                lines.append('    path = await browser.screenshot()')
                lines.append('    return StepResult(success=True, data=path)')

        lines.extend([
            "    return StepResult(success=True)",
            "",
            "steps = [",
            '    AtomicStep("main", run_task, lambda r: r.success)',
            "]",
            'workflow = Workflow(task_id="auto_task", steps=steps)',
            "",
        ])

        code = "\n".join(lines)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(code, encoding="utf-8")
        return output_path
