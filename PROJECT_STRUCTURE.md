# OmniAuto 项目结构说明

这个文件只解释目录怎么分，不涉及架构变化。

## 一眼看懂的主分区

- `src/omniauto/`
  - 核心 RPA 程序。
  - 包含状态机、浏览器引擎、视觉引擎、服务层、生成器、校验器等真正运行的代码。
- `workflows/`
  - 用户最常接触的任务脚本目录。
  - 只放任务工作流脚本，不放框架源码。
- `tests/`
  - 自动化代码测试目录。
  - 只放 `pytest` 这类单元测试、集成测试和 E2E 测试，不和用户任务脚本混放。
- `test_artifacts/`
  - 测试、验收、调试过程中产生的截图、临时文档和历史测试残留。
  - 只放测试产物，不放核心源码和正式工作流。
- `skills/`
  - 面向用户的 AI Skill 导航目录。
  - 这里放可读说明，方便快速定位。
- `.agents/skills/`
  - 运行时真正生效的 Skill 资产目录。
  - 这是为了兼容 Codex、Kimi、Claude 一类工具的约定，保留不动。

## workflows 目录约定

- `workflows/examples/`
  - 参考示例。
  - 用来展示这套系统可以怎么写、怎么跑。
  - 当前按 `browser/`、`desktop/`、`scenarios/` 分组。
- `workflows/verification/`
  - 手动验收脚本。
  - 用来做真实场景测试、边界验证和功能验收。
  - 当前按 `browser/`、`marketplaces/` 分组。
- `workflows/generated/`
  - AI 或模板自动生成的任务脚本。
  - 用户下达任务后，默认产物应该落到这里。
  - 当前再按 `browser/`、`desktop/`、`marketplaces/` 分组。
- `workflows/archive/`
  - 历史脚本归档。

## 这次整理后的区分原则

- 核心程序看 `src/omniauto/`
- 自动化代码测试看 `tests/`
- 测试运行产物看 `test_artifacts/`
- 用户任务脚本看 `workflows/`
- AI Skill 说明看 `skills/`
- AI Skill 运行时资产看 `.agents/skills/`

## 为什么保留 `.agents/skills/`

因为这是 AI 工具链识别 Skill 的实际运行目录。为了保证功能不变，这次只新增了用户可读的 `skills/` 导航层，不改运行时位置。
