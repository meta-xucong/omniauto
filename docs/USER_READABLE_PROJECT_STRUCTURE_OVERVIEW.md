# 项目文件结构说明

本文面向使用者和后续开发者，用描述性语言说明当前 OmniAuto 项目的主要目录、微信 AI 客服应用的位置，以及其他已有任务的独立程度和健康状态。

## 1. 总体结构

可以把当前项目理解成五层：

```text
platform/                         OmniAuto 通用底座
apps/wechat_ai_customer_service/   微信 AI 客服专用应用
knowledge/                         给开发者和系统使用的知识索引
runtime/                           运行状态、日志、测试产物
docs/                              人能直接阅读的说明文档
```

核心原则：

- `platform/` 只放通用能力，不放具体业务。
- `apps/` 放已经整理成独立应用的复杂任务。
- `knowledge/` 放开发知识、任务索引和可复用经验。
- `runtime/` 放运行过程中产生的状态、日志、报告和测试产物。
- `docs/` 放用户和开发者阅读的方案、说明、验收记录。

## 2. OmniAuto 通用底座

目录：

```text
platform/src/omniauto/
```

这里是 OmniAuto 的基础能力层。适合放：

- Windows 桌面自动化基础能力。
- 浏览器自动化基础能力。
- 任务调度、校验、恢复、审计。
- 通用知识沉淀和 closeout 机制。
- 可被多个任务复用的工具和接口。

不应该放：

- 微信客服话术。
- 商品资料。
- 具体客户数据。
- 某个任务专用的业务流程。

## 3. 微信 AI 客服应用

目录：

```text
apps/wechat_ai_customer_service/
```

这是当前已经正式整理出来的微信 AI 客服专用应用包。后续凡是和微信客服强相关的代码、配置、知识、测试，优先放在这里。

### 3.1 配置

```text
apps/wechat_ai_customer_service/configs/
```

用途：

- 保存运行配置。
- 控制测试联系人、回复前缀、限流策略、日志路径、是否启用 DeepSeek。

重要文件：

- `default.example.json`
- `test_contact.example.json`
- `customer_service_rules.example.json`

### 3.2 适配器

```text
apps/wechat_ai_customer_service/adapters/
```

用途：

- 连接微信。
- 连接 wxauto4 sidecar。
- 按需加载知识。

重要文件：

- `wechat_connector.py`：主程序调用微信 sidecar 的稳定边界。
- `wxauto4_sidecar.py`：真正和 Windows 微信交互。
- `wechat_sidecar_runner.py`：手动调试 sidecar 的命令入口。
- `knowledge_loader.py`：根据用户消息生成本轮 evidence pack。

### 3.3 工作流

```text
apps/wechat_ai_customer_service/workflows/
```

用途：

- 放可以直接运行的业务流程。

重要文件：

- `listen_and_reply.py`：微信客服监听和回复主流程。
- `preflight.py`：运行前检查。
- `approved_outbound_send.py`：白名单外发和未来定时触达基础。
- `build_evidence_pack.py`：查看某句话会加载哪些知识。
- `generate_review_candidates.py`：从原始资料生成待审核候选知识。
- `customer_intent_assist.py`：DeepSeek / LLM advisory 逻辑。
- `product_knowledge.py`：当前确定性商品和 FAQ 判断逻辑。
- `customer_data_capture.py`：客户资料抽取和 Excel 写入。

### 3.4 正式业务知识

```text
apps/wechat_ai_customer_service/data/structured/
```

用途：

- 放已经审核过、允许客服流程使用的业务资料。

重要文件：

- `manifest.json`：业务知识索引，控制按需加载。
- `product_knowledge.example.json`：商品、公司、开票、物流、售后、FAQ 测试数据。
- `style_examples.json`：客服话术风格样例。

运行时 DeepSeek 不直接读取全局知识文件，而是通过 `manifest.json` 选择和本轮问题相关的资料，组成 evidence pack。

### 3.5 原始资料入口

```text
apps/wechat_ai_customer_service/data/raw_inbox/
```

用途：

- 放未整理的原始聊天记录。
- 放原始产品资料。
- 放政策文档。
- 放 ERP 导出数据。

