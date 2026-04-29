from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import csv
import math
import os
import pickle
import random
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from omniauto.engines.visual import VisualEngine


def _enable_dpi_awareness() -> None:
    """Best-effort DPI awareness so window rect, screenshot, and mouse coords use one scale."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_dpi_awareness()


EXE_PATH = Path("D:/Program Files (x86)/\u626b\u96f7/Minesweeper.exe")
ARTIFACT_DIR = Path("D:/AI/AI_RPA/runtime/test_artifacts/verification/minesweeper")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATE_LIBRARY_DIR = ARTIFACT_DIR / "template_library"
TEMPLATE_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
SPECIAL_TEMPLATE_LIBRARY_DIR = ARTIFACT_DIR / "template_library_special"
SPECIAL_TEMPLATE_LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
EDGE_CASE_DIR = ARTIFACT_DIR / "recognition_edge_cases"
EDGE_CASE_DIR.mkdir(parents=True, exist_ok=True)
OPEN_EMPTY_CASE_DIR = ARTIFACT_DIR / "recognition_open_empty_cases"
OPEN_EMPTY_CASE_DIR.mkdir(parents=True, exist_ok=True)

PROCESS_NAME = "Minesweeper.exe"
TOTAL_MINES = 99
MAX_ATTEMPTS = 50
MAX_REPEAT_FAILURE_SECONDS = 180
MAX_STAGNATION_SECONDS = 12
MAX_NO_PROGRESS_SECONDS = 20
MAX_SINGLE_ATTEMPT_STEPS = 50000
WINDOW_APPEAR_TIMEOUT_SECONDS = 8.0
WINDOW_APPEAR_POLL_SECONDS = 0.2
ENABLE_CSP_FLAGS = os.getenv("OMNIAUTO_MINESWEEPER_ENABLE_CSP_FLAGS", "0") == "1"
MAX_CSP_OPEN_BATCH = 256
MAX_DET_OPEN_BATCH = 256
MAX_DET_FLAG_BATCH = 256
OPENING_BOOST_OPENED_THRESHOLD = 18
MAX_OPENING_BOOST_CLICKS = 4
BOARD_CONSENSUS_FRAMES = 3
POST_OPEN_SETTLE_SECONDS = 0.12
CLICK_RELEASE_SETTLE_SECONDS = 0.06
RIGHT_CLICK_RELEASE_SETTLE_SECONDS = 0.04
CONSENSUS_INITIAL_WAIT_SECONDS = 0.02
CONSENSUS_EXTRA_WAIT_SECONDS = 0.03
TEMPLATE_PROFILE_STORE_INTERVAL_SECONDS = 2.0
VISIBLE_TEMPLATE_RECORD_STEP_INTERVAL = 6
VISIBLE_TEMPLATE_RECORD_MIN_STEP = 3
VISIBLE_TEMPLATE_RECORD_MAX_STEP = 18
VISIBLE_TEMPLATE_RECORD_MIN_OPENED = 18
POST_OPEN_ACTION_WAIT_SECONDS = 0.12
POST_FLAG_ACTION_WAIT_SECONDS = 0.08
ACTION_RETRY_WAIT_SECONDS = 0.04
MAX_OPEN_CLICK_VARIANTS = 6
MAX_FLAG_CLICK_VARIANTS = 4
MAX_OPEN_NO_EFFECT_VARIANTS = 3
MAX_OPEN_IDENTICAL_NO_EFFECT_VARIANTS = 2
MAX_FLAG_NO_EFFECT_VARIANTS = 2
MAX_FLAG_IDENTICAL_NO_EFFECT_VARIANTS = 2
MIN_GOOD_OPENING_OPENED = 12
MAX_EXACT_COMPONENT_CELLS = 22
MAX_GROUPED_COMPONENT_AREAS = 26
MAX_EXACT_DFS_STATES = 60000
MAX_GROUPED_DFS_STATES = 40000
MAX_EXACT_COMPONENT_SECONDS = 0.20
MAX_GROUPED_COMPONENT_SECONDS = 0.16
MAX_FRONTIER_CACHE_ENTRIES = 256
MAX_BOARD_ANALYSIS_CACHE_ENTRIES = 256
DET_FLAG_CONFIRM_FRAMES = 2
DET_OPEN_CONFIRM_FRAMES = 1
CSP_FLAG_CONFIRM_FRAMES = 2
CSP_OPEN_CONFIRM_FRAMES = 1
SHARED_FLAG_CONFIRM_FRAMES = 2
RUN_MODE_CHOICES = ("single", "retry", "until_success")


def parse_bool_text(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ValueError(f"unsupported boolean value: {value}")


def env_bool(name: str, default: bool = False) -> bool:
    try:
        return parse_bool_text(os.getenv(name), default=default)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def default_run_mode() -> str:
    explicit_mode = os.getenv("OMNIAUTO_MINESWEEPER_RUN_MODE", "").strip().lower()
    if explicit_mode in RUN_MODE_CHOICES:
        return explicit_mode
    if env_bool("OMNIAUTO_MINESWEEPER_SINGLE_ATTEMPT", False):
        return "single"
    return "retry"

STATE_HIDDEN = -1
STATE_FLAG = -2
STATE_EMPTY = 0

NUMBER_COLORS = {
    1: np.array([81, 96, 192]),
    2: np.array([45, 113, 24]),
    3: np.array([190, 55, 45]),
    4: np.array([48, 48, 135]),
    5: np.array([125, 46, 46]),
    6: np.array([45, 122, 122]),
    7: np.array([20, 20, 20]),
    8: np.array([120, 120, 120]),
}

TEMPLATE_SAMPLES: dict[str, list[tuple[str, tuple[int, int]]]] = {
    "hidden": [
        ("attempt_01_fresh.png", (0, 0)),
        ("attempt_01_fresh.png", (0, 10)),
        ("attempt_01_fresh.png", (7, 15)),
        ("attempt_01_fresh.png", (12, 20)),
        ("attempt_04_after_first_click.png", (0, 22)),
        ("attempt_04_after_first_click.png", (1, 22)),
        ("attempt_04_after_first_click.png", (5, 15)),
        ("attempt_01_after_first_click.png", (0, 0)),
        ("attempt_01_after_first_click.png", (0, 5)),
        ("attempt_01_after_first_click.png", (3, 0)),
        ("attempt_01_after_first_click.png", (0, 12)),
        ("attempt_01_after_first_click.png", (1, 12)),
        ("attempt_01_after_first_click.png", (2, 10)),
        ("attempt_01_after_first_click.png", (3, 11)),
        ("attempt_01_after_first_click.png", (4, 8)),
        ("attempt_01_after_first_click.png", (5, 7)),
    ],
    "empty": [
        ("attempt_04_after_first_click.png", (0, 18)),
        ("attempt_04_after_first_click.png", (0, 19)),
        ("attempt_04_after_first_click.png", (0, 20)),
    ],
    "1": [
        ("attempt_04_after_first_click.png", (0, 17)),
        ("attempt_03_csp_flags_000.png", (0, 20)),
    ],
    "2": [
        ("attempt_04_after_first_click.png", (1, 16)),
        ("attempt_03_csp_flags_000.png", (1, 19)),
    ],
    "3": [
        ("attempt_04_after_first_click.png", (2, 15)),
        ("attempt_04_after_first_click.png", (3, 15)),
        ("attempt_03_csp_flags_000.png", (1, 18)),
    ],
    "4": [
        ("attempt_04_after_first_click.png", (1, 15)),
        ("attempt_04_after_first_click.png", (4, 15)),
    ],
    "flag": [
        ("attempt_03_csp_flags_000.png", (0, 19)),
        ("attempt_03_csp_flags_000.png", (11, 14)),
        ("attempt_03_csp_flags_000.png", (13, 12)),
    ],
}

TEMPLATE_LABELS = ("hidden", "empty", "1", "2", "3", "4", "flag")
TEMPLATE_PROFILE_CACHE_VERSION = 5
MIN_TEMPLATE_REFERENCES_PER_LABEL = 4
MAX_RUNTIME_TEMPLATES_PER_LABEL = 8
MAX_RUNTIME_TEMPLATE_IMAGES = 12
MAX_TEMPLATE_LIBRARY_SAMPLES_PER_LABEL = 32
MAX_SPECIAL_TEMPLATE_SAMPLES_PER_LABEL = 96
TEMPLATE_MATCH_TOP_K = 3
TEMPLATE_LIBRARY_DUPLICATE_DISTANCE = 5.0
TEMPLATE_LIBRARY_REPLACE_MIN_NOVELTY = 8.0
TEMPLATE_LIBRARY_REDUNDANT_DISTANCE = 6.4


@dataclass
class BoardGeometry:
    left: int
    top: int
    cell: int
    cols: int
    rows: int
    x_edges: list[int] | None = None
    y_edges: list[int] | None = None

    def center_local(self, row: int, col: int) -> tuple[int, int]:
        if self.x_edges and self.y_edges and len(self.x_edges) >= self.cols + 1 and len(self.y_edges) >= self.rows + 1:
            return (
                int(round((self.x_edges[col] + self.x_edges[col + 1]) / 2)),
                int(round((self.y_edges[row] + self.y_edges[row + 1]) / 2)),
            )
        return (
            int(self.left + col * self.cell + self.cell / 2),
            int(self.top + row * self.cell + self.cell / 2),
        )

    def cell_rect_local(self, row: int, col: int) -> tuple[int, int, int, int]:
        if self.x_edges and self.y_edges and len(self.x_edges) >= self.cols + 1 and len(self.y_edges) >= self.rows + 1:
            return (
                int(self.x_edges[col]),
                int(self.y_edges[row]),
                int(self.x_edges[col + 1]),
                int(self.y_edges[row + 1]),
            )
        return (
            int(self.left + col * self.cell),
            int(self.top + row * self.cell),
            int(self.left + (col + 1) * self.cell),
            int(self.top + (row + 1) * self.cell),
        )

    def click_points_local(self, row: int, col: int) -> list[tuple[int, int]]:
        left, top, right, bottom = self.cell_rect_local(row, col)
        width = max(1, right - left)
        height = max(1, bottom - top)
        center_x = int(round((left + right) / 2))
        center_y = int(round((top + bottom) / 2))
        # Stay near the cell center. The older board-center "inward" bias could
        # push clicks onto borders when geometry was even slightly off.
        offset_x = max(2, min(6, int(round(width * 0.12))))
        offset_y = max(2, min(6, int(round(height * 0.12))))
        inset_left = left + max(3, int(round(width * 0.28)))
        inset_right = right - max(3, int(round(width * 0.28)))
        inset_top = top + max(3, int(round(height * 0.28)))
        inset_bottom = bottom - max(3, int(round(height * 0.28)))

        def clamp_point(x: int, y: int) -> tuple[int, int]:
            return (
                min(max(x, inset_left), inset_right),
                min(max(y, inset_top), inset_bottom),
            )

        points = [
            clamp_point(center_x, center_y),
            clamp_point(center_x - offset_x, center_y),
            clamp_point(center_x + offset_x, center_y),
            clamp_point(center_x, center_y - offset_y),
            clamp_point(center_x, center_y + offset_y),
            clamp_point(center_x - offset_x, center_y - offset_y),
            clamp_point(center_x + offset_x, center_y - offset_y),
            clamp_point(center_x - offset_x, center_y + offset_y),
            clamp_point(center_x + offset_x, center_y + offset_y),
        ]
        deduped: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for point in points:
            if point not in seen:
                deduped.append(point)
                seen.add(point)
        points = deduped
        return points

    def board_rect_local(self) -> tuple[int, int, int, int]:
        if self.x_edges and self.y_edges:
            return (
                int(self.x_edges[0]),
                int(self.y_edges[0]),
                int(self.x_edges[-1]),
                int(self.y_edges[-1]),
            )
        return (
            self.left,
            self.top,
            self.left + self.cols * self.cell,
            self.top + self.rows * self.cell,
        )


@dataclass(frozen=True)
class RunConfig:
    mode: str
    max_attempts: int | None
    stop_on_loss: bool
    max_repeat_failure_seconds: float | None
    max_single_attempt_steps: int

    @property
    def single_attempt_mode(self) -> bool:
        return self.mode == "single"

    @property
    def attempt_limit(self) -> int | None:
        if self.single_attempt_mode:
            return 1
        return self.max_attempts


def parse_run_config(argv: list[str] | None = None) -> RunConfig:
    args_list = list(sys.argv[1:] if argv is None else argv)
    env_mode = default_run_mode()
    env_stop_on_loss = env_bool("OMNIAUTO_MINESWEEPER_STOP_ON_FAILURE", False)
    env_max_attempts_raw = os.getenv("OMNIAUTO_MINESWEEPER_MAX_ATTEMPTS")
    env_repeat_failure_raw = os.getenv("OMNIAUTO_MINESWEEPER_MAX_REPEAT_FAILURE_SECONDS")
    parser = argparse.ArgumentParser(description="Windows Minesweeper auto-solver")
    parser.add_argument(
        "--mode",
        choices=RUN_MODE_CHOICES,
        default=env_mode,
        help="single: 单局即停; retry: 最多重试 N 局; until_success: 持续重试直到成功（可选限制局数）",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="最多尝试局数；<=0 表示不限制。single 模式下会忽略这个值。",
    )
    parser.add_argument(
        "--stop-on-loss",
        type=parse_bool_text,
        nargs="?",
        const=True,
        default=env_stop_on_loss,
        help="失败后是否立刻结束整个运行；默认读取环境变量 OMNIAUTO_MINESWEEPER_STOP_ON_FAILURE。",
    )
    parser.add_argument(
        "--max-repeat-failure-seconds",
        type=float,
        default=None,
        help="连续失败累计多长时间后停止；<=0 表示不限制。",
    )
    parser.add_argument(
        "--single-attempt-steps",
        type=int,
        default=env_int("OMNIAUTO_MINESWEEPER_SINGLE_ATTEMPT_STEPS", MAX_SINGLE_ATTEMPT_STEPS),
        help="single 模式下的最大步数上限。",
    )
    args = parser.parse_args(args_list)

    if args.max_attempts is None:
        if env_max_attempts_raw is not None and env_max_attempts_raw.strip():
            try:
                max_attempts = int(env_max_attempts_raw.strip())
            except ValueError:
                max_attempts = MAX_ATTEMPTS
        elif args.mode == "until_success":
            max_attempts = None
        else:
            max_attempts = MAX_ATTEMPTS
    else:
        max_attempts = args.max_attempts
    if max_attempts is not None and max_attempts <= 0:
        max_attempts = None

    if args.max_repeat_failure_seconds is None:
        if env_repeat_failure_raw is not None and env_repeat_failure_raw.strip():
            try:
                max_repeat_failure_seconds = float(env_repeat_failure_raw.strip())
            except ValueError:
                max_repeat_failure_seconds = float(MAX_REPEAT_FAILURE_SECONDS)
        else:
            max_repeat_failure_seconds = float(MAX_REPEAT_FAILURE_SECONDS)
    else:
        max_repeat_failure_seconds = args.max_repeat_failure_seconds
    if max_repeat_failure_seconds is not None and max_repeat_failure_seconds <= 0:
        max_repeat_failure_seconds = None

    return RunConfig(
        mode=args.mode,
        max_attempts=max_attempts,
        stop_on_loss=bool(args.stop_on_loss),
        max_repeat_failure_seconds=max_repeat_failure_seconds,
        max_single_attempt_steps=max(1, int(args.single_attempt_steps)),
    )


class MinesweeperSolver:
    def __init__(self, run_config: RunConfig | None = None) -> None:
        self.vis = VisualEngine().start()
        self.user32 = ctypes.windll.user32
        self.geometry: BoardGeometry | None = None
        self.window_rect = (0, 0, 0, 0)
        self.attempt = 0
        self.run_config = run_config or parse_run_config([])
        self.last_actions: list[str] = []
        self.failed_guess_counts: dict[tuple[int, int], int] = defaultdict(int)
        self.failed_openers: dict[tuple[int, int], int] = defaultdict(int)
        self.current_first_click: tuple[int, int] | None = None
        self.run_started_at = time.time()
        self.failure_started_at: float | None = None
        self.reuse_existing_game = False
        self.dialog_restart_successes = 0
        self.last_dialog_restart_mode: str | None = None
        self.preferred_restart_point: tuple[int, int] | None = None
        self.reference_templates: dict[str, np.ndarray] | None = None
        self.reference_template_profiles: dict[str, dict[str, list[np.ndarray]]] | None = None
        self.frontier_cache: dict[
            int,
            tuple[
                dict[tuple[int, int], float],
                float,
                set[tuple[int, int]],
                set[tuple[int, int]],
            ],
        ] = {}
        self.constraint_cache: dict[
            int,
            tuple[list[tuple[list[tuple[int, int]], int]], set[tuple[int, int]]],
        ] = {}
        self.rule_cache: dict[
            int,
            tuple[
                tuple[tuple[int, int], ...],
                tuple[tuple[int, int], ...],
                tuple[tuple[int, int], ...],
                tuple[tuple[int, int], ...],
            ],
        ] = {}
        self.support_cache: dict[int, dict[tuple[int, int], int]] = {}
        self.template_match_cache: dict[bytes, dict[str, dict[str, float]]] = {}
        self.template_library_counts: dict[str, int] = {}
        self.special_template_library_counts: dict[str, int] = {}
        self.precision_click_cells: dict[tuple[int, int], int] = defaultdict(int)
        self.last_template_profile_store_at = 0.0

    @property
    def single_attempt_mode(self) -> bool:
        return self.run_config.single_attempt_mode

    @property
    def stop_on_failure(self) -> bool:
        return self.run_config.stop_on_loss

    def _enum_windows(self) -> list[int]:
        hwnds: list[int] = []
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            if self.user32.IsWindowVisible(hwnd):
                hwnds.append(hwnd)
            return True

        self.user32.EnumWindows(enum_proc(callback), 0)
        return hwnds

    def minesweeper_process_ids(self) -> set[int]:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {PROCESS_NAME}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except Exception:
            return set()
        pids: set[int] = set()
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line or "No tasks are running" in line:
                continue
            try:
                row = next(csv.reader([line]))
            except Exception:
                continue
            if len(row) < 2:
                continue
            image_name = row[0].strip().strip('"')
            pid_text = row[1].strip().strip('"').replace(",", "")
            if image_name.lower() != PROCESS_NAME.lower():
                continue
            try:
                pids.add(int(pid_text))
            except ValueError:
                continue
        return pids

    def find_minesweeper_hwnd(self) -> int | None:
        process_ids = self.minesweeper_process_ids()
        for hwnd in self._enum_windows():
            pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if process_ids and pid.value not in process_ids:
                continue
            class_buffer = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(hwnd, class_buffer, 256)
            class_name = class_buffer.value
            length = self.user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(max(1, length + 1))
            self.user32.GetWindowTextW(hwnd, buffer, max(1, length + 1))
            title = buffer.value
            if class_name == "Minesweeper" or "\u626b\u96f7" in title or PROCESS_NAME.replace(".exe", "").lower() in title.lower():
                return hwnd
        return None

    def find_dialog_hwnd(self, keywords: list[str]) -> int | None:
        for hwnd in self._enum_windows():
            length = self.user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                continue
            buffer = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            if any(keyword in title for keyword in keywords):
                return hwnd
        return None

    def _enum_child_windows(self, parent_hwnd: int) -> list[int]:
        hwnds: list[int] = []
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            hwnds.append(hwnd)
            return True

        self.user32.EnumChildWindows(parent_hwnd, enum_proc(callback), 0)
        return hwnds

    def dump_dialog_controls(self, tag: str) -> None:
        lines = []
        for keyword in ["????", "????", "???"]:
            hwnd = self.find_dialog_hwnd([keyword])
            if hwnd is None:
                continue
            lines.append(f"dialog={keyword} hwnd={hwnd}")
            for child in self._enum_child_windows(hwnd):
                length = self.user32.GetWindowTextLengthW(child)
                buffer = ctypes.create_unicode_buffer(max(1, length + 1))
                self.user32.GetWindowTextW(child, buffer, max(1, length + 1))
                class_buffer = ctypes.create_unicode_buffer(256)
                self.user32.GetClassNameW(child, class_buffer, 256)
                lines.append(f"child hwnd={child} class={class_buffer.value} text={buffer.value}")
        if lines:
            (ARTIFACT_DIR / f"dialog_controls_{tag}.txt").write_text("\n".join(lines), encoding="utf-8")

    def click_dialog_button(self, dialog_keywords: list[str], button_keywords: list[str]) -> bool:
        BM_CLICK = 0x00F5
        dialog_hwnd = self.find_dialog_hwnd(dialog_keywords)
        if dialog_hwnd is None:
            return False
        for child in self._enum_child_windows(dialog_hwnd):
            length = self.user32.GetWindowTextLengthW(child)
            if length <= 0:
                continue
            buffer = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(child, buffer, length + 1)
            text = buffer.value
            if any(keyword in text for keyword in button_keywords):
                self.user32.SendMessageW(child, BM_CLICK, 0, 0)
                time.sleep(0.4)
                return True
        return False

    def ensure_window(self, timeout: float = 0.0) -> int:
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SW_MAXIMIZE = 3
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        deadline = time.time() + max(0.0, timeout)
        hwnd = None
        while hwnd is None:
            hwnd = self.find_minesweeper_hwnd()
            if hwnd is not None:
                break
            if time.time() >= deadline:
                raise RuntimeError("\u672a\u627e\u5230\u626b\u96f7\u7a97\u53e3")
            time.sleep(WINDOW_APPEAR_POLL_SECONDS)
        self.user32.ShowWindow(hwnd, SW_MAXIMIZE)
        self.user32.BringWindowToTop(hwnd)
        self.user32.SetForegroundWindow(hwnd)
        self.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        self.user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        rect = wintypes.RECT()
        self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        self.window_rect = (rect.left, rect.top, rect.right, rect.bottom)
        time.sleep(0.18)
        return hwnd

    def kill_existing_game(self) -> None:
        os.system(f'taskkill /IM "{PROCESS_NAME}" /F >nul 2>nul')
        time.sleep(0.4)

    def is_session_locked(self) -> bool:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq LogonUI.exe"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except Exception:
            return False
        return "LogonUI.exe" in (result.stdout or "")

    def launch_fresh_game(self) -> None:
        self.kill_existing_game()
        os.startfile(str(EXE_PATH))
        self.ensure_window(timeout=WINDOW_APPEAR_TIMEOUT_SECONDS)
        self.reuse_existing_game = True

    def click_absolute(self, x: int, y: int) -> None:
        self.ensure_window()
        self.vis.click(x=x, y=y, pre_delay=(0.02, 0.05), duration=0.06)
        self.park_cursor_off_board()
        time.sleep(0.08)

    def cursor_parking_point(self) -> tuple[int, int]:
        if self.window_rect[2] <= self.window_rect[0] or self.window_rect[3] <= self.window_rect[1]:
            self.ensure_window()
        left, top, right, bottom = self.window_rect
        width = max(1, right - left)
        height = max(1, bottom - top)
        margin = 28
        candidates: list[tuple[int, int]] = []
        if self.geometry is not None:
            board_left, board_top, board_right, board_bottom = self.geometry.board_rect_local()
            if height - board_bottom >= 44:
                candidates.append((
                    min(width - margin, max(margin, int(round((board_left + board_right) / 2)))),
                    min(height - margin, board_bottom + max(24, (height - board_bottom) // 2)),
                ))
            if width - board_right >= 44:
                candidates.append((
                    min(width - margin, board_right + max(24, (width - board_right) // 2)),
                    min(height - margin, max(margin, int(round((board_top + board_bottom) / 2)))),
                ))
            if board_top >= 44:
                candidates.append((width - margin, max(margin, board_top // 2)))
        candidates.append((width - margin, height - margin))
        for local_x, local_y in candidates:
            abs_x = left + min(width - margin, max(margin, local_x))
            abs_y = top + min(height - margin, max(margin, local_y))
            return abs_x, abs_y
        return left + width - margin, top + height - margin

    def park_cursor_off_board(self) -> None:
        try:
            x, y = self.cursor_parking_point()
            self.user32.SetCursorPos(int(x), int(y))
            time.sleep(0.02)
        except Exception:
            pass

    def click_absolute_raw(self, x: int, y: int) -> None:
        self.ensure_window()
        self.user32.SetCursorPos(x, y)
        time.sleep(0.02)
        self.user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.02)
        self.user32.mouse_event(0x0004, 0, 0, 0, 0)
        self.park_cursor_off_board()
        time.sleep(CLICK_RELEASE_SETTLE_SECONDS)

    def left_click(self, row: int, col: int, variant: int = 0) -> None:
        self.ensure_window()
        points = self.action_click_points_local(row, col)
        local_x, local_y = points[min(variant, len(points) - 1)]
        x = self.window_rect[0] + local_x
        y = self.window_rect[1] + local_y
        # Use the same raw Win32 path as right_click to avoid pyauto_desktop
        # introducing button-state ambiguity or coordinate drift.
        self.click_absolute_raw(x, y)

    def right_click(self, row: int, col: int, variant: int = 0) -> None:
        self.ensure_window()
        points = self.action_click_points_local(row, col)
        local_x, local_y = points[min(variant, len(points) - 1)]
        x = self.window_rect[0] + local_x
        y = self.window_rect[1] + local_y
        self.user32.SetCursorPos(x, y)
        time.sleep(0.02)
        self.user32.mouse_event(0x0008, 0, 0, 0, 0)
        time.sleep(0.02)
        self.user32.mouse_event(0x0010, 0, 0, 0, 0)
        self.park_cursor_off_board()
        time.sleep(RIGHT_CLICK_RELEASE_SETTLE_SECONDS)

    def action_click_points_local(self, row: int, col: int) -> list[tuple[int, int]]:
        assert self.geometry is not None
        points = list(self.geometry.click_points_local(row, col))
        trouble_score = self.precision_click_cells.get((row, col), 0)
        shadow_weight = self.cell_shadow_weight(row, col)
        near_edge = row in {0, 1, self.geometry.rows - 2, self.geometry.rows - 1} or col in {
            0,
            1,
            self.geometry.cols - 2,
            self.geometry.cols - 1,
        }
        if trouble_score <= 0 and shadow_weight < 0.34 and not near_edge:
            return points

        left, top, right, bottom = self.geometry.cell_rect_local(row, col)
        width = max(1, right - left)
        height = max(1, bottom - top)
        center_x = int(round((left + right) / 2))
        center_y = int(round((top + bottom) / 2))
        fine_x = max(1, min(4, int(round(width * 0.08))))
        fine_y = max(1, min(4, int(round(height * 0.08))))
        inset_left = left + max(3, int(round(width * 0.24)))
        inset_right = right - max(3, int(round(width * 0.24)))
        inset_top = top + max(3, int(round(height * 0.24)))
        inset_bottom = bottom - max(3, int(round(height * 0.24)))

        def clamp_point(x: int, y: int) -> tuple[int, int]:
            return (
                min(max(x, inset_left), inset_right),
                min(max(y, inset_top), inset_bottom),
            )

        extra = [
            clamp_point(center_x - 2 * fine_x, center_y),
            clamp_point(center_x + 2 * fine_x, center_y),
            clamp_point(center_x, center_y - 2 * fine_y),
            clamp_point(center_x, center_y + 2 * fine_y),
            clamp_point(center_x - fine_x, center_y - fine_y),
            clamp_point(center_x + fine_x, center_y - fine_y),
            clamp_point(center_x - fine_x, center_y + fine_y),
            clamp_point(center_x + fine_x, center_y + fine_y),
            clamp_point(center_x - 2 * fine_x, center_y - fine_y),
            clamp_point(center_x + 2 * fine_x, center_y - fine_y),
            clamp_point(center_x - 2 * fine_x, center_y + fine_y),
            clamp_point(center_x + 2 * fine_x, center_y + fine_y),
        ]
        deduped: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for point in points + extra:
            if point in seen:
                continue
            deduped.append(point)
            seen.add(point)
        max_points = 5
        if shadow_weight >= 0.34 or near_edge or trouble_score > 0:
            max_points = 9
        if trouble_score >= 3:
            max_points = 13
        return deduped[:max_points]

    def capture(self, name: str) -> tuple[Image.Image, np.ndarray]:
        self.ensure_window()
        self.park_cursor_off_board()
        time.sleep(0.03)
        path = ARTIFACT_DIR / name
        self.vis.screenshot(str(path))
        with Image.open(path) as raw_img:
            img = raw_img.convert("RGB")
        left, top, right, bottom = self.window_rect
        crop = img.crop((max(0, left), max(0, top), max(left + 1, right), max(top + 1, bottom)))
        crop.save(str(path))
        arr = np.array(crop)
        return crop, arr

    @staticmethod
    def _groups(values: list[int]) -> list[tuple[int, int]]:
        if not values:
            return []
        groups: list[tuple[int, int]] = []
        start = prev = values[0]
        for value in values[1:]:
            if value == prev + 1:
                prev = value
                continue
            groups.append((start, prev))
            start = prev = value
        groups.append((start, prev))
        return groups

    def detect_geometry(self, arr: np.ndarray) -> BoardGeometry:
        dark = (arr[:, :, 0] < 90) & (arr[:, :, 1] < 90) & (arr[:, :, 2] < 120)
        col_counts = dark.sum(axis=0)
        row_counts = dark.sum(axis=1)
        col_threshold = max(40, int(arr.shape[0] * 0.55))
        row_threshold = max(40, int(arr.shape[1] * 0.55))
        col_groups = self._groups([i for i, c in enumerate(col_counts) if c > col_threshold])
        row_groups = self._groups([i for i, c in enumerate(row_counts) if c > row_threshold])

        col_margin = max(12, int(arr.shape[1] * 0.04))
        row_min = max(40, int(arr.shape[0] * 0.18))
        row_max = max(row_min + 40, int(arr.shape[0] * 0.9))

        selected_col_groups = [g for g in col_groups if col_margin <= g[0] <= arr.shape[1] - col_margin]
        col_starts = [g[0] for g in selected_col_groups]
        if len(col_starts) < 10:
            raise RuntimeError("\u65e0\u6cd5\u8bc6\u522b\u626b\u96f7\u68cb\u76d8\u5217\u8fb9\u754c")
        cell = int(round(float(np.median(np.diff(col_starts)))))
        left = col_starts[0]
        cols = int(round((col_starts[-1] - left) / cell))

        selected_row_groups = [g for g in row_groups if row_min <= g[0] <= row_max]
        row_starts = [g[0] for g in selected_row_groups]
        if len(row_starts) < 8:
            raise RuntimeError("\u65e0\u6cd5\u8bc6\u522b\u626b\u96f7\u68cb\u76d8\u884c\u8fb9\u754c")
        row_cell = int(round(float(np.median(np.diff(row_starts[: min(6, len(row_starts) - 1)])))))
        cell = int(round((cell + row_cell) / 2))
        top = row_starts[0] - cell
        rows = int(round((row_starts[-1] - top) / cell))
        x_edges = [int(round((g[0] + g[1]) / 2)) for g in selected_col_groups[: cols + 1]]
        y_edges = [int(round((g[0] + g[1]) / 2)) for g in selected_row_groups[: rows + 1]]
        if len(x_edges) < cols + 1:
            x_edges = [int(round(left + i * cell)) for i in range(cols + 1)]
        if len(y_edges) < rows + 1:
            y_edges = [int(round(top + i * cell)) for i in range(rows + 1)]
        return BoardGeometry(left=left, top=top, cell=cell, cols=cols, rows=rows, x_edges=x_edges, y_edges=y_edges)

    def geometry_alignment_score(self, arr: np.ndarray, geometry: BoardGeometry) -> float:
        board_left, board_top, board_right, board_bottom = geometry.board_rect_local()
        if (
            geometry.cell < 12
            or board_left < 2
            or board_top < 2
            or board_right > arr.shape[1] - 2
            or board_bottom > arr.shape[0] - 2
        ):
            return float("-inf")
        dark = (arr[:, :, 0] < 90) & (arr[:, :, 1] < 90) & (arr[:, :, 2] < 120)
        line_scores: list[float] = []
        for index in range(geometry.cols + 1):
            x = int(round(geometry.left + index * geometry.cell))
            strip = dark[board_top:board_bottom, x - 1 : x + 2]
            line_scores.append(float(strip.mean()))
        for index in range(geometry.rows + 1):
            y = int(round(geometry.top + index * geometry.cell))
            strip = dark[y - 1 : y + 2, board_left:board_right]
            line_scores.append(float(strip.mean()))
        if not line_scores:
            return float("-inf")
        return float(np.mean(line_scores))

    def refine_geometry(self, arr: np.ndarray, geometry: BoardGeometry) -> BoardGeometry:
        best = geometry
        best_score = self.geometry_alignment_score(arr, geometry)
        for cell_delta in (-1, 0, 1):
            candidate_cell = geometry.cell + cell_delta
            if candidate_cell < 12:
                continue
            for dx in range(-4, 5):
                for dy in range(-4, 5):
                    candidate = BoardGeometry(
                        left=geometry.left + dx,
                        top=geometry.top + dy,
                        cell=candidate_cell,
                        cols=geometry.cols,
                        rows=geometry.rows,
                    )
                    score = self.geometry_alignment_score(arr, candidate)
                    if score > best_score:
                        best = candidate
                        best_score = score
        return best

    def normalize_cell_patch(self, crop: np.ndarray) -> np.ndarray:
        inner = crop[8:-8, 8:-8]
        if inner.size == 0:
            inner = crop
        return np.array(Image.fromarray(inner).resize((24, 24), Image.Resampling.BILINEAR))

    @staticmethod
    def normalize_match_patch(patch: np.ndarray) -> np.ndarray:
        arr = patch.astype(np.float32)
        mean = arr.mean(axis=(0, 1), keepdims=True)
        std = np.maximum(arr.std(axis=(0, 1), keepdims=True), 1.0)
        return np.clip((arr - mean) / std, -4.0, 4.0)

    @staticmethod
    def fuzzy_match_patch(patch: np.ndarray) -> np.ndarray:
        arr = np.clip(patch, 0, 255).astype(np.uint8)
        return np.array(Image.fromarray(arr).resize((12, 12), Image.Resampling.BILINEAR)).astype(np.float32)

    def cell_core(self, crop: np.ndarray, min_margin: int = 8, max_margin: int = 20, ratio: float = 0.22) -> np.ndarray:
        core_margin = max(min_margin, min(max_margin, int(round(min(crop.shape[0], crop.shape[1]) * ratio))))
        core = crop[core_margin:-core_margin, core_margin:-core_margin]
        if core.size == 0:
            return crop
        return core

    def patch_symbol_profile(self, patch: np.ndarray) -> dict[str, float | int]:
        patch_arr = np.clip(patch, 0, 255).astype(np.float32)
        core = self.cell_core(patch_arr, min_margin=4, max_margin=8, ratio=0.18)
        luminance = np.mean(core, axis=2)
        channel_diff = np.max(core, axis=2) - np.min(core, axis=2)
        red_mask = (core[:, :, 0] > 160) & (core[:, :, 1] < 120) & (core[:, :, 2] < 120)
        grayish_mask = (channel_diff < 22) & (luminance > 150)
        colorful_mask = channel_diff > 40
        red_pixels = int(np.sum(red_mask))
        grayish_pixels = int(np.sum(grayish_mask))
        colorful_pixels = int(np.sum(colorful_mask))
        bright_pixels = int(np.sum(luminance > 215))
        dark_pixels = int(np.sum(luminance < 70))
        height, width = core.shape[:2]
        profile: dict[str, float | int] = {
            "red_pixels": red_pixels,
            "grayish_pixels": grayish_pixels,
            "colorful_pixels": colorful_pixels,
            "bright_pixels": bright_pixels,
            "dark_pixels": dark_pixels,
            "width": width,
            "height": height,
            "red_bbox_width": 0,
            "red_bbox_height": 0,
            "red_bbox_width_ratio": 0.0,
            "red_bbox_height_ratio": 0.0,
            "red_centroid_x": 0.0,
            "red_centroid_y": 0.0,
        }
        if red_pixels:
            yy, xx = np.where(red_mask)
            bbox_width = int(xx.max() - xx.min() + 1)
            bbox_height = int(yy.max() - yy.min() + 1)
            profile.update(
                {
                    "red_bbox_width": bbox_width,
                    "red_bbox_height": bbox_height,
                    "red_bbox_width_ratio": float(bbox_width) / max(1, width),
                    "red_bbox_height_ratio": float(bbox_height) / max(1, height),
                    "red_centroid_x": float(xx.mean()) / max(1, width),
                    "red_centroid_y": float(yy.mean()) / max(1, height),
                }
            )
        return profile

    def patch_looks_flag_symbol(self, patch: np.ndarray) -> bool:
        profile = self.patch_symbol_profile(patch)
        return (
            int(profile["red_pixels"]) >= 52
            and int(profile["bright_pixels"]) >= 8
            and int(profile["dark_pixels"]) <= 8
            and int(profile["colorful_pixels"]) >= 170
            and float(profile["red_bbox_width_ratio"]) <= 0.74
            and float(profile["red_bbox_height_ratio"]) <= 0.70
            and float(profile["red_centroid_x"]) <= 0.43
            and float(profile["red_centroid_y"]) <= 0.27
        )

    def patch_looks_red_digit_three(self, patch: np.ndarray) -> bool:
        profile = self.patch_symbol_profile(patch)
        return (
            int(profile["red_pixels"]) >= 82
            and int(profile["dark_pixels"]) >= 38
            and int(profile["colorful_pixels"]) >= 95
            and float(profile["red_bbox_width_ratio"]) >= 0.72
            and float(profile["red_bbox_height_ratio"]) >= 0.92
            and float(profile["red_centroid_x"]) >= 0.60
            and float(profile["red_centroid_y"]) >= 0.38
        )

    def patch_feature_vector(self, patch: np.ndarray) -> np.ndarray:
        patch_arr = np.clip(patch, 0, 255).astype(np.float32)
        core = self.cell_core(patch_arr, min_margin=4, max_margin=8, ratio=0.18)
        luminance = np.mean(core, axis=2)
        channel_diff = np.max(core, axis=2) - np.min(core, axis=2)
        area = max(1, core.shape[0] * core.shape[1])
        profile = self.patch_symbol_profile(patch_arr)
        mean_rgb = core.mean(axis=(0, 1))
        std_rgb = core.std(axis=(0, 1))
        return np.array(
            [
                float(mean_rgb[0]) / 255.0,
                float(mean_rgb[1]) / 255.0,
                float(mean_rgb[2]) / 255.0,
                float(std_rgb[0]) / 128.0,
                float(std_rgb[1]) / 128.0,
                float(std_rgb[2]) / 128.0,
                int(profile["red_pixels"]) / area,
                int(profile["bright_pixels"]) / area,
                int(profile["dark_pixels"]) / area,
                int(np.sum(channel_diff > 40)) / area,
                int(np.sum((channel_diff < 22) & (luminance > 150))) / area,
                float(profile["red_bbox_width_ratio"]),
                float(profile["red_bbox_height_ratio"]),
                float(profile["red_centroid_x"]),
                float(profile["red_centroid_y"]),
            ],
            dtype=np.float32,
        )

    @staticmethod
    def topk_mean_abs_distance(sample: np.ndarray, refs: list[np.ndarray], top_k: int = TEMPLATE_MATCH_TOP_K) -> float:
        if not refs:
            return float("inf")
        distances = sorted(float(np.mean(np.abs(sample - ref))) for ref in refs)
        return float(np.mean(distances[: min(top_k, len(distances))]))

    def template_match_details(
        self,
        patch: np.ndarray,
        template_profiles: dict[str, dict[str, list[np.ndarray]]],
    ) -> dict[str, dict[str, float]]:
        cache_key = patch.tobytes()
        cached = self.template_match_cache.get(cache_key)
        if cached is not None:
            return cached
        patch_f32 = patch.astype(np.float32)
        normalized_patch = self.normalize_match_patch(patch_f32)
        fuzzy_patch = self.fuzzy_match_patch(patch_f32)
        feature_vector = self.patch_feature_vector(patch_f32)
        details: dict[str, dict[str, float]] = {}
        for label, profile in template_profiles.items():
            raw_score = self.topk_mean_abs_distance(patch_f32, profile.get("float_refs", []))
            fuzzy_score = self.topk_mean_abs_distance(fuzzy_patch, profile.get("fuzzy_refs", []))
            normalized_score = self.topk_mean_abs_distance(normalized_patch, profile.get("normalized_refs", []))
            feature_score = self.topk_mean_abs_distance(feature_vector, profile.get("feature_refs", []))
            if not any(np.isfinite(score) for score in (raw_score, fuzzy_score, normalized_score, feature_score)):
                continue
            details[label] = {
                "raw": raw_score,
                "fuzzy": fuzzy_score,
                "normalized": normalized_score,
                "feature": feature_score,
                "combined": raw_score + fuzzy_score + normalized_score * 60.0 + feature_score * 220.0,
            }
        if len(self.template_match_cache) >= 4096:
            self.template_match_cache.clear()
        self.template_match_cache[cache_key] = details
        return details

    def cell_shadow_weight(self, row: int, col: int) -> float:
        if self.geometry is None:
            return 0.0
        row_ratio = (row + 0.5) / max(1, self.geometry.rows)
        col_ratio = (col + 0.5) / max(1, self.geometry.cols)
        return max(0.0, min(1.0, col_ratio * 0.85 + row_ratio * 0.55 - 0.62))

    @staticmethod
    def red_symbol_profile(core: np.ndarray) -> dict[str, float | int]:
        luminance = np.mean(core, axis=2)
        channel_diff = np.max(core, axis=2) - np.min(core, axis=2)
        red_mask = (core[:, :, 0] > 160) & (core[:, :, 1] < 120) & (core[:, :, 2] < 120)
        grayish_mask = (channel_diff < 22) & (luminance > 150)
        red_pixels = int(np.sum(red_mask))
        grayish_pixels = int(np.sum(grayish_mask))
        bright_pixels = int(np.sum(luminance > 215))
        dark_pixels = int(np.sum(luminance < 70))
        height, width = core.shape[:2]
        profile: dict[str, float | int] = {
            "red_pixels": red_pixels,
            "grayish_pixels": grayish_pixels,
            "bright_pixels": bright_pixels,
            "dark_pixels": dark_pixels,
            "width": width,
            "height": height,
            "red_bbox_width": 0,
            "red_bbox_height": 0,
            "red_centroid_x": 0.0,
            "red_centroid_y": 0.0,
        }
        if red_pixels:
            yy, xx = np.where(red_mask)
            bbox_width = int(xx.max() - xx.min() + 1)
            bbox_height = int(yy.max() - yy.min() + 1)
            profile.update(
                {
                    "red_bbox_width": bbox_width,
                    "red_bbox_height": bbox_height,
                    "red_centroid_x": float(xx.mean()) / max(1, width),
                    "red_centroid_y": float(yy.mean()) / max(1, height),
                }
            )
        return profile

    def cell_looks_flag_symbol(self, core: np.ndarray) -> bool:
        profile = self.red_symbol_profile(core)
        red_pixels = int(profile["red_pixels"])
        if red_pixels < 140:
            return False
        width = max(1, int(profile["width"]))
        height = max(1, int(profile["height"]))
        bbox_width = int(profile["red_bbox_width"])
        bbox_height = int(profile["red_bbox_height"])
        centroid_x = float(profile["red_centroid_x"])
        centroid_y = float(profile["red_centroid_y"])
        bright_pixels = int(profile["bright_pixels"])
        dark_pixels = int(profile["dark_pixels"])
        grayish_pixels = int(profile["grayish_pixels"])
        return (
            bbox_width <= int(round(width * 0.72))
            and bbox_height <= int(round(height * 0.72))
            and centroid_x <= 0.48
            and centroid_y <= 0.52
            and bright_pixels <= 220
            and dark_pixels <= 120
            and grayish_pixels >= max(24, int(round(width * height * 0.06)))
        )

    def cell_looks_red_digit_three(self, core: np.ndarray) -> bool:
        profile = self.red_symbol_profile(core)
        red_pixels = int(profile["red_pixels"])
        if red_pixels < 180:
            return False
        width = max(1, int(profile["width"]))
        height = max(1, int(profile["height"]))
        bbox_width = int(profile["red_bbox_width"])
        bbox_height = int(profile["red_bbox_height"])
        centroid_x = float(profile["red_centroid_x"])
        bright_pixels = int(profile["bright_pixels"])
        dark_pixels = int(profile["dark_pixels"])
        return (
            bbox_width >= int(round(width * 0.55))
            and bbox_height >= int(round(height * 0.82))
            and centroid_x >= 0.52
            and bright_pixels >= 240
            and dark_pixels >= 180
        )

    def template_label_from_crop(self, crop: np.ndarray) -> str | None:
        core = self.cell_core(crop)
        patch = self.normalize_cell_patch(crop)
        channel_diff = np.max(core, axis=2) - np.min(core, axis=2)
        dark_pixels = int(np.sum(np.mean(core, axis=2) < 70))
        bright_pixels = int(np.sum(np.mean(core, axis=2) > 215))
        red_pixels = int(np.sum((core[:, :, 0] > 160) & (core[:, :, 1] < 110) & (core[:, :, 2] < 110)))
        colorful = core[channel_diff > 40]
        mean_rgb = core.mean(axis=(0, 1))
        std_rgb = core.std(axis=(0, 1))

        if self.patch_looks_flag_symbol(patch):
            return "flag"
        if self.patch_looks_red_digit_three(patch):
            return "3"
        if self.cell_looks_flag_symbol(core):
            return "flag"
        if self.cell_looks_red_digit_three(core):
            return "3"
        if (
            red_pixels == 0
            and dark_pixels < 40
            and bright_pixels < 40
            and len(colorful) > 500
            and std_rgb[0] < 18
            and std_rgb[1] < 18
            and std_rgb[2] < 12
        ):
            return "hidden"
        if (
            red_pixels == 0
            and len(colorful) < 20
            and dark_pixels < 40
            and mean_rgb[0] > 185
            and mean_rgb[1] > 195
            and mean_rgb[2] > 215
            and std_rgb[0] < 8
            and std_rgb[1] < 8
            and std_rgb[2] < 8
        ):
            return "empty"
        if len(colorful) == 0:
            return None

        color_hits: dict[int, int] = {}
        for number, target in NUMBER_COLORS.items():
            diffs = np.linalg.norm(colorful.astype(np.float32) - target.astype(np.float32), axis=1)
            color_hits[number] = int(np.sum(diffs < 55))
        ordered_hits = sorted(color_hits.items(), key=lambda item: item[1], reverse=True)
        best_num, best_hits = ordered_hits[0]
        second_hits = ordered_hits[1][1] if len(ordered_hits) > 1 else 0
        if best_hits >= 10 and best_hits >= second_hits + 4:
            return str(best_num)
        return None

    def runtime_template_candidate_paths(self) -> list[Path]:
        ignored_tokens = (
            "consensus",
            "reconfirm",
            "pre_guess",
            "stagnation",
            "dialog_probe",
            "lost",
            "won",
            "timeout",
            "startup_retry",
        )
        candidate_paths = [
            path
            for path in sorted(
                ARTIFACT_DIR.glob("attempt_*.png"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if not any(token in path.name for token in ignored_tokens)
        ][:MAX_RUNTIME_TEMPLATE_IMAGES]
        preferred_paths = [
            path
            for path in candidate_paths
            if any(
                token in path.name
                for token in (
                    "fresh",
                    "after_first_click",
                    "opening_boost",
                    "csp_",
                    "flags",
                    "subset_",
                    "guess_",
                    "rescue_",
                    "_open_",
                )
            )
        ]
        ordered: list[Path] = []
        seen_paths: set[Path] = set()
        for path in preferred_paths + candidate_paths:
            if path in seen_paths:
                continue
            ordered.append(path)
            seen_paths.add(path)
        return ordered

    def template_profile_cache_path(self) -> Path:
        return ARTIFACT_DIR / "reference_template_profiles.pkl"

    def template_library_label_dir(self, label: str) -> Path:
        path = TEMPLATE_LIBRARY_DIR / label
        path.mkdir(parents=True, exist_ok=True)
        return path

    def special_template_library_label_dir(self, label: str) -> Path:
        path = SPECIAL_TEMPLATE_LIBRARY_DIR / label
        path.mkdir(parents=True, exist_ok=True)
        return path

    def template_library_sample_count(self, label: str) -> int:
        if label not in self.template_library_counts:
            self.template_library_counts[label] = len(list(self.template_library_label_dir(label).glob("*.png")))
        return self.template_library_counts[label]

    def special_template_library_sample_count(self, label: str) -> int:
        if label not in self.special_template_library_counts:
            self.special_template_library_counts[label] = len(
                list(self.special_template_library_label_dir(label).glob("*.png"))
            )
        return self.special_template_library_counts[label]

    def log_template_library_event(self, event: str, label: str, detail: str) -> None:
        log_path = ARTIFACT_DIR / "template_library_events.txt"
        line = f"attempt={self.attempt} event={event} label={label} {detail}"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def log_special_template_library_event(self, event: str, label: str, detail: str) -> None:
        log_path = EDGE_CASE_DIR / "template_events.txt"
        line = f"attempt={self.attempt} event={event} label={label} {detail}"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def template_library_distance_score(self, patch_a: np.ndarray, patch_b: np.ndarray) -> float:
        arr_a = patch_a.astype(np.float32)
        arr_b = patch_b.astype(np.float32)
        raw_distance = float(np.mean(np.abs(arr_a - arr_b)))
        fuzzy_distance = float(np.mean(np.abs(self.fuzzy_match_patch(arr_a) - self.fuzzy_match_patch(arr_b))))
        feature_distance = float(np.mean(np.abs(self.patch_feature_vector(arr_a) - self.patch_feature_vector(arr_b))))
        return raw_distance + fuzzy_distance * 0.35 + feature_distance * 80.0

    def most_redundant_template_sample(
        self,
        existing_samples: list[tuple[Path, np.ndarray]],
    ) -> tuple[int, float] | None:
        if len(existing_samples) < 2:
            return None
        redundancy_scores: list[tuple[int, float]] = []
        for index, (_path, sample) in enumerate(existing_samples):
            distances = [
                self.template_library_distance_score(sample, other_sample)
                for other_index, (_other_path, other_sample) in enumerate(existing_samples)
                if other_index != index and other_sample.shape == sample.shape
            ]
            if not distances:
                continue
            redundancy_scores.append((index, min(distances)))
        if not redundancy_scores:
            return None
        return min(redundancy_scores, key=lambda item: item[1])

    @staticmethod
    def board_value_to_template_label(value: int) -> str | None:
        if value == STATE_EMPTY:
            return "empty"
        if 1 <= value <= 4:
            return str(value)
        if value == STATE_FLAG:
            return "flag"
        return None

    def save_template_library_sample(self, label: str, crop: np.ndarray) -> None:
        if label not in TEMPLATE_LABELS:
            return
        patch = self.normalize_cell_patch(crop)
        if label == "flag" and not self.patch_looks_flag_symbol(patch):
            return
        if label == "3" and not self.patch_looks_red_digit_three(patch):
            return
        label_dir = self.template_library_label_dir(label)
        existing_files = sorted(label_dir.glob("*.png"))
        patch_f32 = patch.astype(np.float32)
        existing_samples: list[tuple[Path, np.ndarray]] = []
        min_distance = float("inf")
        replaced_existing = False
        for path in existing_files:
            try:
                existing = np.array(Image.open(path).convert("RGB"))
            except Exception:
                continue
            if existing.shape != patch.shape:
                continue
            existing_samples.append((path, existing))
            distance = self.template_library_distance_score(patch_f32, existing.astype(np.float32))
            min_distance = min(min_distance, distance)
        if existing_samples and min_distance < TEMPLATE_LIBRARY_DUPLICATE_DISTANCE:
            return
        if len(existing_files) >= MAX_TEMPLATE_LIBRARY_SAMPLES_PER_LABEL:
            self.template_library_counts[label] = len(existing_files)
            redundant_candidate = self.most_redundant_template_sample(existing_samples)
            if (
                redundant_candidate is None
                or min_distance < TEMPLATE_LIBRARY_REPLACE_MIN_NOVELTY
                or redundant_candidate[1] > TEMPLATE_LIBRARY_REDUNDANT_DISTANCE
                or min_distance <= redundant_candidate[1] + 0.6
            ):
                return
            replace_index, _redundancy = redundant_candidate
            replace_path, _replace_patch = existing_samples[replace_index]
            try:
                replace_path.unlink()
            except Exception:
                return
            existing_files = [path for path in existing_files if path != replace_path]
            replaced_existing = True
            self.log_template_library_event(
                "replace_candidate",
                label,
                f"removed={replace_path.name} novelty={min_distance:.3f} redundant={redundant_candidate[1]:.3f}",
            )
        target_name = f"{int(time.time() * 1000)}_{abs(hash(patch.tobytes())) % 100000000:08d}.png"
        Image.fromarray(patch).save(label_dir / target_name)
        self.template_library_counts[label] = len(existing_files) + 1
        self.template_match_cache.clear()
        if replaced_existing:
            self.log_template_library_event("replace_added", label, f"added={target_name}")
            self.reference_templates = None
            self.reference_template_profiles = None
            return
        self.log_template_library_event("add", label, f"added={target_name} count={len(existing_files) + 1}")
        if self.reference_templates is not None:
            bucket = self.reference_templates.setdefault(label, [])
            if len(bucket) < MAX_TEMPLATE_LIBRARY_SAMPLES_PER_LABEL + MAX_RUNTIME_TEMPLATES_PER_LABEL:
                bucket.append(patch)
        if self.reference_template_profiles is not None:
            profile_bucket = self.reference_template_profiles.setdefault(
                label,
                {"float_refs": [], "fuzzy_refs": [], "normalized_refs": [], "feature_refs": []},
            )
            profile_bucket["float_refs"].append(patch_f32)
            profile_bucket["fuzzy_refs"].append(self.fuzzy_match_patch(patch_f32))
            profile_bucket["normalized_refs"].append(self.normalize_match_patch(patch_f32))
            profile_bucket["feature_refs"].append(self.patch_feature_vector(patch_f32))
            self.maybe_store_reference_template_profiles()

    def save_special_template_library_sample(
        self,
        label: str,
        crop: np.ndarray,
        event: str,
        cell: tuple[int, int],
    ) -> None:
        if label not in TEMPLATE_LABELS:
            return
        patch = self.normalize_cell_patch(crop)
        if label == "flag" and not self.patch_looks_flag_symbol(patch):
            return
        if label == "3" and not self.patch_looks_red_digit_three(patch):
            return
        label_dir = self.special_template_library_label_dir(label)
        existing_files = sorted(label_dir.glob("*.png"))
        patch_f32 = patch.astype(np.float32)
        existing_samples: list[tuple[Path, np.ndarray]] = []
        min_distance = float("inf")
        replaced_existing = False
        for path in existing_files:
            try:
                existing = np.array(Image.open(path).convert("RGB"))
            except Exception:
                continue
            if existing.shape != patch.shape:
                continue
            existing_samples.append((path, existing))
            distance = self.template_library_distance_score(patch_f32, existing.astype(np.float32))
            min_distance = min(min_distance, distance)
        if existing_samples and min_distance < TEMPLATE_LIBRARY_DUPLICATE_DISTANCE * 0.85:
            return
        if len(existing_files) >= MAX_SPECIAL_TEMPLATE_SAMPLES_PER_LABEL:
            redundant_candidate = self.most_redundant_template_sample(existing_samples)
            if (
                redundant_candidate is None
                or min_distance < TEMPLATE_LIBRARY_REPLACE_MIN_NOVELTY * 0.8
                or redundant_candidate[1] > TEMPLATE_LIBRARY_REDUNDANT_DISTANCE * 1.1
            ):
                return
            replace_index, _redundancy = redundant_candidate
            replace_path, _replace_patch = existing_samples[replace_index]
            try:
                replace_path.unlink()
            except Exception:
                return
            existing_files = [path for path in existing_files if path != replace_path]
            replaced_existing = True
            self.log_special_template_library_event(
                "replace_candidate",
                label,
                f"event={event} cell={cell} removed={replace_path.name} novelty={min_distance:.3f}",
            )
        target_name = (
            f"{int(time.time() * 1000)}_r{cell[0]}_c{cell[1]}_{event[:24].replace(':', '_')}"
            f"_{abs(hash(patch.tobytes())) % 100000000:08d}.png"
        )
        Image.fromarray(patch).save(label_dir / target_name)
        self.special_template_library_counts[label] = len(existing_files) + 1
        self.template_match_cache.clear()
        if replaced_existing:
            self.reference_templates = None
            self.reference_template_profiles = None
            self.log_special_template_library_event("replace_added", label, f"event={event} cell={cell} added={target_name}")
            return
        self.log_special_template_library_event(
            "add",
            label,
            f"event={event} cell={cell} added={target_name} count={len(existing_files) + 1}",
        )
        if self.reference_templates is not None:
            bucket = self.reference_templates.setdefault(label, [])
            if len(bucket) < MAX_SPECIAL_TEMPLATE_SAMPLES_PER_LABEL + MAX_RUNTIME_TEMPLATES_PER_LABEL:
                bucket.append(patch)
        if self.reference_template_profiles is not None:
            profile_bucket = self.reference_template_profiles.setdefault(
                label,
                {"float_refs": [], "fuzzy_refs": [], "normalized_refs": [], "feature_refs": []},
            )
            profile_bucket["float_refs"].append(patch_f32)
            profile_bucket["fuzzy_refs"].append(self.fuzzy_match_patch(patch_f32))
            profile_bucket["normalized_refs"].append(self.normalize_match_patch(patch_f32))
            profile_bucket["feature_refs"].append(self.patch_feature_vector(patch_f32))
            self.maybe_store_reference_template_profiles()

    def record_edge_case_artifact(
        self,
        event: str,
        arr: np.ndarray,
        cell: tuple[int, int],
        board_value: int | None,
    ) -> None:
        if self.geometry is None:
            return
        row, col = cell
        x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
        crop = arr[y0:y1, x0:x1]
        context_left = max(0, x0 - (x1 - x0))
        context_top = max(0, y0 - (y1 - y0))
        context_right = min(arr.shape[1], x1 + (x1 - x0))
        context_bottom = min(arr.shape[0], y1 + (y1 - y0))
        event_dir = EDGE_CASE_DIR / event.replace(":", "_")
        event_dir.mkdir(parents=True, exist_ok=True)
        base_name = f"{int(time.time() * 1000)}_r{row}_c{col}"
        try:
            Image.fromarray(crop).save(event_dir / f"{base_name}_cell.png")
            Image.fromarray(arr[context_top:context_bottom, context_left:context_right]).save(
                event_dir / f"{base_name}_context.png"
            )
        except Exception:
            pass

        label_hint: str | None = None
        if event.startswith("skip_visual_open_0"):
            label_hint = "empty"
        else:
            visual_hint = self.confident_visible_open_value(arr, row, col)
            if visual_hint is not None:
                label_hint = self.board_value_to_template_label(visual_hint)
            elif board_value is not None:
                label_hint = self.board_value_to_template_label(board_value)
        if label_hint == "empty" and event.startswith("skip_visual_open_0"):
            label_hint = None
        if label_hint is not None:
            self.save_special_template_library_sample(label_hint, crop, event, cell)
        if label_hint == "empty" and (
            event.startswith("late_visual_open_0")
            or "no_effect_budget_exhausted" in event
            or "wrong_target" in event
        ):
            try:
                open_empty_dir = OPEN_EMPTY_CASE_DIR / event.replace(":", "_")
                open_empty_dir.mkdir(parents=True, exist_ok=True)
                base_name = f"{int(time.time() * 1000)}_r{row}_c{col}"
                Image.fromarray(crop).save(open_empty_dir / f"{base_name}_cell.png")
                Image.fromarray(arr[context_top:context_bottom, context_left:context_right]).save(
                    open_empty_dir / f"{base_name}_context.png"
                )
            except Exception:
                pass
            self.save_template_library_sample("empty", crop)
        if "wrong_target" in event or "blocked_variant" in event or "no_effect" in event:
            self.precision_click_cells[cell] += 1

    def record_trusted_board_templates(
        self,
        arr: np.ndarray,
        before_board: np.ndarray | None,
        after_board: np.ndarray,
        flag_cell: tuple[int, int] | None = None,
    ) -> None:
        if self.geometry is None:
            return
        for row in range(after_board.shape[0]):
            for col in range(after_board.shape[1]):
                value = int(after_board[row, col])
                if value < 0:
                    continue
                if before_board is not None and int(before_board[row, col]) >= 0:
                    continue
                label = self.board_value_to_template_label(value)
                if label is None:
                    continue
                x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
                crop = arr[y0:y1, x0:x1]
                self.save_template_library_sample(label, crop)
        if flag_cell is not None and before_board is not None:
            row, col = flag_cell
            if int(after_board[row, col]) == STATE_FLAG:
                x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
                crop = arr[y0:y1, x0:x1]
                if self.cell_looks_visual_flag(arr, row, col):
                    self.save_template_library_sample("flag", crop)

    def record_open_empty_transition_samples(
        self,
        arr: np.ndarray,
        before_board: np.ndarray | None,
        after_board: np.ndarray,
        event: str,
        max_samples: int = 6,
    ) -> None:
        if self.geometry is None:
            return
        candidate_cells: list[tuple[float, int, int]] = []
        for row in range(after_board.shape[0]):
            for col in range(after_board.shape[1]):
                if int(after_board[row, col]) != STATE_EMPTY:
                    continue
                if before_board is not None and int(before_board[row, col]) >= 0:
                    continue
                shadow_weight = self.cell_shadow_weight(row, col)
                if shadow_weight < 0.08 and row not in {0, after_board.shape[0] - 1} and col not in {0, after_board.shape[1] - 1}:
                    continue
                candidate_cells.append((shadow_weight, row, col))
        if not candidate_cells:
            return
        candidate_cells.sort(reverse=True)
        candidate_cells = candidate_cells[: max_samples * 4]
        template_profiles = self.get_reference_template_profiles()
        saved = 0
        for shadow_weight, row, col in candidate_cells:
            if not self.cell_looks_open_empty(arr, row, col, template_profiles=template_profiles):
                continue
            if (
                shadow_weight < 0.18
                and not self.cell_looks_shadowed_open_empty(
                    arr,
                    row,
                    col,
                    template_profiles=template_profiles,
                )
            ):
                continue
            x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
            crop = arr[y0:y1, x0:x1]
            context_left = max(0, x0 - (x1 - x0))
            context_top = max(0, y0 - (y1 - y0))
            context_right = min(arr.shape[1], x1 + (x1 - x0))
            context_bottom = min(arr.shape[0], y1 + (y1 - y0))
            self.save_special_template_library_sample("empty", crop, event, (row, col))
            self.save_template_library_sample("empty", crop)
            try:
                open_empty_dir = OPEN_EMPTY_CASE_DIR / event.replace(":", "_")
                open_empty_dir.mkdir(parents=True, exist_ok=True)
                base_name = f"{int(time.time() * 1000)}_r{row}_c{col}"
                Image.fromarray(crop).save(open_empty_dir / f"{base_name}_cell.png")
                Image.fromarray(arr[context_top:context_bottom, context_left:context_right]).save(
                    open_empty_dir / f"{base_name}_context.png"
                )
            except Exception:
                pass
            saved += 1
            if saved >= max_samples:
                return

    def record_visible_trusted_templates(
        self,
        arr: np.ndarray,
        board: np.ndarray,
        confirmed_open_values: dict[tuple[int, int], int],
        placed_flag_cells: set[tuple[int, int]],
    ) -> None:
        if self.geometry is None:
            return
        target_labels = {
            label
            for label in ("empty", "1", "2", "3", "4", "flag")
            if self.template_library_sample_count(label) < min(MAX_TEMPLATE_LIBRARY_SAMPLES_PER_LABEL, 12)
        }
        if not target_labels:
            return
        template_profiles = self.get_reference_template_profiles()
        saved_per_label: dict[str, int] = defaultdict(int)
        for (row, col), value in confirmed_open_values.items():
            label = self.board_value_to_template_label(value)
            if label not in target_labels:
                continue
            if board[row, col] != value or saved_per_label[label] >= 2:
                continue
            if not self.cell_matches_expected_open_value(arr, row, col, value, template_profiles=template_profiles):
                continue
            x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
            self.save_template_library_sample(label, arr[y0:y1, x0:x1])
            saved_per_label[label] += 1
        if "flag" not in target_labels:
            return
        for row, col in placed_flag_cells:
            if board[row, col] != STATE_FLAG or saved_per_label["flag"] >= 2:
                continue
            x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
            crop = arr[y0:y1, x0:x1]
            if not self.cell_looks_visual_flag(arr, row, col):
                continue
            self.save_template_library_sample("flag", crop)
            saved_per_label["flag"] += 1

    def template_profile_cache_key(self) -> tuple:
        sample_files = sorted({filename for samples in TEMPLATE_SAMPLES.values() for filename, _ in samples})
        sample_file_state = [
            (filename, (ARTIFACT_DIR / filename).exists())
            for filename in sample_files
        ]
        library_state = []
        for label in TEMPLATE_LABELS:
            label_dir = self.template_library_label_dir(label)
            files = sorted(label_dir.glob("*.png"))
            latest_mtime = max((int(path.stat().st_mtime) for path in files), default=0)
            library_state.append((label, len(files), latest_mtime))
        special_library_state = []
        for label in TEMPLATE_LABELS:
            label_dir = self.special_template_library_label_dir(label)
            files = sorted(label_dir.glob("*.png"))
            latest_mtime = max((int(path.stat().st_mtime) for path in files), default=0)
            special_library_state.append((label, len(files), latest_mtime))
        return (
            TEMPLATE_PROFILE_CACHE_VERSION,
            TEMPLATE_LABELS,
            MIN_TEMPLATE_REFERENCES_PER_LABEL,
            MAX_RUNTIME_TEMPLATES_PER_LABEL,
            tuple(sample_file_state),
            tuple(library_state),
            tuple(special_library_state),
        )

    def load_cached_template_profiles(self) -> dict[str, dict[str, list[np.ndarray]]] | None:
        cache_path = self.template_profile_cache_path()
        if not cache_path.exists():
            return None
        try:
            with cache_path.open("rb") as handle:
                payload = pickle.load(handle)
        except Exception:
            return None
        if not isinstance(payload, dict) or payload.get("key") != self.template_profile_cache_key():
            return None
        profiles = payload.get("profiles")
        if not isinstance(profiles, dict):
            return None
        return profiles

    def store_cached_template_profiles(self, profiles: dict[str, dict[str, list[np.ndarray]]]) -> None:
        cache_path = self.template_profile_cache_path()
        payload = {
            "key": self.template_profile_cache_key(),
            "profiles": profiles,
        }
        try:
            with cache_path.open("wb") as handle:
                pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception:
            return

    def maybe_store_reference_template_profiles(self, force: bool = False) -> None:
        if self.reference_template_profiles is None:
            return
        now = time.time()
        if not force and now - self.last_template_profile_store_at < TEMPLATE_PROFILE_STORE_INTERVAL_SECONDS:
            return
        self.store_cached_template_profiles(self.reference_template_profiles)
        self.last_template_profile_store_at = now

    def prewarm_reference_template_profiles(self) -> None:
        if self.reference_template_profiles is not None:
            return
        self.get_reference_template_profiles()

    def should_record_visible_templates(self, step: int, opened: int) -> bool:
        if step < VISIBLE_TEMPLATE_RECORD_MIN_STEP:
            return False
        if step > VISIBLE_TEMPLATE_RECORD_MAX_STEP:
            return False
        if step % VISIBLE_TEMPLATE_RECORD_STEP_INTERVAL != 0:
            return False
        if opened < VISIBLE_TEMPLATE_RECORD_MIN_OPENED:
            return False
        sample_target = min(MAX_TEMPLATE_LIBRARY_SAMPLES_PER_LABEL, 12)
        return any(
            self.template_library_sample_count(label) < sample_target
            for label in ("empty", "1", "2", "3", "4", "flag")
        )

    def harvest_runtime_templates(self, templates: dict[str, list[np.ndarray]]) -> None:
        needed = {
            label
            for label in TEMPLATE_LABELS
            if len(templates.get(label, [])) < MIN_TEMPLATE_REFERENCES_PER_LABEL
        }
        if not needed:
            return

        for path in self.runtime_template_candidate_paths():
            try:
                arr = np.array(Image.open(path).convert("RGB"))
                geometry = self.refine_geometry(arr, self.detect_geometry(arr))
            except Exception:
                continue
            for row in range(geometry.rows):
                for col in range(geometry.cols):
                    x0, y0, x1, y1 = geometry.cell_rect_local(row, col)
                    crop = arr[y0:y1, x0:x1]
                    label = self.template_label_from_crop(crop)
                    if label is None or label not in needed:
                        continue
                    bucket = templates.setdefault(label, [])
                    if len(bucket) >= max(MIN_TEMPLATE_REFERENCES_PER_LABEL, MAX_RUNTIME_TEMPLATES_PER_LABEL):
                        continue
                    bucket.append(self.normalize_cell_patch(crop))
                    if len(bucket) >= MIN_TEMPLATE_REFERENCES_PER_LABEL:
                        needed.discard(label)
            if not needed:
                return

    def get_reference_templates(self) -> dict[str, list[np.ndarray]]:
        if self.reference_templates is not None:
            return self.reference_templates
        templates: dict[str, list[np.ndarray]] = defaultdict(list)
        for label, samples in TEMPLATE_SAMPLES.items():
            for filename, (row, col) in samples:
                path = ARTIFACT_DIR / filename
                if not path.exists():
                    continue
                arr = np.array(Image.open(path).convert("RGB"))
                geometry = self.detect_geometry(arr)
                x0, y0, x1, y1 = geometry.cell_rect_local(row, col)
                crop = arr[y0:y1, x0:x1]
                patch = self.normalize_cell_patch(crop)
                if label == "flag" and not self.patch_looks_flag_symbol(patch):
                    continue
                if label == "3" and not self.patch_looks_red_digit_three(patch):
                    continue
                templates[label].append(patch)
        for label in TEMPLATE_LABELS:
            for path in sorted(self.template_library_label_dir(label).glob("*.png")):
                try:
                    crop = np.array(Image.open(path).convert("RGB"))
                except Exception:
                    continue
                if label == "flag" and not self.patch_looks_flag_symbol(crop):
                    continue
                if label == "3" and not self.patch_looks_red_digit_three(crop):
                    continue
                templates[label].append(crop)
            if label == "empty":
                continue
            for path in sorted(self.special_template_library_label_dir(label).glob("*.png")):
                try:
                    crop = np.array(Image.open(path).convert("RGB"))
                except Exception:
                    continue
                if label == "flag" and not self.patch_looks_flag_symbol(crop):
                    continue
                if label == "3" and not self.patch_looks_red_digit_three(crop):
                    continue
                templates[label].append(crop)
        self.harvest_runtime_templates(templates)
        self.reference_templates = dict(templates)
        self.reference_template_profiles = None
        return self.reference_templates

    def get_reference_template_profiles(self) -> dict[str, dict[str, list[np.ndarray]]]:
        if self.reference_template_profiles is not None:
            return self.reference_template_profiles
        cached_profiles = self.load_cached_template_profiles()
        if cached_profiles is not None:
            self.reference_template_profiles = cached_profiles
            return cached_profiles
        templates = self.get_reference_templates()
        profiles: dict[str, dict[str, list[np.ndarray]]] = {}
        for label, refs in templates.items():
            if not refs:
                continue
            float_refs = [ref.astype(np.float32) for ref in refs]
            fuzzy_refs = [self.fuzzy_match_patch(ref) for ref in float_refs]
            normalized_refs = [self.normalize_match_patch(ref) for ref in float_refs]
            feature_refs = [self.patch_feature_vector(ref) for ref in float_refs]
            profiles[label] = {
                "float_refs": float_refs,
                "fuzzy_refs": fuzzy_refs,
                "normalized_refs": normalized_refs,
                "feature_refs": feature_refs,
            }
        self.reference_template_profiles = profiles
        self.store_cached_template_profiles(profiles)
        return profiles

    def classify_cell(
        self,
        arr: np.ndarray,
        row: int,
        col: int,
        template_profiles: dict[str, dict[str, list[np.ndarray]]] | None = None,
    ) -> int:
        x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)  # type: ignore[union-attr]
        crop = arr[y0:y1, x0:x1]
        core = self.cell_core(crop)
        patch = self.normalize_cell_patch(crop)
        flag_like = self.cell_looks_flag_symbol(core) or self.patch_looks_flag_symbol(patch)
        red_three_like = self.cell_looks_red_digit_three(core) or self.patch_looks_red_digit_three(patch)
        shadow_weight = self.cell_shadow_weight(row, col)
        luminance = np.mean(core, axis=2)
        channel_diff = np.max(core, axis=2) - np.min(core, axis=2)
        dark_pixels = np.sum(np.mean(core, axis=2) < 70)
        bright_pixels = np.sum(np.mean(core, axis=2) > 215)
        red_pixels = np.sum((core[:, :, 0] > 160) & (core[:, :, 1] < 110) & (core[:, :, 2] < 110))
        grayish_pixels = np.sum((channel_diff < 18) & (luminance > 168))
        colorful = core[channel_diff > 40]
        mean_rgb = core.mean(axis=(0, 1))
        std_rgb = core.std(axis=(0, 1))
        maybe_shadowed_empty = (
            red_pixels == 0
            and mean_rgb[0] > 160 - shadow_weight * 12.0
            and mean_rgb[1] > 168 - shadow_weight * 12.0
            and mean_rgb[2] > 200 - shadow_weight * 10.0
            and std_rgb[0] < 20
            and std_rgb[1] < 20
            and std_rgb[2] < 14
        )
        bright_shadow_empty_candidate = (
            red_pixels == 0
            and dark_pixels < 10 + shadow_weight * 8.0
            and bright_pixels < 12 + shadow_weight * 8.0
            and len(colorful) > 420
            and mean_rgb[0] > 170 - shadow_weight * 10.0
            and mean_rgb[1] > 178 - shadow_weight * 10.0
            and mean_rgb[2] > 210 - shadow_weight * 8.0
            and std_rgb[0] < 8.2
            and std_rgb[1] < 8.2
            and std_rgb[2] < 4.6
        )

        if flag_like:
            return STATE_FLAG
        if bright_shadow_empty_candidate:
            return STATE_EMPTY
        shadow_empty_candidate = (
            shadow_weight >= 0.18
            and red_pixels < 24
            and dark_pixels < 30 + shadow_weight * 10.0
            and len(colorful) < 220
            and grayish_pixels > 120
            and mean_rgb[0] > 148 - shadow_weight * 18.0
            and mean_rgb[1] > 158 - shadow_weight * 16.0
            and mean_rgb[2] > 192 - shadow_weight * 12.0
        )
        if shadow_empty_candidate and self.cell_looks_shadowed_open_empty(arr, row, col, template_profiles=template_profiles):
            return STATE_EMPTY
        if (
            red_pixels == 0
            and dark_pixels < 40
            and bright_pixels < 40
            and len(colorful) > 500
            and std_rgb[0] < 18
            and std_rgb[1] < 18
            and std_rgb[2] < 12
        ):
            if maybe_shadowed_empty and self.cell_looks_shadowed_open_empty(
                arr,
                row,
                col,
                template_profiles=template_profiles,
            ):
                return STATE_EMPTY
            return STATE_HIDDEN
        if (
            red_pixels == 0
            and len(colorful) < 20
            and dark_pixels < 40
            and mean_rgb[0] > 185
            and mean_rgb[1] > 195
            and mean_rgb[2] > 215
            and std_rgb[0] < 8
            and std_rgb[1] < 8
            and std_rgb[2] < 8
        ):
            return STATE_EMPTY

        template_profiles = template_profiles or self.get_reference_template_profiles()
        template_scores = self.template_match_details(patch, template_profiles)
        if template_scores:
            ordered = sorted(template_scores.items(), key=lambda item: item[1]["combined"])
            best_label, best_details = ordered[0]
            best_score = float(best_details["combined"])
            second_score = float(ordered[1][1]["combined"]) if len(ordered) > 1 else best_score + 999.0
            hidden_score = float(template_scores.get("hidden", {}).get("combined", best_score + 999.0))
            if best_label == "flag" and not flag_like:
                fallback_label = next((label for label, _details in ordered[1:] if label != "flag"), "hidden")
                best_label = "3" if red_three_like else fallback_label
                best_score = float(template_scores.get(best_label, best_details)["combined"])
            if best_label == "flag" and red_pixels < 70 and not self.patch_looks_flag_symbol(patch):
                fallback_label = next((label for label, _details in ordered[1:] if label != "flag"), "hidden")
                best_label = "3" if red_three_like else fallback_label
                best_score = float(template_scores.get(best_label, best_details)["combined"])
            if best_label == "4" and hidden_score - best_score < 14.0:
                best_label = "hidden"
                best_score = hidden_score
            if (
                best_label != "hidden"
                and (best_score + 18.0 < second_score or best_score < 52.0 - shadow_weight * 4.0)
            ) or (
                best_label == "hidden"
                and len(colorful) < 40
                and (best_score + 16.0 < second_score or best_score < 46.0 + shadow_weight * 8.0)
            ):
                if best_label == "hidden":
                    return STATE_HIDDEN
                if best_label == "empty":
                    return STATE_EMPTY
                if best_label == "flag":
                    return STATE_FLAG
                if best_label.isdigit():
                    return int(best_label)

        if flag_like:
            return STATE_FLAG
        if red_three_like:
            return 3
        if bright_pixels > max(110, 150 - int(round(35 * shadow_weight))) and len(colorful) < 80:
            return STATE_EMPTY
        if bright_pixels < 40 + int(round(18 * shadow_weight)) and len(colorful) > max(380, 500 - int(round(90 * shadow_weight))):
            if maybe_shadowed_empty and self.cell_looks_shadowed_open_empty(
                arr,
                row,
                col,
                template_profiles=template_profiles,
            ):
                return STATE_EMPTY
            return STATE_HIDDEN
        if len(colorful) < 20:
            return STATE_EMPTY

        color_hits: dict[int, int] = {}
        for number, target in NUMBER_COLORS.items():
            diffs = np.linalg.norm(colorful.astype(np.float32) - target.astype(np.float32), axis=1)
            color_hits[number] = int(np.sum(diffs < 55))
        best_num = max(color_hits, key=color_hits.get)
        if color_hits[best_num] < 8:
            return STATE_EMPTY
        return best_num

    def read_board(self, arr: np.ndarray) -> np.ndarray:
        template_profiles = self.get_reference_template_profiles()
        board = np.zeros((self.geometry.rows, self.geometry.cols), dtype=int)  # type: ignore[union-attr]
        for row in range(self.geometry.rows):  # type: ignore[union-attr]
            for col in range(self.geometry.cols):  # type: ignore[union-attr]
                board[row, col] = self.classify_cell(arr, row, col, template_profiles=template_profiles)
        return board

    def read_board_consensus(self, arr: np.ndarray, tag: str) -> tuple[np.ndarray, np.ndarray]:
        first_board = self.read_board(arr)
        boards = [first_board]
        latest_arr = arr
        time.sleep(CONSENSUS_INITIAL_WAIT_SECONDS)
        try:
            _, latest_arr = self.capture(f"{tag}_consensus_01.png")
        except RuntimeError:
            return first_board, latest_arr
        second_board = self.read_board(latest_arr)
        boards.append(second_board)

        if np.array_equal(first_board, second_board):
            return second_board, latest_arr

        for frame_idx in range(2, BOARD_CONSENSUS_FRAMES):
            time.sleep(CONSENSUS_EXTRA_WAIT_SECONDS)
            try:
                _, latest_arr = self.capture(f"{tag}_consensus_{frame_idx:02d}.png")
            except RuntimeError:
                break
            boards.append(self.read_board(latest_arr))

        board_stack = np.stack(boards, axis=0)
        consensus = np.zeros_like(boards[0])
        for row in range(consensus.shape[0]):
            for col in range(consensus.shape[1]):
                values = board_stack[:, row, col].tolist()
                counts = defaultdict(int)
                for value in values:
                    counts[int(value)] += 1
                consensus[row, col] = max(
                    counts.items(),
                    key=lambda item: (
                        item[1],
                        1 if item[0] >= 0 else 0,
                        -abs(item[0]),
                    ),
                )[0]
        return consensus, latest_arr

    def neighbors(self, row: int, col: int) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = row + dr, col + dc
                if 0 <= nr < self.geometry.rows and 0 <= nc < self.geometry.cols:  # type: ignore[union-attr]
                    result.append((nr, nc))
        return result

    @staticmethod
    def board_signature(board: np.ndarray) -> int:
        return hash(board.tobytes())

    def trim_board_caches(self) -> None:
        if len(self.constraint_cache) >= MAX_BOARD_ANALYSIS_CACHE_ENTRIES:
            self.constraint_cache.clear()
        if len(self.rule_cache) >= MAX_BOARD_ANALYSIS_CACHE_ENTRIES:
            self.rule_cache.clear()
        if len(self.support_cache) >= MAX_BOARD_ANALYSIS_CACHE_ENTRIES:
            self.support_cache.clear()

    def support_count(self, board: np.ndarray, cell: tuple[int, int]) -> int:
        board_signature = self.board_signature(board)
        cached = self.support_cache.get(board_signature)
        if cached is None:
            cached = {}
            self.support_cache[board_signature] = cached
            self.trim_board_caches()
        if cell not in cached:
            row, col = cell
            cached[cell] = sum(1 for nr, nc in self.neighbors(row, col) if board[nr, nc] > 0)
        return cached[cell]

    def open_priority_key(
        self,
        board: np.ndarray,
        cell: tuple[int, int],
        rule_backed: bool = False,
    ) -> tuple[int, int, float, int, int]:
        shadow_weight = self.cell_shadow_weight(cell[0], cell[1])
        center_bias = abs(cell[0] - board.shape[0] // 2) + abs(cell[1] - board.shape[1] // 2)
        return (
            0 if rule_backed else 1,
            -self.support_count(board, cell),
            shadow_weight,
            center_bias,
            cell[0] * 100 + cell[1],
        )

    def prune_conflicting_virtual_flags(
        self,
        board: np.ndarray,
        virtual_flags: set[tuple[int, int]],
    ) -> set[tuple[int, int]]:
        pruned = set(virtual_flags)
        changed = True
        while changed:
            changed = False
            offenders: list[tuple[int, int, int]] = []
            for row in range(board.shape[0]):
                for col in range(board.shape[1]):
                    value = int(board[row, col])
                    if value <= 0:
                        continue
                    flagged_neighbors = [(nr, nc) for nr, nc in self.neighbors(row, col) if (nr, nc) in pruned]
                    if len(flagged_neighbors) <= value:
                        continue
                    for cell in flagged_neighbors:
                        offenders.append((self.support_count(board, cell), cell[0], cell[1]))
            if offenders:
                _, row, col = min(offenders)
                pruned.discard((row, col))
                changed = True
        return pruned

    def opening_candidates(self) -> list[tuple[int, int]]:
        rows = self.geometry.rows  # type: ignore[union-attr]
        cols = self.geometry.cols  # type: ignore[union-attr]
        mid_r = rows // 2
        mid_c = cols // 2
        candidates = [
            (mid_r, mid_c),
            (mid_r - 1, mid_c),
            (mid_r + 1, mid_c),
            (mid_r, mid_c - 1),
            (mid_r, mid_c + 1),
            (rows // 4, cols // 4),
            (rows // 4, (3 * cols) // 4),
            ((3 * rows) // 4, cols // 4),
            ((3 * rows) // 4, (3 * cols) // 4),
            (rows // 3, cols // 2),
            ((2 * rows) // 3, cols // 2),
            (rows // 2, cols // 3),
            (rows // 2, (2 * cols) // 3),
            (0, 0),
            (0, cols - 1),
            (rows - 1, 0),
            (rows - 1, cols - 1),
            (1, 1),
            (1, cols - 2),
            (rows - 2, 1),
            (rows - 2, cols - 2),
        ]
        seen = set()
        unique: list[tuple[int, int]] = []
        for row, col in candidates:
            row = max(0, min(rows - 1, row))
            col = max(0, min(cols - 1, col))
            cell = (row, col)
            if cell not in seen:
                unique.append(cell)
                seen.add(cell)
        preference = {cell: idx for idx, cell in enumerate(unique)}
        unique.sort(key=lambda cell: (self.failed_openers[cell], preference[cell], random.random()))
        return unique

    @staticmethod
    def forbidden_open_cells(
        clicked_open_cells: set[tuple[int, int]],
        ever_open_cells: set[tuple[int, int]],
        confirmed_open_values: dict[tuple[int, int], int],
        excluded_cells: set[tuple[int, int]] | None = None,
    ) -> set[tuple[int, int]]:
        blocked = set(clicked_open_cells) | set(ever_open_cells) | set(confirmed_open_values)
        if excluded_cells:
            blocked |= set(excluded_cells)
        return blocked

    @staticmethod
    def active_open_cooldown_cells(
        board: np.ndarray,
        cooldowns: dict[tuple[int, int], int],
        step: int,
    ) -> set[tuple[int, int]]:
        active: set[tuple[int, int]] = set()
        for cell, expires_at in list(cooldowns.items()):
            row, col = cell
            if (
                expires_at <= step
                or not (0 <= row < board.shape[0] and 0 <= col < board.shape[1])
                or board[row, col] != STATE_HIDDEN
            ):
                cooldowns.pop(cell, None)
                continue
            active.add(cell)
        return active

    @staticmethod
    def extend_open_cell_cooldown(
        cooldowns: dict[tuple[int, int], int],
        cell: tuple[int, int],
        step: int,
        cooldown_steps: int = 4,
    ) -> None:
        cooldowns[cell] = max(cooldowns.get(cell, step), step + cooldown_steps)

    def can_open_cell(
        self,
        cell: tuple[int, int],
        board: np.ndarray,
        clicked_open_cells: set[tuple[int, int]],
        ever_open_cells: set[tuple[int, int]],
        confirmed_open_values: dict[tuple[int, int], int],
        excluded_cells: set[tuple[int, int]] | None = None,
    ) -> bool:
        if cell in self.forbidden_open_cells(clicked_open_cells, ever_open_cells, confirmed_open_values, excluded_cells):
            return False
        row, col = cell
        return board[row, col] == STATE_HIDDEN

    @staticmethod
    def prune_hidden_open_tracking(
        board: np.ndarray,
        clicked_open_cells: set[tuple[int, int]],
        ever_open_cells: set[tuple[int, int]],
        confirmed_open_values: dict[tuple[int, int], int],
    ) -> None:
        stale_hidden_cells = [
            cell
            for cell in (set(clicked_open_cells) | set(ever_open_cells) | set(confirmed_open_values))
            if 0 <= cell[0] < board.shape[0]
            and 0 <= cell[1] < board.shape[1]
            and board[cell] == STATE_HIDDEN
        ]
        for cell in stale_hidden_cells:
            clicked_open_cells.discard(cell)
            ever_open_cells.discard(cell)
            confirmed_open_values.pop(cell, None)

    @staticmethod
    def release_safe_open_candidates(
        board: np.ndarray,
        candidates: set[tuple[int, int]],
        clicked_open_cells: set[tuple[int, int]],
        ever_open_cells: set[tuple[int, int]],
        confirmed_open_values: dict[tuple[int, int], int],
        excluded_cells: set[tuple[int, int]],
    ) -> None:
        for cell in candidates:
            row, col = cell
            if not (0 <= row < board.shape[0] and 0 <= col < board.shape[1]):
                continue
            if board[row, col] != STATE_HIDDEN:
                continue
            clicked_open_cells.discard(cell)
            ever_open_cells.discard(cell)
            confirmed_open_values.pop(cell, None)

    def stable_candidates(
        self,
        candidates: list[tuple[int, int]],
        pending_counts: dict[tuple[int, int], int],
        confirm_frames: int,
        same_board_turns: int = 0,
        agreement_counts: dict[tuple[int, int], int] | None = None,
    ) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
        if not candidates:
            return [], {}
        active = set(candidates)
        refreshed_counts = {
            cell: count
            for cell, count in pending_counts.items()
            if cell in active
        }
        for cell in candidates:
            refreshed_counts[cell] = refreshed_counts.get(cell, 0) + 1
        confirmed: list[tuple[int, int]] = []
        for cell in candidates:
            threshold = max(1, confirm_frames)
            agreement = agreement_counts.get(cell, 1) if agreement_counts is not None else 1
            if agreement >= 2:
                threshold = 1
            elif same_board_turns > 0 and threshold > 1:
                threshold = max(1, threshold - min(same_board_turns, threshold - 1))
            if refreshed_counts[cell] >= threshold:
                confirmed.append(cell)
        return confirmed, refreshed_counts

    def try_opening_boost(
        self,
        arr: np.ndarray,
        board: np.ndarray,
        clicked_open_cells: set[tuple[int, int]],
        ever_open_cells: set[tuple[int, int]],
        confirmed_open_values: dict[tuple[int, int], int],
        excluded_cells: set[tuple[int, int]],
        opening_boost_clicks: int,
        step: int,
    ) -> tuple[np.ndarray | None, int, tuple[int, int] | None]:
        if opening_boost_clicks >= MAX_OPENING_BOOST_CLICKS:
            return None, opening_boost_clicks, None

        rows, cols = board.shape
        preferred = self.opening_candidates()
        extra_scatter = [
            (rows // 3, cols // 2),
            ((2 * rows) // 3, cols // 2),
            (rows // 2, cols // 3),
            (rows // 2, (2 * cols) // 3),
        ]
        candidates = []
        seen: set[tuple[int, int]] = set()
        for cell in preferred + extra_scatter:
            row, col = cell
            row = max(0, min(rows - 1, row))
            col = max(0, min(cols - 1, col))
            normalized = (row, col)
            if normalized not in seen:
                candidates.append(normalized)
                seen.add(normalized)

        for boost_row, boost_col in candidates:
            boost_cell = (boost_row, boost_col)
            if not self.can_open_cell(boost_cell, board, clicked_open_cells, ever_open_cells, confirmed_open_values, excluded_cells):
                continue
            arr, _post_open_board, click_result = self.attempt_open_action(
                arr,
                board,
                board_signature=hash(board.tobytes()),
                cell=boost_cell,
                tag=f"attempt_{self.attempt:02d}_opening_boost_{step:03d}.png",
                confirmed_open_values=confirmed_open_values,
                ever_open_cells=ever_open_cells,
            )
            if click_result == "synced" and _post_open_board is not None:
                self.record_trusted_open_values(board, _post_open_board, confirmed_open_values, ever_open_cells)
                self.record_trusted_board_templates(arr, board, _post_open_board)
                self.last_actions.append(f"opening_sync:{boost_row},{boost_col}")
                return arr, opening_boost_clicks, None
            if click_result in {"changed", "game_over_dialog", "lost"}:
                clicked_open_cells.add(boost_cell)
                if click_result == "changed" and _post_open_board is not None:
                    self.record_trusted_board_templates(arr, board, _post_open_board)
                opening_boost_clicks += 1
                self.last_actions.append(f"opening_boost:{boost_row},{boost_col}")
                return arr, opening_boost_clicks, boost_cell
            if click_result in {"no_effect", "blocked"}:
                excluded_cells.add(boost_cell)

        return None, MAX_OPENING_BOOST_CLICKS, None

    def deterministic_actions(self, board: np.ndarray) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        board_signature = self.board_signature(board)
        cached = self.rule_cache.get(board_signature)
        if cached is not None:
            det_open, det_flag, _subset_open, _subset_flag = cached
            return list(det_open), list(det_flag)
        to_open: set[tuple[int, int]] = set()
        to_flag: set[tuple[int, int]] = set()
        for row in range(board.shape[0]):
            for col in range(board.shape[1]):
                value = int(board[row, col])
                if value <= 0:
                    continue
                nbs = self.neighbors(row, col)
                hidden = [(r, c) for r, c in nbs if board[r, c] == STATE_HIDDEN]
                flagged = sum(1 for r, c in nbs if board[r, c] == STATE_FLAG)
                if hidden and value == flagged:
                    to_open.update(hidden)
                elif hidden and value == flagged + len(hidden):
                    to_flag.update(hidden)
        result = (tuple(sorted(to_open)), tuple(sorted(to_flag)))
        existing = self.rule_cache.get(board_signature)
        if existing is None:
            self.rule_cache[board_signature] = (result[0], result[1], tuple(), tuple())
        else:
            self.rule_cache[board_signature] = (result[0], result[1], existing[2], existing[3])
        self.trim_board_caches()
        return list(result[0]), list(result[1])

    def subset_inference_actions(self, board: np.ndarray) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        board_signature = self.board_signature(board)
        cached = self.rule_cache.get(board_signature)
        if cached is not None and (cached[2] or cached[3]):
            _det_open, _det_flag, subset_open, subset_flag = cached
            return list(subset_open), list(subset_flag)
        to_open: set[tuple[int, int]] = set()
        to_flag: set[tuple[int, int]] = set()
        constraints, _ = self.build_constraints(board)
        normalized: list[tuple[set[tuple[int, int]], int]] = []
        for cells, remain in constraints:
            cell_set = set(cells)
            if cell_set:
                normalized.append((cell_set, remain))

        for idx, (cells_a, remain_a) in enumerate(normalized):
            for jdx, (cells_b, remain_b) in enumerate(normalized):
                if idx == jdx or not cells_a or not cells_b:
                    continue
                if not cells_a.issubset(cells_b):
                    continue
                diff = cells_b - cells_a
                if not diff:
                    continue
                diff_remain = remain_b - remain_a
                if diff_remain < 0 or diff_remain > len(diff):
                    continue
                if diff_remain == 0:
                    to_open.update(diff)
                elif diff_remain == len(diff):
                    to_flag.update(diff)
        result = (tuple(sorted(to_open)), tuple(sorted(to_flag)))
        existing = self.rule_cache.get(board_signature)
        if existing is None:
            self.rule_cache[board_signature] = (tuple(), tuple(), result[0], result[1])
        else:
            self.rule_cache[board_signature] = (existing[0], existing[1], result[0], result[1])
        self.trim_board_caches()
        return list(result[0]), list(result[1])

    def build_constraints(self, board: np.ndarray) -> tuple[list[tuple[list[tuple[int, int]], int]], set[tuple[int, int]]]:
        board_signature = self.board_signature(board)
        cached = self.constraint_cache.get(board_signature)
        if cached is not None:
            constraints, frontier = cached
            return list(constraints), set(frontier)
        constraints: list[tuple[list[tuple[int, int]], int]] = []
        frontier: set[tuple[int, int]] = set()
        for row in range(board.shape[0]):
            for col in range(board.shape[1]):
                value = int(board[row, col])
                if value <= 0:
                    continue
                nbs = self.neighbors(row, col)
                hidden = [(r, c) for r, c in nbs if board[r, c] == STATE_HIDDEN]
                if not hidden:
                    continue
                flagged = sum(1 for r, c in nbs if board[r, c] == STATE_FLAG)
                remain = value - flagged
                if remain < 0:
                    continue
                constraints.append((hidden, remain))
                frontier.update(hidden)
        self.constraint_cache[board_signature] = (list(constraints), set(frontier))
        self.trim_board_caches()
        return constraints, frontier

    def split_frontier_components(
        self,
        frontier: set[tuple[int, int]],
        constraints: list[tuple[list[tuple[int, int]], int]],
    ) -> list[tuple[list[tuple[int, int]], list[tuple[list[tuple[int, int]], int]]]]:
        if not frontier:
            return []
        cell_to_constraints: dict[tuple[int, int], list[int]] = defaultdict(list)
        for idx, (cells, _) in enumerate(constraints):
            for cell in cells:
                if cell in frontier:
                    cell_to_constraints[cell].append(idx)

        remaining = set(frontier)
        components: list[tuple[list[tuple[int, int]], list[tuple[list[tuple[int, int]], int]]]] = []
        while remaining:
            start = next(iter(remaining))
            queue = [start]
            comp_cells: set[tuple[int, int]] = set()
            comp_constraint_ids: set[int] = set()
            while queue:
                cell = queue.pop()
                if cell in comp_cells:
                    continue
                comp_cells.add(cell)
                remaining.discard(cell)
                for cid in cell_to_constraints.get(cell, []):
                    if cid in comp_constraint_ids:
                        continue
                    comp_constraint_ids.add(cid)
                    for other in constraints[cid][0]:
                        if other in frontier and other not in comp_cells:
                            queue.append(other)
            comp_constraints = [constraints[cid] for cid in sorted(comp_constraint_ids)]
            components.append((sorted(comp_cells), comp_constraints))
        return components

    def exact_component_probabilities(
        self,
        component_cells: list[tuple[int, int]],
        component_constraints: list[tuple[list[tuple[int, int]], int]],
    ) -> dict[tuple[int, int], float] | None:
        if not component_cells:
            return {}
        if len(component_cells) > MAX_EXACT_COMPONENT_CELLS:
            return None

        index = {cell: idx for idx, cell in enumerate(component_cells)}
        cell_constraints: list[list[int]] = [[] for _ in component_cells]
        normalized: list[tuple[list[int], int]] = []
        for cid, (cells, required) in enumerate(component_constraints):
            idxs = [index[cell] for cell in cells if cell in index]
            normalized.append((idxs, required))
            for idx in idxs:
                cell_constraints[idx].append(cid)

        assigned = [-1] * len(component_cells)
        remaining_unassigned = [len(cells) for cells, _ in normalized]
        assigned_mines = [0] * len(normalized)
        total_valid = 0
        mine_counts = [0] * len(component_cells)
        deadline = time.perf_counter() + MAX_EXACT_COMPONENT_SECONDS
        explored_states = 0
        aborted = False
        order = sorted(range(len(component_cells)), key=lambda idx: (-len(cell_constraints[idx]), random.random()))

        def feasible(cid: int) -> bool:
            _, required = normalized[cid]
            mines = assigned_mines[cid]
            rem = remaining_unassigned[cid]
            return mines <= required <= mines + rem

        def dfs(pos: int) -> None:
            nonlocal total_valid, explored_states, aborted
            if aborted:
                return
            explored_states += 1
            if explored_states > MAX_EXACT_DFS_STATES or time.perf_counter() > deadline:
                aborted = True
                return
            if pos == len(order):
                for cid, (_, required) in enumerate(normalized):
                    if assigned_mines[cid] != required:
                        return
                total_valid += 1
                for idx, value in enumerate(assigned):
                    if value == 1:
                        mine_counts[idx] += 1
                return

            idx = order[pos]
            for value in (0, 1):
                assigned[idx] = value
                touched = []
                ok = True
                for cid in cell_constraints[idx]:
                    remaining_unassigned[cid] -= 1
                    assigned_mines[cid] += value
                    touched.append(cid)
                    if not feasible(cid):
                        ok = False
                        break
                if ok:
                    dfs(pos + 1)
                for cid in touched:
                    assigned_mines[cid] -= value
                    remaining_unassigned[cid] += 1
                assigned[idx] = -1

        dfs(0)
        if aborted or total_valid == 0:
            return None
        return {
            component_cells[idx]: mine_counts[idx] / total_valid
            for idx in range(len(component_cells))
        }

    def grouped_component_probabilities(
        self,
        component_cells: list[tuple[int, int]],
        component_constraints: list[tuple[list[tuple[int, int]], int]],
    ) -> dict[tuple[int, int], float] | None:
        if not component_cells:
            return {}

        index = {cell: idx for idx, cell in enumerate(component_cells)}
        normalized_constraints: list[tuple[list[int], int]] = []
        membership_sets: list[list[int]] = [[] for _ in component_cells]
        for cid, (cells, required) in enumerate(component_constraints):
            idxs = [index[cell] for cell in cells if cell in index]
            normalized_constraints.append((idxs, required))
            for idx in idxs:
                membership_sets[idx].append(cid)

        area_map: dict[tuple[int, ...], list[tuple[int, int]]] = defaultdict(list)
        for idx, memberships in enumerate(membership_sets):
            area_map[tuple(sorted(memberships))].append(component_cells[idx])

        areas = list(area_map.values())
        if len(areas) > MAX_GROUPED_COMPONENT_AREAS:
            return None

        area_sizes = [len(area) for area in areas]
        area_index_by_signature = {
            signature: area_idx
            for area_idx, signature in enumerate(area_map.keys())
        }
        constraint_to_areas: list[tuple[list[int], int]] = []
        for idxs, required in normalized_constraints:
            area_indexes = sorted({
                area_index_by_signature[tuple(sorted(membership_sets[idx]))]
                for idx in idxs
            })
            constraint_to_areas.append((area_indexes, required))

        assignments = [0] * len(areas)
        total_weight = 0
        area_mine_weight = [0] * len(areas)
        deadline = time.perf_counter() + MAX_GROUPED_COMPONENT_SECONDS
        explored_states = 0
        aborted = False

        def feasible() -> bool:
            for area_indexes, required in constraint_to_areas:
                assigned = 0
                remaining = 0
                for area_idx in area_indexes:
                    value = assignments[area_idx]
                    if value >= 0:
                        assigned += value
                    else:
                        remaining += area_sizes[area_idx]
                if assigned > required:
                    return False
                if assigned + remaining < required:
                    return False
            return True

        area_domains = [list(range(size + 1)) for size in area_sizes]
        order = sorted(range(len(areas)), key=lambda idx: (len(areas[idx]), idx))
        assignments = [-1] * len(areas)

        def dfs(pos: int) -> None:
            nonlocal total_weight, explored_states, aborted
            if aborted:
                return
            explored_states += 1
            if explored_states > MAX_GROUPED_DFS_STATES or time.perf_counter() > deadline:
                aborted = True
                return
            if pos == len(order):
                for area_indexes, required in constraint_to_areas:
                    total = sum(assignments[area_idx] for area_idx in area_indexes)
                    if total != required:
                        return
                weight = 1
                for area_idx, mines in enumerate(assignments):
                    weight *= math.comb(area_sizes[area_idx], mines)
                total_weight += weight
                for area_idx, mines in enumerate(assignments):
                    area_mine_weight[area_idx] += weight * mines
                return

            area_idx = order[pos]
            for mines in area_domains[area_idx]:
                assignments[area_idx] = mines
                if feasible():
                    dfs(pos + 1)
                assignments[area_idx] = -1

        dfs(0)
        if aborted or total_weight == 0:
            return None

        probabilities: dict[tuple[int, int], float] = {}
        for area_idx, cells in enumerate(areas):
            cell_probability = area_mine_weight[area_idx] / (total_weight * area_sizes[area_idx])
            for cell in cells:
                probabilities[cell] = cell_probability
        return probabilities

    def frontier_probabilities(
        self,
        board: np.ndarray,
    ) -> tuple[
        dict[tuple[int, int], float],
        float,
        set[tuple[int, int]],
        set[tuple[int, int]],
    ]:
        board_signature = hash(board.tobytes())
        cached = self.frontier_cache.get(board_signature)
        if cached is not None:
            combined_risks, global_risk, exact_safe_open, exact_safe_flag = cached
            return dict(combined_risks), global_risk, set(exact_safe_open), set(exact_safe_flag)
        hidden_cells = {
            (r, c)
            for r in range(board.shape[0])
            for c in range(board.shape[1])
            if board[r, c] == STATE_HIDDEN
        }
        flagged_count = int(np.sum(board == STATE_FLAG))
        remaining_mines = max(0, TOTAL_MINES - flagged_count)
        global_risk = remaining_mines / max(1, len(hidden_cells))
        constraints, frontier = self.build_constraints(board)
        combined_risks: dict[tuple[int, int], float] = {}
        exact_safe_open: set[tuple[int, int]] = set()
        exact_safe_flag: set[tuple[int, int]] = set()

        for component_cells, component_constraints in self.split_frontier_components(frontier, constraints):
            exact = self.exact_component_probabilities(component_cells, component_constraints)
            if exact is not None:
                combined_risks.update(exact)
                exact_safe_open.update(
                    cell for cell, probability in exact.items() if probability <= 1e-9
                )
                exact_safe_flag.update(
                    cell for cell, probability in exact.items() if probability >= 1.0 - 1e-9
                )
            else:
                grouped = self.grouped_component_probabilities(component_cells, component_constraints)
                if grouped is not None:
                    combined_risks.update(grouped)
                    exact_safe_open.update(
                        cell for cell, probability in grouped.items() if probability <= 1e-9
                    )
                    exact_safe_flag.update(
                        cell for cell, probability in grouped.items() if probability >= 1.0 - 1e-9
                    )
                else:
                    combined_risks.update(
                        self.heuristic_frontier_risks(set(component_cells), component_constraints, global_risk)
                    )

        non_frontier_hidden = hidden_cells - frontier
        if non_frontier_hidden:
            frontier_expected_mines = sum(
                max(0.0, min(1.0, combined_risks.get(cell, global_risk)))
                for cell in frontier
                if cell in hidden_cells
            )
            non_frontier_remaining_mines = max(0.0, min(float(remaining_mines), float(remaining_mines) - frontier_expected_mines))
            non_frontier_risk = max(0.0, min(1.0, non_frontier_remaining_mines / max(1, len(non_frontier_hidden))))
        else:
            non_frontier_risk = global_risk
        for cell in hidden_cells:
            combined_risks.setdefault(cell, non_frontier_risk if cell in non_frontier_hidden else global_risk)
        result = (dict(combined_risks), global_risk, set(exact_safe_open), set(exact_safe_flag))
        if len(self.frontier_cache) >= MAX_FRONTIER_CACHE_ENTRIES:
            self.frontier_cache.clear()
        self.frontier_cache[board_signature] = result
        return dict(combined_risks), global_risk, set(exact_safe_open), set(exact_safe_flag)

    def reconfirm_csp_actions(
        self,
        arr: np.ndarray,
        board: np.ndarray,
        csp_open: set[tuple[int, int]],
        csp_flag: set[tuple[int, int]],
        tag: str,
        confirmed_open_values: dict[tuple[int, int], int],
        ever_open_cells: set[tuple[int, int]],
        placed_flag_cells: set[tuple[int, int]],
    ) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]], list[tuple[int, int]]]:
        refreshed_board, refreshed_arr = self.read_board_consensus(arr, f"{tag}_reconfirm")
        refreshed_board, _ = self.merge_solver_board_state(
            refreshed_board,
            confirmed_open_values,
            ever_open_cells,
            placed_flag_cells,
            refreshed_arr,
        )
        _risks, _global_risk, refreshed_open, refreshed_flag = self.frontier_probabilities(refreshed_board)
        stable_open = sorted(set(csp_open) & set(refreshed_open))
        stable_flag = sorted(set(csp_flag) & set(refreshed_flag))
        return refreshed_arr, refreshed_board, stable_open, stable_flag

    def reconfirm_rule_actions(
        self,
        arr: np.ndarray,
        board: np.ndarray,
        det_open: set[tuple[int, int]],
        det_flag: set[tuple[int, int]],
        subset_open: set[tuple[int, int]],
        subset_flag: set[tuple[int, int]],
        tag: str,
        confirmed_open_values: dict[tuple[int, int], int],
        ever_open_cells: set[tuple[int, int]],
        placed_flag_cells: set[tuple[int, int]],
    ) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]]]:
        refreshed_board, refreshed_arr = self.read_board_consensus(arr, f"{tag}_rules_reconfirm")
        refreshed_board, _ = self.merge_solver_board_state(
            refreshed_board,
            confirmed_open_values,
            ever_open_cells,
            placed_flag_cells,
            refreshed_arr,
        )
        refreshed_det_open, refreshed_det_flag = self.deterministic_actions(refreshed_board)
        refreshed_subset_open, refreshed_subset_flag = self.subset_inference_actions(refreshed_board)
        stable_det_open = sorted(set(det_open) & set(refreshed_det_open))
        stable_det_flag = sorted(set(det_flag) & set(refreshed_det_flag))
        stable_subset_open = sorted(set(subset_open) & set(refreshed_subset_open))
        stable_subset_flag = sorted(set(subset_flag) & set(refreshed_subset_flag))
        return (
            refreshed_arr,
            refreshed_board,
            stable_det_open,
            stable_det_flag,
            stable_subset_open,
            stable_subset_flag,
        )

    def heuristic_frontier_risks(
        self,
        frontier: set[tuple[int, int]],
        constraints: list[tuple[list[tuple[int, int]], int]],
        global_risk: float,
    ) -> dict[tuple[int, int], float]:
        risks: dict[tuple[int, int], list[float]] = defaultdict(list)
        for cells, remain in constraints:
            if not cells:
                continue
            local_risk = max(0.0, min(1.0, remain / len(cells)))
            for cell in cells:
                if cell in frontier:
                    risks[cell].append(local_risk)
        return {
            cell: max(global_risk, sum(vals) / len(vals)) if vals else global_risk
            for cell, vals in risks.items()
        }

    def guess_cell(
        self,
        board: np.ndarray,
        blocked_cells: set[tuple[int, int]] | None = None,
    ) -> tuple[int, int]:
        blocked = blocked_cells or set()
        hidden_cells = {
            (r, c)
            for r in range(board.shape[0])
            for c in range(board.shape[1])
            if board[r, c] == STATE_HIDDEN and (r, c) not in blocked
        }
        if not hidden_cells:
            raise RuntimeError("没有可用于猜测的隐藏格")
        combined_risks, global_risk, _, _ = self.frontier_probabilities(board)
        opened_cells = int(np.sum(board >= 0))
        _, frontier = self.build_constraints(board)

        for cell in hidden_cells:
            combined_risks.setdefault(cell, global_risk)

        if opened_cells < 30:
            for candidate in self.opening_candidates():
                if candidate in hidden_cells:
                    return candidate

        min_risk = min(combined_risks[cell] for cell in hidden_cells)
        best_safety = 1.0 - min_risk
        cutoff_safety = best_safety * 0.90
        candidates = [
            cell
            for cell in hidden_cells
            if (1.0 - combined_risks[cell]) >= cutoff_safety or combined_risks[cell] <= min_risk + 0.02
        ]
        non_frontier_hidden = [cell for cell in hidden_cells if cell not in frontier]
        opened_cells_set = {
            (r, c)
            for r in range(board.shape[0])
            for c in range(board.shape[1])
            if board[r, c] >= 0
        }
        rows, cols = board.shape
        corner_like_cells = {
            (0, 0), (0, cols - 1), (rows - 1, 0), (rows - 1, cols - 1),
            (1, 1), (1, cols - 2), (rows - 2, 1), (rows - 2, cols - 2),
        }
        edge_cells = {
            cell for cell in hidden_cells
            if cell[0] in {0, 1, rows - 2, rows - 1} or cell[1] in {0, 1, cols - 2, cols - 1}
        }

        def hidden_cluster_gain(cell: tuple[int, int], radius: int = 2) -> int:
            seen: set[tuple[int, int]] = set()
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    nr, nc = cell[0] + dr, cell[1] + dc
                    if 0 <= nr < rows and 0 <= nc < cols and board[nr, nc] == STATE_HIDDEN:
                        seen.add((nr, nc))
            return len(seen)

        def zero_probability(cell: tuple[int, int]) -> float:
            cells = {cell}
            for nb in self.neighbors(*cell):
                if board[nb] == STATE_HIDDEN:
                    cells.add(nb)
            prob = 1.0
            for item in cells:
                prob *= max(0.0, 1.0 - combined_risks.get(item, global_risk))
            return prob

        frontier_support = {
            cell: self.support_count(board, cell)
            for cell in hidden_cells
        }
        reference_cells = opened_cells_set or frontier or hidden_cells

        def unconstrained_score(cell: tuple[int, int]) -> tuple[float, float, int, int, int]:
            nearest_known = min(
                abs(cell[0] - other[0]) + abs(cell[1] - other[1])
                for other in reference_cells
                if other != cell
            )
            zero_chance = zero_probability(cell)
            opening_gain = hidden_cluster_gain(cell)
            expected_gain = zero_chance * opening_gain
            border_penalty = 0 if cell in corner_like_cells else (1 if cell in edge_cells else 2)
            center_bias = abs(cell[0] - board.shape[0] // 2) + abs(cell[1] - board.shape[1] // 2)
            return (
                combined_risks.get(cell, global_risk) + self.failed_guess_counts[cell] * 0.08,
                -expected_gain,
                -zero_chance,
                border_penalty,
                center_bias - nearest_known + self.failed_guess_counts[cell],
            )

        def secondary_safety(cell: tuple[int, int]) -> float:
            safe_neighbors = [
                1.0 - combined_risks.get(nb, global_risk)
                for nb in self.neighbors(*cell)
                if board[nb] == STATE_HIDDEN
            ]
            if not safe_neighbors:
                return 1.0 - combined_risks[cell]
            return (1.0 - combined_risks[cell]) * (sum(safe_neighbors) / len(safe_neighbors))

        def frontier_influence(cell: tuple[int, int]) -> int:
            return sum(1 for nb in self.neighbors(*cell) if board[nb] > 0)

        def candidate_score(cell: tuple[int, int]) -> tuple[float, float, float, float, int, int]:
            risk = combined_risks[cell] + self.failed_guess_counts[cell] * 0.08
            zero_chance = zero_probability(cell)
            influence = frontier_influence(cell)
            secondary = secondary_safety(cell)
            center_bias = abs(cell[0] - board.shape[0] // 2) + abs(cell[1] - board.shape[1] // 2)
            opening_gain = hidden_cluster_gain(cell)
            expected_gain = zero_chance * opening_gain
            return (risk, -expected_gain, -zero_chance, -secondary, -influence, center_bias + cell[0] * 100 + cell[1])

        if non_frontier_hidden and global_risk <= min_risk + 0.03:
            strategic_non_frontier = [
                cell for cell in non_frontier_hidden if combined_risks.get(cell, global_risk) <= min_risk + 0.03
            ]
            if strategic_non_frontier:
                return min(strategic_non_frontier, key=unconstrained_score)

        return min(candidates, key=candidate_score)

    @staticmethod
    def dialog_kind(arr: np.ndarray) -> str | None:
        h, w = arr.shape[:2]
        center = arr[int(h * 0.28):int(h * 0.72), int(w * 0.33):int(w * 0.67)]
        whiteish = np.sum((center[:, :, 0] > 220) & (center[:, :, 1] > 220) & (center[:, :, 2] > 220))
        blue_text = np.sum((center[:, :, 2] > 150) & (center[:, :, 1] > 100) & (center[:, :, 0] < 120))
        if whiteish <= 50000 or blue_text <= 600:
            return None
        button_gray = np.sum(
            (center[:, :, 0] > 170)
            & (center[:, :, 0] < 240)
            & ((np.max(center, axis=2) - np.min(center, axis=2)) < 25)
        )
        if button_gray > 30000:
            return "game_over_dialog"
        if button_gray > 8000:
            return "exit_game"
        return "new_game"

    def continue_game_dialog(self) -> None:
        if self.click_dialog_button(["\u65b0\u6e38\u620f"], ["\u7ee7\u7eed\u6e38\u620f", "K"]):
            return
        left, top, right, bottom = self.window_rect
        width = right - left
        height = bottom - top
        self.click_absolute_raw(left + int(width * 0.42), top + int(height * 0.57))

    def cancel_exit_dialog(self) -> None:
        if self.click_dialog_button(["\u9000\u51fa\u6e38\u620f"], ["\u53d6\u6d88"]):
            return
        left, top, right, bottom = self.window_rect
        width = right - left
        height = bottom - top
        self.click_absolute_raw(left + int(width * 0.58), top + int(height * 0.52))

    def play_again_dialog(self) -> None:
        try:
            self.ensure_window()
        except RuntimeError:
            self.reuse_existing_game = False
            return
        _, arr = self.capture(f"dialog_probe_attempt_{self.attempt:02d}.png")

        def restart_succeeded(probe: np.ndarray, tag: str) -> bool:
            if self.find_dialog_hwnd(["\u6e38\u620f\u5931\u8d25"]) is None:
                time.sleep(0.25)
                try:
                    _, confirm = self.capture(f"{tag}_confirm.png")
                except RuntimeError:
                    self.reuse_existing_game = False
                    return False
                if self.find_dialog_hwnd(["\u6e38\u620f\u5931\u8d25"]) is None:
                    confirm_dialog = self.dialog_kind(confirm)
                    if confirm_dialog != "game_over_dialog":
                        return True
            dialog = self.dialog_kind(probe)
            if dialog != "game_over_dialog":
                interruption = self.interruption_kind(probe)
                if interruption not in {"game_over_dialog", "lost"}:
                    return True
            return False

        def try_points(points: list[tuple[int, int]], prefix: str, mode: str) -> bool:
            for idx, (x, y) in enumerate(points):
                try:
                    self.click_absolute(x, y)
                except RuntimeError:
                    self.reuse_existing_game = False
                    return False
                time.sleep(0.55)
                try:
                    _, probe = self.capture(f"{prefix}_{self.attempt:02d}_{idx}.png")
                except RuntimeError:
                    self.reuse_existing_game = False
                    return False
                if restart_succeeded(probe, f"{prefix}_{self.attempt:02d}_{idx}"):
                    self.log_dialog_restart(mode, idx, (x, y))
                    return True
                try:
                    self.click_absolute_raw(x, y)
                except RuntimeError:
                    self.reuse_existing_game = False
                    return False
                time.sleep(0.45)
                try:
                    _, probe = self.capture(f"{prefix}_{self.attempt:02d}_{idx}_raw.png")
                except RuntimeError:
                    self.reuse_existing_game = False
                    return False
                if restart_succeeded(probe, f"{prefix}_{self.attempt:02d}_{idx}_raw"):
                    self.log_dialog_restart(mode, idx, (x, y))
                    return True
            return False

        if self.preferred_restart_point is not None:
            if try_points([self.preferred_restart_point], "dialog_probe_remembered", "play_again_remembered"):
                return

        h, w = arr.shape[:2]
        center = arr[int(h * 0.22):int(h * 0.78), int(w * 0.25):int(w * 0.75)]
        white_mask = (center[:, :, 0] > 220) & (center[:, :, 1] > 220) & (center[:, :, 2] > 220)
        rows = np.where(white_mask.sum(axis=1) > center.shape[1] * 0.45)[0]
        cols = np.where(white_mask.sum(axis=0) > center.shape[0] * 0.20)[0]
        if len(rows) and len(cols):
            dialog_left = int(w * 0.25) + int(cols[0])
            dialog_right = int(w * 0.25) + int(cols[-1])
            dialog_top = int(h * 0.22) + int(rows[0])
            dialog_bottom = int(h * 0.22) + int(rows[-1])
            dialog = arr[dialog_top:dialog_bottom + 1, dialog_left:dialog_right + 1]
            band = dialog[int(dialog.shape[0] * 0.72):int(dialog.shape[0] * 0.95)]
            mask = (
                (band[:, :, 0] > 160)
                & (band[:, :, 0] < 235)
                & ((np.max(band, axis=2) - np.min(band, axis=2)) < 22)
            )
            seen = np.zeros_like(mask, dtype=bool)
            components: list[tuple[int, int, int, int, int]] = []
            for row in range(mask.shape[0]):
                for col in range(mask.shape[1]):
                    if not mask[row, col] or seen[row, col]:
                        continue
                    stack = [(row, col)]
                    seen[row, col] = True
                    pts: list[tuple[int, int]] = []
                    while stack:
                        cur_row, cur_col = stack.pop()
                        pts.append((cur_row, cur_col))
                        for next_row, next_col in (
                            (cur_row - 1, cur_col),
                            (cur_row + 1, cur_col),
                            (cur_row, cur_col - 1),
                            (cur_row, cur_col + 1),
                        ):
                            if 0 <= next_row < mask.shape[0] and 0 <= next_col < mask.shape[1]:
                                if mask[next_row, next_col] and not seen[next_row, next_col]:
                                    seen[next_row, next_col] = True
                                    stack.append((next_row, next_col))
                    if len(pts) >= 200:
                        ys = [pt[0] for pt in pts]
                        xs = [pt[1] for pt in pts]
                        components.append((len(pts), min(xs), min(ys), max(xs), max(ys)))
            if components:
                sorted_components = sorted(components, key=lambda item: item[1])
                preferred_indices = [2, 1, 0]
                preferred_components = [
                    sorted_components[idx]
                    for idx in preferred_indices
                    if idx < len(sorted_components)
                ]
                for component in sorted_components:
                    if component not in preferred_components:
                        preferred_components.append(component)

                for click_index, (_, left, top, right, bottom) in enumerate(preferred_components):
                    button_left = self.window_rect[0] + dialog_left + left
                    button_right = self.window_rect[0] + dialog_left + right
                    button_top = self.window_rect[1] + dialog_top + int(dialog.shape[0] * 0.72) + top
                    button_bottom = self.window_rect[1] + dialog_top + int(dialog.shape[0] * 0.72) + bottom
                    button_width = max(1, button_right - button_left + 1)
                    button_height = max(1, button_bottom - button_top + 1)
                    inset_x = max(14, int(button_width * 0.22))
                    inset_y = max(8, int(button_height * 0.22))
                    inner_left = button_left + inset_x
                    inner_right = button_right - inset_x
                    inner_top = button_top + inset_y
                    inner_bottom = button_bottom - inset_y
                    if inner_left >= inner_right:
                        inner_left = button_left + int(button_width * 0.30)
                        inner_right = button_left + int(button_width * 0.70)
                    if inner_top >= inner_bottom:
                        inner_top = button_top + int(button_height * 0.30)
                        inner_bottom = button_top + int(button_height * 0.70)
                    center_x = (inner_left + inner_right) // 2
                    center_y = (inner_top + inner_bottom) // 2
                    probe_points = [
                        (center_x, center_y),
                        (inner_left, center_y),
                        (inner_right, center_y),
                        (center_x, inner_top),
                        (center_x, inner_bottom),
                    ]
                    mode = "play_again" if click_index == 0 else ("restart_same_board" if click_index == 1 else "exit_fallback")
                    if try_points(probe_points, f"dialog_probe_after_click_{click_index}", mode):
                        return
            else:
                fallback_points = [
                    (
                        self.window_rect[0] + dialog_left + int((dialog_right - dialog_left) * 0.68),
                        self.window_rect[1] + dialog_top + int((dialog_bottom - dialog_top) * 0.79),
                    ),
                    (
                        self.window_rect[0] + dialog_left + int((dialog_right - dialog_left) * 0.75),
                        self.window_rect[1] + dialog_top + int((dialog_bottom - dialog_top) * 0.79),
                    ),
                ]
                if try_points(fallback_points, "dialog_probe_fallback", "fallback"):
                    return
        else:
            left, top, right, bottom = self.window_rect
            width = right - left
            height = bottom - top
            generic_points = [
                (left + int(width * 0.55), top + int(height * 0.57)),
                (left + int(width * 0.60), top + int(height * 0.57)),
            ]
            try_points(generic_points, "dialog_probe_generic", "generic")
        try:
            self.launch_fresh_game()
            self.reuse_existing_game = True
        except RuntimeError:
            self.reuse_existing_game = False

    def detect_loss(self, arr: np.ndarray) -> bool:
        if self.geometry is None:
            return False
        for row in range(self.geometry.rows):
            for col in range(self.geometry.cols):
                x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
                crop = arr[y0:y1, x0:x1]
                center = crop[10:-10, 10:-10]
                red = np.sum((center[:, :, 0] > 170) & (center[:, :, 1] < 120) & (center[:, :, 2] < 120))
                dark = np.sum((center[:, :, 0] < 60) & (center[:, :, 1] < 60) & (center[:, :, 2] < 60))
                gray = np.sum(((np.max(center, axis=2) - np.min(center, axis=2)) < 20) & (center[:, :, 0] > 80) & (center[:, :, 0] < 190))
                if red > 120 and dark > 45:
                    return True
                if dark > 180 and gray > 120:
                    return True
        return False

    def interruption_kind(self, arr: np.ndarray) -> str | None:
        if self.find_minesweeper_hwnd() is None:
            return "process_missing"
        if self.find_dialog_hwnd(["\u6e38\u620f\u5931\u8d25"]) is not None:
            return "game_over_dialog"
        if self.find_dialog_hwnd(["\u9000\u51fa\u6e38\u620f"]) is not None:
            return "exit_game"
        if self.find_dialog_hwnd(["\u65b0\u6e38\u620f"]) is not None:
            return "new_game"
        if self.detect_loss(arr):
            return "lost"
        dialog = self.dialog_kind(arr)
        if dialog is not None:
            return dialog
        return None

    def board_progress(self, board: np.ndarray) -> tuple[int, int, int]:
        hidden = int(np.sum(board == STATE_HIDDEN))
        flagged = int(np.sum(board == STATE_FLAG))
        opened = int(np.sum(board >= 0))
        return hidden, flagged, opened

    @staticmethod
    def record_trusted_open_values(
        before_board: np.ndarray | None,
        after_board: np.ndarray,
        confirmed_open_values: dict[tuple[int, int], int],
        ever_open_cells: set[tuple[int, int]],
    ) -> None:
        for row in range(after_board.shape[0]):
            for col in range(after_board.shape[1]):
                value = int(after_board[row, col])
                if value < 0:
                    continue
                if before_board is not None and int(before_board[row, col]) >= 0:
                    continue
                confirmed_open_values[(row, col)] = value
                ever_open_cells.add((row, col))

    def merge_solver_board_state(
        self,
        raw_board: np.ndarray,
        confirmed_open_values: dict[tuple[int, int], int],
        ever_open_cells: set[tuple[int, int]],
        placed_flag_cells: set[tuple[int, int]] | None = None,
        arr: np.ndarray | None = None,
    ) -> tuple[np.ndarray, set[tuple[int, int]]]:
        board = raw_board.copy()
        trusted_flags = set(placed_flag_cells or set())
        observed_flag_cells: set[tuple[int, int]] = set()
        template_profiles = self.get_reference_template_profiles() if arr is not None else None
        for row in range(raw_board.shape[0]):
            for col in range(raw_board.shape[1]):
                value = int(raw_board[row, col])
                if value >= 0 and (row, col) in confirmed_open_values:
                    confirmed_open_values[(row, col)] = value
                    ever_open_cells.add((row, col))
                elif value == STATE_FLAG and (row, col) in trusted_flags:
                    observed_flag_cells.add((row, col))
                elif (
                    value == STATE_FLAG
                    and arr is not None
                    and self.cell_looks_visual_flag(arr, row, col, template_profiles=template_profiles)
                ):
                    board[row, col] = STATE_FLAG
                    observed_flag_cells.add((row, col))
                elif value == STATE_FLAG:
                    board[row, col] = STATE_HIDDEN
        for row, col in trusted_flags:
            if board[row, col] == STATE_HIDDEN:
                board[row, col] = STATE_FLAG
            observed_flag_cells.add((row, col))
        for (row, col), value in confirmed_open_values.items():
            if (
                board[row, col] == STATE_HIDDEN
                and arr is not None
                and self.cell_matches_expected_open_value(arr, row, col, value, template_profiles=template_profiles)
            ):
                board[row, col] = value
        if arr is not None:
            for row in range(board.shape[0]):
                for col in range(board.shape[1]):
                    if board[row, col] != STATE_HIDDEN:
                        continue
                    if (row, col) in trusted_flags:
                        continue
                    if not self.cell_looks_open_empty(arr, row, col, template_profiles=template_profiles):
                        continue
                    board[row, col] = STATE_EMPTY
                    confirmed_open_values[(row, col)] = STATE_EMPTY
                    ever_open_cells.add((row, col))
        return board, observed_flag_cells

    def local_board_signature(self, board: np.ndarray, cell: tuple[int, int]) -> tuple[int, ...]:
        cells = [cell] + self.neighbors(*cell)
        return tuple(int(board[row, col]) for row, col in cells)

    def local_visual_signature(self, arr: np.ndarray, cell: tuple[int, int]) -> tuple[int, ...]:
        assert self.geometry is not None
        cells = [cell] + self.neighbors(*cell)
        signature: list[int] = []
        for row, col in cells:
            x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
            crop = arr[y0:y1, x0:x1]
            core = self.cell_core(crop)
            mean_rgb = core.mean(axis=(0, 1))
            std_rgb = core.std(axis=(0, 1))
            red_pixels = int(np.sum((core[:, :, 0] > 160) & (core[:, :, 1] < 110) & (core[:, :, 2] < 110)))
            bright_pixels = int(np.sum(np.mean(core, axis=2) > 215))
            dark_pixels = int(np.sum(np.mean(core, axis=2) < 70))
            colorful = int(np.sum((np.max(core, axis=2) - np.min(core, axis=2)) > 40))
            signature.extend(
                [
                    int(round(mean_rgb[0])),
                    int(round(mean_rgb[1])),
                    int(round(mean_rgb[2])),
                    int(round(std_rgb[0])),
                    int(round(std_rgb[1])),
                    int(round(std_rgb[2])),
                    red_pixels // 10,
                    bright_pixels // 10,
                    dark_pixels // 10,
                    colorful // 10,
                ]
            )
        return tuple(signature)

    def cell_visual_metrics(self, arr: np.ndarray, row: int, col: int) -> dict[str, float | int]:
        assert self.geometry is not None
        x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
        crop = arr[y0:y1, x0:x1]
        core = self.cell_core(crop)
        luminance = np.mean(core, axis=2)
        channel_diff = np.max(core, axis=2) - np.min(core, axis=2)
        mean_rgb = core.mean(axis=(0, 1))
        std_rgb = core.std(axis=(0, 1))
        return {
            "mean_r": float(mean_rgb[0]),
            "mean_g": float(mean_rgb[1]),
            "mean_b": float(mean_rgb[2]),
            "std_r": float(std_rgb[0]),
            "std_g": float(std_rgb[1]),
            "std_b": float(std_rgb[2]),
            "red_pixels": int(np.sum((core[:, :, 0] > 160) & (core[:, :, 1] < 110) & (core[:, :, 2] < 110))),
            "bright_pixels": int(np.sum(luminance > 215)),
            "dark_pixels": int(np.sum(luminance < 70)),
            "colorful_pixels": int(np.sum(channel_diff > 40)),
            "grayish_pixels": int(np.sum((channel_diff < 18) & (luminance > 168))),
        }

    def cell_edge_profile(self, arr: np.ndarray, row: int, col: int) -> dict[str, float]:
        assert self.geometry is not None
        x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
        crop = arr[y0:y1, x0:x1].astype(np.float32)
        if crop.size == 0:
            return {
                "center_top_gap": 0.0,
                "center_bottom_gap": 0.0,
                "left_right_gap": 0.0,
                "top_bottom_gap": 0.0,
                "diag_gap": 0.0,
            }
        h, w = crop.shape[:2]
        edge = max(2, min(h, w) // 8)
        if h <= 2 * edge or w <= 2 * edge:
            center = crop
        else:
            center = crop[edge:-edge, edge:-edge]
        top = crop[:edge, :, :]
        bottom = crop[-edge:, :, :]
        left = crop[:, :edge, :]
        right = crop[:, -edge:, :]
        tl = crop[:edge, :edge, :]
        br = crop[-edge:, -edge:, :]

        def luminance_mean(region: np.ndarray) -> float:
            if region.size == 0:
                return 0.0
            return float(np.mean(np.mean(region, axis=2)))

        center_l = luminance_mean(center)
        top_l = luminance_mean(top)
        bottom_l = luminance_mean(bottom)
        left_l = luminance_mean(left)
        right_l = luminance_mean(right)
        tl_l = luminance_mean(tl)
        br_l = luminance_mean(br)
        return {
            "center_top_gap": center_l - top_l,
            "center_bottom_gap": center_l - bottom_l,
            "left_right_gap": left_l - right_l,
            "top_bottom_gap": top_l - bottom_l,
            "diag_gap": tl_l - br_l,
        }

    def cell_looks_shadowed_open_empty(
        self,
        arr: np.ndarray,
        row: int,
        col: int,
        template_profiles: dict[str, dict[str, list[np.ndarray]]] | None = None,
    ) -> bool:
        metrics = self.cell_visual_metrics(arr, row, col)
        shadow_weight = self.cell_shadow_weight(row, col)
        edge_profile = self.cell_edge_profile(arr, row, col)
        assert self.geometry is not None
        x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
        crop = arr[y0:y1, x0:x1]
        patch = self.normalize_cell_patch(crop)
        template_profiles = template_profiles or self.get_reference_template_profiles()
        scores = self.template_match_details(patch, template_profiles)
        if not scores:
            return False
        ordered = sorted(scores.items(), key=lambda item: item[1]["combined"])
        best_label, best_details = ordered[0]
        best_score = float(best_details["combined"])
        second_score = float(ordered[1][1]["combined"]) if len(ordered) > 1 else best_score + 999.0
        hidden_score = float(scores.get("hidden", {}).get("combined", best_score + 999.0))
        if best_label != "empty":
            return False
        return (
            int(metrics["red_pixels"]) < 24
            and int(metrics["dark_pixels"]) < 22 + int(round(14 * shadow_weight))
            and float(metrics["mean_r"]) > 168 - shadow_weight * 18.0
            and float(metrics["mean_g"]) > 176 - shadow_weight * 16.0
            and float(metrics["mean_b"]) > 209 - shadow_weight * 10.0
            and hidden_score - best_score > 40.0 - shadow_weight * 4.0
            and second_score - best_score > 40.0 - shadow_weight * 4.0
            and edge_profile["center_bottom_gap"] < 8.0 + shadow_weight * 6.0
            and edge_profile["center_top_gap"] > 58.0 - shadow_weight * 10.0
            and edge_profile["top_bottom_gap"] < -58.0 + shadow_weight * 12.0
            and edge_profile["diag_gap"] < -96.0 + shadow_weight * 20.0
        )

    def cell_looks_open_empty(
        self,
        arr: np.ndarray,
        row: int,
        col: int,
        template_profiles: dict[str, dict[str, list[np.ndarray]]] | None = None,
    ) -> bool:
        return self.cell_looks_flat_open(arr, row, col) or self.cell_looks_shadowed_open_empty(
            arr,
            row,
            col,
            template_profiles=template_profiles,
        )

    def cell_looks_flat_open(self, arr: np.ndarray, row: int, col: int) -> bool:
        metrics = self.cell_visual_metrics(arr, row, col)
        shadow_weight = self.cell_shadow_weight(row, col)
        max_std = max(float(metrics["std_r"]), float(metrics["std_g"]), float(metrics["std_b"]))
        blue_excess_r = float(metrics["mean_b"]) - float(metrics["mean_r"])
        blue_excess_g = float(metrics["mean_b"]) - float(metrics["mean_g"])
        return (
            int(metrics["red_pixels"]) < 40
            and int(metrics["dark_pixels"]) < 45 + int(round(28 * shadow_weight))
            and int(metrics["colorful_pixels"]) < 24 + int(round(10 * shadow_weight))
            and int(metrics["grayish_pixels"]) > 16 + int(round(34 * shadow_weight))
            and max_std < 10.5 + shadow_weight * 2.8
            and float(metrics["mean_r"]) > 174 - shadow_weight * 24.0
            and float(metrics["mean_g"]) > 182 - shadow_weight * 20.0
            and float(metrics["mean_b"]) > 208 - shadow_weight * 14.0
            and blue_excess_r < 44
            and blue_excess_g < 34
        )

    def confident_visible_open_value(
        self,
        arr: np.ndarray,
        row: int,
        col: int,
        template_profiles: dict[str, dict[str, list[np.ndarray]]] | None = None,
    ) -> int | None:
        if self.cell_looks_open_empty(arr, row, col, template_profiles=template_profiles):
            return STATE_EMPTY
        assert self.geometry is not None
        x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
        crop = arr[y0:y1, x0:x1]
        patch = self.normalize_cell_patch(crop)
        template_profiles = template_profiles or self.get_reference_template_profiles()
        scores = self.template_match_details(patch, template_profiles)
        if not scores:
            return None
        ordered = sorted(scores.items(), key=lambda item: item[1]["combined"])
        best_label, best_details = ordered[0]
        if best_label in {"hidden", "flag"}:
            return None
        best_score = float(best_details["combined"])
        second_score = float(ordered[1][1]["combined"]) if len(ordered) > 1 else best_score + 999.0
        hidden_score = float(scores.get("hidden", {}).get("combined", best_score + 999.0))
        if best_label == "empty":
            if self.cell_looks_open_empty(arr, row, col, template_profiles=template_profiles) and (
                best_score + 14.0 < second_score or hidden_score - best_score > 16.0
            ):
                return STATE_EMPTY
            return None
        if best_label.isdigit():
            if best_label == "3" and self.patch_looks_red_digit_three(patch) and hidden_score - best_score > 10.0:
                return int(best_label)
            if best_score + 16.0 < second_score and hidden_score - best_score > 10.0:
                return int(best_label)
        return None

    def cell_looks_visual_flag(
        self,
        arr: np.ndarray,
        row: int,
        col: int,
        template_profiles: dict[str, dict[str, list[np.ndarray]]] | None = None,
    ) -> bool:
        if self.cell_looks_open_empty(arr, row, col, template_profiles=template_profiles):
            return False
        assert self.geometry is not None
        x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
        crop = arr[y0:y1, x0:x1]
        core = self.cell_core(crop)
        patch = self.normalize_cell_patch(crop)
        flag_like = self.cell_looks_flag_symbol(core) or self.patch_looks_flag_symbol(patch)
        red_three_like = self.cell_looks_red_digit_three(core) or self.patch_looks_red_digit_three(patch)
        template_profiles = template_profiles or self.get_reference_template_profiles()
        scores = self.template_match_details(patch, template_profiles)
        if not scores:
            return flag_like and not red_three_like

        flag_score = float(scores.get("flag", {}).get("combined", 999.0))
        hidden_score = float(scores.get("hidden", {}).get("combined", 999.0))
        three_score = float(scores.get("3", {}).get("combined", 999.0))
        ordered = sorted(scores.items(), key=lambda item: item[1]["combined"])
        best_label, best_details = ordered[0]
        best_score = float(best_details["combined"])
        second_score = float(ordered[1][1]["combined"]) if len(ordered) > 1 else best_score + 999.0

        if red_three_like and three_score <= flag_score + 4.0:
            return False
        if best_label == "flag" and hidden_score - flag_score > 8.0 and not red_three_like:
            return flag_like or flag_score + 10.0 < second_score
        if flag_like and hidden_score - flag_score > 12.0 and flag_score <= best_score + 10.0 and not red_three_like:
            return True
        return False

    def cell_matches_expected_open_value(
        self,
        arr: np.ndarray,
        row: int,
        col: int,
        expected_value: int,
        template_profiles: dict[str, dict[str, list[np.ndarray]]] | None = None,
    ) -> bool:
        if expected_value == STATE_EMPTY:
            if self.cell_looks_open_empty(arr, row, col, template_profiles=template_profiles):
                return True
            visual_hint = self.confident_visible_open_value(arr, row, col, template_profiles=template_profiles)
            return visual_hint == STATE_EMPTY
        visual_hint = self.confident_visible_open_value(arr, row, col, template_profiles=template_profiles)
        if visual_hint == expected_value:
            return True
        assert self.geometry is not None
        x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)
        crop = arr[y0:y1, x0:x1]
        patch = self.normalize_cell_patch(crop)
        template_profiles = template_profiles or self.get_reference_template_profiles()
        scores = self.template_match_details(patch, template_profiles)
        label = str(expected_value)
        if label not in scores:
            return False
        expected_score = float(scores[label]["combined"])
        ordered = sorted(scores.items(), key=lambda item: item[1]["combined"])
        best_label, best_details = ordered[0]
        best_score = float(best_details["combined"])
        hidden_score = float(scores.get("hidden", {}).get("combined", best_score + 999.0))
        if best_label == label and hidden_score - expected_score > 8.0:
            return True
        if expected_value == 3 and self.patch_looks_red_digit_three(patch) and hidden_score - expected_score > 6.0:
            return True
        return expected_score <= best_score + 6.0 and hidden_score - expected_score > 12.0

    def sync_visual_open_candidates(
        self,
        arr: np.ndarray,
        board: np.ndarray,
        candidates: list[tuple[int, int]],
        confirmed_open_values: dict[tuple[int, int], int],
        ever_open_cells: set[tuple[int, int]],
    ) -> tuple[np.ndarray, list[tuple[int, int]]]:
        if not candidates:
            return board, []
        synced_board = board.copy()
        synced_cells: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for row, col in candidates:
            cell = (row, col)
            if cell in seen:
                continue
            seen.add(cell)
            if not (0 <= row < synced_board.shape[0] and 0 <= col < synced_board.shape[1]):
                continue
            if synced_board[row, col] != STATE_HIDDEN:
                continue
            if not self.cell_looks_open_empty(arr, row, col):
                continue
            synced_board[row, col] = STATE_EMPTY
            confirmed_open_values[cell] = STATE_EMPTY
            ever_open_cells.add(cell)
            synced_cells.append(cell)
        return synced_board, synced_cells

    def rebuild_runtime_board_from_arr(
        self,
        arr: np.ndarray,
        tag: str,
        confirmed_open_values: dict[tuple[int, int], int],
        ever_open_cells: set[tuple[int, int]],
        placed_flag_cells: set[tuple[int, int]],
        clicked_open_cells: set[tuple[int, int]],
    ) -> tuple[np.ndarray, np.ndarray, set[tuple[int, int]], int]:
        self.refresh_geometry_from(arr)
        raw_board, arr = self.read_board_consensus(arr, tag)
        board, observed_flag_cells = self.merge_solver_board_state(
            raw_board,
            confirmed_open_values,
            ever_open_cells,
            placed_flag_cells,
            arr,
        )
        self.prune_hidden_open_tracking(
            board,
            clicked_open_cells,
            ever_open_cells,
            confirmed_open_values,
        )
        return arr, board, observed_flag_cells, hash(board.tobytes())

    def stabilize_after_successful_open(
        self,
        arr: np.ndarray,
        before_board: np.ndarray,
        post_open_board: np.ndarray,
        cell: tuple[int, int],
        tag: str,
        click_result: str,
        confirmed_open_values: dict[tuple[int, int], int],
        ever_open_cells: set[tuple[int, int]],
        placed_flag_cells: set[tuple[int, int]],
        clicked_open_cells: set[tuple[int, int]],
    ) -> tuple[np.ndarray, np.ndarray, set[tuple[int, int]], int]:
        self.record_trusted_open_values(before_board, post_open_board, confirmed_open_values, ever_open_cells)
        self.record_trusted_board_templates(arr, before_board, post_open_board)
        board, observed_flag_cells = self.merge_solver_board_state(
            post_open_board,
            confirmed_open_values,
            ever_open_cells,
            placed_flag_cells,
            arr,
        )
        self.prune_hidden_open_tracking(
            board,
            clicked_open_cells,
            ever_open_cells,
            confirmed_open_values,
        )
        board_signature = hash(board.tobytes())
        row, col = cell
        opened_before = int(np.sum(before_board >= 0))
        opened_after = int(np.sum(post_open_board >= 0))
        needs_settle_refresh = (
            click_result == "synced"
            or int(post_open_board[row, col]) == STATE_EMPTY
            or opened_after - opened_before > 1
        )
        if not needs_settle_refresh:
            if click_result == "changed":
                time.sleep(POST_OPEN_SETTLE_SECONDS)
            return arr, board, observed_flag_cells, board_signature
        time.sleep(POST_OPEN_SETTLE_SECONDS)
        settled_before_board = board.copy()
        arr, board, observed_flag_cells, board_signature = self.rebuild_runtime_board_from_arr(
            arr,
            tag,
            confirmed_open_values,
            ever_open_cells,
            placed_flag_cells,
            clicked_open_cells,
        )
        self.record_trusted_open_values(settled_before_board, board, confirmed_open_values, ever_open_cells)
        self.record_trusted_board_templates(arr, settled_before_board, board)
        self.record_open_empty_transition_samples(
            arr,
            settled_before_board,
            board,
            "settled_open_empty",
        )
        self.prune_hidden_open_tracking(
            board,
            clicked_open_cells,
            ever_open_cells,
            confirmed_open_values,
        )
        return arr, board, observed_flag_cells, board_signature

    def log_cell_diagnostic(self, event: str, arr: np.ndarray, cell: tuple[int, int], board_value: int | None = None) -> None:
        metrics = self.cell_visual_metrics(arr, cell[0], cell[1])
        parts = [
            f"attempt={self.attempt}",
            f"event={event}",
            f"cell={cell}",
            f"board_value={board_value}",
            f"mean=({metrics['mean_r']:.1f},{metrics['mean_g']:.1f},{metrics['mean_b']:.1f})",
            f"std=({metrics['std_r']:.1f},{metrics['std_g']:.1f},{metrics['std_b']:.1f})",
            f"red={metrics['red_pixels']}",
            f"bright={metrics['bright_pixels']}",
            f"dark={metrics['dark_pixels']}",
            f"colorful={metrics['colorful_pixels']}",
            f"grayish={metrics['grayish_pixels']}",
        ]
        with (ARTIFACT_DIR / "cell_action_diagnostics.txt").open("a", encoding="utf-8") as handle:
            handle.write(" ".join(parts) + "\n")
        if (
            event.startswith("skip_visual_open_")
            or "wrong_target" in event
            or "blocked_variant" in event
            or "no_effect" in event
        ):
            self.record_edge_case_artifact(event, arr, cell, board_value)

    def refresh_geometry_from(self, arr: np.ndarray) -> None:
        try:
            detected = self.detect_geometry(arr)
        except RuntimeError:
            detected = None

        if detected is not None:
            self.geometry = self.refine_geometry(arr, detected)
            return
        if self.geometry is not None:
            self.geometry = self.refine_geometry(arr, self.geometry)

    def assess_board_action_result(
        self,
        before_arr: np.ndarray,
        before_board: np.ndarray,
        before_signature: int,
        cell: tuple[int, int],
        tag: str,
        expected_state: int | None = None,
        require_cell_reveal: bool = False,
    ) -> tuple[np.ndarray, np.ndarray | None, str]:
        template_profiles = self.get_reference_template_profiles() if require_cell_reveal else None

        def late_sync(arr_now: np.ndarray, board_now: np.ndarray) -> tuple[np.ndarray | None, int | None]:
            if not require_cell_reveal:
                return None, None
            row_now, col_now = cell
            visual_hint = self.confident_visible_open_value(
                arr_now,
                row_now,
                col_now,
                template_profiles=template_profiles,
            )
            if visual_hint is None:
                return None, None
            synced_board = board_now.copy()
            synced_board[row_now, col_now] = visual_hint
            return synced_board, visual_hint

        _, arr = self.capture(tag)
        interruption = self.interruption_kind(arr)
        if interruption in {"game_over_dialog", "lost", "new_game", "exit_game", "process_missing"}:
            return arr, None, interruption

        post_board = self.read_board(arr)

        row, col = cell
        before_visual = self.local_visual_signature(before_arr, cell)
        after_visual = self.local_visual_signature(arr, cell)
        visual_changed = before_visual != after_visual
        if expected_state is not None and post_board[row, col] == expected_state:
            return arr, post_board, "changed"
        if require_cell_reveal and post_board[row, col] >= 0:
            return arr, post_board, "changed"
        synced_board, visual_hint = late_sync(arr, post_board)
        if synced_board is not None and visual_hint is not None:
            self.log_cell_diagnostic(f"late_visual_open_{visual_hint}", arr, cell, int(before_board[row, col]))
            return arr, synced_board, "synced"
        if expected_state is not None and post_board[row, col] != expected_state:
            time.sleep(ACTION_RETRY_WAIT_SECONDS)
            _, retry_arr = self.capture(f"{tag}_target_retry.png")
            interruption = self.interruption_kind(retry_arr)
            if interruption in {"game_over_dialog", "lost", "new_game", "exit_game", "process_missing"}:
                return retry_arr, None, interruption
            retry_board, retry_arr = self.read_board_consensus(retry_arr, f"{tag}_target_retry_consensus")
            interruption = self.interruption_kind(retry_arr)
            if interruption in {"game_over_dialog", "lost", "new_game", "exit_game", "process_missing"}:
                return retry_arr, retry_board, interruption
            if retry_board[row, col] == expected_state:
                return retry_arr, retry_board, "changed"
            synced_retry_board, visual_hint = late_sync(retry_arr, retry_board)
            if synced_retry_board is not None and visual_hint is not None:
                self.log_cell_diagnostic(f"late_visual_open_{visual_hint}", retry_arr, cell, int(before_board[row, col]))
                return retry_arr, synced_retry_board, "synced"
            self.refresh_geometry_from(retry_arr)
            self.log_cell_diagnostic("post_click_wrong_target_state", retry_arr, cell, int(before_board[row, col]))
            return retry_arr, retry_board, "blocked"
        if hash(post_board.tobytes()) == before_signature:
            if visual_changed:
                time.sleep(ACTION_RETRY_WAIT_SECONDS)
                _, retry_arr = self.capture(f"{tag}_retry.png")
                interruption = self.interruption_kind(retry_arr)
                if interruption in {"game_over_dialog", "lost", "new_game", "exit_game", "process_missing"}:
                    return retry_arr, None, interruption
                retry_board, retry_arr = self.read_board_consensus(retry_arr, f"{tag}_retry_consensus")
                interruption = self.interruption_kind(retry_arr)
                if interruption in {"game_over_dialog", "lost", "new_game", "exit_game", "process_missing"}:
                    return retry_arr, retry_board, interruption
                if expected_state is not None and retry_board[row, col] == expected_state:
                    return retry_arr, retry_board, "changed"
                if require_cell_reveal and retry_board[row, col] >= 0:
                    return retry_arr, retry_board, "changed"
                synced_retry_board, visual_hint = late_sync(retry_arr, retry_board)
                if synced_retry_board is not None and visual_hint is not None:
                    self.log_cell_diagnostic(f"late_visual_open_{visual_hint}", retry_arr, cell, int(before_board[row, col]))
                    return retry_arr, synced_retry_board, "synced"
                if not require_cell_reveal and hash(retry_board.tobytes()) != before_signature:
                    return retry_arr, retry_board, "changed"
                if not require_cell_reveal and self.local_visual_signature(retry_arr, cell) != before_visual:
                    return retry_arr, retry_board, "changed"
            synced_board, visual_hint = late_sync(arr, post_board)
            if synced_board is not None and visual_hint is not None:
                self.log_cell_diagnostic(f"late_visual_open_{visual_hint}", arr, cell, int(before_board[row, col]))
                return arr, synced_board, "synced"
            self.refresh_geometry_from(arr)
            return arr, post_board, "no_effect"

        if require_cell_reveal and post_board[row, col] == STATE_HIDDEN:
            time.sleep(ACTION_RETRY_WAIT_SECONDS)
            _, retry_arr = self.capture(f"{tag}_target_retry.png")
            interruption = self.interruption_kind(retry_arr)
            if interruption in {"game_over_dialog", "lost", "new_game", "exit_game", "process_missing"}:
                return retry_arr, None, interruption
            retry_board, retry_arr = self.read_board_consensus(retry_arr, f"{tag}_target_retry_consensus")
            interruption = self.interruption_kind(retry_arr)
            if interruption in {"game_over_dialog", "lost", "new_game", "exit_game", "process_missing"}:
                return retry_arr, retry_board, interruption
            if retry_board[row, col] >= 0:
                return retry_arr, retry_board, "changed"
            synced_retry_board, visual_hint = late_sync(retry_arr, retry_board)
            if synced_retry_board is not None and visual_hint is not None:
                self.log_cell_diagnostic(f"late_visual_open_{visual_hint}", retry_arr, cell, int(before_board[row, col]))
                return retry_arr, synced_retry_board, "synced"
            self.refresh_geometry_from(retry_arr)
            self.log_cell_diagnostic("post_click_wrong_target", retry_arr, cell, int(before_board[row, col]))
            return retry_arr, retry_board, "blocked"

        before_local = self.local_board_signature(before_board, cell)
        after_local = self.local_board_signature(post_board, cell)
        if post_board[row, col] == STATE_HIDDEN and before_local == after_local:
            if visual_changed:
                return arr, post_board, "changed"
            self.refresh_geometry_from(arr)
            return arr, post_board, "blocked"

        return arr, post_board, "changed"

    def attempt_open_action(
        self,
        arr: np.ndarray,
        board: np.ndarray,
        board_signature: int,
        cell: tuple[int, int],
        tag: str,
        confirmed_open_values: dict[tuple[int, int], int] | None = None,
        ever_open_cells: set[tuple[int, int]] | None = None,
    ) -> tuple[np.ndarray, np.ndarray | None, str]:
        row, col = cell
        template_profiles = self.get_reference_template_profiles()
        visual_open_hint = self.confident_visible_open_value(arr, row, col, template_profiles=template_profiles)
        if visual_open_hint is not None:
            self.log_cell_diagnostic(f"skip_visual_open_{visual_open_hint}", arr, cell, int(board[row, col]))
            synced_board = board.copy()
            synced_board[row, col] = visual_open_hint
            return arr, synced_board, "synced"
        latest_arr = arr
        latest_board: np.ndarray | None = None
        latest_result = "no_effect"
        click_points = self.action_click_points_local(row, col)
        max_variants = min(len(click_points), MAX_OPEN_CLICK_VARIANTS)
        last_visual_signature = self.local_visual_signature(latest_arr, cell)
        no_effect_variants = 0
        identical_no_effect_variants = 0
        for variant in range(max_variants):
            self.left_click(row, col, variant=variant)
            time.sleep(POST_OPEN_ACTION_WAIT_SECONDS)
            if variant == 0:
                variant_tag = tag
            else:
                stem, dot, suffix = tag.rpartition(".")
                variant_tag = f"{stem}_alt{variant}.{suffix}" if dot else f"{tag}_alt{variant}"
            latest_arr, latest_board, latest_result = self.assess_board_action_result(
                latest_arr,
                board,
                board_signature,
                cell,
                variant_tag,
                require_cell_reveal=True,
            )
            if latest_result == "no_effect":
                self.log_cell_diagnostic(f"post_click_{latest_result}_variant_{variant}", latest_arr, cell, int(board[row, col]))
                no_effect_variants += 1
                current_visual_signature = self.local_visual_signature(latest_arr, cell)
                if current_visual_signature == last_visual_signature:
                    identical_no_effect_variants += 1
                else:
                    identical_no_effect_variants = 0
                last_visual_signature = current_visual_signature
                if (
                    no_effect_variants >= MAX_OPEN_NO_EFFECT_VARIANTS
                    or identical_no_effect_variants >= MAX_OPEN_IDENTICAL_NO_EFFECT_VARIANTS
                ):
                    self.log_cell_diagnostic("post_click_no_effect_budget_exhausted", latest_arr, cell, int(board[row, col]))
                    latest_result = "blocked"
                    break
                continue
            if latest_result == "blocked":
                self.log_cell_diagnostic(f"post_click_{latest_result}_variant_{variant}", latest_arr, cell, int(board[row, col]))
                return latest_arr, latest_board, latest_result
            if latest_result != "no_effect":
                return latest_arr, latest_board, latest_result
        return latest_arr, latest_board, latest_result

    def attempt_flag_action(
        self,
        arr: np.ndarray,
        board: np.ndarray,
        board_signature: int,
        cell: tuple[int, int],
        tag: str,
    ) -> tuple[np.ndarray, np.ndarray | None, str]:
        row, col = cell
        template_profiles = self.get_reference_template_profiles()
        if self.cell_looks_visual_flag(arr, row, col, template_profiles=template_profiles):
            synced_board = board.copy()
            synced_board[row, col] = STATE_FLAG
            return arr, synced_board, "changed"

        latest_arr = arr
        latest_board: np.ndarray | None = None
        latest_result = "no_effect"
        click_points = self.action_click_points_local(row, col)
        max_variants = min(len(click_points), MAX_FLAG_CLICK_VARIANTS)
        last_visual_signature = self.local_visual_signature(latest_arr, cell)
        no_effect_variants = 0
        identical_no_effect_variants = 0
        for variant in range(max_variants):
            self.right_click(row, col, variant=variant)
            time.sleep(POST_FLAG_ACTION_WAIT_SECONDS)
            if variant == 0:
                variant_tag = tag
            else:
                stem, dot, suffix = tag.rpartition(".")
                variant_tag = f"{stem}_alt{variant}.{suffix}" if dot else f"{tag}_alt{variant}"
            latest_arr, latest_board, latest_result = self.assess_board_action_result(
                latest_arr,
                board,
                board_signature,
                cell,
                variant_tag,
                expected_state=STATE_FLAG,
            )
            if latest_result not in {"no_effect", "blocked"}:
                return latest_arr, latest_board, latest_result
            if self.cell_looks_visual_flag(latest_arr, row, col, template_profiles=template_profiles):
                synced_board = latest_board.copy() if latest_board is not None else board.copy()
                synced_board[row, col] = STATE_FLAG
                return latest_arr, synced_board, "changed"
            self.log_cell_diagnostic(f"post_flag_{latest_result}_variant_{variant}", latest_arr, cell, int(board[row, col]))
            if latest_result == "no_effect":
                no_effect_variants += 1
                current_visual_signature = self.local_visual_signature(latest_arr, cell)
                if current_visual_signature == last_visual_signature:
                    identical_no_effect_variants += 1
                else:
                    identical_no_effect_variants = 0
                last_visual_signature = current_visual_signature
                if (
                    no_effect_variants >= MAX_FLAG_NO_EFFECT_VARIANTS
                    or identical_no_effect_variants >= MAX_FLAG_IDENTICAL_NO_EFFECT_VARIANTS
                ):
                    self.log_cell_diagnostic("post_flag_no_effect_budget_exhausted", latest_arr, cell, int(board[row, col]))
                    return latest_arr, latest_board, "blocked"
            if latest_result == "blocked":
                return latest_arr, latest_board, latest_result
        return latest_arr, latest_board, latest_result

    def board_looks_like_loss_overlay(self, board: np.ndarray) -> bool:
        opened = int(np.sum(board >= 0))
        if opened < 40:
            return False
        fours = int(np.sum(board == 4))
        eights = int(np.sum(board == 8))
        high_numbers = int(np.sum(board >= 3))
        if eights >= 3:
            return True
        if fours >= max(24, int(opened * 0.25)):
            return True
        if high_numbers >= max(55, int(opened * 0.68)):
            return True
        return False

    def log_dialog_restart(self, mode: str, click_index: int, point: tuple[int, int]) -> None:
        self.dialog_restart_successes += 1
        self.last_dialog_restart_mode = mode
        self.preferred_restart_point = point
        log_path = ARTIFACT_DIR / "dialog_restart_events.txt"
        line = (
            f"attempt={self.attempt} success=true mode={mode} click_index={click_index} "
            f"point={point} total_successes={self.dialog_restart_successes}"
        )
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def write_stop_summary(self, reason: str) -> None:
        self.maybe_store_reference_template_profiles(force=True)
        summary_path = ARTIFACT_DIR / "solver_stop_summary.txt"
        lines = [
            f"reason: {reason}",
            f"attempt: {self.attempt}",
            f"elapsed_seconds: {int(time.time() - self.run_started_at)}",
            f"run_mode: {self.run_config.mode}",
            f"configured_max_attempts: {self.run_config.max_attempts}",
            f"configured_stop_on_loss: {self.run_config.stop_on_loss}",
            f"configured_repeat_failure_seconds: {self.run_config.max_repeat_failure_seconds}",
            f"configured_single_attempt_steps: {self.run_config.max_single_attempt_steps}",
            f"current_first_click: {self.current_first_click}",
            f"last_actions: {self.last_actions[-20:]}",
            f"failed_openers: {dict(self.failed_openers)}",
            f"failed_guesses_top: {sorted(self.failed_guess_counts.items(), key=lambda item: item[1], reverse=True)[:10]}",
            f"dialog_restart_successes: {self.dialog_restart_successes}",
            f"last_dialog_restart_mode: {self.last_dialog_restart_mode}",
            "analysis: interruption handling is prioritized before any further board action.",
            "next_steps: inspect latest screenshots, review opener rotation, review probability choices, and confirm whether the process or a modal dialog interrupted gameplay.",
        ]
        summary_path.write_text("\n".join(lines), encoding="utf-8")

    def start_attempt(self) -> np.ndarray:
        if self.is_session_locked():
            self.write_stop_summary("session_locked")
            raise RuntimeError("绯荤粺褰撳墠澶勪簬閿佸睆/鐧诲綍鐣岄潰锛屾棤娉曠户缁壂闆疯嚜鍔ㄥ寲")
        if self.reuse_existing_game and self.find_minesweeper_hwnd() is not None:
            try:
                self.ensure_window()
            except RuntimeError:
                self.launch_fresh_game()
                _, arr = self.capture(f"attempt_{self.attempt:02d}_fresh.png")
                self.reuse_existing_game = True
                self.geometry = self.detect_geometry(arr)
                self.prewarm_reference_template_profiles()
                first_row, first_col = self.opening_candidates()[0]
                self.current_first_click = (first_row, first_col)
                self.left_click(first_row, first_col)
                time.sleep(0.8)
                _, arr = self.capture(f"attempt_{self.attempt:02d}_after_first_click.png")
                return arr
            time.sleep(0.6)
            _, probe = self.capture(f"attempt_{self.attempt:02d}_reuse_probe.png")
            if self.dialog_kind(probe) == "game_over_dialog":
                self.reuse_existing_game = False
                self.launch_fresh_game()
        else:
            self.launch_fresh_game()
        retry_error: RuntimeError | None = None
        for startup_try in range(3):
            self.ensure_window()
            time.sleep(0.5 + startup_try * 0.3)
            _, arr = self.capture(f"attempt_{self.attempt:02d}_fresh.png")
            self.reuse_existing_game = True
            try:
                self.geometry = self.detect_geometry(arr)
                break
            except RuntimeError as exc:
                retry_error = exc
                self.capture(f"attempt_{self.attempt:02d}_startup_retry_{startup_try:02d}.png")
                if startup_try == 2:
                    raise
                self.launch_fresh_game()
        if retry_error is not None and self.geometry is None:
            raise retry_error
        self.prewarm_reference_template_profiles()
        first_row, first_col = self.opening_candidates()[0]
        self.current_first_click = (first_row, first_col)
        self.left_click(first_row, first_col)
        time.sleep(0.8)
        _, arr = self.capture(f"attempt_{self.attempt:02d}_after_first_click.png")
        return arr

    def solve_once(self) -> bool:
        arr = self.start_attempt()
        self.frontier_cache.clear()
        last_opened = -1
        guessed_cells: list[tuple[int, int]] = []
        confirmed_open_values: dict[tuple[int, int], int] = {}
        clicked_open_cells: set[tuple[int, int]] = set()
        ever_open_cells: set[tuple[int, int]] = set()
        placed_flag_cells: set[tuple[int, int]] = set()
        disallowed_open_cells: set[tuple[int, int]] = set()
        open_cell_cooldowns: dict[tuple[int, int], int] = {}
        if self.current_first_click is not None:
            clicked_open_cells.add(self.current_first_click)
            ever_open_cells.add(self.current_first_click)
        pending_csp_flags: dict[tuple[int, int], int] = defaultdict(int)
        pending_det_flags: dict[tuple[int, int], int] = defaultdict(int)
        pending_shared_flags: dict[tuple[int, int], int] = defaultdict(int)
        pending_det_opens: dict[tuple[int, int], int] = defaultdict(int)
        pending_subset_opens: dict[tuple[int, int], int] = defaultdict(int)
        last_board_signature: int | None = None
        same_board_turns = 0
        stagnation_started_at = time.time()
        last_progress_at = time.time()
        previous_hidden: int | None = None
        previous_flagged: int | None = None
        opening_boost_clicks = 0
        flag_only_streak = 0
        pending_streak = 0
        pre_guess_rule_streak = 0

        max_steps = self.run_config.max_single_attempt_steps if self.single_attempt_mode else 1200
        for step in range(max_steps):
            interruption = self.interruption_kind(arr)
            if interruption == "game_over_dialog":
                self.capture(f"attempt_{self.attempt:02d}_game_over_dialog_{step:03d}.png")
                self.dump_dialog_controls(f"attempt_{self.attempt:02d}_{step:03d}")
                if self.stop_on_failure:
                    self.last_actions.append("failure_dialog_stop")
                    return False
                self.reuse_existing_game = False
                if self.current_first_click is not None:
                    self.failed_openers[self.current_first_click] += 1
                for cell in guessed_cells[-3:]:
                    self.failed_guess_counts[cell] += 1
                return False
            if interruption == "new_game":
                self.capture(f"attempt_{self.attempt:02d}_new_game_dialog_{step:03d}.png")
                self.reuse_existing_game = False
                return False
            if interruption == "exit_game":
                self.capture(f"attempt_{self.attempt:02d}_exit_dialog_{step:03d}.png")
                self.reuse_existing_game = False
                return False
            if interruption == "process_missing":
                self.write_stop_summary("process_interrupted_or_closed")
                raise RuntimeError("\u626b\u96f7\u8fdb\u7a0b\u88ab\u4e2d\u65ad\u6216\u5173\u95ed")
            if interruption == "lost":
                self.capture(f"attempt_{self.attempt:02d}_lost_{step:03d}.png")
                if self.stop_on_failure:
                    self.last_actions.append("loss_stop")
                    return False
                self.reuse_existing_game = False
                if self.current_first_click is not None:
                    self.failed_openers[self.current_first_click] += 1
                for cell in guessed_cells[-3:]:
                    self.failed_guess_counts[cell] += 1
                return False

            self.refresh_geometry_from(arr)
            raw_board, arr = self.read_board_consensus(arr, f"attempt_{self.attempt:02d}_step_{step:03d}")
            if not confirmed_open_values:
                self.record_trusted_open_values(None, raw_board, confirmed_open_values, ever_open_cells)
            board, observed_flag_cells = self.merge_solver_board_state(
                raw_board,
                confirmed_open_values,
                ever_open_cells,
                placed_flag_cells,
                arr,
            )
            self.prune_hidden_open_tracking(
                board,
                clicked_open_cells,
                ever_open_cells,
                confirmed_open_values,
            )
            disallowed_open_cells |= self.active_open_cooldown_cells(board, open_cell_cooldowns, step)
            hidden, flagged, opened = self.board_progress(board)
            if self.should_record_visible_templates(step, opened):
                self.record_visible_trusted_templates(arr, board, confirmed_open_values, placed_flag_cells)
            board_signature = hash(board.tobytes())
            if board_signature != last_board_signature:
                last_board_signature = board_signature
                stagnation_started_at = time.time()
                same_board_turns = 0
                disallowed_open_cells.clear()
                pre_guess_rule_streak = 0
            else:
                same_board_turns += 1
            if previous_hidden is None or hidden < previous_hidden or flagged > (previous_flagged or 0):
                last_progress_at = time.time()
            previous_hidden = hidden
            previous_flagged = flagged

            if time.time() - stagnation_started_at > MAX_STAGNATION_SECONDS:
                self.capture(f"attempt_{self.attempt:02d}_stagnation_{step:03d}.png")
                if self.single_attempt_mode:
                    self.last_actions.append("stagnation_force_guess")
                    stagnation_started_at = time.time()
                    last_progress_at = time.time()
                else:
                    self.last_actions.append("stagnation")
                    if self.current_first_click is not None and step <= 10:
                        self.failed_openers[self.current_first_click] += 1
                    return False
            if time.time() - last_progress_at > MAX_NO_PROGRESS_SECONDS:
                self.capture(f"attempt_{self.attempt:02d}_no_progress_{step:03d}.png")
                if self.single_attempt_mode:
                    self.last_actions.append("no_progress_force_guess")
                    stagnation_started_at = time.time()
                    last_progress_at = time.time()
                else:
                    self.last_actions.append("no_progress")
                    if self.current_first_click is not None and step <= 10:
                        self.failed_openers[self.current_first_click] += 1
                    return False

            if hidden == 0:
                self.capture(f"attempt_{self.attempt:02d}_won_{step:03d}.png")
                return True

            if hidden + flagged == TOTAL_MINES:
                template_profiles = self.get_reference_template_profiles()
                for row, col in [
                    (r, c)
                    for r in range(board.shape[0])
                    for c in range(board.shape[1])
                    if board[r, c] == STATE_HIDDEN
                ]:
                    if self.cell_looks_visual_flag(arr, row, col, template_profiles=template_profiles):
                        continue
                    self.right_click(row, col)
                time.sleep(0.8)
                _, arr = self.capture(f"attempt_{self.attempt:02d}_final_flags_{step:03d}.png")
                board = self.read_board(arr)
                hidden, flagged, _ = self.board_progress(board)
                if hidden == 0:
                    self.capture(f"attempt_{self.attempt:02d}_won_{step:03d}.png")
                    return True

            det_open, det_flag = self.deterministic_actions(board)
            subset_open, subset_flag = self.subset_inference_actions(board)
            csp_open: list[tuple[int, int]] = []
            csp_flag: list[tuple[int, int]] = []
            needs_reconfirm = same_board_turns > 0
            self.release_safe_open_candidates(
                board,
                set(det_open) | set(subset_open),
                clicked_open_cells,
                ever_open_cells,
                confirmed_open_values,
                disallowed_open_cells,
            )
            if needs_reconfirm and (det_open or subset_open or det_flag or subset_flag):
                arr, board, det_open, det_flag, subset_open, subset_flag = self.reconfirm_rule_actions(
                    arr,
                    board,
                    set(det_open),
                    set(det_flag),
                    set(subset_open),
                    set(subset_flag),
                    f"attempt_{self.attempt:02d}_step_{step:03d}",
                    confirmed_open_values,
                    ever_open_cells,
                    placed_flag_cells,
                )
                board, observed_flag_cells = self.merge_solver_board_state(
                    board,
                    confirmed_open_values,
                    ever_open_cells,
                    placed_flag_cells,
                    arr,
                )
                self.prune_hidden_open_tracking(
                    board,
                    clicked_open_cells,
                    ever_open_cells,
                    confirmed_open_values,
                )
                board_signature = hash(board.tobytes())
                self.release_safe_open_candidates(
                    board,
                    set(det_open) | set(subset_open),
                    clicked_open_cells,
                    ever_open_cells,
                    confirmed_open_values,
                    disallowed_open_cells,
                )
            if not (det_open or subset_open or det_flag or subset_flag):
                _exact_probabilities, _, exact_safe_open, exact_safe_flag = self.frontier_probabilities(board)
                csp_open = sorted(exact_safe_open)
                csp_flag = sorted(exact_safe_flag)
                self.release_safe_open_candidates(
                    board,
                    set(csp_open),
                    clicked_open_cells,
                    ever_open_cells,
                    confirmed_open_values,
                    disallowed_open_cells,
                )
                if needs_reconfirm and (csp_open or csp_flag):
                    arr, board, csp_open, csp_flag = self.reconfirm_csp_actions(
                        arr,
                        board,
                        set(csp_open),
                        set(csp_flag),
                        f"attempt_{self.attempt:02d}_step_{step:03d}",
                        confirmed_open_values,
                        ever_open_cells,
                        placed_flag_cells,
                    )
                    board, observed_flag_cells = self.merge_solver_board_state(
                        board,
                        confirmed_open_values,
                        ever_open_cells,
                        placed_flag_cells,
                        arr,
                    )
                    self.prune_hidden_open_tracking(
                        board,
                        clicked_open_cells,
                        ever_open_cells,
                        confirmed_open_values,
                    )
                    board_signature = hash(board.tobytes())

            flag_agreement_counts: dict[tuple[int, int], int] = {}
            for flag_group in (set(csp_flag), set(det_flag), set(subset_flag)):
                for cell in flag_group:
                    flag_agreement_counts[cell] = flag_agreement_counts.get(cell, 0) + 1

            prior_rule_board = board.copy()
            board, synced_visual_rule_cells = self.sync_visual_open_candidates(
                arr,
                board,
                sorted(set(csp_open) | set(det_open) | set(subset_open)),
                confirmed_open_values,
                ever_open_cells,
            )
            if synced_visual_rule_cells:
                self.record_trusted_open_values(prior_rule_board, board, confirmed_open_values, ever_open_cells)
                self.record_trusted_board_templates(arr, prior_rule_board, board)
                self.record_open_empty_transition_samples(arr, prior_rule_board, board, "visual_rule_sync_empty")
                self.prune_hidden_open_tracking(
                    board,
                    clicked_open_cells,
                    ever_open_cells,
                    confirmed_open_values,
                )
                pending_det_opens.clear()
                pending_subset_opens.clear()
                board_signature = hash(board.tobytes())
                self.last_actions.append(f"visual_sync:{len(synced_visual_rule_cells)}")
                continue

            if (
                step <= 1
                and opened < MIN_GOOD_OPENING_OPENED
                and not csp_open
                and not csp_flag
                and not det_open
                and not det_flag
                and not subset_open
                and not subset_flag
            ):
                self.capture(f"attempt_{self.attempt:02d}_poor_opening_{step:03d}.png")
                boosted_arr, opening_boost_clicks, boost_cell = self.try_opening_boost(
                    arr,
                    board,
                    clicked_open_cells,
                    ever_open_cells,
                    confirmed_open_values,
                    disallowed_open_cells,
                    opening_boost_clicks,
                    step,
                )
                if boosted_arr is not None:
                    arr = boosted_arr
                    flag_only_streak = 0
                    pending_streak = 0
                    if boost_cell is not None:
                        guessed_cells.append(boost_cell)
                    continue
                if self.single_attempt_mode:
                    self.last_actions.append("poor_opening_continue")
                else:
                    self.last_actions.append("poor_opening_restart")
                    if self.current_first_click is not None:
                        self.failed_openers[self.current_first_click] += 1
                    return False

            if csp_open:
                rule_backed_open_cells = set(det_open) | set(subset_open)
                csp_open = sorted(
                    [
                        cell
                        for cell in csp_open
                        if self.can_open_cell(
                            cell,
                            board,
                            clicked_open_cells,
                            ever_open_cells,
                            confirmed_open_values,
                            disallowed_open_cells,
                        )
                        and self.support_count(board, cell) >= 1
                    ],
                    key=lambda cell: self.open_priority_key(
                        board,
                        cell,
                        rule_backed=cell in rule_backed_open_cells,
                    ),
                )[:MAX_CSP_OPEN_BATCH]
                if csp_open:
                    interrupted = False
                    executed_csp_opens = 0
                    skipped_csp_opens = 0
                    for open_index, (row, col) in enumerate(csp_open):
                        cell = (row, col)
                        if not self.can_open_cell(
                            cell,
                            board,
                            clicked_open_cells,
                            ever_open_cells,
                            confirmed_open_values,
                            disallowed_open_cells,
                        ):
                            disallowed_open_cells.add(cell)
                            self.extend_open_cell_cooldown(open_cell_cooldowns, cell, step)
                            self.last_actions.append("csp_open_blocked")
                            skipped_csp_opens += 1
                            continue
                        arr, post_open_board, click_result = self.attempt_open_action(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_csp_opens_{step:03d}_{open_index:02d}.png",
                            confirmed_open_values=confirmed_open_values,
                            ever_open_cells=ever_open_cells,
                        )
                        if click_result in {"game_over_dialog", "lost"}:
                            clicked_open_cells.add(cell)
                            interrupted = True
                            break
                        if click_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"csp_open_interrupted:{click_result}")
                            interrupted = True
                            break
                        if click_result in {"changed", "synced"} and post_open_board is not None:
                            if click_result == "changed":
                                clicked_open_cells.add(cell)
                            arr, board, observed_flag_cells, board_signature = self.stabilize_after_successful_open(
                                arr,
                                board,
                                post_open_board,
                                cell,
                                f"attempt_{self.attempt:02d}_csp_open_settle_{step:03d}_{open_index:02d}",
                                click_result,
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                clicked_open_cells,
                            )
                            executed_csp_opens = open_index + 1
                            continue
                        if click_result == "no_effect":
                            disallowed_open_cells.add(cell)
                            self.extend_open_cell_cooldown(open_cell_cooldowns, cell, step)
                            self.capture(f"attempt_{self.attempt:02d}_csp_open_no_effect_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("csp_open_no_effect")
                            skipped_csp_opens += 1
                            arr, board, observed_flag_cells, board_signature = self.rebuild_runtime_board_from_arr(
                                arr,
                                f"attempt_{self.attempt:02d}_csp_open_resync_{step:03d}_{open_index:02d}",
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                clicked_open_cells,
                            )
                            continue
                        if click_result == "blocked":
                            disallowed_open_cells.add(cell)
                            self.extend_open_cell_cooldown(open_cell_cooldowns, cell, step)
                            self.capture(f"attempt_{self.attempt:02d}_csp_open_blocked_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("csp_open_blocked")
                            skipped_csp_opens += 1
                            arr, board, observed_flag_cells, board_signature = self.rebuild_runtime_board_from_arr(
                                arr,
                                f"attempt_{self.attempt:02d}_csp_open_resync_{step:03d}_{open_index:02d}",
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                clicked_open_cells,
                            )
                            continue
                    if interrupted or executed_csp_opens > 0 or skipped_csp_opens > 0:
                        self.last_actions.append(f"csp_opens:{executed_csp_opens}")
                        if skipped_csp_opens > 0:
                            self.last_actions.append(f"csp_open_skips:{skipped_csp_opens}")
                        flag_only_streak = 0
                        pending_streak = 0
                        if interrupted:
                            continue
                        last_opened = opened
                        continue

            shared_rule_flags = sorted(
                [
                    cell
                    for cell in (set(det_flag) & set(subset_flag))
                    if (
                        cell not in observed_flag_cells
                        and cell not in confirmed_open_values
                        and board[cell] == STATE_HIDDEN
                    )
                ],
                key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
            )[:MAX_DET_FLAG_BATCH]
            shared_rule_flags, pending_shared_flags = self.stable_candidates(
                shared_rule_flags,
                pending_shared_flags,
                SHARED_FLAG_CONFIRM_FRAMES,
                same_board_turns=same_board_turns,
                agreement_counts=flag_agreement_counts,
            )
            if shared_rule_flags:
                prioritized_flags = shared_rule_flags
                prioritized_flags = sorted(
                    prioritized_flags,
                    key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
                )[:MAX_DET_FLAG_BATCH]
                interrupted = False
                skipped_prioritized_flags = 0
                for flag_index, (row, col) in enumerate(prioritized_flags):
                    cell = (row, col)
                    if cell in observed_flag_cells or cell in confirmed_open_values or board[cell] != STATE_HIDDEN:
                        continue
                    arr, post_flag_board, flag_result = self.attempt_flag_action(
                        arr,
                        board,
                        board_signature,
                        cell,
                        f"attempt_{self.attempt:02d}_prioritized_flags_{step:03d}_{flag_index:02d}.png",
                    )
                    if flag_result in {"game_over_dialog", "lost"}:
                        interrupted = True
                        break
                    if flag_result in {"new_game", "exit_game", "process_missing"}:
                        self.last_actions.append(f"prioritized_flag_interrupted:{flag_result}")
                        interrupted = True
                        break
                    if flag_result == "changed" and post_flag_board is not None:
                        placed_flag_cells.add(cell)
                        self.record_trusted_board_templates(arr, board, post_flag_board, flag_cell=cell)
                        board, observed_flag_cells = self.merge_solver_board_state(
                            post_flag_board,
                            confirmed_open_values,
                            ever_open_cells,
                            placed_flag_cells,
                            arr,
                        )
                        board_signature = hash(board.tobytes())
                    if flag_result == "no_effect":
                        self.capture(f"attempt_{self.attempt:02d}_prioritized_flag_no_effect_{step:03d}_{flag_index:02d}.png")
                        self.last_actions.append("prioritized_flag_no_effect")
                        skipped_prioritized_flags += 1
                        continue
                    if flag_result == "blocked":
                        self.capture(f"attempt_{self.attempt:02d}_prioritized_flag_blocked_{step:03d}_{flag_index:02d}.png")
                        self.last_actions.append("prioritized_flag_blocked")
                        skipped_prioritized_flags += 1
                        continue
                self.last_actions.append(f"prioritized_flags:{len(prioritized_flags)}")
                if skipped_prioritized_flags > 0:
                    self.last_actions.append(f"prioritized_flag_skips:{skipped_prioritized_flags}")
                flag_only_streak += 1
                pending_streak = 0
                if interrupted:
                    continue
            else:
                pending_shared_flags.clear()

            if det_open:
                det_open_candidates = sorted(
                    [
                        cell
                        for cell in det_open
                        if self.can_open_cell(
                            cell,
                            board,
                            clicked_open_cells,
                            ever_open_cells,
                            confirmed_open_values,
                            disallowed_open_cells,
                        )
                    ],
                    key=lambda cell: self.open_priority_key(board, cell, rule_backed=True),
                )[:MAX_DET_OPEN_BATCH]
                det_open, pending_det_opens = self.stable_candidates(
                    det_open_candidates,
                    pending_det_opens,
                    DET_OPEN_CONFIRM_FRAMES,
                    same_board_turns=same_board_turns,
                )
                if det_open:
                    interrupted = False
                    executed_det_opens = 0
                    skipped_det_opens = 0
                    for open_index, (row, col) in enumerate(det_open):
                        cell = (row, col)
                        if not self.can_open_cell(
                            cell,
                            board,
                            clicked_open_cells,
                            ever_open_cells,
                            confirmed_open_values,
                            disallowed_open_cells,
                        ):
                            disallowed_open_cells.add(cell)
                            self.extend_open_cell_cooldown(open_cell_cooldowns, cell, step)
                            self.last_actions.append("open_blocked")
                            skipped_det_opens += 1
                            continue
                        arr, post_open_board, click_result = self.attempt_open_action(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_opens_{step:03d}_{open_index:02d}.png",
                            confirmed_open_values=confirmed_open_values,
                            ever_open_cells=ever_open_cells,
                        )
                        if click_result in {"game_over_dialog", "lost"}:
                            clicked_open_cells.add(cell)
                            interrupted = True
                            break
                        if click_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"open_interrupted:{click_result}")
                            interrupted = True
                            break
                        if click_result in {"changed", "synced"} and post_open_board is not None:
                            if click_result == "changed":
                                clicked_open_cells.add(cell)
                            arr, board, observed_flag_cells, board_signature = self.stabilize_after_successful_open(
                                arr,
                                board,
                                post_open_board,
                                cell,
                                f"attempt_{self.attempt:02d}_open_settle_{step:03d}_{open_index:02d}",
                                click_result,
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                clicked_open_cells,
                            )
                            executed_det_opens = open_index + 1
                            continue
                        if click_result == "no_effect":
                            disallowed_open_cells.add(cell)
                            self.extend_open_cell_cooldown(open_cell_cooldowns, cell, step)
                            self.capture(f"attempt_{self.attempt:02d}_open_no_effect_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("open_no_effect")
                            skipped_det_opens += 1
                            arr, board, observed_flag_cells, board_signature = self.rebuild_runtime_board_from_arr(
                                arr,
                                f"attempt_{self.attempt:02d}_open_resync_{step:03d}_{open_index:02d}",
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                clicked_open_cells,
                            )
                            continue
                        if click_result == "blocked":
                            disallowed_open_cells.add(cell)
                            self.extend_open_cell_cooldown(open_cell_cooldowns, cell, step)
                            self.capture(f"attempt_{self.attempt:02d}_open_blocked_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("open_blocked")
                            skipped_det_opens += 1
                            arr, board, observed_flag_cells, board_signature = self.rebuild_runtime_board_from_arr(
                                arr,
                                f"attempt_{self.attempt:02d}_open_resync_{step:03d}_{open_index:02d}",
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                clicked_open_cells,
                            )
                            continue
                    if interrupted or executed_det_opens > 0 or skipped_det_opens > 0:
                        self.last_actions.append(f"det_opens:{executed_det_opens}")
                        if skipped_det_opens > 0:
                            self.last_actions.append(f"det_open_skips:{skipped_det_opens}")
                        flag_only_streak = 0
                        pending_streak = 0
                        if interrupted:
                            continue
                        last_opened = opened
                        continue
            else:
                pending_det_opens.clear()

            if csp_flag:
                fresh_csp_flag_candidates = sorted(
                    [
                        cell
                        for cell in csp_flag
                        if cell not in observed_flag_cells
                        and cell not in confirmed_open_values
                        and board[cell] == STATE_HIDDEN
                    ],
                    key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
                )[:MAX_DET_FLAG_BATCH]
                fresh_csp_flags, pending_csp_flags = self.stable_candidates(
                    fresh_csp_flag_candidates,
                    pending_csp_flags,
                    CSP_FLAG_CONFIRM_FRAMES,
                    same_board_turns=same_board_turns,
                    agreement_counts=flag_agreement_counts,
                )
                if not fresh_csp_flags:
                    if fresh_csp_flag_candidates:
                        self.last_actions.append("csp_flags_pending")
                else:
                    interrupted = False
                    skipped_csp_flags = 0
                    for flag_index, (row, col) in enumerate(fresh_csp_flags):
                        cell = (row, col)
                        if cell in observed_flag_cells or cell in confirmed_open_values or cell in clicked_open_cells or board[cell] != STATE_HIDDEN:
                            continue
                        pending_csp_flags.pop(cell, None)
                        arr, post_flag_board, flag_result = self.attempt_flag_action(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_csp_flags_{step:03d}_{flag_index:02d}.png",
                        )
                        if flag_result in {"game_over_dialog", "lost"}:
                            interrupted = True
                            break
                        if flag_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"csp_flag_interrupted:{flag_result}")
                            interrupted = True
                            break
                        if flag_result == "changed" and post_flag_board is not None:
                            placed_flag_cells.add(cell)
                            self.record_trusted_board_templates(arr, board, post_flag_board, flag_cell=cell)
                            board, observed_flag_cells = self.merge_solver_board_state(
                                post_flag_board,
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                arr,
                            )
                            board_signature = hash(board.tobytes())
                        if flag_result == "no_effect":
                            self.capture(f"attempt_{self.attempt:02d}_csp_flag_no_effect_{step:03d}_{flag_index:02d}.png")
                            self.last_actions.append("csp_flag_no_effect")
                            skipped_csp_flags += 1
                            continue
                        if flag_result == "blocked":
                            self.capture(f"attempt_{self.attempt:02d}_csp_flag_blocked_{step:03d}_{flag_index:02d}.png")
                            self.last_actions.append("csp_flag_blocked")
                            skipped_csp_flags += 1
                            continue
                    self.last_actions.append(f"csp_flags:{len(fresh_csp_flags)}")
                    if skipped_csp_flags > 0:
                        self.last_actions.append(f"csp_flag_skips:{skipped_csp_flags}")
                    flag_only_streak += 1
                    pending_streak = 0
                    if interrupted:
                        continue
                    continue

            if det_flag:
                fresh_flag_candidates = [
                    cell
                    for cell in det_flag
                    if cell not in observed_flag_cells
                    and cell not in confirmed_open_values
                    and board[cell] == STATE_HIDDEN
                ]
                fresh_flags, pending_det_flags = self.stable_candidates(
                    fresh_flag_candidates,
                    pending_det_flags,
                    DET_FLAG_CONFIRM_FRAMES,
                    same_board_turns=same_board_turns,
                    agreement_counts=flag_agreement_counts,
                )
                if not fresh_flags:
                    if fresh_flag_candidates:
                        self.last_actions.append("flags_pending")
                else:
                    fresh_flags = sorted(
                        fresh_flags,
                        key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
                    )[:MAX_DET_FLAG_BATCH]
                    interrupted = False
                    skipped_det_flags = 0
                    for flag_index, (row, col) in enumerate(fresh_flags):
                        cell = (row, col)
                        if cell in observed_flag_cells or cell in confirmed_open_values or cell in clicked_open_cells or board[cell] != STATE_HIDDEN:
                            continue
                        pending_det_flags.pop(cell, None)
                        arr, post_flag_board, flag_result = self.attempt_flag_action(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_flags_{step:03d}_{flag_index:02d}.png",
                        )
                        if flag_result in {"game_over_dialog", "lost"}:
                            interrupted = True
                            break
                        if flag_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"flag_interrupted:{flag_result}")
                            interrupted = True
                            break
                        if flag_result == "changed" and post_flag_board is not None:
                            placed_flag_cells.add(cell)
                            self.record_trusted_board_templates(arr, board, post_flag_board, flag_cell=cell)
                            board, observed_flag_cells = self.merge_solver_board_state(
                                post_flag_board,
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                arr,
                            )
                            board_signature = hash(board.tobytes())
                        if flag_result == "no_effect":
                            self.capture(f"attempt_{self.attempt:02d}_flag_no_effect_{step:03d}_{flag_index:02d}.png")
                            self.last_actions.append("flag_no_effect")
                            skipped_det_flags += 1
                            continue
                        if flag_result == "blocked":
                            self.capture(f"attempt_{self.attempt:02d}_flag_blocked_{step:03d}_{flag_index:02d}.png")
                            self.last_actions.append("flag_blocked")
                            skipped_det_flags += 1
                            continue
                    self.last_actions.append(f"flags:{len(fresh_flags)}")
                    if skipped_det_flags > 0:
                        self.last_actions.append(f"flag_skips:{skipped_det_flags}")
                    flag_only_streak += 1
                    pending_streak = 0
                    if interrupted:
                        continue
                    continue

            if subset_open:
                subset_open_candidates = sorted(
                    [
                        cell
                        for cell in subset_open
                        if self.can_open_cell(
                            cell,
                            board,
                            clicked_open_cells,
                            ever_open_cells,
                            confirmed_open_values,
                            disallowed_open_cells,
                        )
                    ],
                    key=lambda cell: self.open_priority_key(board, cell, rule_backed=True),
                )[:MAX_DET_OPEN_BATCH]
                subset_open, pending_subset_opens = self.stable_candidates(
                    subset_open_candidates,
                    pending_subset_opens,
                    DET_OPEN_CONFIRM_FRAMES,
                    same_board_turns=same_board_turns,
                )
                if subset_open:
                    interrupted = False
                    executed_subset_opens = 0
                    skipped_subset_opens = 0
                    for open_index, (row, col) in enumerate(subset_open):
                        cell = (row, col)
                        if not self.can_open_cell(
                            cell,
                            board,
                            clicked_open_cells,
                            ever_open_cells,
                            confirmed_open_values,
                            disallowed_open_cells,
                        ):
                            disallowed_open_cells.add(cell)
                            self.extend_open_cell_cooldown(open_cell_cooldowns, cell, step)
                            self.last_actions.append("subset_open_blocked")
                            skipped_subset_opens += 1
                            continue
                        arr, post_open_board, click_result = self.attempt_open_action(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_subset_opens_{step:03d}_{open_index:02d}.png",
                            confirmed_open_values=confirmed_open_values,
                            ever_open_cells=ever_open_cells,
                        )
                        if click_result in {"game_over_dialog", "lost"}:
                            clicked_open_cells.add(cell)
                            interrupted = True
                            break
                        if click_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"subset_open_interrupted:{click_result}")
                            interrupted = True
                            break
                        if click_result in {"changed", "synced"} and post_open_board is not None:
                            if click_result == "changed":
                                clicked_open_cells.add(cell)
                            arr, board, observed_flag_cells, board_signature = self.stabilize_after_successful_open(
                                arr,
                                board,
                                post_open_board,
                                cell,
                                f"attempt_{self.attempt:02d}_subset_open_settle_{step:03d}_{open_index:02d}",
                                click_result,
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                clicked_open_cells,
                            )
                            executed_subset_opens = open_index + 1
                            continue
                        if click_result == "no_effect":
                            disallowed_open_cells.add(cell)
                            self.extend_open_cell_cooldown(open_cell_cooldowns, cell, step)
                            self.capture(f"attempt_{self.attempt:02d}_subset_open_no_effect_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("subset_open_no_effect")
                            skipped_subset_opens += 1
                            arr, board, observed_flag_cells, board_signature = self.rebuild_runtime_board_from_arr(
                                arr,
                                f"attempt_{self.attempt:02d}_subset_open_resync_{step:03d}_{open_index:02d}",
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                clicked_open_cells,
                            )
                            continue
                        if click_result == "blocked":
                            disallowed_open_cells.add(cell)
                            self.extend_open_cell_cooldown(open_cell_cooldowns, cell, step)
                            self.capture(f"attempt_{self.attempt:02d}_subset_open_blocked_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("subset_open_blocked")
                            skipped_subset_opens += 1
                            arr, board, observed_flag_cells, board_signature = self.rebuild_runtime_board_from_arr(
                                arr,
                                f"attempt_{self.attempt:02d}_subset_open_resync_{step:03d}_{open_index:02d}",
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                clicked_open_cells,
                            )
                            continue
                    if interrupted or executed_subset_opens > 0 or skipped_subset_opens > 0:
                        self.last_actions.append(f"subset_opens:{executed_subset_opens}")
                        if skipped_subset_opens > 0:
                            self.last_actions.append(f"subset_open_skips:{skipped_subset_opens}")
                        flag_only_streak = 0
                        pending_streak = 0
                        if interrupted:
                            continue
                        last_opened = opened
                        continue
            else:
                pending_subset_opens.clear()

            if subset_flag:
                fresh_subset_flags = [
                    cell
                    for cell in subset_flag
                    if cell not in observed_flag_cells
                    and cell not in confirmed_open_values
                    and board[cell] == STATE_HIDDEN
                ]
                if fresh_subset_flags:
                    interrupted = False
                    skipped_subset_flags = 0
                    for flag_index, (row, col) in enumerate(sorted(fresh_subset_flags)[:MAX_DET_FLAG_BATCH]):
                        cell = (row, col)
                        if cell in observed_flag_cells or cell in confirmed_open_values or board[cell] != STATE_HIDDEN:
                            continue
                        arr, post_flag_board, flag_result = self.attempt_flag_action(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_subset_flags_{step:03d}_{flag_index:02d}.png",
                        )
                        if flag_result in {"game_over_dialog", "lost"}:
                            interrupted = True
                            break
                        if flag_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"subset_flag_interrupted:{flag_result}")
                            interrupted = True
                            break
                        if flag_result == "changed" and post_flag_board is not None:
                            placed_flag_cells.add(cell)
                            self.record_trusted_board_templates(arr, board, post_flag_board, flag_cell=cell)
                            board, observed_flag_cells = self.merge_solver_board_state(
                                post_flag_board,
                                confirmed_open_values,
                                ever_open_cells,
                                placed_flag_cells,
                                arr,
                            )
                            board_signature = hash(board.tobytes())
                        if flag_result == "no_effect":
                            self.capture(f"attempt_{self.attempt:02d}_subset_flag_no_effect_{step:03d}_{flag_index:02d}.png")
                            self.last_actions.append("subset_flag_no_effect")
                            skipped_subset_flags += 1
                            continue
                        if flag_result == "blocked":
                            self.capture(f"attempt_{self.attempt:02d}_subset_flag_blocked_{step:03d}_{flag_index:02d}.png")
                            self.last_actions.append("subset_flag_blocked")
                            skipped_subset_flags += 1
                            continue
                    self.last_actions.append(f"subset_flags:{min(len(fresh_subset_flags), MAX_DET_FLAG_BATCH)}")
                    if skipped_subset_flags > 0:
                        self.last_actions.append(f"subset_flag_skips:{skipped_subset_flags}")
                    flag_only_streak += 1
                    pending_streak = 0
                    if interrupted:
                        continue
                    continue

            if opened < OPENING_BOOST_OPENED_THRESHOLD and opening_boost_clicks < MAX_OPENING_BOOST_CLICKS:
                boosted_arr, opening_boost_clicks, boost_cell = self.try_opening_boost(
                    arr,
                    board,
                    clicked_open_cells,
                    ever_open_cells,
                    confirmed_open_values,
                    disallowed_open_cells,
                    opening_boost_clicks,
                    step,
                )
                if boosted_arr is not None:
                    arr = boosted_arr
                    if boost_cell is not None:
                        guessed_cells.append(boost_cell)
                    continue

            rescue_risks, _, rescue_open, rescue_flag = self.frontier_probabilities(board)
            rescue_open = sorted(
                [
                    cell for cell in rescue_open
                    if self.can_open_cell(
                        cell,
                        board,
                        clicked_open_cells,
                        ever_open_cells,
                        confirmed_open_values,
                        disallowed_open_cells,
                    )
                ],
                key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
            )[:1]
            rescue_flag = sorted(
                [
                    cell for cell in rescue_flag
                    if cell not in observed_flag_cells
                    and cell not in confirmed_open_values
                    and board[cell] == STATE_HIDDEN
                ],
                key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
            )[:1]
            if rescue_open:
                prior_rescue_board = board.copy()
                board, synced_visual_rescue_cells = self.sync_visual_open_candidates(
                    arr,
                    board,
                    rescue_open,
                    confirmed_open_values,
                    ever_open_cells,
                )
                if synced_visual_rescue_cells:
                    self.record_trusted_open_values(prior_rescue_board, board, confirmed_open_values, ever_open_cells)
                    self.record_trusted_board_templates(arr, prior_rescue_board, board)
                    self.record_open_empty_transition_samples(arr, prior_rescue_board, board, "rescue_visual_sync_empty")
                    self.prune_hidden_open_tracking(
                        board,
                        clicked_open_cells,
                        ever_open_cells,
                        confirmed_open_values,
                    )
                    board_signature = hash(board.tobytes())
                    self.last_actions.append("rescue_visual_sync")
                    continue
                cell = rescue_open[0]
                arr, post_open_board, click_result = self.attempt_open_action(
                    arr,
                    board,
                    board_signature,
                    cell,
                    f"attempt_{self.attempt:02d}_rescue_open_{step:03d}.png",
                    confirmed_open_values=confirmed_open_values,
                    ever_open_cells=ever_open_cells,
                )
                self.last_actions.append("rescue_open")
                if click_result in {"changed", "synced", "game_over_dialog", "lost"}:
                    if click_result in {"changed", "lost", "game_over_dialog"}:
                        clicked_open_cells.add(cell)
                    if click_result in {"changed", "synced"} and post_open_board is not None:
                        arr, board, observed_flag_cells, board_signature = self.stabilize_after_successful_open(
                            arr,
                            board,
                            post_open_board,
                            cell,
                            f"attempt_{self.attempt:02d}_rescue_open_settle_{step:03d}",
                            click_result,
                            confirmed_open_values,
                            ever_open_cells,
                            placed_flag_cells,
                            clicked_open_cells,
                        )
                    continue
                if click_result in {"new_game", "exit_game", "process_missing"}:
                    self.last_actions.append(f"rescue_open_interrupted:{click_result}")
                    return False
                disallowed_open_cells.add(cell)
                continue
            if rescue_flag:
                row, col = rescue_flag[0]
                cell = (row, col)
                arr, post_flag_board, flag_result = self.attempt_flag_action(
                    arr,
                    board,
                    board_signature,
                    cell,
                    f"attempt_{self.attempt:02d}_rescue_flag_{step:03d}.png",
                )
                self.last_actions.append("rescue_flag")
                if flag_result in {"changed", "game_over_dialog", "lost"}:
                    if flag_result == "changed" and post_flag_board is not None:
                        placed_flag_cells.add(cell)
                        self.record_trusted_board_templates(arr, board, post_flag_board, flag_cell=cell)
                        board, observed_flag_cells = self.merge_solver_board_state(
                            post_flag_board,
                            confirmed_open_values,
                            ever_open_cells,
                            placed_flag_cells,
                            arr,
                        )
                        board_signature = hash(board.tobytes())
                    continue
                if flag_result in {"new_game", "exit_game", "process_missing"}:
                    self.last_actions.append(f"rescue_flag_interrupted:{flag_result}")
                    return False
                continue

            self.refresh_geometry_from(arr)
            pre_guess_board, arr = self.read_board_consensus(
                arr,
                f"attempt_{self.attempt:02d}_step_{step:03d}_pre_guess",
            )
            board, observed_flag_cells = self.merge_solver_board_state(
                pre_guess_board,
                confirmed_open_values,
                ever_open_cells,
                placed_flag_cells,
                arr,
            )
            self.prune_hidden_open_tracking(
                board,
                clicked_open_cells,
                ever_open_cells,
                confirmed_open_values,
            )
            board_signature = hash(board.tobytes())
            _preguess_risks, _preguess_global_risk, pre_guess_csp_open, pre_guess_csp_flag = self.frontier_probabilities(board)
            pre_guess_det_open, pre_guess_det_flag = self.deterministic_actions(board)
            pre_guess_subset_open, pre_guess_subset_flag = self.subset_inference_actions(board)
            self.release_safe_open_candidates(
                board,
                set(pre_guess_csp_open) | set(pre_guess_det_open) | set(pre_guess_subset_open),
                clicked_open_cells,
                ever_open_cells,
                confirmed_open_values,
                disallowed_open_cells,
            )
            actionable_pre_guess_open = [
                cell
                for cell in sorted(set(pre_guess_csp_open) | set(pre_guess_det_open) | set(pre_guess_subset_open))
                if self.can_open_cell(
                    cell,
                    board,
                    clicked_open_cells,
                    ever_open_cells,
                    confirmed_open_values,
                    disallowed_open_cells,
                )
            ]
            actionable_pre_guess_flag = [
                cell
                for cell in sorted(set(pre_guess_csp_flag) | set(pre_guess_det_flag) | set(pre_guess_subset_flag))
                if cell not in observed_flag_cells and cell not in confirmed_open_values and board[cell] == STATE_HIDDEN
            ]
            if actionable_pre_guess_open or actionable_pre_guess_flag:
                pre_guess_rule_streak += 1
                if pre_guess_rule_streak <= 6 or same_board_turns <= 2:
                    self.last_actions.append("pre_guess_rules_found")
                    continue
                arr, board, observed_flag_cells, board_signature = self.rebuild_runtime_board_from_arr(
                    arr,
                    f"attempt_{self.attempt:02d}_step_{step:03d}_pre_guess_resync",
                    confirmed_open_values,
                    ever_open_cells,
                    placed_flag_cells,
                    clicked_open_cells,
                )
                pre_guess_rule_streak = 0
                self.last_actions.append("pre_guess_rules_resync")
                continue
            else:
                pre_guess_rule_streak = 0

            blocked_guess_cells = self.forbidden_open_cells(
                clicked_open_cells,
                ever_open_cells,
                confirmed_open_values,
                disallowed_open_cells,
            )
            guess_row, guess_col = self.guess_cell(board, blocked_guess_cells)
            prior_guess_board = board.copy()
            board, synced_visual_guess_cells = self.sync_visual_open_candidates(
                arr,
                board,
                [(guess_row, guess_col)],
                confirmed_open_values,
                ever_open_cells,
            )
            if synced_visual_guess_cells:
                self.record_trusted_open_values(prior_guess_board, board, confirmed_open_values, ever_open_cells)
                self.record_trusted_board_templates(arr, prior_guess_board, board)
                self.record_open_empty_transition_samples(arr, prior_guess_board, board, "guess_visual_sync_empty")
                self.prune_hidden_open_tracking(
                    board,
                    clicked_open_cells,
                    ever_open_cells,
                    confirmed_open_values,
                )
                board_signature = hash(board.tobytes())
                self.last_actions.append("guess_visual_sync")
                continue
            if not self.can_open_cell(
                (guess_row, guess_col),
                board,
                clicked_open_cells,
                ever_open_cells,
                confirmed_open_values,
                disallowed_open_cells,
            ):
                disallowed_open_cells.add((guess_row, guess_col))
                self.capture(f"attempt_{self.attempt:02d}_guess_opened_blocked_{step:03d}.png")
                self.last_actions.append("guess_opened_blocked")
                if self.single_attempt_mode:
                    continue
                return False
            arr, post_guess_board, click_result = self.attempt_open_action(
                arr,
                board,
                board_signature,
                (guess_row, guess_col),
                f"attempt_{self.attempt:02d}_guess_{step:03d}.png",
                confirmed_open_values=confirmed_open_values,
                ever_open_cells=ever_open_cells,
            )
            self.last_actions.append(f"guess:{guess_row},{guess_col}")
            flag_only_streak = 0
            pending_streak = 0
            if click_result in {"game_over_dialog", "lost"}:
                guessed_cells.append((guess_row, guess_col))
                clicked_open_cells.add((guess_row, guess_col))
                self.capture(f"attempt_{self.attempt:02d}_lost_guess_{step:03d}.png")
                if self.current_first_click is not None:
                    self.failed_openers[self.current_first_click] += 1
                for cell in guessed_cells[-3:]:
                    self.failed_guess_counts[cell] += 1
                return False
            if click_result in {"new_game", "exit_game", "process_missing"}:
                self.last_actions.append(f"guess_interrupted:{click_result}")
                return False
            if click_result == "changed":
                guessed_cells.append((guess_row, guess_col))
                clicked_open_cells.add((guess_row, guess_col))
            if click_result in {"changed", "synced"} and post_guess_board is not None:
                arr, board, observed_flag_cells, board_signature = self.stabilize_after_successful_open(
                    arr,
                    board,
                    post_guess_board,
                    (guess_row, guess_col),
                    f"attempt_{self.attempt:02d}_guess_settle_{step:03d}",
                    click_result,
                    confirmed_open_values,
                    ever_open_cells,
                    placed_flag_cells,
                    clicked_open_cells,
                )
            if click_result == "no_effect":
                guessed_cells.append((guess_row, guess_col))
                disallowed_open_cells.add((guess_row, guess_col))
                self.capture(f"attempt_{self.attempt:02d}_guess_no_effect_{step:03d}.png")
                self.last_actions.append("guess_no_effect")
                self.failed_guess_counts[(guess_row, guess_col)] += 2
                continue
            if click_result == "blocked":
                guessed_cells.append((guess_row, guess_col))
                disallowed_open_cells.add((guess_row, guess_col))
                self.capture(f"attempt_{self.attempt:02d}_guess_blocked_{step:03d}.png")
                self.last_actions.append("guess_blocked")
                self.failed_guess_counts[(guess_row, guess_col)] += 1
                if self.single_attempt_mode:
                    continue
                return False
            last_opened = opened

        self.capture(f"attempt_{self.attempt:02d}_timeout.png")
        return False

    def run(self) -> None:
        attempt_limit = self.run_config.attempt_limit
        attempt = 0
        while attempt_limit is None or attempt < attempt_limit:
            attempt += 1
            self.attempt = attempt
            if self.solve_once():
                print(f"SUCCESS attempt={attempt}")
                return
            if self.single_attempt_mode:
                self.write_stop_summary("single_attempt_finished_without_win")
                raise RuntimeError("\u5355\u5c40\u6d4b\u8bd5\u5df2\u7ed3\u675f\uff08\u672a\u901a\u5173\uff09")
            if self.run_config.stop_on_loss:
                self.write_stop_summary("stopped_after_loss")
                raise RuntimeError("\u5df2\u6309\u914d\u7f6e\u5728\u9996\u6b21\u5931\u8d25\u540e\u505c\u6b62")
            if self.failure_started_at is None:
                self.failure_started_at = time.time()
            if (
                self.run_config.max_repeat_failure_seconds is not None
                and time.time() - self.failure_started_at > self.run_config.max_repeat_failure_seconds
            ):
                self.write_stop_summary("repeated_failures_over_time_limit")
                raise RuntimeError(
                    f"\u91cd\u590d\u5931\u8d25\u5df2\u8d85\u8fc7 {int(self.run_config.max_repeat_failure_seconds)} \u79d2\uff0c\u5df2\u505c\u6b62\u81ea\u52a8\u91cd\u8bd5"
                )
            print(f"RETRY attempt={attempt}")
            time.sleep(0.8)
        self.write_stop_summary("attempt_limit_reached")
        raise RuntimeError("\u626b\u96f7\u672a\u80fd\u5728\u9650\u5b9a\u6b21\u6570\u5185\u901a\u5173")


if __name__ == "__main__":
    MinesweeperSolver(parse_run_config()).run()
