"""AI 脚本生成器.

基于 TaskPlanner 生成确定性的 AtomicStep Workflow 脚本.
"""

from pathlib import Path
from typing import Any, List, Tuple

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
        imports, statements = self._build_atomic_steps(steps)
        lines = [
            "# Auto-generated OmniAuto atomic script",
            f"# Task: {task_description}",
            "",
            "from omniauto.core.state_machine import Workflow",
        ]
        lines.extend(sorted(imports))
        lines.extend(
            [
                "",
                "requires_browser = True",
                "",
                'workflow = Workflow(task_id="auto_task")',
            ]
        )
        lines.extend(statements)
        lines.append("")

        code = "\n".join(lines)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(code, encoding="utf-8")
        return output_path

    def _build_atomic_steps(self, steps: List[dict]) -> Tuple[set[str], List[str]]:
        """根据规划结果构造 Workflow 导入与步骤语句."""
        imports: set[str] = set()
        statements: List[str] = []

        for step in steps:
            import_line, statement = self._render_step(step)
            imports.add(import_line)
            statements.append(statement)

        return imports, statements

    def _render_step(self, step: dict) -> Tuple[str, str]:
        """将单个步骤配置渲染为导入语句与 Workflow 添加语句."""
        stype = step.get("type")

        if stype == "navigate":
            url = step.get("url", "https://example.com")
            return (
                "from omniauto.steps.navigate import NavigateStep",
                f"workflow.add_step(NavigateStep({url!r}))",
            )

        if stype == "click":
            selector = step.get("selector", "button")
            return (
                "from omniauto.steps.click import ClickStep",
                f"workflow.add_step(ClickStep({selector!r}))",
            )

        if stype == "type":
            selector = step.get("selector", "input")
            text = step.get("text", "")
            return (
                "from omniauto.steps.type import TypeStep",
                f"workflow.add_step(TypeStep({selector!r}, {text!r}, interval=(0.05, 0.15)))",
            )

        if stype == "extract_text":
            selector = step.get("selector", "body")
            return (
                "from omniauto.steps.extract import ExtractTextStep",
                f"workflow.add_step(ExtractTextStep({selector!r}))",
            )

        if stype == "hotkey":
            keys = step.get("keys", [])
            key_args = ", ".join(repr(key) for key in keys)
            return (
                "from omniauto.steps.hotkey import HotkeyStep",
                f"workflow.add_step(HotkeyStep({key_args}))",
            )

        if stype == "screenshot":
            output_dir = step.get("output_dir", "./screenshots")
            return (
                "from omniauto.steps.screenshot import ScreenshotStep",
                f"workflow.add_step(ScreenshotStep({output_dir!r}))",
            )

        raise ValueError(f"不支持的步骤类型: {stype!r}")
