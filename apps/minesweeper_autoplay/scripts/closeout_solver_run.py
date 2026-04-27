from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable


DEFAULT_TASK_ID = "minesweeper_solver_exploration"
DEFAULT_DESCRIPTION = "Minesweeper autoplay skill run"
MEANINGFUL_MIN_DURATION_SECONDS = 180.0
MEANINGFUL_STOP_REASONS = {
    "attempt_limit_reached",
    "repeated_failures_over_time_limit",
}
MEANINGFUL_ERROR_TOKENS = (
    "timeout",
    "not found",
    "manual_handoff",
    "verification challenge",
    "process_missing",
    "exit_game",
    "new_game",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Close out one minesweeper solver run into OmniAuto knowledge.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--solver", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--mode", default="single")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--run-start-epoch", type=float, default=0.0)
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--domain", default="desktop")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.resolve().as_posix()


def parse_summary(summary_path: Path) -> dict[str, str]:
    if not summary_path.exists():
        return {}
    data: dict[str, str] = {}
    for raw_line in summary_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def parse_float(raw_value: str | None) -> float:
    if not raw_value:
        return 0.0
    try:
        return float(raw_value)
    except ValueError:
        return 0.0


def newest_matching(paths: Iterable[Path], *, run_start_epoch: float) -> Path | None:
    eligible = []
    min_epoch = run_start_epoch - 2.0 if run_start_epoch > 0 else 0.0
    for path in paths:
        try:
            if path.is_file() and path.stat().st_mtime >= min_epoch:
                eligible.append(path)
        except OSError:
            continue
    if not eligible:
        return None
    return max(eligible, key=lambda item: item.stat().st_mtime)


def latest_terminal_artifact(artifacts_dir: Path, *, run_start_epoch: float) -> Path | None:
    patterns = (
        "attempt_*_won*.png",
        "attempt_*_lost*.png",
        "attempt_*_lost_guess_*.png",
        "attempt_*_timeout.png",
        "attempt_*_process_missing*.png",
    )
    candidates = []
    for pattern in patterns:
        candidates.extend(artifacts_dir.glob(pattern))
    return newest_matching(candidates, run_start_epoch=run_start_epoch)


def latest_stderr_log(artifacts_dir: Path, *, run_start_epoch: float) -> Path | None:
    return newest_matching(artifacts_dir.glob("*.err.log"), run_start_epoch=run_start_epoch)


