# OmniAuto — AI 开发助手行为规范

> **适用对象**: Kimi Code / Codex / Claude Code 等 AI 编程助手  
> **生效范围**: `D:\AI\AI_RPA` 及其所有子目录

---

## 0. 根本目的（不可偏离）

在参与 OmniAuto 项目开发时，你必须始终牢记以下两条根本原则：

1. **影刀 RPA 开源替代定位**：OmniAuto 的目标是做出**类似「影刀 RPA」的自动操作功能**，自己从头编写。扩展性和与 **Python、AI 结合的相性** 是最高优先级，所有技术决策必须围绕这一点展开。
2. **开源工具优先原则**：开发过程中必须**持续调研并优先复用**适合该目标的高质量开源软件与 Skill（如 browser-use、Stagehand、pyauto-desktop、OmniParser、Smolagents 等），**避免重复造轮子**，最大限度节省开发时间成本。若存在成熟开源方案，应先集成再考虑自研。

---

## 1. 项目核心哲学

1. **人类描述意图**: 用户用自然语言描述自动化任务。
2. **AI 生成脚本**: AI 生成符合规范的原子化 Python 脚本。
3. **状态机执行**: 所有 UI 操作必须由 `StateMachine` 调用 `AtomicStep` 执行，禁止 AI 在运行时直接操作浏览器或桌面 UI。
4. **异常兜底**: 步骤失败时上报给 AI 决策器或人工审核节点（Guardian），禁止静默忽略错误。

---

## 2. 代码风格与规范

### 2.1 语言与版本
- **主语言**: Python 3.11+
- **强制使用类型注解**: 所有公共函数、类方法必须标注参数类型与返回值类型
- **异步优先**: UI 操作类函数必须声明为 `async def`，使用 `async/await` 模式

### 2.2 Docstring 规范
- 所有公共模块、类、函数必须包含 Google Style Docstring
- 示例：
  ```python
  async def human_like_move(x: int, y: int, duration: float = 0.5) -> None:
      """使用贝塞尔曲线将鼠标移动到目标坐标。

      Args:
          x: 目标屏幕 X 坐标。
          y: 目标屏幕 Y 坐标。
          duration: 移动耗时（秒），默认 0.5。
      """
  ```

### 2.3 命名规范
- **类名**: `PascalCase`（如 `StealthBrowser`, `AtomicStep`）
- **函数/变量**: `snake_case`（如 `random_delay`, `task_context`）
- **常量**: `UPPER_SNAKE_CASE`（如 `STEALTH_CONFIG`, `MAX_RETRY`）
- **私有成员**: 以下划线开头（如 `_persist_state`）

---

## 3. 强制约束（红线条款）

以下规则在任何情况下**不得违反**，违者必须重构：

### 3.1 浏览器操作约束
- **禁止**直接使用原生 `selenium` / `webdriver` 操作浏览器。
- **禁止**在业务代码中直接实例化 `playwright.sync_api.Page` 并执行点击/输入。
- **必须**通过 `StealthBrowser` 或 `AtomicStep` 包装层调用浏览器 API。
- **优先**集成 `browser-use` / `Stagehand` / `agent-browser` 等成熟开源方案，而非从零封装 CDP。

### 3.2 桌面自动化约束
- **优先**使用 `pyauto-desktop`（跨分辨率、内置 Inspector、性能更优）而非裸 `pyautogui`。
- 所有 UI 交互（点击、输入、滚动、截图、提取）**必须**封装为 `AtomicStep` 的子类或实例。
- 每个 `AtomicStep` **必须**提供独立的 `validator` 函数，用于校验执行结果。

### 3.3 行为模拟约束
- 鼠标移动**必须**使用 `human_like_move()`（贝塞尔曲线），禁止调用瞬时移动 API（如 `pyautogui.moveTo(x, y)` 不加过渡）。
- 所有点击操作前**必须**调用 `random_delay(0.1, 0.5)`。
- 键盘输入**必须**设置 `interval` 参数，模拟人类打字节奏（建议 0.05 ~ 0.15 秒/字符）。