这些资料不会直接变成正式知识。它们需要先经过整理，生成候选。

### 3.6 待审核候选知识

```text
apps/wechat_ai_customer_service/data/review_candidates/
```

用途：

- 保存 AI 或程序根据原始资料整理出来的候选知识。
- 人工审核后才能进入正式业务知识。

子目录：

- `pending/`：待审核。
- `approved/`：已认可。
- `rejected/`：不采用。

### 3.7 Prompt 与客服行为约束

```text
apps/wechat_ai_customer_service/prompts/
```

用途：

- 定义客服人设。
- 定义回复边界。
- 定义转人工策略。
- 定义 evidence pack 模板。

这些文件帮助 DeepSeek 保持“只基于证据回答，不瞎承诺”的行为。

### 3.8 离线测试

```text
apps/wechat_ai_customer_service/tests/
```

用途：

- 不连接微信，也不调用 LLM，直接测试客服核心逻辑。

重要文件：

- `run_offline_regression.py`
- `scenarios/offline_regression.json`

当前离线回归覆盖：

- 商品列表。
- 商品报价。
- 低于公开阶梯价的议价转人工。
- 开票政策。
- 公司信息。
- 上下文物流。
- 客户资料采集。
- 合同、月结、账期转人工。

## 4. 微信客服任务知识索引

目录：

```text
knowledge/tasks/desktop/wechat_ai_customer_service/
```

用途：

- 给 Codex 和开发者阅读。
- 记录微信客服任务的架构导引、经验、调试说明。

注意：

- 这里不是 DeepSeek 运行时的业务知识库。
- DeepSeek 运行时应读取 app 内的 `data/structured/manifest.json`，再按需获得 evidence pack。

## 5. 微信客服运行产物

目录：

```text
runtime/apps/wechat_ai_customer_service/
```

用途：

- 放运行状态。
- 放审计日志。
- 放测试产物。

子目录：

- `state/`：已处理消息、会话上下文、运行状态。
- `logs/`：审计日志、操作记录、人工接管记录。
- `test_artifacts/`：测试生成的文件。

这些文件是运行痕迹，不是正式业务知识。

## 6. 方案和说明文档

目录：

```text
docs/
```

微信客服相关主要文档：

- `WECHAT_AI_CUSTOMER_SERVICE_OPTIMIZATION_GUIDE.md`
- `WECHAT_AI_CUSTOMER_SERVICE_IMPLEMENTATION_GUIDE.md`
- `WECHAT_CUSTOMER_SERVICE_DEBUG_LESSONS_AND_ROADMAP.md`
- `WECHAT_CUSTOMER_SERVICE_ENVIRONMENT_REQUIREMENTS.md`
- `WECHAT_CUSTOMER_SERVICE_FINAL_BASELINE.md`
- `WECHAT_CUSTOMER_SERVICE_RPA_SPEC.md`

其中：

- `WECHAT_AI_CUSTOMER_SERVICE_OPTIMIZATION_GUIDE.md` 解释为什么这样改。
- `WECHAT_AI_CUSTOMER_SERVICE_IMPLEMENTATION_GUIDE.md` 解释每个章节怎么实现和验收。
- 本文档解释当前文件结构给使用者看。

## 7. 其他任务的独立程度和健康状态

下面是本次检查后的结论。

### 7.1 微信 AI 客服

独立程度：高。

当前状态：

- 已经有正式应用包：`apps/wechat_ai_customer_service/`。
- 配置、业务知识、prompt、候选知识、测试场景、运行产物都已分开。
- 旧临时入口保留兼容转发。
- 全量静态检查、JSON 校验、离线回归、preflight、微信 dry-run 已通过。

结论：

```text
微信 AI 客服已经进入正式独立应用结构。
```

### 7.2 1688 关键词调研 / 爬数据任务

独立程度：高。

当前相关位置：

```text
apps/marketplace_1688_research/
.agents/skills/1688-marketplace-research/
skills/task_skills/marketplace_1688_research/
workflows/generated/marketplaces/
runtime/apps/marketplace_1688_research/
```

说明：

