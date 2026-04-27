# Complex Task App Structure Standard

本文记录 OmniAuto 中复杂任务的标准落地方式。以后凡是类似微信 AI 客服、1688 调研、扫雷自动游玩这类“长期维护、运行产物多、需要独立测试和复盘”的任务，默认都按本文结构创建。

## 1. 适用范围

应当使用独立 app 结构的任务通常具备以下特征：

- 有自己的业务流程，不只是一个很小的工具函数。
- 会产生运行状态、日志、截图、报告、缓存、浏览器 profile 或测试产物。
- 需要长期迭代、复盘、修复问题。
- 需要专门的配置、runner、测试、技能说明或用户文档。
- 不适合直接混入 `platform/src/omniauto/` 的通用底层。

典型例子：

```text
apps/wechat_ai_customer_service/
apps/marketplace_1688_research/
apps/minesweeper_autoplay/
```

## 2. 总体原则

复杂任务按三层分离：

```text
platform/src/omniauto/        通用底层能力
apps/<task_name>/             任务专用应用包
runtime/apps/<task_name>/     任务运行产物
```

核心原则：

- `platform/` 只沉淀通用能力，例如浏览器控制、桌面控制、恢复机制、知识 closeout、模板渲染等。
- `apps/<task_name>/` 放具体任务的业务代码、配置、runner、测试和任务内文档。
- `runtime/apps/<task_name>/` 放运行时产生的文件，不放正式业务源代码。
- `.agents/skills/<skill_name>/` 是 AI 操作入口说明，不是主代码目录。
- `skills/task_skills/<task_name>/` 是用户批准过的任务族说明，不是运行产物目录。
- 旧入口可以保留兼容，但新开发、新测试、新运行默认走 `apps/<task_name>/`。

## 3. 标准目录模板

每个复杂任务默认按下面结构创建：

```text
apps/<task_name>/
  README.md
  configs/
    default.example.json
  workflows/
    <main_workflow_or_solver>.py
  scripts/
    run-<task>.ps1
    closeout_<task>_run.py
  tests/
    run_offline_checks.py
  docs/
```

根据任务需要，可以增加：

```text
apps/<task_name>/
  adapters/       外部软件、网站、sidecar、API 的适配层
  data/           任务专用正式数据、原始资料、候选知识
  prompts/        LLM prompt、人设、回复边界、evidence pack 模板
  templates/      任务专用报告或输出模板
```

## 4. Runtime 目录模板

每个复杂任务必须有自己的运行产物目录：

```text
runtime/apps/<task_name>/
  logs/
  test_artifacts/
```

按任务类型扩展：

```text
runtime/apps/marketplace_1688_research/
  chrome_profile_1688_safe/
  generated_workflows/
  reports/
  logs/

runtime/apps/minesweeper_autoplay/
  test_artifacts/
  logs/

runtime/apps/wechat_ai_customer_service/
  state/
  logs/
  test_artifacts/
```

运行产物目录可以保存：

- 截图、视频、诊断图。
- `run_status.json`、停止摘要、审计日志。
- 报告、导出的 JSON、HTML。
- 浏览器 profile、缓存、临时生成 workflow。

运行产物目录不应保存：

- 主业务源码。
- 正式配置模板。
- 需要长期维护的 prompt 或结构化知识。

## 5. README 要求

每个 `apps/<task_name>/README.md` 至少说明：

- 这个 app 负责什么。
- 主入口 runner 是哪个。
- 主 workflow / solver 是哪个。
- 配置文件在哪。
- 运行产物输出到哪里。
- 如何运行离线检查。
- 哪些旧路径只是兼容入口。

推荐格式：

```text
# <task_name>

Purpose:
- ...

Primary entry:
- apps/<task_name>/scripts/run-<task>.ps1

Runtime:
- runtime/apps/<task_name>/

Checks:
- uv run python apps/<task_name>/tests/run_offline_checks.py
```

## 6. Runner 要求

每个复杂任务应有一个稳定 runner：

```text
apps/<task_name>/scripts/run-<task>.ps1
```

runner 应做到：

- 从仓库根目录解析路径，避免依赖当前 shell 所在目录。
- 设置任务需要的环境变量。
- 把运行产物指向 `runtime/apps/<task_name>/`。
- 支持 `-Preview` 或等价模式，用于不启动外部 UI 的安全检查。
- 正常运行后执行 meaningful-only closeout，除非用户明确跳过。

## 7. 测试要求

