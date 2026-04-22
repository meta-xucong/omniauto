# OmniAuto Skill Upgrade Guide

这份文档定义了把“已经成熟的任务知识”升级为 OmniAuto 正式 skill 的标准流程。

从现在开始，除非用户明确要求例外，仓库内所有新的正式 skill 升级都应遵循本文件，而不是按临时习惯自由落地。

本文件是对以下治理文件的操作化补充：

- [skills/UPGRADE_POLICY.md](UPGRADE_POLICY.md)
- [skills/README.md](README.md)
- [docs/KNOWLEDGE_WORKFLOW.md](../docs/KNOWLEDGE_WORKFLOW.md)

## 1. 核心原则

1. `knowledge/` 是软升级层，允许自动沉淀。
2. `skills/` 是硬落地区，只有用户明确批准后才能进入。
3. OmniAuto 正式 skill 采用“双落点”结构：
   - 运行时 bundle 放在 `.agents/skills/`
   - 人类可读、项目正式批准入口放在 `skills/`
4. 默认优先复用现有稳定资产，不强行把成熟 workflow 或 solver 从原路径搬走。
5. skill 升级不等于 platform 升级。只有当能力已经稳定到值得成为程序级 API 时，才进入 `platform/`。
6. 每一个正式 skill 默认都要附带一份 `usage` 文档，用来说明标准调用方式、常见运行命令和典型任务请求。

## 2. 什么时候允许升级成正式 skill

只有同时满足以下条件，才应进入正式升级流程：

1. 用户已经明确要求“升级成 skill”。
2. 该任务族有重复复用价值，而不是一次性脚本。
3. 执行路径已经足够稳定，能清楚写出触发条件、标准步骤和失败分流。
4. 关键资产已经存在且稳定，例如：
   - 主要 workflow / solver 路径
   - 运行命令
   - 产物目录
   - 诊断入口
5. 已经沉淀出可复用的经验边界，而不只是零散观察。
6. 可以清楚区分：
   - 这是 `task_skill`
   - 还是 `capability_skill`
   - 还是应该继续上升为 `platform` 能力

如果这些条件没有同时满足，优先继续沉淀到：

- `knowledge/tasks/`
- `knowledge/patterns/`
- `knowledge/lessons/`
- `knowledge/capabilities/`
- `knowledge/proposals/skill_candidates/`

## 3. 分类规则

### 3.1 `task_skill`

适用于“某一类任务已经成熟，可按固定套路反复执行”。

典型特征：

- 绑定具体任务族或具体应用场景
- 有清晰输入、执行、诊断、验收路径
- 仍然主要复用现有 workflow / solver / artifacts

示例方向：

- 扫雷自动游玩
- 某类网站的固定调研任务
- 某个桌面应用的专项自动化任务

### 3.2 `capability_skill`

适用于“跨任务、跨场景都能复用的能力或治理规则”。

典型特征：

- 不绑定单一任务族
- 更像能力包、原则包、治理包
- 常用于方法论、边界规则、稳定工作模式

示例：

- `guarded_knowledge_closeout`

### 3.3 `platform` 升级

只有在下列条件成立时才考虑进入 `platform/src/omniauto/skills/`：

1. 能力已经不只是“给 AI 用的 skill 说明”，而是需要程序级调用
2. 需要稳定 Python API / service 接口
3. 多个 workflow 会复用同一套代码封装
4. 用户明确批准进入平台层

默认规则：

- 先 skill
- 后 platform

不要反过来。

## 4. 正式 skill 的标准落点

每一个新批准的 OmniAuto 正式 skill，至少应落到下面 3 个位置。

### 4.1 运行时 bundle

路径：

- `.agents/skills/<bundle-id>/`

要求：

- 必须包含 `SKILL.md`
- 可按需包含 `scripts/`、`references/`、`assets/`

命名规则：

- `bundle-id` 使用 `hyphen-case`
- 例：`minesweeper-autoplay`

### 4.2 正式项目入口

路径：