def safe_read_text(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def should_trust_summary(summary_path: Path, *, exit_code: int, run_start_epoch: float) -> bool:
    if exit_code == 0:
        return False
    if not summary_path.exists():
        return False
    if run_start_epoch <= 0:
        return True
    try:
        return summary_path.stat().st_mtime >= (run_start_epoch - 2.0)
    except OSError:
        return False


def infer_final_state(exit_code: int, stop_reason: str) -> str:
    if exit_code == 0:
        return "COMPLETED"
    if stop_reason == "repeated_failures_over_time_limit":
        return "TIMEOUT"
    if stop_reason in {
        "single_attempt_finished_without_win",
        "stopped_after_loss",
        "attempt_limit_reached",
    }:
        return "FAILED"
    if any(token in stop_reason for token in ("without_win", "loss", "attempt_limit", "fail")):
        return "FAILED"
    return "ERROR"


def meaningful_reasons(
    *,
    exit_code: int,
    stop_reason: str,
    duration_seconds: float,
    summary_data: dict[str, str],
    stderr_log: Path | None,
    terminal_artifact: Path | None,
) -> list[str]:
    reasons: list[str] = []
    if exit_code == 0:
        reasons.append("solver_completed_successfully")
    if stop_reason in MEANINGFUL_STOP_REASONS:
        reasons.append(f"stop_reason:{stop_reason}")
    if duration_seconds >= MEANINGFUL_MIN_DURATION_SECONDS and stop_reason:
        reasons.append(f"duration>={int(MEANINGFUL_MIN_DURATION_SECONDS)}s")
    lowered_blob = " ".join(
        part
        for part in (
            stop_reason,
            summary_data.get("analysis", ""),
            summary_data.get("next_steps", ""),
            safe_read_text(stderr_log),
        )
        if part
    ).lower()
    if any(token in lowered_blob for token in MEANINGFUL_ERROR_TOKENS):
        reasons.append("boundary_or_error_signal")
    if terminal_artifact is not None and "won" in terminal_artifact.name.lower():
        reasons.append("terminal_win_artifact")
    return reasons


def build_manual_note(
    *,
    mode: str,
    exit_code: int,
    stop_reason: str,
    duration_seconds: float,
    summary_path: Path | None,
    terminal_artifact: Path | None,
    stderr_log: Path | None,
    summary_data: dict[str, str],
    repo_root: Path,
) -> str:
    lines = [
        "Automated closeout from minesweeper-autoplay wrapper.",
        f"wrapper_mode={mode}",
        f"solver_exit_code={exit_code}",
    ]
    if stop_reason:
        lines.append(f"stop_reason={stop_reason}")
    if duration_seconds > 0:
        lines.append(f"elapsed_seconds={duration_seconds}")
    if summary_path is not None:
        lines.append(f"summary={relative_to_repo(summary_path, repo_root)}")
    if terminal_artifact is not None:
        lines.append(f"terminal_artifact={relative_to_repo(terminal_artifact, repo_root)}")
    if stderr_log is not None:
        lines.append(f"stderr_log={relative_to_repo(stderr_log, repo_root)}")
    if summary_data.get("run_mode"):
        lines.append(f"solver_run_mode={summary_data['run_mode']}")
    if summary_data.get("last_actions"):
        lines.append(f"last_actions={summary_data['last_actions']}")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    solver_path = Path(args.solver).resolve()
    artifacts_dir = Path(args.artifacts_dir).resolve()
    summary_path = artifacts_dir / "solver_stop_summary.txt"

    summary_data = {}
    if should_trust_summary(summary_path, exit_code=args.exit_code, run_start_epoch=args.run_start_epoch):
        summary_data = parse_summary(summary_path)

    stop_reason = summary_data.get("reason", "")
    duration_seconds = parse_float(summary_data.get("elapsed_seconds"))
    final_state = infer_final_state(args.exit_code, stop_reason)

    terminal_artifact = latest_terminal_artifact(artifacts_dir, run_start_epoch=args.run_start_epoch)
    stderr_log = latest_stderr_log(artifacts_dir, run_start_epoch=args.run_start_epoch)
    trusted_summary_path = summary_path if summary_data else None

    note = build_manual_note(
        mode=args.mode,
        exit_code=args.exit_code,
        stop_reason=stop_reason,
        duration_seconds=duration_seconds,
        summary_path=trusted_summary_path,
        terminal_artifact=terminal_artifact,
        stderr_log=stderr_log,
        summary_data=summary_data,
        repo_root=repo_root,
    )

    payload = {
        "script": relative_to_repo(solver_path, repo_root),
        "task_id": args.task_id,
        "description": args.description,
        "domain": args.domain,
        "final_state": final_state,
        "duration_seconds": duration_seconds,
        "note": note,
    }
    reasons = meaningful_reasons(
        exit_code=args.exit_code,
        stop_reason=stop_reason,
        duration_seconds=duration_seconds,
        summary_data=summary_data,
        stderr_log=stderr_log,
        terminal_artifact=terminal_artifact,
    )
    payload["meaningful_reasons"] = reasons
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not reasons:
        print(
            json.dumps(
                {
                    "enabled": False,
                    "applied": False,
                    "reason": "run_not_meaningful",
                    "task_id": args.task_id,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    sys.path.insert(0, str((repo_root / "platform" / "src").resolve()))
    from omniauto.service import OmniAutoService

    service = OmniAutoService()
    summary = service.closeout_task(
        str(solver_path),
        task_id=args.task_id,
        final_state=final_state,
        description=args.description,
        note=note,
        domain=args.domain,
        duration_seconds=duration_seconds,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
