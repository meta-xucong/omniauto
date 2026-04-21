# Automatic Knowledge Growth Blueprint

这份蓝图定义 OmniAuto 如何在任务执行后自动吸收长期知识，同时保持知识库可分层、可导航、可按需读取。

## 目标

这套机制要解决的不是“把所有历史堆成一个大文件”，而是让仓库具备下面这条自动闭环：

`任务执行 -> 证据落地 -> 经验提炼 -> 知识写回 -> 索引更新 -> 后续任务按需读取`

## 设计原则

1. `knowledge/` 自动成长，`skills/` 和 `platform/` 只接受用户明确批准后的硬落地。
2. 知识必须拆成多个小文件，按“知识类型 + 业务领域”分类存放，避免单文件无限膨胀。
3. 任何自动写回都必须带证据路径，不能凭空生成“经验”。
4. AI 默认先读取摘要导航，再按需打开对应正文，避免一次性加载整库内容。
5. 自动沉淀要幂等，可反复运行而不把知识库写乱。

## 非目标

1. 不做模型参数级学习。
2. 不让系统自动把经验升级成正式 `skill`。
3. 不让系统自动把实验代码硬化进 `platform/src/` 或 `platform/tests/`。

## 目标目录结构

知识库采用“类型分层 + 领域分桶 + 摘要索引”的结构：

```text
knowledge/
├─ tasks/
│  ├─ browser/
│  ├─ desktop/
│  ├─ marketplaces/
│  ├─ platform/
│  └─ general/
├─ patterns/
│  ├─ emerging/
│  │  ├─ browser/
│  │  ├─ desktop/
│  │  ├─ marketplaces/
│  │  ├─ platform/
│  │  └─ general/
│  └─ reusable/
│     ├─ browser/
│     ├─ desktop/
│     ├─ marketplaces/
│     ├─ platform/
│     └─ general/
├─ lessons/
│  ├─ browser/
│  ├─ desktop/
│  ├─ marketplaces/
│  ├─ platform/
│  └─ general/
├─ capabilities/
│  ├─ observed/
│  │  ├─ browser/
│  │  ├─ desktop/
│  │  ├─ marketplaces/
│  │  ├─ platform/
│  │  └─ general/
│  └─ candidate/
│     ├─ browser/
│     ├─ desktop/
│     ├─ marketplaces/
│     ├─ platform/
│     └─ general/
├─ proposals/
│  ├─ skill_candidates/
│  │  ├─ browser/
│  │  ├─ desktop/
│  │  ├─ marketplaces/
│  │  ├─ platform/
│  │  └─ general/
│  └─ platform_candidates/
│     ├─ browser/
│     ├─ desktop/
│     ├─ marketplaces/
│     ├─ platform/
│     └─ general/
├─ index/
│  ├─ task_catalog.md
│  ├─ pattern_index.md
│  ├─ lesson_index.md
│  ├─ capability_matrix.md
│  ├─ proposal_queue.md
│  ├─ knowledge_registry.json
│  └─ README.md
└─ _templates/
```

## 目录职责

### `knowledge/tasks/`

记录某次任务或某个任务族做了什么、输出在哪里、结论是什么。

### `knowledge/patterns/`

记录可复用方法，不等于正式 `skill`。

- `emerging/`
  - 刚从实践中提炼出来，值得参考，但还不够稳定。
- `reusable/`
  - 已经较稳定，后续任务应优先参考。

### `knowledge/lessons/`

记录长期有效的经验、边界、坑点、故障规律、调试结论。

### `knowledge/capabilities/`

记录项目目前已经被证据支持的能力边界。

- `observed/`
  - 已被真实任务或测试证据支持。
- `candidate/`
  - 值得进一步 formalize，但还不该自动宣称为正式能力。

### `knowledge/proposals/`

只做升级候选池。

- `skill_candidates/`
  - 等待用户决定是否升级成 `skills/`
- `platform_candidates/`
  - 等待用户决定是否进入 `platform/`

### `knowledge/index/`

只放摘要导航和机器可读注册表，不放长篇正文。

## 摘要导航设计

为了降低上下文和 token 成本，知识检索必须先读索引，再打开正文。

### `task_catalog.md`

一行概括一个任务或任务族，包含：

1. 标题
2. 领域
3. 状态
4. 主记录文件
5. 主要脚本或证据路径

### `pattern_index.md`

一行概括一个模式，包含：

1. 模式名称
2. 领域
3. 成熟度
4. 正文位置
5. 适用场景

### `lesson_index.md`

一行概括一条 lesson，包含：

1. lesson 名称
2. 领域
3. 触发问题
4. 正文位置

### `capability_matrix.md`

矩阵式概览当前能力域、成熟度、证据位置、边界说明。

### `proposal_queue.md`

集中查看目前等待人工审批的升级项。

### `knowledge_registry.json`

机器可读索引，给 AI 或自动程序快速检索用。

## 知识文件元数据

每个知识文件都应包含统一元数据头，便于自动更新和检索。

推荐字段：

```yaml
title: Minesweeper State-Sync Guard
kind: lesson
domain: desktop
status: observed
maturity: medium
tags:
  - visual
  - board-state
  - repeated-click
last_updated: 2026-04-21
evidence:
  - runtime/test_artifacts/verification/minesweeper/solver_stop_summary.txt
  - runtime/test_artifacts/verification/minesweeper/cell_action_diagnostics.txt
related:
  - knowledge/tasks/desktop/minesweeper_solver_exploration.md
  - knowledge/patterns/emerging/desktop/post_click_state_resync.md
promotion_target: none
approval_required: true
```

## 自动沉淀的写入边界

### 自动允许写入

