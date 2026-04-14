# OmniAuto AI-Agentic 集成开发技术指导

> **版本**: v1.0  
> **目标**: 将 OmniAuto 从"CLI 工具"升级为"AI 可直接操控的 Agent 平台"，支持用户在 Kimi Code / Codex / OpenClaude 的聊天窗口中通过自然语言驱动自动化工作流。

---

## 1. 架构总览

OmniAuto 的 AI-Agentic 模式采用**三层架构**：

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户交互层 (Chat Layer)                        │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐    │
│  │ Kimi Code  │  │   Codex    │  │  Telegram  │  │   微信     │    │
│  │  聊天窗口  │  │  聊天窗口  │  │    Bot     │  │   Bot      │    │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘    │
└────────┼───────────────┼───────────────┼───────────────┼───────────┘
         │               │               │               │
         └───────────────┴───────┬───────┴───────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   Message Gateway       │
                    │  (统一消息路由/会话管理) │
                    └────────────┬────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────┐
│                        Agent Runtime 层                             │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    OmniAutoAgent                            │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │   │
│  │  │ 意图理解 │→│ 任务规划 │→│ 脚本生成 │→│ 执行监控 │    │   │
│  │  │ (LLM)    │  │ (Planner)│  │(Generator)│  │(Observer)│    │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │   │
│  │  ┌──────────┐  ┌──────────┐                                 │   │
│  │  │ 自我修复 │  │ 定时调度 │                                 │   │
│  │  │ (Fixer)  │  │(Scheduler)│                                │   │
│  │  └──────────┘  └──────────┘                                 │   │
│  └─────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ Function Calls
┌────────────────────────────────▼────────────────────────────────────┐
│                      Function Bridge 层                             │
│  ┌─────────────────────┐  ┌─────────────────────┐                   │
│  │   MCP Server        │  │   FastAPI REST API  │                   │
│  │  (Kimi/Codex/Claude)│  │  (Telegram/微信Bot) │                   │
│  └──────────┬──────────┘  └──────────┬──────────┘                   │
│             │                        │                               │
│             └────────────┬───────────┘                               │
│                          │                                           │
│               ┌──────────▼──────────┐                                │
│               │   OmniAutoService   │                                │
│               │  (核心业务逻辑封装)  │                                │
│               └──────────┬──────────┘                                │
└──────────────────────────┼──────────────────────────────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
      ┌──────────┐  ┌──────────┐  ┌──────────┐
      │ Script   │  │ Workflow │  │  State   │
      │ Generator│  │ Engine   │  │  Store   │
      └──────────┘  └──────────┘  └──────────┘