每个复杂任务至少要有离线检查：

```text
apps/<task_name>/tests/run_offline_checks.py
```

离线检查应覆盖：

- 必要文件是否存在。
- 配置 JSON 是否能解析。
- runner preview 是否能生成正确命令或产物路径。
- 生成文件是否落在 `runtime/apps/<task_name>/` 下。
- 关键安全边界是否未被破坏。

对需要外部网站或桌面 UI 的任务，离线检查不强制实跑外部服务。实跑测试应单独执行，并记录结果。

## 8. Skill 和文档入口

AI-facing skill 入口放在：

```text
.agents/skills/<skill_name>/SKILL.md
```

用户批准过的任务族说明放在：

```text
skills/task_skills/<task_name>/README.md
```

这两类文件应该指向 app 主入口，例如：

```text
App package: apps/<task_name>/
Runner: apps/<task_name>/scripts/run-<task>.ps1
Runtime artifacts: runtime/apps/<task_name>/
```

不要把核心业务逻辑写进 skill 文档里。skill 文档只负责告诉 AI 如何安全地运行、诊断和修改 app。

## 9. 知识和数据分层

复杂任务的数据应分清来源和用途：

```text
apps/<task_name>/data/raw_inbox/          原始资料入口
apps/<task_name>/data/review_candidates/  待审核候选知识
apps/<task_name>/data/structured/         已审核正式业务知识
knowledge/tasks/<domain>/<task_name>/     给开发者和 Codex 阅读的任务索引、经验和复盘
```

原则：

- 运行时模型不要无脑读取全部知识文件。
- 需要按 manifest、索引或检索结果选择相关知识。
- 原始资料不能直接变成正式知识，应先生成候选，再人工或规则审核。
- 任务专用知识留在任务 app 内，通用经验再沉淀到 `knowledge/` 或 `platform/`。

## 10. Platform 沉淀规则

只有满足以下条件的能力，才建议从 app 抽到 `platform/src/omniauto/`：

- 被两个以上任务复用。
- 与具体业务无关。
- 有稳定接口和测试。
- 抽出后不会让任务边界变模糊。

适合沉淀到底层的例子：

- 浏览器 CDP 连接。
- Windows 窗口置顶、截图、鼠标键盘控制。
- 人工接管提示。
- closeout 和知识候选生成。
- 通用报告模板渲染。

不适合沉淀到底层的例子：

- 微信客服话术。
- 1688 专用搜索策略。
- 扫雷求解策略。
- 某个客户、商品、ERP 字段的业务逻辑。

## 11. 新复杂任务创建流程

以后开启新复杂任务时，按这个顺序做：

1. 先判断是否属于复杂任务。
2. 创建 `apps/<task_name>/` 骨架。
3. 创建 `runtime/apps/<task_name>/` 骨架。
4. 写 `README.md`、`configs/default.example.json`。
5. 放入主 workflow / solver。
6. 写 runner，并确保产物进入 app runtime。
7. 写离线检查。
8. 如用户批准，创建 `.agents/skills/<skill_name>/` 和 `skills/task_skills/<task_name>/`。
9. 跑离线检查。
10. 再跑最小实盘 smoke。
11. 通过后，更新项目结构说明文档。

## 12. 验收清单

一个复杂任务算完成第一轮应用化，至少满足：

- `apps/<task_name>/README.md` 存在。
- `apps/<task_name>/configs/default.example.json` 存在且 JSON 合法。
- `apps/<task_name>/scripts/run-*.ps1` 存在。
- `apps/<task_name>/tests/run_offline_checks.py` 存在并通过。
- 运行产物进入 `runtime/apps/<task_name>/`。
- skill 文档指向 app 主入口。
- 旧入口若保留，需要明确是兼容入口。
- 实盘 smoke 的结果已记录，或者明确说明为什么没有实跑。

## 13. 当前参考实现

当前可作为样板的任务：

```text
apps/wechat_ai_customer_service/
apps/marketplace_1688_research/
apps/minesweeper_autoplay/
```

其中：

- 微信 AI 客服是数据、prompt、adapter 都较完整的复杂业务 app。
- 1688 调研是浏览器自动化、人工验证接管、报告产物型 app。
- 扫雷自动游玩是桌面 UI 自动化、识图诊断、策略迭代型 app。

后续新复杂任务默认以这三者为参考，不再把任务实现散落到 `workflows/generated/`、`workflows/temporary/` 或 `platform/` 里。