- `skills/task_skills/<entry_id>/README.md`
- 或 `skills/capability_skills/<entry_id>/README.md`

要求：

- 用于人类阅读和项目治理登记
- 必须说明：
  - skill 的正式名称
  - skill 类型
  - 运行时 bundle 路径
  - 适用范围
  - 与 `knowledge/` 和 `platform/` 的边界

命名规则：

- `entry_id` 使用 `snake_case`
- 例：`minesweeper_autoplay`

### 4.3 目录注册

必须更新：

- [skills/SKILL_CATALOG.md](SKILL_CATALOG.md)

要求：

- 把该 skill 登记到正确分组
- 写明运行时 bundle 路径
- 写明人类入口路径
- 写明 scope

## 5. 可选落点

### 5.1 候选升级记录

可选保留在：

- `knowledge/proposals/skill_candidates/<domain>/<entry_id>.md`

用途：

- 记录为什么它值得被 hard landing
- 保留从 knowledge 到 skill 的证据链

注意：

- 这不是正式 skill
- 它只是升级前或升级时的提案/归档材料

### 5.2 平台级代码封装

仅在需要程序级稳定接口时，才新增：

- `platform/src/omniauto/skills/<module_name>.py`

这一步不是正式 skill 升级的默认组成部分。

## 6. 标准升级流程

每次正式 skill 升级都按下面顺序进行。

### Step 1. 确认批准边界

明确用户已经批准“升级成正式 skill”，而不只是允许写入 `knowledge/`。

### Step 2. 冻结现有成熟资产

确认下列资产已经存在并可复用：

1. 主 workflow / solver 路径
2. 运行命令
3. 产物目录
4. 常见失败模式
5. 验收方式

不要在这一步先重构代码位置。

### Step 3. 选择 skill 类型

只能三选一：

1. `task_skill`
2. `capability_skill`
3. `platform` 候选

如果分类不清楚，默认先按 `task_skill` 处理。

### Step 4. 确定双命名

为同一个 skill 同时确定两套名字：

1. 运行时 bundle 名：`hyphen-case`
2. 项目入口名：`snake_case`

推荐保持语义一致，例如：

- bundle: `minesweeper-autoplay`
- entry: `minesweeper_autoplay`

### Step 5. 创建运行时 bundle

在 `.agents/skills/<bundle-id>/` 创建：

- `SKILL.md`
- `references/` 按需
- `scripts/` 按需

`SKILL.md` 必须最少写清楚：

1. 触发条件
2. 主资产路径
3. 标准运行方式
4. 关键产物路径
5. 诊断顺序
6. 何时继续测试、何时停下分析

此外，运行时 bundle 默认必须提供：

- `references/usage.md`

如果该 skill 使用自定义 wrapper / runner，而且这条执行路径不会自然经过受控 closeout 入口，那么该 runner 默认还应补一层“meaningful-only”知识收口：
- 调用 `omni closeout`
- 或调用 `OmniAutoService.closeout_task(...)`

除非是在专门调试 wrapper 或参数解析，否则不要把 closeout 设为默认关闭；但默认也不应把每次低价值运行都写进 formal knowledge。

这份文档用于统一：

1. 面向 AI 的对话调用示例
2. 面向命令行/脚本的直接运行示例
3. 常见模式组合
4. 预览、诊断、长测、失败即停等标准调用写法

### Step 6. 创建正式项目入口

在 `skills/task_skills/<entry_id>/README.md` 或 `skills/capability_skills/<entry_id>/README.md` 创建正式入口。

这份 README 必须说明：

1. 这是用户批准的正式 OmniAuto skill
2. 运行时 bundle 在哪
3. 适用于什么任务
4. 不适用于什么任务
5. 为什么它属于当前分类

### Step 7. 更新技能目录

更新 `skills/SKILL_CATALOG.md`。

这一步不可省略。

没有目录登记的 skill，不算正式项目技能完成。

### Step 8. 可选补充提案档案

如果需要保留来源和升级依据，则补一份：

- `knowledge/proposals/skill_candidates/...`