```

---

## 2. 核心设计原则

### 2.1 AI 不直接操作 UI

与 OmniAuto 基础架构一致：AI 只通过 **Function Call / MCP Tool** 调用抽象接口，实际的浏览器/桌面操作仍由 `Workflow` + `AtomicStep` 在确定性状态机中执行。

### 2.2 所有用户指令必须可追踪

每条来自聊天窗口的指令都会生成：
- 一个 `session_id`（对话会话）
- 一个或多个 `task_id`（具体任务）
- 一份持久化到 SQLite 的执行记录

### 2.3 失败必须可观测、可修复

Agent Runtime 必须具备：
- 执行失败时自动获取截图
- 将错误日志、状态机快照、脚本内容返回给 LLM
- LLM 诊断后调用 `regenerate_and_rerun` 进行自修复

### 2.4 高信任模式可配置

Guardian 节点默认开启。用户可以在配置文件中设置 `TRUST_MODE=high`，允许 AI 自动跳过非高危 Guardian 确认。

---

## 3. MCP Tools 规范（Function Bridge）

以下 Tools 是 AI Agent 直接操控 OmniAuto 的接口。每个 Tool 都是**有状态、可观测、幂等或可追溯**的。

### 3.1 `omni_plan_task`

**用途**: 将自然语言指令转换为结构化任务计划。

**签名**:
```json
{
  "name": "omni_plan_task",
  "description": "根据用户自然语言描述，生成 OmniAuto 原子步骤计划",
  "parameters": {
    "type": "object",
    "properties": {
      "description": {
        "type": "string",
        "description": "用户的任务描述，如'访问百度搜索影刀RPA'"
      }
    },
    "required": ["description"]
  }
}
```

**返回值**:
```json
{
  "plan_id": "plan_xxx",
  "steps": [
    {"type": "navigate", "url": "https://www.baidu.com"},
    {"type": "type", "selector": "#kw", "text": "影刀RPA"},
    {"type": "click", "selector": "#su"},
    {"type": "extract_text", "selector": "div.result"}
  ],
  "estimated_risk": "low",
  "needs_guardian": false
}
```

### 3.2 `omni_generate_script`

**用途**: 基于计划生成可执行的 Python 原子脚本。

**签名**:
```json
{
  "name": "omni_generate_script",
  "description": "根据任务计划生成 OmniAuto 原子脚本",
  "parameters": {
    "type": "object",
    "properties": {
      "description": {"type": "string"},
      "output_path": {
        "type": "string",
        "description": "脚本保存路径，如'./scripts/task_001.py'"
      }
    },
    "required": ["description", "output_path"]
  }
}
```

**返回值**:
```json
{
  "script_path": "./scripts/task_001.py",
  "generated_at": "2026-04-13T10:00:00Z",
  "lines_of_code": 42
}
```

### 3.3 `omni_validate_script`

**用途**: 对生成的脚本进行静态安全扫描。

**签名**:
```json
{
  "name": "omni_validate_script",
  "description": "校验脚本是否包含危险操作或硬编码敏感信息",
  "parameters": {
    "type": "object",
    "properties": {
      "script_path": {"type": "string"}
    },
    "required": ["script_path"]
  }
}
```

**返回值**:
```json
{
  "valid": true,
  "issues": [],
  "report": "[OK] 脚本校验通过"
}
```

### 3.4 `omni_run_workflow`

**用途**: 执行指定的原子脚本，启动工作流。

**签名**:
```json
{
  "name": "omni_run_workflow",
  "description": "执行 OmniAuto 工作流脚本",
  "parameters": {
    "type": "object",
    "properties": {
      "script_path": {"type": "string"},
      "headless": {
        "type": "boolean",
        "description": "是否使用无头模式",
        "default": true
      },
      "task_id": {
        "type": "string",
        "description": "可选的任务ID，用于断点续传"
      }
    },
    "required": ["script_path"]
  }
}
```

**返回值**:
```json
{
  "task_id": "task_xxx",
  "final_state": "COMPLETED",
  "outputs": {
    "extract_text_result": "影刀RPA 是一款..."
  },
  "duration_seconds": 12.5
}
```

### 3.5 `omni_get_screenshot`

**用途**: 获取当前浏览器页面或桌面截图，供 AI 做视觉诊断。

**签名**:
```json
{
  "name": "omni_get_screenshot",
  "description": "获取当前浏览器或桌面截图（base64格式）",
  "parameters": {
    "type": "object",
    "properties": {
      "engine": {
        "type": "string",
        "enum": ["browser", "visual"],
        "default": "browser"
      }
    }
  }
}
```

**返回值**:
```json
{
  "image_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
  "format": "png",
  "timestamp": "2026-04-13T10:00:12Z"
}
```

### 3.6 `omni_get_task_status`

**用途**: 查询指定任务的执行状态和输出。

**签名**:
```json
{
  "name": "omni_get_task_status",
  "description": "查询任务当前状态",
  "parameters": {
    "type": "object",
    "properties": {
      "task_id": {"type": "string"}
    },
    "required": ["task_id"]
  }
}
```

**返回值**:
```json
{
  "task_id": "task_xxx",
  "state": "ESCALATED",
  "current_step": 3,
  "outputs": {},
  "error": "TimeoutError: 元素未找到",
  "updated_at": "2026-04-13T10:05:00Z"
}
```

### 3.7 `omni_get_queue`

**用途**: 获取所有异常、暂停或待处理的任务列表。

**签名**:
```json
{
  "name": "omni_get_queue",
  "description": "查看异常和待处理任务队列",
  "parameters": {
    "type": "object",
    "properties": {}
  }
}
```

**返回值**:
```json
{
  "pending_tasks": [
    {
      "task_id": "task_xxx",
      "state": "ESCALATED",
      "current_step": 3,
      "error": "TimeoutError",
      "updated_at": "2026-04-13T10:05:00Z"
    }
  ]
}
```

### 3.8 `omni_schedule_task`

**用途**: 将脚本注册为定时重复任务。

**签名**:
```json
{
  "name": "omni_schedule_task",
  "description": "创建定时重复执行的自动化任务",
  "parameters": {
    "type": "object",
    "properties": {
      "script_path": {"type": "string"},
      "task_name": {"type": "string"},
      "cron_expr": {
        "type": "string",
        "description": "Cron 表达式，如'0 9 * * *'表示每天早9点"
      },
      "headless": {"type": "boolean", "default": true}
    },
    "required": ["script_path", "task_name", "cron_expr"]
  }
}
```

**返回值**:
```json
{
  "schedule_id": "sch_xxx",
  "task_name": "daily_erp_report",
  "cron_expr": "0 9 * * *",
  "next_run": "2026-04-14T09:00:00Z"
}
```

### 3.9 `omni_list_scheduled_tasks`

**用途**: 列出所有已注册的定时任务。

**返回值**:
```json
{
  "schedules": [
    {
      "schedule_id": "sch_xxx",
      "task_name": "daily_erp_report",
      "cron_expr": "0 9 * * *",
      "active": true
    }
  ]
}
```

### 3.10 `omni_list_available_steps`

**用途**: 返回系统支持的所有原子步骤类型及使用说明，帮助 AI 在手动编写脚本时参考。

**返回值**:
```json
{
  "steps": [
    {
      "name": "NavigateStep",
      "params": ["url"],
      "description": "导航到指定URL"
    },
    {
      "name": "ClickStep",
      "params": ["selector"],
      "description": "点击CSS选择器匹配的元素"
    }
  ]
}
```

---

## 4. Agent Runtime 决策循环设计

### 4.1 ReAct 循环（观测-思考-行动）

OmniAutoAgent 采用类 ReAct 的决策循环：

```
[Observation] 接收用户自然语言指令
      ↓