- 1688 已经晋升为独立应用包：`apps/marketplace_1688_research/`。
- 1688 仍保留专门 skill：`.agents/skills/1688-marketplace-research/`。
- 也有用户可读的 task skill 入口：`skills/task_skills/marketplace_1688_research/README.md`。
- 旧生成型 workflow 仍保留在 `workflows/generated/marketplaces/` 作为历史兼容。
- 新生成型 workflow 进入 `runtime/apps/marketplace_1688_research/generated_workflows/`。
- 正常运行推荐通过 `apps/marketplace_1688_research/scripts/run-report.ps1`。

本次检查：

- 1688 app 的核心脚本存在。
- 1688 task skill README 存在。
- app-local base workflow、builder、closeout helper 和离线检查脚本静态编译通过。
- app-local runner preview 通过，未启动浏览器。
- app-local builder 能生成 workflow 到 `runtime/apps/marketplace_1688_research/`。

未做的检查：

- 本次没有实际启动浏览器抓取 1688。
- 因为实跑会访问外部网站，可能触发登录、验证码、人工接管和较长运行。

结论：

```text
1688 任务已经晋升为 apps 下的正式独立应用包。
旧 task skill 和 generated workflows 仍保留，但新的正式开发和运行入口是 apps/marketplace_1688_research/。
```

### 7.3 Windows 扫雷自动游玩任务

独立程度：高。

当前相关位置：

```text
apps/minesweeper_autoplay/
workflows/temporary/desktop/minesweeper_solver.py
.agents/skills/minesweeper-autoplay/
skills/task_skills/minesweeper_autoplay/README.md
runtime/apps/minesweeper_autoplay/
```

说明：

- 扫雷已经晋升为独立应用包：`apps/minesweeper_autoplay/`。
- 扫雷仍保留专门 skill：`.agents/skills/minesweeper-autoplay/`。
- 也有用户可读的 task skill 入口：`skills/task_skills/minesweeper_autoplay/README.md`。
- 新运行产物集中在 `runtime/apps/minesweeper_autoplay/test_artifacts/`。
- 旧主程序仍在 `workflows/temporary/desktop/minesweeper_solver.py` 作为历史兼容。
- 新正式 solver 位于 `apps/minesweeper_autoplay/workflows/minesweeper_solver.py`。

本次检查：

- app-local `minesweeper_solver.py` 静态编译通过。
- skill 的 `closeout_solver_run.py` 静态编译通过。
- app-local `run-solver.ps1` 存在并通过 preview。
- app-local solver `--help` 通过，未启动扫雷。
- task skill README 存在。
- 发现旧的 `active_longtest_pid.txt`，但对应 PID 当前没有运行进程，判断为历史运行痕迹。

未做的检查：

- 本次没有实际打开 Windows 扫雷跑一局。
- 因为实跑会操作桌面 UI，不适合在结构检查阶段自动启动。

结论：

```text
扫雷任务已经晋升为 apps 下的正式独立应用包。
旧 temporary workflow 仍保留，但新的正式开发和运行入口是 apps/minesweeper_autoplay/。
```

## 8. 总体判断

当前微信客服、1688 调研和扫雷自动游玩都已经具备独立 app 应用包。旧 skill、generated workflow、temporary workflow 入口保留用于兼容和历史追溯。

当前独立程度排序：

```text
微信 AI 客服：最高，已经是 apps 独立应用包
1688 调研：最高，已经是 apps 独立应用包
扫雷自动游玩：最高，已经是 apps 独立应用包
```

建议后续逐步统一结构：

```text
apps/wechat_ai_customer_service/
apps/marketplace_1688_research/
apps/minesweeper_autoplay/
```

目前这三个长期维护任务已经完成第一轮 apps 应用化。后续新复杂任务也建议先进入独立 `apps/<task_name>/`，再决定是否把通用能力沉淀到 `platform/`。

## 9. 后续复杂任务结构规范

以后新增类似微信 AI 客服、1688 调研、扫雷自动游玩这种复杂任务时，默认遵循独立 app 结构：

```text
apps/<task_name>/
runtime/apps/<task_name>/
.agents/skills/<skill_name>/
skills/task_skills/<task_name>/
```

详细规范见：

```text
docs/COMPLEX_TASK_APP_STRUCTURE_STANDARD.md
```
