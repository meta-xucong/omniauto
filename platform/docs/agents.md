# OmniAuto AI 协作约束

这份文档给接手本仓库的 AI 助手一个最小、明确的工作边界。

## 核心原则

1. 运行时保持确定性 workflow，不在执行中让 AI 自由接管 UI。
2. 任务完成后允许自动更新 `knowledge/`，但不自动升级成 `skills/`。
3. 只有用户明确要求时，才把内容正式吸收进 `platform/`。

## 默认落点

- 临时或探索性任务：
  - `workflows/temporary/`
- 自动生成的任务脚本：
  - `workflows/generated/`
- 真实环境验收：
  - `workflows/verification/`
- 任务记忆、经验、模式、能力说明：
  - `knowledge/`
- 平台代码与测试：
  - `platform/src/`
  - `platform/tests/`

## 软升级与硬落地

- 软升级：
  - 任务记录
  - 模式提炼
  - 长期经验
  - 观察到的能力
  - 候选升级提案
- 硬落地：
  - 进入 `skills/`
  - 进入 `platform/src/`
  - 进入 `platform/tests/` 作为正式保障

硬落地必须由用户明确批准。

## 处理任务时的默认顺序

1. 先确认是否已有平台能力可直接复用
2. 没有的话，优先生成或编写 workflow
3. 执行和验证任务
4. 把结论沉淀到 `knowledge/`
5. 如果发现稳定模式，只生成候选提案，不自行升级到 `skills/` 或 `platform/`