[Thought] LLM 分析：这是新任务 / 重复任务 / 查询 / 修复？
      ↓
[Action] 调用相应 MCP Tool
      ↓
[Observation] 获取 Tool 执行结果
      ↓
[Thought] 判断：是否需要继续执行下一步？是否需要修复？
      ↓
... 循环直到任务完成或达到最大轮数
      ↓
[Final Answer] 向用户返回结果摘要
```

### 4.2 标准任务执行流

对于一次性任务，Agent 的标准调用链为：

```
omni_plan_task(description)
    ↓
omni_generate_script(description, output_path)
    ↓
omni_validate_script(script_path)
    ↓ [若 valid=false，返回修正]
omni_run_workflow(script_path, headless=true)
    ↓ [若 state=COMPLETED]
向用户返回 outputs
    ↓ [若 state=ESCALATED/FAILED]
omni_get_screenshot()
omni_get_task_status(task_id)
    ↓
LLM 诊断错误原因
    ↓
[修正脚本] → omni_run_workflow(修正后的脚本) [最多重试 3 轮]
    ↓ [仍失败]
向用户报告失败原因 + 截图，请求人工介入
```

### 4.3 重复任务执行流

```
用户："每天早上9点登录钉钉打卡"
    ↓
omni_plan_task("登录钉钉打卡")
    ↓
omni_generate_script(...)
    ↓
omni_validate_script(...)
    ↓
omni_run_workflow(...)  [先预执行一次验证]
    ↓ [预执行成功]
omni_schedule_task(script_path, cron_expr="0 9 * * *", task_name="dingding_checkin")
    ↓
向用户确认："已创建定时任务，每天早9点执行，下次执行时间为明天 09:00"
```

### 4.4 自我修复 Prompt 模板

当任务失败时，OmniAutoAgent 会将以下上下文注入 LLM：

```
任务执行失败，请分析原因并生成修正后的脚本。

[原始指令]
{user_description}

[失败信息]
状态: {final_state}
错误: {error_message}
失败步骤: {step_id}

[当前脚本内容]
{script_content}

[截图分析]
{base64_screenshot}  ← 若支持多模态则直接传入图片

[要求]
1. 分析失败原因（选择器失效 / 页面加载慢 / 反检测拦截 / 网络异常）
2. 生成修正后的完整脚本
3. 如果是反检测，考虑增加 WaitStep 或切换到 visual 模式
4. 禁止引入 eval / exec / subprocess 等危险代码
```

---

## 5. 接口实现细节

### 5.1 OmniAutoService 设计

将 CLI 中的核心逻辑解耦为 `OmniAutoService`：

```python
class OmniAutoService:
    def __init__(self, state_store: StateStore = None):
        self.store = state_store or StateStore()
        self.generator = ScriptGenerator()
        self.validator = ScriptValidator()
        self.scheduler = TaskScheduler()  # APScheduler 封装

    async def plan_task(self, description: str) -> dict:
        ...

    async def generate_script(self, description: str, output_path: str) -> dict:
        ...

    async def validate_script(self, script_path: str) -> dict:
        ...

    async def run_workflow(
        self, script_path: str, headless: bool = True, task_id: str = None
    ) -> dict:
        ...

    async def get_screenshot(self, engine: str = "browser") -> dict:
        ...

    async def get_task_status(self, task_id: str) -> dict:
        ...

    async def schedule_task(
        self, script_path: str, task_name: str, cron_expr: str, headless: bool = True
    ) -> dict:
        ...