### 3.4 安全约束
- **禁止**在生成的代码中使用 `eval()`, `exec()`, `compile()`, `__import__()`, `subprocess`, `os.system` 等动态执行或系统调用。
- 凭证（密码、API Key、Cookie）**必须**存储在加密凭据管理器中，禁止硬编码在脚本内。
- 高危操作（转账、删除、发送消息、修改配置）**必须**在执行前添加 `Guardian` 人工确认节点。

### 3.5 错误处理约束
- 所有 `AtomicStep` 的异常**必须**被捕获并转换为 `TaskState.FAILED` 或 `TaskState.ESCALATED`，禁止吞掉异常。
- 异常信息**必须**通过结构化日志（JSON 格式）输出，包含 `task_id`, `step_id`, `error_type`, `message`, `screenshot_path`。

### 3.6 开源工具优先约束
- 在引入任何自研模块前，先搜索并评估是否有合适的开源库可用。
- 若选择自研，必须在代码注释或文档中说明**不采用某开源方案的具体理由**（如协议冲突、功能不匹配、性能不达标）。
- 积极关注并引用以下生态的最新进展：`browser-use`、`Stagehand`、`Skyvern`、`agent-browser`、`Lightpanda`、`pyauto-desktop`、`OmniParser`、`Smolagents`、`Robocorp`、`BotCity`。

---

## 4. 目录结构规范

建议的项目目录组织方式如下：

```
D:\AI\AI_RPA
├── README.md                 # 项目说明（面向人类贡献者）
├── pyproject.toml            # 项目配置与依赖
├── .gitignore
├── .agents/                  # Agent Skill 上下文与模板资源
│   └── skills/
│       └── deterministic-rpa-workflow/
│           ├── SKILL.md
│           ├── assets/
│           │   └── workflow-template.py.j2
│           └── references/
├── docs/                     # 项目文档
│   ├── agents.md             # 本文件（AI 开发助手行为规范）
│   ├── requirements.md       # 需求规格说明书
│   ├── development.md        # 开发架构与实施指南
│   ├── AI_AGENT_INTEGRATION.md
│   └── USER_GUIDE_AI_MODE.md
├── src/
│   └── omniauto/
│       ├── __init__.py
│       ├── cli.py            # CLI 入口
│       ├── api.py            # FastAPI REST API
│       ├── mcp_server.py     # MCP Server
│       ├── service.py        # 核心业务服务
│       ├── core/
│       │   ├── __init__.py
│       │   ├── state_machine.py   # 状态机核心
│       │   ├── context.py         # TaskContext 定义
│       │   └── exceptions.py      # 自定义异常
│       ├── engines/
│       │   ├── __init__.py
│       │   ├── browser.py         # Stealth Browser Engine
│       │   └── visual.py          # Visual Fallback Engine
│       ├── high_level/
│       │   ├── browser_agent.py
│       │   └── task_planner.py
│       ├── orchestration/
│       │   ├── __init__.py
│       │   ├── generator.py       # AI 脚本生成器
│       │   ├── validator.py       # 静态代码检查
│       │   └── guardian.py        # 人工审核节点
│       ├── steps/              # 原子步骤库
│       │   ├── __init__.py
│       │   ├── navigate.py
│       │   ├── click.py
│       │   ├── type.py
│       │   ├── extract.py
│       │   ├── screenshot.py
│       │   ├── scroll.py
│       │   ├── wait.py
│       │   ├── hotkey.py
│       │   └── visual_click.py
│       ├── templates/          # Jinja2 工作流模板
│       │   ├── workflows/
│       │   │   └── ecom_product_research.py.j2
│       │   └── reports/
│       │       └── ecom_report.html.j2
│       ├── templating/         # 模板渲染与注册
│       │   ├── __init__.py
│       │   ├── generator.py
│       │   └── registry.py
│       └── utils/
│           ├── __init__.py
│           ├── auth_manager.py  # 登录/验证码检测与人工介入
│           ├── fingerprint.py   # 浏览器指纹与 Profile 轮换
│           ├── stealth.py       # 反检测配置与脚本
│           ├── mouse.py         # 人类化鼠标移动
│           └── logger.py        # 结构化日志
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── scripts/                    # 脚本目录（已分类）
│   ├── examples/               # 演示与场景脚本
│   ├── tests/                  # 测试脚本
│   ├── generated/              # 由模板生成的工作流脚本
│   └── archive/                # 旧脚本归档
├── data/
│   ├── auth/                   # 认证凭据（如 taobao.com_auth.json）
│   ├── chrome_profile_1688/    # 已登录的 1688 Chrome Profile
│   ├── logs/                   # 运行日志
│   └── reports/                # 任务报告产出
├── outputs/                    # 运行时输出（Excel/Word/截图）
└── tools/                      # 维护与诊断工具
```

