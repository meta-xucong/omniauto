from __future__ import annotations

import ctypes
from ctypes import wintypes
import math
import os
import random
import subprocess
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

PROCESS_NAME = "Minesweeper.exe"
TOTAL_MINES = 99
MAX_ATTEMPTS = 50
MAX_REPEAT_FAILURE_SECONDS = 180
MAX_STAGNATION_SECONDS = 12
MAX_NO_PROGRESS_SECONDS = 20
WINDOW_APPEAR_TIMEOUT_SECONDS = 8.0
WINDOW_APPEAR_POLL_SECONDS = 0.2
STOP_ON_FAILURE = os.getenv("OMNIAUTO_MINESWEEPER_STOP_ON_FAILURE", "0") == "1"
SINGLE_ATTEMPT_MODE = os.getenv("OMNIAUTO_MINESWEEPER_SINGLE_ATTEMPT", "0") == "1"
ENABLE_CSP_FLAGS = os.getenv("OMNIAUTO_MINESWEEPER_ENABLE_CSP_FLAGS", "0") == "1"
MAX_CSP_OPEN_BATCH = 1
MAX_DET_OPEN_BATCH = 5
MAX_DET_FLAG_BATCH = 6
OPENING_BOOST_OPENED_THRESHOLD = 18
MAX_OPENING_BOOST_CLICKS = 4
BOARD_CONSENSUS_FRAMES = 3
MIN_GOOD_OPENING_OPENED = 12
MAX_EXACT_COMPONENT_CELLS = 22
MAX_GROUPED_COMPONENT_AREAS = 26
DET_FLAG_CONFIRM_FRAMES = 1
DET_OPEN_CONFIRM_FRAMES = 1
CSP_FLAG_CONFIRM_FRAMES = 2
CSP_OPEN_CONFIRM_FRAMES = 1

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
        board_left, board_top, board_right, board_bottom = self.board_rect_local()
        board_center_x = (board_left + board_right) / 2
        board_center_y = (board_top + board_bottom) / 2
        inward_x = center_x + int(round((board_center_x - center_x) * 0.18))
        inward_y = center_y + int(round((board_center_y - center_y) * 0.18))
        inset_left = left + max(3, int(round(width * 0.25)))
        inset_right = right - max(3, int(round(width * 0.25)))
        inset_top = top + max(3, int(round(height * 0.25)))
        inset_bottom = bottom - max(3, int(round(height * 0.25)))
        inward_x = min(max(inward_x, inset_left), inset_right)
        inward_y = min(max(inward_y, inset_top), inset_bottom)
        inward = (inward_x, inward_y)
        points = [inward]
        if (center_x, center_y) != inward:
            points.append((center_x, center_y))
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


