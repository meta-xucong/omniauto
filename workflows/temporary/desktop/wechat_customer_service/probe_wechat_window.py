"""Probe Windows WeChat UIA visibility and window activation."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from _probe_common import (
    add_common_args,
    capture_window_screenshot,
    dump_controls,
    ensure_artifact_dir,
    find_wechat_windows,
    focus_window,
    select_best_window,
    summaries_as_dicts,
    summarize_window,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    args = parser.parse_args()

    artifact_dir = ensure_artifact_dir("window_probe")
    windows = find_wechat_windows(args.title_pattern)
    selected = select_best_window(windows)

    result = {
        "title_pattern": args.title_pattern,
        "candidate_count": len(windows),
        "candidates": summaries_as_dicts(windows),
        "selected": asdict(summarize_window(selected)) if selected else None,
        "focused": False,
        "controls_path": None,
        "screenshot_path": None,
    }

    if selected is not None:
        result["focused"] = focus_window(selected)
        controls = dump_controls(selected, max_controls=args.max_controls)
        controls_path = artifact_dir / "uia_controls.json"
        write_json(controls_path, controls)
        result["controls_path"] = str(controls_path)

        screenshot_path = artifact_dir / "wechat_window.png"
        capture_window_screenshot(selected, screenshot_path)
        result["screenshot_path"] = str(screenshot_path)

    result_path = artifact_dir / "result.json"
    write_json(result_path, result)
    print(f"window_probe result: {result_path}")
    print(f"candidate_count={result['candidate_count']} focused={result['focused']}")
    return 0 if selected is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())