---

## 5. 错误处理与日志

### 5.1 日志格式
统一使用结构化 JSON 日志，便于后续接入日志分析系统：

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "step_completed",
    task_id=ctx.task_id,
    step_id=step.id,
    duration_ms=420,
    screenshot_path="/tmp/shot_001.png",
)
```

### 5.2 异常上报
当 `AtomicStep` 执行失败时，必须构造 `StepResult` 并上报状态机：

```python
except Exception as e:
    logger.error(
        "step_failed",
        task_id=context.task_id,
        step_id=self.id,
        error_type=type(e).__name__,
        message=str(e),
    )
    return TaskState.FAILED, StepResult(success=False, error=e)
```

---

## 6. 工作流规范

当用户要求你生成一个新的自动化任务时，请按以下流程执行：

1. **理解需求**: 仔细阅读用户的自然语言描述，识别关键动作和目标系统。
2. **调研开源方案**: 检查是否有现成的开源库或 Skill 可直接复用（如 browser-use 的 Agent、Stagehand 的 act/extract、pyauto-desktop 的 Inspector 生成代码）。
3. **设计原子步骤**: 将任务拆分为 `AtomicStep` 序列，标注需要的 `Guardian` 节点。
4. **生成代码**: 编写符合本规范的原子脚本，保存在 `scripts/` 目录下。
5. **静态自检**: 使用 AST 或正则扫描生成的代码，确认无安全违规项。
6. **注册工作流**: 提供将脚本注册到状态机的示例代码。
7. **编写测试**: 为关键步骤编写 pytest 单元测试。

### 示例：创建淘宝价格监控任务

```python
# scripts/taobao_monitor.py
from omniauto.core.context import TaskContext
from omniauto.core.state_machine import AtomicStep, StepResult, TaskState
from omniauto.engines.browser import StealthBrowser
from omniauto.utils.mouse import human_like_move
from omniauto.utils.stealth import random_delay

async def atomic_navigate_taobao(ctx: TaskContext) -> StepResult:
    """导航到淘宝首页。"""
    browser = ctx.browser_state["browser"]
    await browser.goto("https://taobao.com")
    return StepResult(success=True)

async def atomic_search_keyboard(ctx: TaskContext) -> StepResult:
    """搜索'机械键盘'。"""
    browser = ctx.browser_state["browser"]
    box = await browser.locator("#q").first
    await human_like_move(box.bounding_box().center)
    await random_delay(0.1, 0.3)
    await box.click()
    await box.type("机械键盘", interval=0.08)
    await random_delay(0.2, 0.5)
    await browser.locator(".btn-search").first.click()
    return StepResult(success=True)

# ... 更多步骤

# 注册到工作流
from omniauto.core.state_machine import Workflow