### Step 9. 验证

至少做这几类验证：

1. 结构验证
   - 路径是否正确
   - `SKILL.md` 是否存在
   - 人类入口 README 是否存在
2. 触发验证
   - skill 描述是否能覆盖真实触发语句
3. 操作验证
   - skill 中引用的脚本/主资产路径是否真实存在
4. 治理验证
   - `skills/SKILL_CATALOG.md` 是否已登记
   - 没有错误写入 `platform/` 或其他不允许位置
5. 使用验证
   - `references/usage.md` 是否存在
   - `usage` 中的主命令和参数是否与当前 skill 的真实入口一致

如使用通用 skill 初始化工具，可以额外运行验证脚本；但 OmniAuto 正式 skill 的项目落点检查仍然必须人工确认。

## 7. 运行时 bundle 的推荐结构

对于大多数 OmniAuto 正式 skill，推荐如下：

```text
.agents/skills/<bundle-id>/
├─ SKILL.md
├─ references/
│  ├─ run-modes.md
│  ├─ usage.md
│  ├─ diagnostics.md
│  └─ artifacts.md
└─ scripts/
   ├─ run.ps1
   └─ closeout helper (optional but recommended when wrapper runs are ad hoc)
```

说明：

- `SKILL.md` 保持精简，只放触发与工作流
- `usage.md` 负责沉淀标准调用示例，避免以后每次重新发明调用方式
- 详细运行模式、故障分流、产物解释放入 `references/`
- 稳定且重复使用的命令放入 `scripts/`

## 8. 不要这样做

以下行为都视为不符合 OmniAuto 正式 skill 升级规则：

1. 只创建 `.agents/skills/...`，但不创建 `skills/...` 正式入口
2. 只创建 `skills/...` README，但没有运行时 bundle
3. 不更新 `skills/SKILL_CATALOG.md`
4. 未经用户批准，直接把成熟任务升为正式 skill
5. 把一次性 workflow 强行包装成正式 skill
6. 为了 skill 化，先把稳定 solver 或 workflow 路径大规模搬家
7. 把应该是 `task_skill` 的东西直接推进 `platform/`
8. 用 skill 替代 `knowledge/`，导致经验链断裂

## 9. 推荐模板

### 9.1 正式项目入口 README 最小模板

```md
# <entry_id>

这是一个用户批准的 OmniAuto 正式 <task/capability> skill。

- Runtime bundle: `.agents/skills/<bundle-id>/`
- Scope: <一句话说明>
- Primary assets: <主要 workflow / solver / references 路径>

## Boundaries

- This skill is for <适用范围>
- This skill is not the same as platform hard landing
- Formal platformization requires separate approval
```

### 9.2 运行时 SKILL.md 最小模板

```md
---
name: <bundle-id>
description: <说明它做什么，以及在什么用户请求下触发>
---

# <Skill Name>

## Core Assets

- Main workflow / solver: <path>
- Artifacts: <path>

## Standard Workflow

1. 启动
2. 运行
3. 监控
4. 诊断
5. 回归

## References

- `references/run-modes.md`
- `references/usage.md`
- `references/diagnostics.md`
- `references/artifacts.md`
```

## 10. 扫雷这类任务的推荐落法

以扫雷为例，正式升级后应优先采用：

1. 运行时 bundle
   - `.agents/skills/minesweeper-autoplay/`
2. 正式项目入口
   - `skills/task_skills/minesweeper_autoplay/README.md`
3. 目录登记
   - `skills/SKILL_CATALOG.md`
4. 可选提案档案
   - `knowledge/proposals/skill_candidates/desktop/minesweeper_autoplay.md`

而不是：

1. 直接只写到 `knowledge/`
2. 直接只做普通本地 skill
3. 直接进入 `platform/src/omniauto/skills/`

## 11. 执行规则

以后只要出现“把成熟任务/成熟经验升级成 OmniAuto 正式 skill”的要求，默认按本文件执行。

如果某次任务要偏离本规则，必须在任务里明确记录偏离原因。