class MinesweeperSolver:
    def __init__(self) -> None:
        self.vis = VisualEngine().start()
        self.user32 = ctypes.windll.user32
        self.geometry: BoardGeometry | None = None
        self.window_rect = (0, 0, 0, 0)
        self.attempt = 0
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

    def _enum_windows(self) -> list[int]:
        hwnds: list[int] = []
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def callback(hwnd, _lparam):
            if self.user32.IsWindowVisible(hwnd):
                hwnds.append(hwnd)
            return True

        self.user32.EnumWindows(enum_proc(callback), 0)
        return hwnds

    def find_minesweeper_hwnd(self) -> int | None:
        for hwnd in self._enum_windows():
            class_buffer = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(hwnd, class_buffer, 256)
            class_name = class_buffer.value
            length = self.user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(max(1, length + 1))
            self.user32.GetWindowTextW(hwnd, buffer, max(1, length + 1))
            title = buffer.value
            if class_name == "Minesweeper" or "\u626b\u96f7" in title:
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
        deadline = time.time() + max(0.0, timeout)
        hwnd = None
        while hwnd is None:
            hwnd = self.find_minesweeper_hwnd()
            if hwnd is not None:
                break
            if time.time() >= deadline:
                raise RuntimeError("\u672a\u627e\u5230\u626b\u96f7\u7a97\u53e3")
            time.sleep(WINDOW_APPEAR_POLL_SECONDS)
        self.user32.ShowWindow(hwnd, 3)
        self.user32.SetForegroundWindow(hwnd)
        rect = wintypes.RECT()
        self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        self.window_rect = (rect.left, rect.top, rect.right, rect.bottom)
        time.sleep(0.1)
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
        time.sleep(0.08)

    def click_absolute_raw(self, x: int, y: int) -> None:
        self.ensure_window()
        self.user32.SetCursorPos(x, y)
        time.sleep(0.02)
        self.user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.02)
        self.user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.09)

    def left_click(self, row: int, col: int, variant: int = 0) -> None:
        self.ensure_window()
        points = self.geometry.click_points_local(row, col)  # type: ignore[union-attr]
        local_x, local_y = points[min(variant, len(points) - 1)]
        x = self.window_rect[0] + local_x
        y = self.window_rect[1] + local_y
        # Use the same raw Win32 path as right_click to avoid pyauto_desktop
        # introducing button-state ambiguity or coordinate drift.
        self.click_absolute_raw(x, y)

    def right_click(self, row: int, col: int) -> None:
        self.ensure_window()
        local_x, local_y = self.geometry.center_local(row, col)  # type: ignore[union-attr]
        x = self.window_rect[0] + local_x
        y = self.window_rect[1] + local_y
        self.user32.SetCursorPos(x, y)
        time.sleep(0.02)
        self.user32.mouse_event(0x0008, 0, 0, 0, 0)
        time.sleep(0.02)
        self.user32.mouse_event(0x0010, 0, 0, 0, 0)
        time.sleep(0.06)

    def capture(self, name: str) -> tuple[Image.Image, np.ndarray]:
        self.ensure_window()
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
        return np.array(Image.fromarray(inner).resize((24, 24), Image.Resampling.BILINEAR))

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
                templates[label].append(self.normalize_cell_patch(crop))
        self.reference_templates = dict(templates)
        return self.reference_templates

    def classify_cell(self, arr: np.ndarray, row: int, col: int) -> int:
        x0, y0, x1, y1 = self.geometry.cell_rect_local(row, col)  # type: ignore[union-attr]
        crop = arr[y0:y1, x0:x1]
        core = crop[20:-20, 20:-20]
        channel_diff = np.max(core, axis=2) - np.min(core, axis=2)
        dark_pixels = np.sum(np.mean(core, axis=2) < 70)
        bright_pixels = np.sum(np.mean(core, axis=2) > 215)
        red_pixels = np.sum((core[:, :, 0] > 160) & (core[:, :, 1] < 110) & (core[:, :, 2] < 110))
        colorful = core[channel_diff > 40]
        mean_rgb = core.mean(axis=(0, 1))
        std_rgb = core.std(axis=(0, 1))

        if red_pixels > 450 and dark_pixels > 220 and bright_pixels < 180:
            return STATE_FLAG
        if red_pixels > 220 and bright_pixels > 340 and dark_pixels < 120:
            return STATE_FLAG
        if red_pixels > 170 and len(colorful) > 420 and dark_pixels < 50:
            return STATE_FLAG
        if (
            red_pixels == 0
            and dark_pixels < 40
            and bright_pixels < 40
            and len(colorful) > 500
            and std_rgb[0] < 18
            and std_rgb[1] < 18
            and std_rgb[2] < 12
        ):
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

        patch = self.normalize_cell_patch(crop)
        templates = self.get_reference_templates()
        template_scores: dict[str, float] = {}
        for label, refs in templates.items():
            if not refs:
                continue
            template_scores[label] = min(
                float(np.mean(np.abs(patch.astype(np.float32) - ref.astype(np.float32))))
                for ref in refs
            )

        if template_scores:
            ordered = sorted(template_scores.items(), key=lambda item: item[1])
            best_label, best_score = ordered[0]
            second_score = ordered[1][1] if len(ordered) > 1 else best_score + 999.0
            hidden_score = template_scores.get("hidden", best_score + 999.0)
            if best_label == "flag" and red_pixels < 150:
                best_label = "3"
            if best_label == "4" and hidden_score - best_score < 6.5:
                best_label = "hidden"
                best_score = hidden_score
            if best_score + 6.0 < second_score or best_score < 32.0:
                if best_label == "hidden":
                    return STATE_HIDDEN
                if best_label == "empty":
                    return STATE_EMPTY
                if best_label == "flag":
                    return STATE_FLAG
                if best_label.isdigit():
                    return int(best_label)

        if red_pixels > 120 and dark_pixels < 120 and bright_pixels < 260:
            return STATE_FLAG
        if bright_pixels > 150 and len(colorful) < 80:
            return STATE_EMPTY
        if bright_pixels < 40 and len(colorful) > 500:
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
        board = np.zeros((self.geometry.rows, self.geometry.cols), dtype=int)  # type: ignore[union-attr]
        for row in range(self.geometry.rows):  # type: ignore[union-attr]
            for col in range(self.geometry.cols):  # type: ignore[union-attr]
                board[row, col] = self.classify_cell(arr, row, col)
        return board

    def read_board_consensus(self, arr: np.ndarray, tag: str) -> tuple[np.ndarray, np.ndarray]:
        first_board = self.read_board(arr)
        boards = [first_board]
        latest_arr = arr
        time.sleep(0.03)
        _, latest_arr = self.capture(f"{tag}_consensus_01.png")
        second_board = self.read_board(latest_arr)
        boards.append(second_board)

        if np.array_equal(first_board, second_board):
            return second_board, latest_arr

        for frame_idx in range(2, BOARD_CONSENSUS_FRAMES):
            time.sleep(0.04)
            _, latest_arr = self.capture(f"{tag}_consensus_{frame_idx:02d}.png")
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

    def support_count(self, board: np.ndarray, cell: tuple[int, int]) -> int:
        row, col = cell
        return sum(1 for nr, nc in self.neighbors(row, col) if board[nr, nc] > 0)

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
            )
            if click_result in {"changed", "game_over_dialog", "lost"}:
                clicked_open_cells.add(boost_cell)
                opening_boost_clicks += 1
                self.last_actions.append(f"opening_boost:{boost_row},{boost_col}")
                return arr, opening_boost_clicks, boost_cell

        return None, MAX_OPENING_BOOST_CLICKS, None

    def deterministic_actions(self, board: np.ndarray) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
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
        return sorted(to_open), sorted(to_flag)

    def subset_inference_actions(self, board: np.ndarray) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
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
        return sorted(to_open), sorted(to_flag)

    def build_constraints(self, board: np.ndarray) -> tuple[list[tuple[list[tuple[int, int]], int]], set[tuple[int, int]]]:
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
        order = sorted(range(len(component_cells)), key=lambda idx: (-len(cell_constraints[idx]), random.random()))

        def feasible(cid: int) -> bool:
            _, required = normalized[cid]
            mines = assigned_mines[cid]
            rem = remaining_unassigned[cid]
            return mines <= required <= mines + rem

        def dfs(pos: int) -> None:
            nonlocal total_valid
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
        if total_valid == 0:
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
            nonlocal total_weight
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
        if total_weight == 0:
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
        hidden_cells = {
            (r, c)
            for r in range(board.shape[0])
            for c in range(board.shape[1])
            if board[r, c] == STATE_HIDDEN
        }
        flagged_count = int(np.sum(board == STATE_FLAG))
        remaining_mines = max(1, TOTAL_MINES - flagged_count)
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

        for cell in hidden_cells:
            combined_risks.setdefault(cell, global_risk)
        return combined_risks, global_risk, exact_safe_open, exact_safe_flag

    def reconfirm_csp_actions(
        self,
        arr: np.ndarray,
        board: np.ndarray,
        csp_open: set[tuple[int, int]],
        csp_flag: set[tuple[int, int]],
        tag: str,
    ) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]], list[tuple[int, int]]]:
        refreshed_board, refreshed_arr = self.read_board_consensus(arr, f"{tag}_reconfirm")
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
    ) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]], list[tuple[int, int]]]:
        refreshed_board, refreshed_arr = self.read_board_consensus(arr, f"{tag}_rules_reconfirm")
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

        def unconstrained_score(cell: tuple[int, int]) -> tuple[int, float, int, int]:
            corner_bias = 0 if cell in corner_like_cells else (1 if cell in edge_cells else 2)
            nearest_known = min(
                abs(cell[0] - other[0]) + abs(cell[1] - other[1])
                for other in reference_cells
                if other != cell
            )
            center_bias = abs(cell[0] - board.shape[0] // 2) + abs(cell[1] - board.shape[1] // 2)
            return (
                corner_bias,
                -zero_probability(cell),
                -nearest_known,
                center_bias + self.failed_guess_counts[cell],
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
            return (risk, -zero_chance, -secondary, -influence, center_bias, cell[0] * 100 + cell[1])

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

    def merge_solver_board_state(
        self,
        raw_board: np.ndarray,
        confirmed_open_values: dict[tuple[int, int], int],
        ever_open_cells: set[tuple[int, int]],
    ) -> tuple[np.ndarray, set[tuple[int, int]]]:
        board = raw_board.copy()
        observed_flag_cells: set[tuple[int, int]] = set()
        for row in range(raw_board.shape[0]):
            for col in range(raw_board.shape[1]):
                value = int(raw_board[row, col])
                if value >= 0:
                    confirmed_open_values[(row, col)] = value
                    ever_open_cells.add((row, col))
                elif value == STATE_FLAG:
                    observed_flag_cells.add((row, col))
        for (row, col), value in confirmed_open_values.items():
            if board[row, col] == STATE_HIDDEN:
                board[row, col] = value
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
            core = crop[20:-20, 20:-20]
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
        core_margin = max(8, min(20, int(round(min(crop.shape[0], crop.shape[1]) * 0.22))))
        core = crop[core_margin:-core_margin, core_margin:-core_margin]
        if core.size == 0:
            core = crop
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

    def cell_looks_flat_open(self, arr: np.ndarray, row: int, col: int) -> bool:
        metrics = self.cell_visual_metrics(arr, row, col)
        max_std = max(float(metrics["std_r"]), float(metrics["std_g"]), float(metrics["std_b"]))
        blue_excess_r = float(metrics["mean_b"]) - float(metrics["mean_r"])
        blue_excess_g = float(metrics["mean_b"]) - float(metrics["mean_g"])
        return (
            int(metrics["red_pixels"]) < 40
            and int(metrics["dark_pixels"]) < 45
            and int(metrics["colorful_pixels"]) < 24
            and max_std < 10.5
            and float(metrics["mean_r"]) > 174
            and float(metrics["mean_g"]) > 182
            and float(metrics["mean_b"]) > 208
            and blue_excess_r < 44
            and blue_excess_g < 34
        )

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

    def refresh_geometry_from(self, arr: np.ndarray) -> None:
        if self.geometry is not None:
            return
        try:
            self.geometry = self.detect_geometry(arr)
        except RuntimeError:
            pass

    def assess_board_action_result(
        self,
        before_arr: np.ndarray,
        before_board: np.ndarray,
        before_signature: int,
        cell: tuple[int, int],
        tag: str,
        expected_state: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray | None, str]:
        _, arr = self.capture(tag)
        interruption = self.interruption_kind(arr)
        if interruption in {"game_over_dialog", "lost", "new_game", "exit_game", "process_missing"}:
            return arr, None, interruption

        post_board, arr = self.read_board_consensus(arr, f"{tag}_consensus")
        interruption = self.interruption_kind(arr)
        if interruption in {"game_over_dialog", "lost", "new_game", "exit_game", "process_missing"}:
            return arr, post_board, interruption

        row, col = cell
        before_visual = self.local_visual_signature(before_arr, cell)
        after_visual = self.local_visual_signature(arr, cell)
        visual_changed = before_visual != after_visual
        if expected_state is not None and post_board[row, col] == expected_state:
            return arr, post_board, "changed"
        if hash(post_board.tobytes()) == before_signature:
            if visual_changed:
                time.sleep(0.06)
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
                if hash(retry_board.tobytes()) != before_signature:
                    return retry_arr, retry_board, "changed"
                if self.local_visual_signature(retry_arr, cell) != before_visual:
                    return retry_arr, retry_board, "changed"
            self.refresh_geometry_from(arr)
            return arr, post_board, "no_effect"

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
    ) -> tuple[np.ndarray, np.ndarray | None, str]:
        row, col = cell
        if self.cell_looks_flat_open(arr, row, col):
            self.log_cell_diagnostic("skip_flat_open", arr, cell, int(board[row, col]))
            return arr, board, "blocked"
        latest_arr = arr
        latest_board: np.ndarray | None = None
        latest_result = "no_effect"
        for variant in range(2):
            self.left_click(row, col, variant=variant)
            time.sleep(0.18)
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
            )
            if latest_result in {"no_effect", "blocked"}:
                self.log_cell_diagnostic(f"post_click_{latest_result}_variant_{variant}", latest_arr, cell, int(board[row, col]))
            if latest_result not in {"no_effect", "blocked"}:
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
        summary_path = ARTIFACT_DIR / "solver_stop_summary.txt"
        lines = [
            f"reason: {reason}",
            f"attempt: {self.attempt}",
            f"elapsed_seconds: {int(time.time() - self.run_started_at)}",
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
                first_row, first_col = self.opening_candidates()[0]
                self.current_first_click = (first_row, first_col)
                self.left_click(first_row, first_col)
                time.sleep(0.8)
                _, arr = self.capture(f"attempt_{self.attempt:02d}_after_first_click.png")
                return arr
            time.sleep(0.6)
            _, probe = self.capture(f"attempt_{self.attempt:02d}_reuse_probe.png")
            if self.dialog_kind(probe) == "game_over_dialog":
                self.play_again_dialog()
                time.sleep(1.0)
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
        first_row, first_col = self.opening_candidates()[0]
        self.current_first_click = (first_row, first_col)
        self.left_click(first_row, first_col)
        time.sleep(0.8)
        _, arr = self.capture(f"attempt_{self.attempt:02d}_after_first_click.png")
        return arr

    def solve_once(self) -> bool:
        arr = self.start_attempt()
        last_opened = -1
        guessed_cells: list[tuple[int, int]] = []
        confirmed_open_values: dict[tuple[int, int], int] = {}
        clicked_open_cells: set[tuple[int, int]] = set()
        ever_open_cells: set[tuple[int, int]] = set()
        disallowed_open_cells: set[tuple[int, int]] = set()
        if self.current_first_click is not None:
            clicked_open_cells.add(self.current_first_click)
            ever_open_cells.add(self.current_first_click)
        pending_csp_flags: dict[tuple[int, int], int] = defaultdict(int)
        pending_det_flags: dict[tuple[int, int], int] = defaultdict(int)
        last_board_signature: int | None = None
        same_board_turns = 0
        stagnation_started_at = time.time()
        last_progress_at = time.time()
        previous_hidden: int | None = None
        previous_flagged: int | None = None
        opening_boost_clicks = 0
        flag_only_streak = 0
        pending_streak = 0

        for step in range(1200):
            interruption = self.interruption_kind(arr)
            if interruption == "game_over_dialog":
                self.capture(f"attempt_{self.attempt:02d}_game_over_dialog_{step:03d}.png")
                self.dump_dialog_controls(f"attempt_{self.attempt:02d}_{step:03d}")
                if STOP_ON_FAILURE:
                    self.last_actions.append("failure_dialog_stop")
                    return False
                self.play_again_dialog()
                time.sleep(1.2)
                self.reuse_existing_game = True
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
                if STOP_ON_FAILURE:
                    self.last_actions.append("loss_stop")
                    return False
                self.play_again_dialog()
                time.sleep(0.8)
                self.reuse_existing_game = True
                if self.current_first_click is not None:
                    self.failed_openers[self.current_first_click] += 1
                for cell in guessed_cells[-3:]:
                    self.failed_guess_counts[cell] += 1
                return False

            raw_board, arr = self.read_board_consensus(arr, f"attempt_{self.attempt:02d}_step_{step:03d}")
            board, observed_flag_cells = self.merge_solver_board_state(
                raw_board,
                confirmed_open_values,
                ever_open_cells,
            )
            hidden, flagged, opened = self.board_progress(board)
            board_signature = hash(board.tobytes())
            if board_signature != last_board_signature:
                last_board_signature = board_signature
                stagnation_started_at = time.time()
                same_board_turns = 0
            else:
                same_board_turns += 1
            if previous_hidden is None or hidden < previous_hidden or flagged > (previous_flagged or 0):
                last_progress_at = time.time()
            previous_hidden = hidden
            previous_flagged = flagged

            if time.time() - stagnation_started_at > MAX_STAGNATION_SECONDS:
                self.capture(f"attempt_{self.attempt:02d}_stagnation_{step:03d}.png")
                if SINGLE_ATTEMPT_MODE:
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
                if SINGLE_ATTEMPT_MODE:
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
                for row, col in [
                    (r, c)
                    for r in range(board.shape[0])
                    for c in range(board.shape[1])
                    if board[r, c] == STATE_HIDDEN
                ]:
                    self.right_click(row, col)
                time.sleep(0.8)
                _, arr = self.capture(f"attempt_{self.attempt:02d}_final_flags_{step:03d}.png")
                board = self.read_board(arr)
                hidden, flagged, _ = self.board_progress(board)
                if hidden == 0:
                    self.capture(f"attempt_{self.attempt:02d}_won_{step:03d}.png")
                    return True

            exact_probabilities, _, exact_safe_open, exact_safe_flag = self.frontier_probabilities(board)
            csp_open = sorted(exact_safe_open)
            csp_flag = sorted(exact_safe_flag)
            det_open, det_flag = self.deterministic_actions(board)
            subset_open, subset_flag = self.subset_inference_actions(board)

            if det_open or subset_open or det_flag or subset_flag:
                csp_open = []
                csp_flag = []
                arr, board, det_open, det_flag, subset_open, subset_flag = self.reconfirm_rule_actions(
                    arr,
                    board,
                    set(det_open),
                    set(det_flag),
                    set(subset_open),
                    set(subset_flag),
                    f"attempt_{self.attempt:02d}_step_{step:03d}",
                )
                board, observed_flag_cells = self.merge_solver_board_state(
                    board,
                    confirmed_open_values,
                    ever_open_cells,
                )
                board_signature = hash(board.tobytes())
            elif csp_open or csp_flag:
                arr, board, csp_open, csp_flag = self.reconfirm_csp_actions(
                    arr,
                    board,
                    set(csp_open),
                    set(csp_flag),
                    f"attempt_{self.attempt:02d}_step_{step:03d}",
                )
                board, observed_flag_cells = self.merge_solver_board_state(
                    board,
                    confirmed_open_values,
                    ever_open_cells,
                )
                board_signature = hash(board.tobytes())

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
                if SINGLE_ATTEMPT_MODE:
                    self.last_actions.append("poor_opening_continue")
                else:
                    self.last_actions.append("poor_opening_restart")
                    if self.current_first_click is not None:
                        self.failed_openers[self.current_first_click] += 1
                    return False

            if csp_open:
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
                    key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
                )[:MAX_CSP_OPEN_BATCH]
                if csp_open:
                    interrupted = False
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
                            self.last_actions.append("csp_open_blocked")
                            interrupted = True
                            break
                        arr, post_open_board, click_result = self.attempt_open_action(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_csp_opens_{step:03d}_{open_index:02d}.png",
                        )
                        clicked_open_cells.add(cell)
                        if click_result in {"game_over_dialog", "lost"}:
                            interrupted = True
                            break
                        if click_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"csp_open_interrupted:{click_result}")
                            interrupted = True
                            break
                        if click_result == "changed" and post_open_board is not None:
                            board, observed_flag_cells = self.merge_solver_board_state(
                                post_open_board,
                                confirmed_open_values,
                                ever_open_cells,
                            )
                            board_signature = hash(board.tobytes())
                        if click_result == "no_effect":
                            disallowed_open_cells.add(cell)
                            self.capture(f"attempt_{self.attempt:02d}_csp_open_no_effect_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("csp_open_no_effect")
                            interrupted = True
                            break
                        if click_result == "blocked":
                            disallowed_open_cells.add(cell)
                            self.capture(f"attempt_{self.attempt:02d}_csp_open_blocked_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("csp_open_blocked")
                            interrupted = True
                            break
                    self.last_actions.append(f"csp_opens:{len(csp_open)}")
                    flag_only_streak = 0
                    pending_streak = 0
                    if interrupted:
                        continue
                    last_opened = opened
                    continue

            if det_flag or subset_flag:
                prioritized_flags: list[tuple[int, int]] = []
                seen_flag_cells: set[tuple[int, int]] = set()
                for source in (det_flag, subset_flag):
                    for cell in source:
                        if cell in seen_flag_cells:
                            continue
                        seen_flag_cells.add(cell)
                        if (
                            cell not in observed_flag_cells
                            and cell not in confirmed_open_values
                            and board[cell] == STATE_HIDDEN
                        ):
                            prioritized_flags.append(cell)
                prioritized_flags = sorted(
                    prioritized_flags,
                    key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
                )[:MAX_DET_FLAG_BATCH]
                if prioritized_flags:
                    interrupted = False
                    for flag_index, (row, col) in enumerate(prioritized_flags):
                        cell = (row, col)
                        if cell in observed_flag_cells or cell in confirmed_open_values or board[cell] != STATE_HIDDEN:
                            continue
                        self.right_click(row, col)
                        time.sleep(0.12)
                        arr, post_flag_board, flag_result = self.assess_board_action_result(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_prioritized_flags_{step:03d}_{flag_index:02d}.png",
                            expected_state=STATE_FLAG,
                        )
                        if flag_result in {"game_over_dialog", "lost"}:
                            interrupted = True
                            break
                        if flag_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"prioritized_flag_interrupted:{flag_result}")
                            interrupted = True
                            break
                        if flag_result == "changed" and post_flag_board is not None:
                            board, observed_flag_cells = self.merge_solver_board_state(
                                post_flag_board,
                                confirmed_open_values,
                                ever_open_cells,
                            )
                            board_signature = hash(board.tobytes())
                        if flag_result == "no_effect":
                            self.capture(f"attempt_{self.attempt:02d}_prioritized_flag_no_effect_{step:03d}_{flag_index:02d}.png")
                            self.last_actions.append("prioritized_flag_no_effect")
                            interrupted = True
                            break
                        if flag_result == "blocked":
                            self.capture(f"attempt_{self.attempt:02d}_prioritized_flag_blocked_{step:03d}_{flag_index:02d}.png")
                            self.last_actions.append("prioritized_flag_blocked")
                            interrupted = True
                            break
                    self.last_actions.append(f"prioritized_flags:{len(prioritized_flags)}")
                    flag_only_streak += 1
                    pending_streak = 0
                    if interrupted:
                        continue
                    continue

            if det_open:
                det_open = sorted(
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
                    key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
                )[:MAX_DET_OPEN_BATCH]
                if det_open:
                    interrupted = False
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
                            self.last_actions.append("open_blocked")
                            interrupted = True
                            break
                        arr, post_open_board, click_result = self.attempt_open_action(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_opens_{step:03d}_{open_index:02d}.png",
                        )
                        clicked_open_cells.add(cell)
                        if click_result in {"game_over_dialog", "lost"}:
                            interrupted = True
                            break
                        if click_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"open_interrupted:{click_result}")
                            interrupted = True
                            break
                        if click_result == "changed" and post_open_board is not None:
                            board, observed_flag_cells = self.merge_solver_board_state(
                                post_open_board,
                                confirmed_open_values,
                                ever_open_cells,
                            )
                            board_signature = hash(board.tobytes())
                        if click_result == "no_effect":
                            disallowed_open_cells.add(cell)
                            self.capture(f"attempt_{self.attempt:02d}_open_no_effect_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("open_no_effect")
                            interrupted = True
                            break
                        if click_result == "blocked":
                            disallowed_open_cells.add(cell)
                            self.capture(f"attempt_{self.attempt:02d}_open_blocked_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("open_blocked")
                            interrupted = True
                            break
                    self.last_actions.append(f"det_opens:{len(det_open)}")
                    flag_only_streak = 0
                    pending_streak = 0
                    if interrupted:
                        continue
                    last_opened = opened
                    continue

            if csp_flag:
                fresh_csp_flags = [
                    cell
                    for cell in csp_flag
                    if cell not in observed_flag_cells
                    and cell not in confirmed_open_values
                    and board[cell] == STATE_HIDDEN
                ]
                voted_cells = []
                current_candidates = set(fresh_csp_flags)
                pending_csp_flags = {
                    cell: count
                    for cell, count in pending_csp_flags.items()
                    if cell in current_candidates
                }
                for cell in fresh_csp_flags:
                    pending_csp_flags[cell] = pending_csp_flags.get(cell, 0) + 1
                    if pending_csp_flags[cell] >= CSP_FLAG_CONFIRM_FRAMES:
                        voted_cells.append(cell)
                fresh_csp_flags = sorted(
                    voted_cells,
                    key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
                )[:MAX_DET_FLAG_BATCH]
                if not fresh_csp_flags:
                    self.last_actions.append("csp_flags_pending")
                    continue
                interrupted = False
                for flag_index, (row, col) in enumerate(fresh_csp_flags):
                    cell = (row, col)
                    if cell in observed_flag_cells or cell in confirmed_open_values or cell in clicked_open_cells or board[cell] != STATE_HIDDEN:
                        continue
                    self.right_click(row, col)
                    pending_csp_flags.pop(cell, None)
                    time.sleep(0.12)
                    arr, post_flag_board, flag_result = self.assess_board_action_result(
                        arr,
                        board,
                        board_signature,
                        cell,
                        f"attempt_{self.attempt:02d}_csp_flags_{step:03d}_{flag_index:02d}.png",
                        expected_state=STATE_FLAG,
                    )
                    if flag_result in {"game_over_dialog", "lost"}:
                        interrupted = True
                        break
                    if flag_result in {"new_game", "exit_game", "process_missing"}:
                        self.last_actions.append(f"csp_flag_interrupted:{flag_result}")
                        interrupted = True
                        break
                    if flag_result == "changed" and post_flag_board is not None:
                        board, observed_flag_cells = self.merge_solver_board_state(
                            post_flag_board,
                            confirmed_open_values,
                            ever_open_cells,
                        )
                        board_signature = hash(board.tobytes())
                    if flag_result == "no_effect":
                        self.capture(f"attempt_{self.attempt:02d}_csp_flag_no_effect_{step:03d}_{flag_index:02d}.png")
                        self.last_actions.append("csp_flag_no_effect")
                        interrupted = True
                        break
                    if flag_result == "blocked":
                        self.capture(f"attempt_{self.attempt:02d}_csp_flag_blocked_{step:03d}_{flag_index:02d}.png")
                        self.last_actions.append("csp_flag_blocked")
                        interrupted = True
                        break
                self.last_actions.append(f"csp_flags:{len(fresh_csp_flags)}")
                flag_only_streak += 1
                pending_streak = 0
                if interrupted:
                    continue
                continue

            if det_flag:
                fresh_flags = [
                    cell
                    for cell in det_flag
                    if cell not in observed_flag_cells
                    and cell not in confirmed_open_values
                    and board[cell] == STATE_HIDDEN
                ]
                current_det_flags = set(fresh_flags)
                pending_det_flags = {
                    cell: count
                    for cell, count in pending_det_flags.items()
                    if cell in current_det_flags
                }
                for cell in fresh_flags:
                    pending_det_flags[cell] = pending_det_flags.get(cell, 0) + 1
                fresh_flags = [cell for cell in fresh_flags if pending_det_flags[cell] >= DET_FLAG_CONFIRM_FRAMES]
                if not fresh_flags:
                    self.last_actions.append("flags_pending")
                    continue
                fresh_flags = sorted(
                    fresh_flags,
                    key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
                )[:MAX_DET_FLAG_BATCH]
                interrupted = False
                for flag_index, (row, col) in enumerate(fresh_flags):
                    cell = (row, col)
                    if cell in observed_flag_cells or cell in confirmed_open_values or cell in clicked_open_cells or board[cell] != STATE_HIDDEN:
                        continue
                    self.right_click(row, col)
                    pending_det_flags.pop(cell, None)
                    time.sleep(0.12)
                    arr, post_flag_board, flag_result = self.assess_board_action_result(
                        arr,
                        board,
                        board_signature,
                        cell,
                        f"attempt_{self.attempt:02d}_flags_{step:03d}_{flag_index:02d}.png",
                        expected_state=STATE_FLAG,
                    )
                    if flag_result in {"game_over_dialog", "lost"}:
                        interrupted = True
                        break
                    if flag_result in {"new_game", "exit_game", "process_missing"}:
                        self.last_actions.append(f"flag_interrupted:{flag_result}")
                        interrupted = True
                        break
                    if flag_result == "changed" and post_flag_board is not None:
                        board, observed_flag_cells = self.merge_solver_board_state(
                            post_flag_board,
                            confirmed_open_values,
                            ever_open_cells,
                        )
                        board_signature = hash(board.tobytes())
                    if flag_result == "no_effect":
                        self.capture(f"attempt_{self.attempt:02d}_flag_no_effect_{step:03d}_{flag_index:02d}.png")
                        self.last_actions.append("flag_no_effect")
                        interrupted = True
                        break
                    if flag_result == "blocked":
                        self.capture(f"attempt_{self.attempt:02d}_flag_blocked_{step:03d}_{flag_index:02d}.png")
                        self.last_actions.append("flag_blocked")
                        interrupted = True
                        break
                self.last_actions.append(f"flags:{len(fresh_flags)}")
                flag_only_streak += 1
                pending_streak = 0
                if interrupted:
                    continue
                continue

            if subset_open:
                subset_open = sorted(
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
                    key=lambda cell: (-self.support_count(board, cell), cell[0], cell[1]),
                )[:MAX_DET_OPEN_BATCH]
                if subset_open:
                    interrupted = False
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
                            self.last_actions.append("subset_open_blocked")
                            interrupted = True
                            break
                        arr, post_open_board, click_result = self.attempt_open_action(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_subset_opens_{step:03d}_{open_index:02d}.png",
                        )
                        clicked_open_cells.add(cell)
                        if click_result in {"game_over_dialog", "lost"}:
                            interrupted = True
                            break
                        if click_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"subset_open_interrupted:{click_result}")
                            interrupted = True
                            break
                        if click_result == "changed" and post_open_board is not None:
                            board, observed_flag_cells = self.merge_solver_board_state(
                                post_open_board,
                                confirmed_open_values,
                                ever_open_cells,
                            )
                            board_signature = hash(board.tobytes())
                        if click_result == "no_effect":
                            disallowed_open_cells.add(cell)
                            self.capture(f"attempt_{self.attempt:02d}_subset_open_no_effect_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("subset_open_no_effect")
                            interrupted = True
                            break
                        if click_result == "blocked":
                            disallowed_open_cells.add(cell)
                            self.capture(f"attempt_{self.attempt:02d}_subset_open_blocked_{step:03d}_{open_index:02d}.png")
                            self.last_actions.append("subset_open_blocked")
                            interrupted = True
                            break
                    self.last_actions.append(f"subset_opens:{len(subset_open)}")
                    flag_only_streak = 0
                    pending_streak = 0
                    if interrupted:
                        continue
                    last_opened = opened
                    continue

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
                    for flag_index, (row, col) in enumerate(sorted(fresh_subset_flags)[:MAX_DET_FLAG_BATCH]):
                        cell = (row, col)
                        if cell in observed_flag_cells or cell in confirmed_open_values or board[cell] != STATE_HIDDEN:
                            continue
                        self.right_click(row, col)
                        time.sleep(0.12)
                        arr, post_flag_board, flag_result = self.assess_board_action_result(
                            arr,
                            board,
                            board_signature,
                            cell,
                            f"attempt_{self.attempt:02d}_subset_flags_{step:03d}_{flag_index:02d}.png",
                            expected_state=STATE_FLAG,
                        )
                        if flag_result in {"game_over_dialog", "lost"}:
                            interrupted = True
                            break
                        if flag_result in {"new_game", "exit_game", "process_missing"}:
                            self.last_actions.append(f"subset_flag_interrupted:{flag_result}")
                            interrupted = True
                            break
                        if flag_result == "changed" and post_flag_board is not None:
                            board, observed_flag_cells = self.merge_solver_board_state(
                                post_flag_board,
                                confirmed_open_values,
                                ever_open_cells,
                            )
                            board_signature = hash(board.tobytes())
                        if flag_result == "no_effect":
                            self.capture(f"attempt_{self.attempt:02d}_subset_flag_no_effect_{step:03d}_{flag_index:02d}.png")
                            self.last_actions.append("subset_flag_no_effect")
                            interrupted = True
                            break
                        if flag_result == "blocked":
                            self.capture(f"attempt_{self.attempt:02d}_subset_flag_blocked_{step:03d}_{flag_index:02d}.png")
                            self.last_actions.append("subset_flag_blocked")
                            interrupted = True
                            break
                    self.last_actions.append(f"subset_flags:{min(len(fresh_subset_flags), MAX_DET_FLAG_BATCH)}")
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
                cell = rescue_open[0]
                arr, post_open_board, click_result = self.attempt_open_action(
                    arr,
                    board,
                    board_signature,
                    cell,
                    f"attempt_{self.attempt:02d}_rescue_open_{step:03d}.png",
                )
                clicked_open_cells.add(cell)
                self.last_actions.append("rescue_open")
                if click_result in {"changed", "game_over_dialog", "lost"}:
                    if click_result == "changed" and post_open_board is not None:
                        board, observed_flag_cells = self.merge_solver_board_state(
                            post_open_board,
                            confirmed_open_values,
                            ever_open_cells,
                        )
                        board_signature = hash(board.tobytes())
                    continue
                if click_result in {"new_game", "exit_game", "process_missing"}:
                    self.last_actions.append(f"rescue_open_interrupted:{click_result}")
                    return False
                disallowed_open_cells.add(cell)
                continue
            if rescue_flag:
                row, col = rescue_flag[0]
                self.right_click(row, col)
                time.sleep(0.12)
                arr, post_flag_board, flag_result = self.assess_board_action_result(
                    arr,
                    board,
                    board_signature,
                    (row, col),
                    f"attempt_{self.attempt:02d}_rescue_flag_{step:03d}.png",
                    expected_state=STATE_FLAG,
                )
                self.last_actions.append("rescue_flag")
                if flag_result in {"changed", "game_over_dialog", "lost"}:
                    if flag_result == "changed" and post_flag_board is not None:
                        board, observed_flag_cells = self.merge_solver_board_state(
                            post_flag_board,
                            confirmed_open_values,
                            ever_open_cells,
                        )
                        board_signature = hash(board.tobytes())
                    continue
                if flag_result in {"new_game", "exit_game", "process_missing"}:
                    self.last_actions.append(f"rescue_flag_interrupted:{flag_result}")
                    return False
                continue

            blocked_guess_cells = self.forbidden_open_cells(
                clicked_open_cells,
                ever_open_cells,
                confirmed_open_values,
                disallowed_open_cells,
            )
            guess_row, guess_col = self.guess_cell(board, blocked_guess_cells)
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
                if SINGLE_ATTEMPT_MODE:
                    continue
                return False
            arr, post_guess_board, click_result = self.attempt_open_action(
                arr,
                board,
                board_signature,
                (guess_row, guess_col),
                f"attempt_{self.attempt:02d}_guess_{step:03d}.png",
            )
            clicked_open_cells.add((guess_row, guess_col))
            self.last_actions.append(f"guess:{guess_row},{guess_col}")
            flag_only_streak = 0
            pending_streak = 0
            guessed_cells.append((guess_row, guess_col))
            if click_result in {"game_over_dialog", "lost"}:
                self.capture(f"attempt_{self.attempt:02d}_lost_guess_{step:03d}.png")
                if self.current_first_click is not None:
                    self.failed_openers[self.current_first_click] += 1
                for cell in guessed_cells[-3:]:
                    self.failed_guess_counts[cell] += 1
                return False
            if click_result in {"new_game", "exit_game", "process_missing"}:
                self.last_actions.append(f"guess_interrupted:{click_result}")
                return False
            if click_result == "no_effect":
                disallowed_open_cells.add((guess_row, guess_col))
                self.capture(f"attempt_{self.attempt:02d}_guess_no_effect_{step:03d}.png")
                self.last_actions.append("guess_no_effect")
                self.failed_guess_counts[(guess_row, guess_col)] += 2
                continue
            if click_result == "blocked":
                disallowed_open_cells.add((guess_row, guess_col))
                self.capture(f"attempt_{self.attempt:02d}_guess_blocked_{step:03d}.png")
                self.last_actions.append("guess_blocked")
                self.failed_guess_counts[(guess_row, guess_col)] += 1
                if SINGLE_ATTEMPT_MODE:
                    continue
                return False
            last_opened = opened

        self.capture(f"attempt_{self.attempt:02d}_timeout.png")
        return False

    def run(self) -> None:
        max_attempts = 1 if SINGLE_ATTEMPT_MODE else MAX_ATTEMPTS
        for attempt in range(1, max_attempts + 1):
            self.attempt = attempt
            if self.solve_once():
                print(f"SUCCESS attempt={attempt}")
                return
            if SINGLE_ATTEMPT_MODE:
                self.write_stop_summary("single_attempt_finished_without_win")
                raise RuntimeError("\u5355\u5c40\u6d4b\u8bd5\u5df2\u7ed3\u675f\uff08\u672a\u901a\u5173\uff09")
            if self.failure_started_at is None:
                self.failure_started_at = time.time()
            if time.time() - self.failure_started_at > MAX_REPEAT_FAILURE_SECONDS:
                self.write_stop_summary("repeated_failures_over_3_minutes")
                raise RuntimeError("\u91cd\u590d\u5931\u8d25\u5df2\u8d85\u8fc7 3 \u5206\u949f\uff0c\u5df2\u505c\u6b62\u81ea\u52a8\u91cd\u8bd5")
            print(f"RETRY attempt={attempt}")
            time.sleep(0.8)
        self.write_stop_summary("attempt_limit_reached")
        raise RuntimeError("\u626b\u96f7\u672a\u80fd\u5728\u9650\u5b9a\u6b21\u6570\u5185\u901a\u5173")


if __name__ == "__main__":
    MinesweeperSolver().run()