steps = [
    AtomicStep("navigate", atomic_navigate_taobao, lambda r: r.success),
    AtomicStep("search", atomic_search_keyboard, lambda r: r.success),
    # ...
]
workflow = Workflow(steps, guardian_points=[4])  # 第4步前人工确认
```

### 6.1 复杂任务执行策略（Deterministic RPA）

对于需要浏览器操作的多步骤复杂任务（如"抓取某电商前 N 页并生成报告"），**禁止**在运行时让 AI 做视觉决策或实时思考。必须遵循以下固定模式：

1. **URL 优先**：分析目标网站是否支持通过 URL 参数完成搜索、排序、翻页；能拼 URL 的绝不点击按钮。
2. **模板生成**：使用 `omniauto.templating.generator.TemplateGenerator` 生成确定性 Workflow 脚本，而非手写 ad-hoc 代码。
   - 电商商品调研 → `task_type="ecom_product_research"`
   - 通用浏览器抓取 → `task_type="generic_browser_scrape"`
3. **步骤拆分固定 4 步**：
   - Step 1: 导航搜索页
   - Step 2: 翻页抓取列表（每页后调用 `browser.throttle_request(4.0, 8.0)`）
   - Step 3: 抽样详情页增强（间隔调用 `browser.cooldown(5.0, 10.0)`）
   - Step 4: 数据清洗与报告生成
4. **行为约束**：
   - `Workflow.inter_step_delay` 必须设置为 `(2.0, 4.0)` 或更高
   - 所有 DOM 选择器必须在脚本中硬编码
   - 报告由 Jinja2 模板填充，禁止调用 LLM 生成文案

相关资源：
- 模板目录：`src/omniauto/templates/workflows/`
- Skill 约定：`.agents/skills/deterministic-rpa-workflow/SKILL.md`

---

## 7. 安全审查清单

在提交任何代码变更前，请确认以下检查项全部通过：

- [ ] 未使用 `eval`, `exec`, `subprocess`, `os.system`
- [ ] 所有浏览器/桌面操作均通过 `AtomicStep` 封装
- [ ] 桌面自动化优先评估了 `pyauto-desktop` 而非直接使用裸 `pyautogui`
- [ ] 浏览器自动化优先评估了 `browser-use` / `Stagehand` / `agent-browser` 等开源方案
- [ ] 鼠标移动使用了 `human_like_move()`
- [ ] 所有点击前包含 `random_delay()`
- [ ] 高危操作添加了 `Guardian` 节点
- [ ] 凭证未硬编码，使用了凭据管理器
- [ ] 异常被捕获并上报，未静默吞掉
- [ ] 公共函数包含类型注解和 Docstring
- [ ] 新增了对应的单元测试或集成测试
- [ ] 若选择自研而非集成开源库，文档中说明了具体理由

---

## 8. 参考资料与持续关注清单

以下开源项目与工具应被持续关注，定期评估其新版本的集成价值：

- [browser-use](https://github.com/browser-use/browser-use) — 85k+ stars，Python 原生 AI 浏览器 Agent
- [Stagehand](https://github.com/browserbase/stagehand) — 21k+ stars，Playwright AI 增强层
- [Skyvern](https://github.com/Skyvern-AI/Skyvern) — 20k+ stars，视觉+LLM 企业级浏览器自动化（AGPL）
- [agent-browser](https://github.com/vercel-labs/agent-browser) — Vercel CDP CLI，snapshot-ref 模式
- [Lightpanda](https://github.com/lightpanda-io/browser) — Zig 高性能无头浏览器（AGPL）
- [pyauto-desktop](https://pypi.org/project/pyauto-desktop/) — 跨分辨率桌面自动化增强库
- [OmniParser](https://github.com/microsoft/OmniParser) — 微软开源 GUI 元素检测
- [Smolagents](https://github.com/huggingface/smolagents) — HuggingFace 代码生成 Agent
- [Robocorp](https://github.com/robocorp) — 成熟 Python RPA 生态
- [BotCity](https://github.com/botcity-dev) — 开源 RPA 框架

