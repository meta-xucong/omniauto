# skills 目录说明

这个目录现在承担两层职责：

1. 用户可读的 skill 导航层
2. 项目本地正式 skill 的保留区

真正给 AI 工具运行时直接使用的现有 Skill 资产仍然放在：

- `.agents/skills/`

## 当前状态

当前仓库还没有新增任何“项目本地正式 skill”。

也就是说：

1. 之前做过的 1688、WPS、扫雷等任务不会在这次重构中自动升级成 skill
2. 只有用户明确要求时，才会从 `knowledge/` 正式提升到 `skills/`

## 目录分层

- `task_skills/`
  - 用户明确批准的任务族 skill

- `capability_skills/`
  - 用户明确批准的通用能力 skill

- `SKILL_CATALOG.md`
  - 当前正式 skill 清单

- `UPGRADE_POLICY.md`
  - 从知识层升级到正式 skill 的规则

## skills 和 knowledge 的关系

- `knowledge/`
  - 先保存任务记录、通用模式、长期经验、候选项

- `skills/`
  - 再保存用户明确批准的正式复用能力包

简单理解：

1. `knowledge/` 自动成长
2. `skills/` 人工批准后正式落地
