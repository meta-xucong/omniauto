# Knowledge Workflow

这份文档说明任务完成后，仓库应该如何自动沉淀知识，以及哪些升级必须等待用户批准。

如果你想看这套机制的正式实施蓝图，请继续阅读：

- [AUTOMATIC_KNOWLEDGE_GROWTH_BLUEPRINT.md](AUTOMATIC_KNOWLEDGE_GROWTH_BLUEPRINT.md)

## 核心原则

这套仓库有两条升级通道：

1. 软升级
   - 自动写入 `knowledge/`
2. 硬落地
   - 只有用户明确要求时，才进入 `skills/` 或 `platform/`

## 每次任务结束后的标准闭环

1. 保留可执行脚本在 `workflows/`
2. 保留正式输出在 `runtime/data/` 或 `runtime/outputs/`
3. 保留调试和验证痕迹在 `runtime/test_artifacts/`
4. 新增或更新 `knowledge/tasks/` 任务记录
5. 把可复用流程提炼到 `knowledge/patterns/emerging/` 或 `knowledge/patterns/reusable/`
6. 把长期经验提炼到 `knowledge/lessons/`
7. 把能力边界变化更新到 `knowledge/capabilities/observed/` 或 `knowledge/capabilities/candidate/`
8. 如果 AI 认为未来值得正式固化，则登记到 `knowledge/proposals/`
9. 只有用户明确要求时，才升级到 `skills/` 或继续硬化进 `platform/`

除了任务显式发出的 observation 之外，closeout 现在还会基于低风险信号自动补一层知识合成，例如：

1. `verification/` 任务成功完成
2. `VALIDATION_FAILED`
3. `timeout` / `not found`
4. `manual handoff` / `verification challenge`

这些自动合成出的内容仍然只会进入 `knowledge/`，不会越级进入 `skills/` 或 `platform/`。

## 受控入口与兜底补结项

默认会自动触发知识沉淀的“受控任务入口”应包括：

1. `OmniAutoService.run_workflow()`
2. `omni run`
3. `OmniAutoAgent.process()` 内部触发的受控 workflow 运行
4. `OmniAutoService.schedule_task()` 触发的定时 workflow 运行

当前自动沉淀的前提是：

1. 任务脚本位于仓库 `workflows/` 目录下
2. 任务通过上述受控入口执行

不满足这两个条件的脚本，默认不会自动写入 `knowledge/`。

这类情况应使用兜底补结项：

1. `OmniAutoService.closeout_task()`
2. `omni closeout`

## 临时任务和长期资产的区别

- `workflows/temporary/`
  - 一次性、探索性、偶尔使用
- `workflows/generated/`
  - 自动生成且仍值得保留
- `knowledge/`
  - 任务记忆、模式、经验、能力说明
- `skills/`
  - 用户批准后的正式能力包
- `platform/`
  - 用户批准后的长期基础设施

## 给新 AI 的最短阅读路径

1. `START_HERE.md`
2. `PROJECT_STRUCTURE.md`
3. `knowledge/README.md`
4. `knowledge/index/task_catalog.md`
5. `knowledge/index/capability_matrix.md`
6. `knowledge/index/proposal_queue.md`

## Governance Addendum

For the landed governance layer, also read:

- [GUARDED_KNOWLEDGE_CLOSEOUT.md](GUARDED_KNOWLEDGE_CLOSEOUT.md)
- `platform/src/omniauto/knowledge/policy.py`
- `.agents/skills/guarded-knowledge-closeout/SKILL.md`
