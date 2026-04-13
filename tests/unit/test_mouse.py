"""Mouse 工具函数单元测试."""

import pytest
from omniauto.utils.mouse import bezier_curve, random_delay


def test_bezier_curve_returns_points():
    points = bezier_curve((0, 0), (100, 100), num_points=10)
    assert len(points) == 11
    assert points[0] == (0, 0)
    assert points[-1] == (100, 100)


def test_bezier_curve_spread():
    points = bezier_curve((0, 0), (100, 0), num_points=5, spread=50)
    # 控制点有偏移，中间点不应完全在直线上
    mid = points[len(points) // 2]
    assert mid[1] != 0 or mid[0] != 50  # 大概率有偏移


@pytest.mark.asyncio
async def test_random_delay_runs():
    import time
    start = time.time()
    await random_delay(0.01, 0.02)
    elapsed = time.time() - start
    assert 0.005 <= elapsed <= 0.05
