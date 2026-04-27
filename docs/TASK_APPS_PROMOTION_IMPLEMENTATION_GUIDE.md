# 1688 与扫雷任务应用化代码实现指导文档

## 1. 实施方式

本改造按章节推进。每章只做一组相关改动，完成后运行对应验证。当前章节验证通过后，再进入下一章。

## 2. 章节 0：方案与任务状态

建立本次应用化改造的方案文档、实施文档和长任务路线。

验收：

```powershell
Test-Path docs/TASK_APPS_PROMOTION_OPTIMIZATION_GUIDE.md
Test-Path docs/TASK_APPS_PROMOTION_IMPLEMENTATION_GUIDE.md
python C:\Users\兰落落的本本\.codex\skills\long-running-task\scripts\validate_state.py --project D:\AI\AI_RPA
```

## 3. 章节 1：建立两个应用包骨架

创建 1688 和扫雷的正式 app 目录。

需要完成：

- `apps/marketplace_1688_research/`
- `apps/minesweeper_autoplay/`
- 对应 `configs/`、`workflows/`、`scripts/`、`tests/`、`docs/`
- 对应 `runtime/apps/...`

验收：

```powershell
Test-Path apps/marketplace_1688_research/README.md
Test-Path apps/minesweeper_autoplay/README.md
```

## 4. 章节 2：1688 应用化迁移

把 1688 调研的正式入口迁移到 `apps/marketplace_1688_research/`。

需要完成：

- 复制基础 workflow 到 app。
- 复制并调整 builder，使生成 workflow 使用 app 内基础 workflow。
- 新增 app runner `scripts/run-report.ps1`。
- 复制 closeout helper。
- 新增默认配置。
- 新增离线检查脚本。

验收：

```powershell
uv run python -m py_compile apps/marketplace_1688_research/workflows/base_1688_research.py
uv run python apps/marketplace_1688_research/workflows/build_1688_workflow.py --repo-root D:\AI\AI_RPA --keyword 测试 --pages 1 --detail-sample-size 0 --task-slug app_smoke
powershell -ExecutionPolicy Bypass -File apps/marketplace_1688_research/scripts/run-report.ps1 -Keyword 测试 -Pages 1 -DetailSampleSize 0 -TaskSlug app_preview -Preview
uv run python apps/marketplace_1688_research/tests/run_offline_checks.py
```

## 5. 章节 3：扫雷应用化迁移

把扫雷自动游玩正式入口迁移到 `apps/minesweeper_autoplay/`。

需要完成：

- 复制 solver 到 app。
- 调整 solver 默认 artifact 目录。
- 新增 app runner `scripts/run-solver.ps1`。
- 复制 closeout helper。
- 新增默认配置。
- 新增离线检查脚本。

验收：

```powershell
uv run python -m py_compile apps/minesweeper_autoplay/workflows/minesweeper_solver.py
uv run python apps/minesweeper_autoplay/workflows/minesweeper_solver.py --help
powershell -ExecutionPolicy Bypass -File apps/minesweeper_autoplay/scripts/run-solver.ps1 -Mode single -Preview
uv run python apps/minesweeper_autoplay/tests/run_offline_checks.py
```

## 6. 章节 4：更新技能入口和用户结构说明

让 AI-facing skill 和用户可读 task skill 都指向新的 app 结构。

需要完成：

- 更新 `.agents/skills/1688-marketplace-research/SKILL.md`。
- 更新 `.agents/skills/minesweeper-autoplay/SKILL.md`。
- 更新 `skills/task_skills/marketplace_1688_research/README.md`。
- 更新 `skills/task_skills/minesweeper_autoplay/README.md`。
- 更新 `docs/USER_READABLE_PROJECT_STRUCTURE_OVERVIEW.md`。

验收：

```powershell
Select-String -Path .agents/skills/1688-marketplace-research/SKILL.md -Pattern apps/marketplace_1688_research
Select-String -Path .agents/skills/minesweeper-autoplay/SKILL.md -Pattern apps/minesweeper_autoplay
```

## 7. 章节 5：全量验证与收尾

确认两个 app 的结构、runner、离线检查和文档全部可用。

验收：

```powershell
uv run python apps/marketplace_1688_research/tests/run_offline_checks.py
uv run python apps/minesweeper_autoplay/tests/run_offline_checks.py
python C:\Users\兰落落的本本\.codex\skills\long-running-task\scripts\validate_state.py --project D:\AI\AI_RPA
```

全部通过后，将 `.codex-longrun/state.json` 标记为 `done`。

