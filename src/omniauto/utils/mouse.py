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


def human_like_move(
    x: int,
    y: int,
    duration: float = 0.5,
    spread: int = 100,
) -> None:
    """使用贝塞尔曲线将鼠标移动到目标坐标.

    该函数直接调用 pyauto-desktop / pyautogui 的 moveTo.
    在 VisualEngine 中应优先使用 Session 封装的移动方法.

    Args:
        x: 目标屏幕 X 坐标.
        y: 目标屏幕 Y 坐标.
        duration: 移动耗时（秒）.
        spread: 贝塞尔曲线控制点偏移幅度.
    """
    try:
        import pyauto_desktop
        current_x, current_y = pyauto_desktop.position()
        points = bezier_curve((current_x, current_y), (x, y), num_points=20, spread=spread)
        step_duration = duration / len(points)
        for px, py in points:
            pyauto_desktop.moveTo(px, py)
            time.sleep(step_duration)
    except Exception:
        # 若 pyauto-desktop 不可用，降级到 pyautogui
        import pyautogui
        current_x, current_y = pyautogui.position()
        points = bezier_curve((current_x, current_y), (x, y), num_points=20, spread=spread)
        step_duration = duration / len(points)
        for px, py in points:
            pyautogui.moveTo(px, py)
            time.sleep(step_duration)
