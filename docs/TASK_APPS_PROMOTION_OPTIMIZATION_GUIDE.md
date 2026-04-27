# 1688 与扫雷任务应用化改造方案

## 1. 改造目标

本次改造目标是把已有的 1688 关键词调研任务和 Windows 扫雷自动游玩任务，晋升为类似微信 AI 客服的独立 `apps/` 应用结构。

完成后应满足：

1. 每个复杂任务都有自己的应用包，任务之间不混放代码、配置、测试和运行产物。
2. 旧入口尽量保留兼容，但新的正式入口统一放在 `apps/` 下。
3. `.agents/skills/` 和 `skills/task_skills/` 继续作为 AI/用户的任务入口说明，但指向新的 app 结构。
4. 运行产物逐步进入 `runtime/apps/<app_name>/`，不再继续扩大混杂的临时目录。
5. 改造过程中不改 OmniAuto 底层能力，不重构业务逻辑，只做应用化整理、入口迁移和测试补齐。

## 2. 目标结构

```text
apps/
  marketplace_1688_research/
    README.md
    configs/
    workflows/
    scripts/
    tests/
    docs/

  minesweeper_autoplay/
    README.md
    configs/
    workflows/
    scripts/
    tests/
    docs/

runtime/
  apps/
    marketplace_1688_research/
      generated_workflows/
      reports/
      logs/

    minesweeper_autoplay/
      test_artifacts/
      logs/
```

## 3. 1688 任务边界

1688 任务的正式应用包：

```text
apps/marketplace_1688_research/
```

应包含基础 1688 调研 workflow、按关键词生成 ad hoc workflow 的 builder、runner、closeout helper、配置示例和离线检查脚本。

旧目录 `workflows/generated/marketplaces/`、`.agents/skills/1688-marketplace-research/`、`skills/task_skills/marketplace_1688_research/` 保留，但后两者应指向新的 app 入口。旧 generated workflows 保留作为历史和兼容参考，不做删除。

## 4. 扫雷任务边界

扫雷任务的正式应用包：

```text
apps/minesweeper_autoplay/
```

应包含 Minesweeper solver、runner、closeout helper、配置示例和离线检查脚本。

旧目录 `workflows/temporary/desktop/minesweeper_solver.py`、`.agents/skills/minesweeper-autoplay/`、`skills/task_skills/minesweeper_autoplay/` 保留作为历史兼容来源，但正式入口转向 `apps/minesweeper_autoplay/`。

## 5. 改造策略

采用“复制稳定入口、更新新入口、保留旧入口”的低风险策略：

1. 先新增 app 目录，不删除旧目录。
2. 将当前稳定代码复制到 app 包。
3. 新 runner 指向 app 内 workflow。
4. skill 文档指向 app 入口。
5. 增加离线检查，避免每次验证都打开浏览器或操作桌面。
6. 全量测试通过后，把 app 入口作为正式推荐入口。

## 6. 验证原则

1688 的实跑会访问外部网站，可能触发登录、验证或人工接管；扫雷实跑会操作桌面 UI。因此应用化阶段默认使用非侵入式验证：

- Python 静态编译。
- JSON 配置校验。
- runner `-Preview`。
- builder 生成 workflow 的离线检查。
- solver `--help` 或配置解析检查。

真实运行留到后续专项测试，不在结构迁移阶段自动触发。

