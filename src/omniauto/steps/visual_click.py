"""视觉点击原子步骤."""

from ..core.state_machine import AtomicStep
from ..core.context import TaskContext


def VisualClickStep(image_path: str, confidence: float = 0.9) -> AtomicStep:
    """创建基于图像识别的点击原子步骤.

    Args:
        image_path: 屏幕模板图像路径.
        confidence: 匹配置信度.

    Returns:
        AtomicStep 实例.
    """
    async def action(ctx: TaskContext) -> bool:
        engine = ctx.visual_state.get("engine")
        if engine is None:
            from ..engines.visual import VisualEngine
            engine = VisualEngine().start()
            ctx.visual_state["engine"] = engine
        return engine.click(image_path=image_path, confidence=confidence)

    return AtomicStep(
        step_id=f"visual_click_{image_path.replace('/', '_').replace('\\', '_')}",
        action=action,
        validator=lambda r: r is True,
        description=f"视觉点击 {image_path}",
    )