```

### 5.2 MCP Server 实现

基于 `mcp` Python SDK 实现：

```python
from mcp.server import Server
from mcp.types import Tool

server = Server("omniauto-mcp")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [...]  # 返回 3.1-3.10 定义的 Tools

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    service = OmniAutoService()
    if name == "omni_plan_task":
        result = await service.plan_task(arguments["description"])
    elif name == "omni_run_workflow":
        result = await service.run_workflow(...)
    ...
    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
```

启动方式：
```bash
uv run python -m omniauto.mcp_server
```

### 5.3 FastAPI REST API 实现

与 MCP Server 共享 `OmniAutoService`：

```python
from fastapi import FastAPI
from omniauto.service import OmniAutoService

app = FastAPI()
service = OmniAutoService()

@app.post("/plan")
async def plan(req: PlanRequest):
    return await service.plan_task(req.description)

@app.post("/run")
async def run(req: RunRequest):
    return await service.run_workflow(...)

@app.get("/task/{task_id}")
async def task_status(task_id: str):
    return await service.get_task_status(task_id)
```

---

## 6. 安全与隔离策略

### 6.1 Guardian 策略矩阵

| 操作类型 | 默认策略 | 高信任模式 |
|---------|---------|-----------|
| 普通网页浏览/数据提取 | AI 自动执行 | AI 自动执行 |
| 点击登录/提交表单 | 询问用户确认 | AI 自动执行 |
| 发送消息/邮件/通知 | **强制人工确认** | **强制人工确认** |
| 转账/删除/修改配置 | **强制人工确认** | **强制人工确认** |
| 调用系统命令 | **永远禁止** | **永远禁止** |

### 6.2 自修复上限

AI 自动修复重试不得超过 **3 轮**。超过后必须转人工，防止无限循环消耗 Token。

### 6.3 脚本沙箱

未来可引入 ` RestrictedPython` 或独立子进程执行生成的脚本，限制文件系统访问范围。

---

## 7. 扩展指南

### 7.1 新增一个 MCP Tool

1. 在 `OmniAutoService` 中实现业务方法
2. 在 `mcp_server.py` 的 `list_tools()` 中注册 Tool Schema
3. 在 `call_tool()` 中增加分支处理
4. 在 `FastAPI` 路由中增加对应的 HTTP endpoint
5. 更新 `agents.md` 和 `USER_GUIDE_AI_MODE.md`

### 7.2 接入新的聊天平台

1. 实现消息适配器：`BaseMessageGateway` 抽象类
2. 实现具体的 `WechatGateway` / `DiscordGateway`
3. 将用户消息转换为统一格式：`UserIntent(session_id, text, attachments)`
4. 调用 `OmniAutoAgent.process(intent)`
5. 将 Agent 返回的 `AgentResponse(text, images, actions)` 发送回聊天平台

---

## 8. 与现有代码的衔接点

| 新模块 | 复用的现有模块 |
|--------|--------------|
| `OmniAutoService.plan_task` | `TaskPlanner` |
| `OmniAutoService.generate_script` | `ScriptGenerator` |
| `OmniAutoService.validate_script` | `ScriptValidator` |
| `OmniAutoService.run_workflow` | `Workflow.run()` + `StealthBrowser` |
| `OmniAutoService.get_task_status` | `StateStore.load_workflow()` |
| `OmniAutoAgent` | `Smolagents` / LLM 封装 |

---

## 9. 开发状态与下一步

### 9.1 已实现
- ✅ `OmniAutoService` 与 `mcp_server.py`（7 个核心 MCP Tool）
- ✅ FastAPI REST API（`api.py`）
- ✅ 状态机持久化、StealthBrowser、视觉引擎
- ✅ Deterministic RPA Workflow 模板系统（电商商品调研等高频任务已模板化）

### 9.2 待补齐
1. **MCP Tool `omni_generate_raw_script`**：让外部 LLM 可以直接注入自定义 Python 代码，突破模板模式对复杂任务（Excel/Word/循环/条件判断）的限制
2. **FastAPI 端点 `/agent-run`**：为 Telegram / 微信 Bot 提供自然语言入口
3. **OpenClaude 集成文档**：给出配置 JSON 和 Bot 调用示例
4. **端到端测试**：覆盖 MCP → Service → Workflow 全链路
