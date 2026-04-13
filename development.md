# OmniAuto 开发架构与实施指南

> **版本**: v1.0  
> **用途**: 指导 OmniAuto 框架的系统级开发，涵盖架构设计、模块接口、CLI 规范与测试策略。  
> **核心目标**: 做出类似「影刀 RPA」的自动操作软件，自己从头编写，扩展性和与 Python、AI 结合的相性优先。

---

## 1. 技术栈总览

| 功能域 | 首选方案 | 备选方案 | 开源协议 | 选型理由 |
|--------|---------|---------|---------|---------|
| **AI 浏览器控制** | [browser-use](https://github.com/browser-use/browser-use) | Skyvern | MIT | 85k+ stars，Python 原生，支持 Ollama/Claude/GPT，社区最活跃 |
| **混合浏览器模式** | [Stagehand](https://github.com/browserbase/stagehand) | Playwright + stealth | MIT | 21k+ stars，提供 `act/extract/observe` 三原语，支持缓存降低 LLM 成本 |
| **CLI / CDP 工具** | [agent-browser](https://github.com/vercel-labs/agent-browser) | Pydoll | MIT | Vercel 出品，Rust 高性能 CLI，snapshot-ref 模式极适合 AI 编程工具 |
| **轻量无头浏览器** | [Lightpanda](https://github.com/lightpanda-io/browser) | — | AGPL-3.0 | Zig 编写，启动快、内存低 10x，CDP 兼容；注意协议限制 |
| **代码生成 Agent** | [Smolagents](https://github.com/huggingface/smolagents) | OpenClaude | Apache 2.0 | 代码优先，让 AI 生成 Python 而非 JSON，契合本架构 |
| **工作流编排** | [Prefect](https://www.prefect.io/) | Dagster / Robocorp | Apache 2.0 | Python 原生，支持重试、日志、可视化监控 |
| **桌面视觉自动化** | [pyauto-desktop](https://pypi.org/project/pyauto-desktop/) | PyAutoGUI | 待确认 | PyAutoGUI 增强替代，跨分辨率 Session 自动缩放、内置 GUI Inspector、性能提升 5x |
| **视觉识别** | [OmniParser](https://github.com/microsoft/OmniParser) + OpenCV | GPT-4V API | MIT / 商业 | 微软开源，适合 GUI 元素检测 |
| **RPA 架构参考** | Robocorp / BotCity / TagUI | — | 多种 | 成熟开源 RPA 生态，可借鉴其 Orchestrator 和异常处理设计 |

**开发语言**: Python 3.11+（异步优先 `async/await`）

### 1.1 关键开源调研结论

- **browser-use vs Stagehand vs Skyvern**: 
  - `browser-use` 最适合自主型 Python Agent（高星、MIT、活跃）；
  - `Stagehand` 适合已有 Playwright 代码库的团队，提供混合模式；
  - `Skyvern` 提供企业级能力（2FA/CAPTCHA/视觉理解），但 AGPL 协议对商业闭源不友好。
- **pyauto-desktop 替代 PyAutoGUI**: 
  - 解决了跨分辨率/DPI 脚本失效的行业痛点，内置 GUI Inspector 可自动生成代码，应作为桌面自动化的首选封装层。
- **agent-browser 的 snapshot-ref 模式**: 
  - AI 通过 `snapshot` 获取 `@e1, @e2` 元素引用，通过 `click @e1` 精确操作，无需 CSS 选择器，特别适合与 Codex / Kimi Code 集成。

---

## 2. 系统架构

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    交互层 (Presentation)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │ 自然语言接口  │  │ 任务监控面板  │  │ 异常处理工作台       │ │
│  │ (CLI / Web)  │  │ (Prefect UI) │  │ (人工审核队列)       │ │
│  └──────────────┘  └──────────────┘  └──────────────────────┘ │
└──────────────────────────┬────────────────────────────────────┘
                           │ API / 事件总线
┌─────────────────────────────────────────────────────────────┐
│                    决策层 (Orchestration)                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              AI 策略引擎 (Claude / Codex / GPT / Ollama) │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │ │
│  │  │ 脚本生成器   │  │ 异常决策器   │  │ 视觉理解器   │    │ │
│  │  │ (Smolagents) │  │ (LLM)        │  │ (OmniParser) │    │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘    │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────┬────────────────────────────────────┘
                           │ 确定性指令
┌─────────────────────────────────────────────────────────────┐
│                    执行层 (Execution)                       │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              状态机工作流引擎 (State Machine)            │ │
│  │         ┌──────────┐  ┌──────────┐  ┌──────────┐       │ │
│  │         │ 状态持久 │→│ 步骤执行 │→│ 异常捕获 │       │ │
│  │         │ 化存储   │  │ 器       │  │ 上报     │       │ │
│  │         └──────────┘  └──────────┘  └──────────┘       │ │
│  └─────────────────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              多引擎自动化驱动（对标影刀双引擎）           │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐ │ │
│  │  │ CDP 真实浏览器│ │ Stagehand AI │ │ 视觉自动化引擎   │ │ │
│  │  │ (agent-      │ │ (browser-use │ │ (pyauto-desktop  │ │ │
│  │  │  browser)    │ │ +Stealth)    │ │  + OmniParser)   │ │ │
│  │  └──────────────┘ └──────────────┘ └──────────────────┘ │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 关键组件职责

| 组件 | 技术选型 | 职责 |
|------|---------|------|
| **Browser Engine** | browser-use + Stagehand | 提供浏览器级自动化能力，支持 AI Agent 与确定性原语切换 |
| **CDP Connector** | agent-browser (Vercel) | Rust 高性能 CLI，通过 snapshot-ref 模式连接真实 Chrome |
| **Visual Engine** | pyauto-desktop + OpenCV + OmniParser | 提供图像级 UI 操作，绕过所有浏览器级检测，支持跨分辨率 |
| **State Manager** | Prefect (或自研轻量版) | 工作流编排、重试、日志、可视化监控 |

---

## 3. 核心模块详细设计

### 3.1 模块 1: 隐形浏览器引擎 (Stealth Browser Engine)

**目标**: 绕过 99% 的反爬虫检测，对标影刀的「浏览器自动化」能力。

#### 3.1.1 三层渗透策略

| 层级 | 方案 | 触发条件 | 技术实现 |
|------|------|---------|---------|
| **L1: 透明层** | CDP 连接现有 Chrome | 网站无强检测 | `browser-use` + `agent-browser` 连接本地 Chrome Profile |
| **L2: 伪装层** | Playwright + Stealth | 常规反爬 | `playwright-stealth` 覆盖指纹属性 |
| **L3: 物理层** | 视觉自动化（屏幕级） | 强检测 / 非浏览器 | `pyauto-desktop` 操作真实窗口，OCR 识别元素 |

#### 3.1.2 反检测配置模板

```python
STEALTH_CONFIG = {
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--disable-web-security",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-infobars",
        "--window-size=1920,1080",
        "--user-data-dir=/path/to/real/profile"
    ],
    "scripts": [
        """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
        window.chrome = { runtime: {} };
        """
    ],
    "behavior": {
        "mouse_curve": "bezier",
        "click_delay": (0.1, 0.3),
        "typing_interval": (0.05, 0.15)
    }
}
```

### 3.2 模块 2: 确定性状态机 (Deterministic State Machine)

**核心原则**: AI 绝不直接操作 UI，只生成配置；状态机负责严格执行。

#### 3.2.1 状态定义

```python
from enum import Enum, auto
from typing import Callable, Awaitable, Any
from dataclasses import dataclass

class TaskState(Enum):
    PENDING = auto()
    RUNNING = auto()
    PAUSED = auto()       # 等待人工确认
    COMPLETED = auto()
    FAILED = auto()       # 可重试
    ESCALATED = auto()    # 已上报 AI 决策

@dataclass
class StepResult:
    success: bool
    data: Any = None
    error: Exception = None

class AtomicStep:
    def __init__(
        self,
        step_id: str,
        action: Callable[["TaskContext"], Awaitable[Any]],
        validator: Callable[[Any], bool],
        retry: int = 3,
    ):
        self.id = step_id
        self.action = action
        self.validator = validator
        self.max_retry = retry
        self.current_retry = 0

    async def execute(self, context: "TaskContext") -> tuple[TaskState, StepResult]:
        try:
            result = await self.action(context)
            if self.validator(result):
                return TaskState.COMPLETED, StepResult(success=True, data=result)
            raise ValidationError("结果校验失败")
        except Exception as e:
            self.current_retry += 1
            if self.current_retry >= self.max_retry:
                return TaskState.ESCALATED, StepResult(success=False, error=e)
            return TaskState.FAILED, StepResult(success=False, error=e)
```

#### 3.2.2 持久化与恢复

- 使用 **SQLite** 作为默认状态存储（单机部署），**Redis** 作为可选扩展（分布式部署）
- 每个原子步骤完成后立即 `COMMIT`
- 支持断点续传：系统崩溃重启后，从当前 `RUNNING` 或 `FAILED` 步骤继续执行

### 3.3 模块 3: AI 编排与代码生成 (AI Orchestration)

#### 3.3.1 脚本生成工作流

```
用户自然语言描述
    ↓
Prompt Engineering (结构化需求)
    ↓
Smolagents / Claude Code 生成 Python 脚本
    ↓
静态代码检查 (AST 分析，Bandit 安全扫描)
    ↓
注册到原子脚本库
    ↓
状态机加载执行
```

#### 3.3.2 生成约束（系统 Prompt 模板）

```text
你是一位自动化脚本生成专家。请生成 Python 函数，要求：
1. 必须使用提供的 StealthBrowser 或 pyauto-desktop 类，禁止直接使用 selenium / webdriver
2. 所有点击操作必须包含 random_delay(0.1, 0.5)
3. 鼠标移动必须使用 human_like_move() 而非瞬时移动
4. 禁止生成 eval()、exec()、subprocess、os.system 等危险代码
5. 函数签名：async def atomic_task_XXX(context: TaskContext) -> StepResult
```

### 3.4 模块 4: 视觉自动化兜底 (Visual Fallback)

当浏览器级自动化完全失效时触发，对标影刀的「桌面软件自动化」能力。

#### 3.4.1 视觉元素定位流程

1. **截图**: `pyauto-desktop` 内置 `mss` 高性能截图
2. **识别**: OpenCV 模板匹配或 OmniParser 元素检测
3. **坐标计算**: 返回元素中心点 `(x, y)`（Session 自动处理跨分辨率缩放）
4. **人类化移动**: 贝塞尔曲线鼠标移动
5. **操作**: 点击 / 输入 / 滚动

#### 3.4.2 降级触发逻辑

```python
if browser_engine.detect_blocking():
    logger.warning("检测到反爬虫拦截，切换至视觉模式")
    visual_engine.take_control()
    # 接管控制权，但保持 AtomicStep 接口不变
```

---

## 4. 数据模型与接口约定

### 4.1 TaskContext

```python
from pydantic import BaseModel
from typing import Dict, Any, Optional

class TaskContext(BaseModel):
    task_id: str
    variables: Dict[str, Any]          # 用户注入的变量
    browser_state: Optional[Dict] = None
    visual_state: Optional[Dict] = None
    outputs: Dict[str, Any] = {}       # 各步骤输出缓存
    metadata: Dict[str, Any] = {}      # 运行元数据（耗时、截图路径等）
```

### 4.2 Workflow 定义

```python
from typing import List

class Workflow:
    def __init__(self, steps: List[AtomicStep], guardian_points: List[int] = None):
        self.steps = steps
        self.guardian_points = set(guardian_points or [])

    async def run(self, context: TaskContext):
        for idx, step in enumerate(self.steps):
            if idx in self.guardian_points:
                await self._pause_for_guardian(step, context)
            state, result = await step.execute(context)
            if state == TaskState.ESCALATED:
                await self._escalate_to_ai(step, result, context)
            elif state == TaskState.FAILED:
                # 内置重试已在 AtomicStep 中处理，此处进入 ESCALATED
                continue
```

---

## 5. CLI 设计规范

```bash
# 脚本生成
omni generate "任务描述" --output ./scripts/task_001.py

# 脚本验证（静态检查 + AST 安全扫描）
omni validate ./scripts/task_001.py

# 调试模式（单步执行，可视化）
omni debug --script ./scripts/task_001.py --step 2

# 生产运行
omni run --task task_001 --headless --notify-dingtalk

# 异常处理队列查看
omni queue --show-pending
```

---

## 6. 测试策略

| 测试类型 | 工具 | 覆盖目标 |
|---------|------|---------|
| **单元测试** | pytest | AtomicStep、TaskContext、工具函数（延迟、坐标计算） |
| **集成测试** | pytest + Playwright | Stealth Browser Engine 与真实网站的交互 |
| **端到端测试** | 自研测试脚本 | 完整工作流（登录 → 提取 → 导出 → 通知） |
| **异常降级测试** | pytest + mock | 模拟检测拦截，验证 L1→L2→L3 自动降级 |
| **安全扫描** | Bandit | 扫描生成的原子脚本，禁止危险操作符 |

---

## 7. 开发路线图 (Roadmap)

### Phase 1: 基础引擎 (Week 1-2)
- [ ] 集成 browser-use 和 Stagehand，完成基础浏览器控制
- [ ] 实现 CDP 连接真实 Chrome 功能（agent-browser 集成）
- [ ] 完成反检测脚本库（StealthConfig）
- [ ] 调研并集成 pyauto-desktop，完成跨分辨率桌面自动化原型

### Phase 2: 状态机与编排 (Week 3-4)
- [ ] 实现 StateMachine 核心类（持久化、重试、异常上报）
- [ ] 集成 Prefect 进行工作流可视化
- [ ] 开发 AI 脚本生成器（基于 Smolagents）

### Phase 3: 视觉兜底 (Week 5-6)
- [ ] 集成 OmniParser / pyauto-desktop 视觉识别
- [ ] 实现浏览器 → 视觉自动降级逻辑
- [ ] 开发人工审核工作台 UI

### Phase 4: AI 工具集成 (Week 7-8)
- [ ] 编写 Claude Code Skill 文件
- [ ] 编写 Kimi Code 插件规范
- [ ] 开发 CLI 工具链

### Phase 5: 生产化 (Week 9-10)
- [ ] 添加日志监控（Prometheus / Grafana）
- [ ] 开发任务市场（共享脚本模板）
- [ ] 编写安全审计模块

---

## 8. 风险与对策

| 风险点 | 可能性 | 对策 |
|--------|--------|------|
| **网站结构大变导致视觉识别失效** | 中 | 多模板匹配 + OCR 双重验证，AI 辅助元素定位 |
| **AI 生成脚本存在安全漏洞** | 中 | 静态代码扫描（Bandit），沙箱执行环境，禁止危险操作符 |
| **反检测策略失效** | 低 | 三层降级策略，及时更新指纹库，监控检测特征 |
| **长时间任务状态丢失** | 低 | 每步持久化到 SQLite，支持断点续传和幂等执行 |
| **开源工具协议冲突** | 低 | 优先选用 MIT/Apache/BSD 协议；AGPL 工具（如 Skyvern/Lightpanda）仅作参考或独立进程调用 |

