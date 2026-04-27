from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


DEFAULT_TASK_ID = "marketplace_1688_research"
DEFAULT_DESCRIPTION = "1688 marketplace research skill run"
MEANINGFUL_MIN_DURATION_SECONDS = 180.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Close out one 1688 marketplace research run into OmniAuto knowledge.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--pages", type=int, default=3)
    parser.add_argument("--detail-sample-size", type=int, default=27)
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--run-start-epoch", type=float, default=0.0)
    parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--domain", default="marketplaces")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def relative_to_repo(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.resolve().as_posix()


def safe_load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def infer_final_state(exit_code: int, status: dict) -> str:
    state = (status.get("state") or "").lower()
    if exit_code == 0 and state == "completed":
        return "COMPLETED"
    if state in {"manual_browser_launched", "manual_handoff_ready"}:
        return "FAILED"
    if state == "error":
        return "ERROR"
    if exit_code == 0:
        return "COMPLETED"
    return "FAILED"


def meaningful_reasons(*, exit_code: int, duration_seconds: float, status: dict, report_data: dict, manual_handoff: dict) -> list[str]:
    reasons: list[str] = []
    if exit_code == 0 and report_data.get("total_items", 0) > 0:
        reasons.append("report_generated")
    if report_data.get("detail_sample_completed", 0) > 0:
        reasons.append("detail_samples_captured")
    if status.get("state") in {"manual_browser_launched", "manual_handoff_ready"}:
        reasons.append("manual_handoff_boundary")
    lowered = " ".join(
        str(part)
        for part in (
            status.get("state", ""),
            status.get("stopped_reason", ""),
            manual_handoff.get("reason", ""),
        )
        if part
    ).lower()
    if any(token in lowered for token in ("verification", "manual_handoff", "captcha", "login")):
        reasons.append("verification_or_login_boundary")
    if duration_seconds >= MEANINGFUL_MIN_DURATION_SECONDS:
        reasons.append(f"duration>={int(MEANINGFUL_MIN_DURATION_SECONDS)}s")
    return reasons


def build_note(
    *,
    repo_root: Path,
    workflow_path: Path,
    output_dir: Path,
    keyword: str,
    pages: int,
    detail_sample_size: int,
    duration_seconds: float,
    status: dict,
    report_data: dict,
    manual_handoff: dict,
) -> str:
    lines = [
        "Automated closeout from 1688-marketplace-research wrapper.",
        f"keyword={keyword}",
        f"pages={pages}",
        f"detail_sample_size={detail_sample_size}",
        f"workflow={relative_to_repo(workflow_path, repo_root)}",
        f"output_dir={relative_to_repo(output_dir, repo_root)}",
    ]
    if duration_seconds > 0:
        lines.append(f"elapsed_seconds={duration_seconds:.1f}")
    if status:
        lines.append(f"status_state={status.get('state', '')}")
        if status.get("stopped_reason"):
            lines.append(f"stopped_reason={status['stopped_reason']}")
    if report_data:
        lines.append(f"total_items={report_data.get('total_items', 0)}")
        lines.append(f"detail_sample_completed={report_data.get('detail_sample_completed', 0)}")
        lines.append(f"report_html={relative_to_repo(output_dir / 'report.html', repo_root)}")
        lines.append(f"report_data={relative_to_repo(output_dir / 'report_data.json', repo_root)}")
    if manual_handoff:
        lines.append(f"manual_handoff={relative_to_repo(output_dir / 'manual_handoff.json', repo_root)}")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    workflow_path = Path(args.workflow).resolve()
    output_dir = Path(args.output_dir).resolve()
    status = safe_load_json(output_dir / "run_status.json")
    report_data = safe_load_json(output_dir / "report_data.json")
    manual_handoff = safe_load_json(output_dir / "manual_handoff.json")
    duration_seconds = max(0.0, time.time() - args.run_start_epoch) if args.run_start_epoch > 0 else 0.0
    final_state = infer_final_state(args.exit_code, status)
    reasons = meaningful_reasons(
        exit_code=args.exit_code,
        duration_seconds=duration_seconds,
        status=status,
        report_data=report_data,
        manual_handoff=manual_handoff,
    )
    note = build_note(
        repo_root=repo_root,
        workflow_path=workflow_path,
        output_dir=output_dir,
        keyword=args.keyword,
        pages=args.pages,
        detail_sample_size=args.detail_sample_size,
        duration_seconds=duration_seconds,
        status=status,
        report_data=report_data,
        manual_handoff=manual_handoff,
    )
    payload = {
        "script": relative_to_repo(workflow_path, repo_root),
        "task_id": args.task_id,
        "description": f"{args.description} ({args.keyword})",
        "domain": args.domain,
        "final_state": final_state,
        "duration_seconds": duration_seconds,
        "note": note,
        "meaningful_reasons": reasons,
    }

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
        str(workflow_path),
        task_id=args.task_id,
        final_state=final_state,
        description=f"{args.description} ({args.keyword})",
        note=note,
        domain=args.domain,
        duration_seconds=duration_seconds,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
