# minesweeper_autoplay

这是一个用户批准的 OmniAuto 正式 `task_skill`。

- Runtime bundle: `.agents/skills/minesweeper-autoplay/`
- App package: `apps/minesweeper_autoplay/`
- Scope: 运行、长测、诊断并优化 Windows 扫雷自动游玩流程
- Primary solver: `apps/minesweeper_autoplay/workflows/minesweeper_solver.py`
- Main artifacts: `runtime/apps/minesweeper_autoplay/test_artifacts/`

## What This Skill Covers

- 自动启动并操作 Windows 扫雷
- 单局与多局回归测试
- 长测监控
- 失败截图与日志复盘
- 识图、几何、点击、策略、运行控制问题的分流诊断
- 在现有 solver 基础上的持续迭代优化

## Boundaries

- This skill formalizes the task family; it does not by itself move the implementation into `platform/src/omniauto/skills/`.
- Formal platformization requires separate user approval.
- Ongoing task memory and reusable lessons should still continue to land in `knowledge/` when appropriate.

## Runtime Entry

For runtime behavior, use the bundle under:

- `apps/minesweeper_autoplay/`
- `.agents/skills/minesweeper-autoplay/`

The app package is the formal task implementation. The `.agents` bundle is the AI-facing operational skill and should point to the app entrypoints.
