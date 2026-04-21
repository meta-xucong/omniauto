"""人类化鼠标移动与行为模拟工具."""

import asyncio
import random
import time
from typing import List, Tuple


def bezier_curve(
    start: Tuple[int, int],
    end: Tuple[int, int],
    num_points: int = 20,
    spread: int = 100,
) -> List[Tuple[int, int]]:
    """生成二次贝塞尔曲线点集，模拟人类非线性鼠标移动.

    Args:
        start: 起点坐标 (x, y).
        end: 终点坐标 (x, y).
        num_points: 曲线上的采样点数.
        spread: 控制点随机偏移幅度，越大曲线越弯曲.

    Returns:
        曲线上的坐标点列表.
    """
    x0, y0 = start
    x2, y2 = end

    # 随机生成控制点，使路径产生自然弯曲
    cx = (x0 + x2) / 2 + random.uniform(-spread, spread)
    cy = (y0 + y2) / 2 + random.uniform(-spread, spread)

    points: List[Tuple[int, int]] = []
    for i in range(num_points + 1):
        t = i / num_points
        # 二次贝塞尔公式
        x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x2
        y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y2
        points.append((int(x), int(y)))
    return points


async def random_delay(min_sec: float = 0.1, max_sec: float = 0.5) -> None:
    """随机延迟，模拟人类反应时间."""
    await asyncio.sleep(random.uniform(min_sec, max_sec))


def _get_cursor_pos() -> Tuple[int, int]:
    """通过 Windows API 获取当前鼠标坐标."""
    import ctypes
    from ctypes import wintypes
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def human_like_move(
    x: int,
    y: int,
    duration: float = 0.5,
    spread: int = 100,
) -> None:
    """使用贝塞尔曲线将鼠标移动到目标坐标.

    基于 pyauto-desktop Session 实现.
    在 VisualEngine 中应优先使用其内部的 _human_like_move 方法.

    Args:
        x: 目标屏幕 X 坐标.
        y: 目标屏幕 Y 坐标.
        duration: 移动耗时（秒）.
        spread: 贝塞尔曲线控制点偏移幅度.
    """
    import pyauto_desktop

    current_x, current_y = _get_cursor_pos()
    points = bezier_curve((current_x, current_y), (x, y), num_points=20, spread=spread)
    step_duration = duration / len(points)

    session = pyauto_desktop.Session()
    for px, py in points:
        session.moveTo(px, py, duration=0)
        time.sleep(step_duration)