1. `knowledge/tasks/`
2. `knowledge/patterns/emerging/`
3. `knowledge/patterns/reusable/`
4. `knowledge/lessons/`
5. `knowledge/capabilities/observed/`
6. `knowledge/capabilities/candidate/`
7. `knowledge/proposals/skill_candidates/`
8. `knowledge/proposals/platform_candidates/`
9. `knowledge/index/`

### 自动禁止写入

1. `skills/`
2. `platform/src/`
3. `platform/tests/`
4. `workflows/` 中与本次任务无关的正式脚本

## 自动沉淀流程

### Phase 1: TaskRun 建档

每次任务开始时创建一次运行记录，建议落到：

`runtime/knowledge_runs/<run_id>/task_run.json`

最少记录：

1. 任务标题
2. 任务领域
3. 关联脚本
4. 产物目录
5. 测试命令与结果
6. 关键日志摘要
7. 变更文件列表

### Phase 2: Evidence Collector

任务结束时自动汇总：

1. 新产物路径
2. 新测试结果
3. 新错误摘要
4. 新日志与诊断文件
5. 关键 diff 文件

### Phase 3: Closeout Synthesizer

根据证据判断是否产生以下知识：

1. `task record`
   - 任务本身有新的结果、验证或收尾结论
2. `pattern`
   - 出现了可复用的做法或控制策略
3. `lesson`
   - 出现了根因、边界、坑点或调试经验
4. `capability update`
   - 当前能力边界被增强、缩小或澄清
5. `proposal`
   - 值得人工考虑升级成 `skill` 或 `platform`

### Phase 4: Knowledge Updater

根据判定结果执行幂等写回：

1. 若已有对应知识文件，则追加“最新迭代”或更新状态字段。
2. 若不存在，则按模板新建最小文件。
3. 同步刷新 `knowledge/index/*` 和 `knowledge_registry.json`。

## 自动判定规则

### 何时自动新增或更新 `task`

满足任一条件即可：

1. 本次任务生成了新的正式输出或验证证据。
2. 本次任务修改了任务脚本或关键执行逻辑。
3. 本次任务得到了新的成功、失败或边界结论。

### 何时自动新增或更新 `pattern`

满足任一条件即可：

1. 某种处理方式在当前任务内被反复使用并证明有效。
2. 某种修复手法明显可迁移到同类任务。
3. 当前任务将原来的临时技巧提升成稳定套路。

### 何时自动新增或更新 `lesson`

满足任一条件即可：

1. 发现新的失败模式。
2. 找到明确根因。
3. 形成明确避免方式或调试规则。

### 何时自动新增或更新 `capability`

满足任一条件即可：

1. 某个能力在真实任务中被再次验证。
2. 某个能力边界被修正。
3. 某个任务从“探索”提升到“较可复用”。

### 何时自动生成 `proposal`

满足以下条件时生成候选，而不是直接硬落地：

1. 经验已多次出现。
2. 证据充分。
3. 复用价值高。
4. 仍需要用户决定是否升级。

## 推荐读取路径

AI 或人类默认按下面顺序读：

1. `knowledge/index/task_catalog.md`
2. `knowledge/index/pattern_index.md`
3. `knowledge/index/lesson_index.md`
4. `knowledge/index/capability_matrix.md`
5. 再按需打开对应正文文件

这样可以避免每次把整个知识库载入上下文。

## 文件命名规则

统一使用短横线或下划线的稳定 slug，不要把时间戳写进正文文件名。

示例：

1. `knowledge/tasks/desktop/minesweeper_solver_exploration.md`
2. `knowledge/patterns/emerging/desktop/post_click_state_resync.md`
3. `knowledge/lessons/desktop/repeated_click_on_open_cell.md`
4. `knowledge/capabilities/observed/desktop/visual_desktop_solver_scope.md`

## 建议的未来平台模块

当用户明确批准把自动沉淀机制正式落进平台基础设施时，推荐代码位置如下：

```text
platform/src/omniauto/knowledge/
├─ models.py
├─ task_run.py
├─ collector.py
├─ synthesizer.py
├─ updater.py
├─ registry.py
├─ templates.py
└─ hooks.py
```

对应测试建议放在：

```text
platform/tests/unit/test_knowledge_*.py
platform/tests/integration/test_knowledge_closeout.py
```

## 实施阶段

### Stage 1: 结构准备

1. 补齐 `knowledge/` 的分领域子目录
2. 增加缺失的索引文件
3. 补齐模板

### Stage 2: 手动半自动化

1. 先由 AI 在任务结束后按规则自动生成候选内容
2. 通过静态校验确保链接和索引一致
3. 暂不挂入平台自动钩子

### Stage 3: 受控自动化

1. 引入 `TaskRun`
2. 自动汇总证据
3. 自动更新 `knowledge/`
4. 自动刷新索引

### Stage 4: 稳定化

1. 为自动沉淀机制补单元测试和集成测试
2. 加入幂等与去重校验
3. 为高频任务验证知识写回质量

## 成功标准

满足以下条件时，说明机制达到目标：

1. 新任务结束后，不需要用户提醒也会自动更新 `knowledge/`
2. 知识不会堆到单一大文件里
3. AI 只需先读摘要文件，就能定位具体知识正文
4. `skills/` 和 `platform/` 仍保持人工审批边界
5. 同一条经验不会被重复、冲突地写进多个地方

## 当前结论

推荐采用这套设计。

它同时满足：

1. 自动吸收长期知识
2. 多文件、多文件夹分类存放
3. 摘要导航，按需加载正文
4. 低 token 成本
5. `knowledge` 自动成长，而 `skills/platform` 继续人工批准
