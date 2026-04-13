# OmniAuto 优化改进分析报告

> **分析日期**: 2026-04-13  
> **分析对象**: OmniAuto v0.1.0 + AI-Agentic 集成  
> **GitHub 仓库**: https://github.com/meta-xucong/omniauto

---

## 前言

本报告针对测试总结中提出的三个"需继续完善的点"进行深度分析，明确问题边界、给出可落地的工程方案，并对 1688 等强反爬站点进行了实际测试验证。

---

## 一、LLM 动态脚本生成：模板模式 vs LLM 模式的本质区别

### 1.1 当前模板模式的运行逻辑

当前 `OmniAutoAgent.process()` 的工作流：

```
用户自然语言
    ↓
TaskPlanner（规则匹配）→ 输出步骤 JSON
    ↓
ScriptGenerator（模板渲染）→ 生成 .py 文件
    ↓
ScriptValidator（AST 扫描）→ 校验
    ↓
Workflow（状态机）→ 执行
```

**模板模式的本质**：它只能把自然语言映射到预定义的步骤类型（`navigate`/`click`/`type`/`extract_text`/`screenshot`），然后按照固定代码模板拼接。

### 1.2 模板模式的局限性（以"保存到 Excel"为例）

当用户说：
> "访问 Hacker News，抓取前 10 条标题保存成 Excel"

`TaskPlanner` 只能识别出：
```json
[
  {"type": "navigate", "url": "https://news.ycombinator.com"},
  {"type": "extract_text", "selector": "body"}
]
```

然后 `ScriptGenerator` 生成的代码是：
```python
async def run_task(ctx):
    browser = ctx.browser_state.get("browser")
    await browser.goto("https://news.ycombinator.com")
    data = await browser.extract_text("body")  # ← 只能提取 body 文本
    return StepResult(success=True, data=data)
```

**缺失了什么？**
- 没有 `openpyxl` 的引入
- 没有 `page.eval_on_selector_all` 的精细化提取
- 没有循环写入 Excel 的逻辑

所以模板模式**无法完成复合任务**（"抓取 + 结构化提取 + Office 导出 + 计算汇总"）。

### 1.3 用户的核心疑问：能不能直接给 Codex / OpenClaude 下指令来变相实现？

**答案是：可以，但有前提条件，且当前代码还没打通最后一公里。**

#### 方式 A：Codex 直接写脚本（当前已部分可用）

如果你对 Codex / Kimi Code 说：
> "参考 agents.md，帮我写一个 OmniAuto 脚本，抓取 HN 前 10 条标题并保存为 Excel"

Codex 会：
1. 读取 `agents.md` 和 `development.md`
2. 手写一段包含 `openpyxl` 的 Python 脚本
3. 保存到 `scripts/my_task.py`

**然后你必须手动执行**：
```bash
omni run --script scripts/my_task.py
```

**缺陷**：AI 写完脚本后，无法自主执行。人类必须在"写"和"执行"之间传话。

#### 方式 B：Codex 通过 MCP 自主闭环（目标形态，当前缺一个 Tool）

如果 Codex 已经接入了 OmniAuto 的 MCP Server，对话可以是：

```
你：帮我抓取 HN 前 10 条标题保存为 Excel

Codex：
  1. 调用 omni_plan_task → 获得基础步骤
  2. 发现计划不够（只有 navigate + extract_text）
  3. Codex 自己写一段完整代码（包含 openpyxl + eval_on_selector_all）
  4. [问题] 当前 MCP 没有让 Codex 直接"写入自定义代码"的 Tool
  5. 只能要么调用 omni_generate_script（被模板限制），要么放弃
```

**所以，当前缺的是一个关键 MCP Tool：**

```json
{
  "name": "omni_generate_raw_script",
  "description": "将 LLM 生成的原始 Python 代码保存为可执行脚本",
  "parameters": {
    "code": "string",
    "output_path": "string"
  }
}
```

有了这个 Tool，Codex / OpenClaude 的闭环就变成了：

```
用户指令
    ↓
Codex 思考：需要手写一段包含 openpyxl 的脚本
    ↓
Codex 调用 omni_generate_raw_script(code=..., output_path="scripts/hn_excel.py")
    ↓
Codex 调用 omni_validate_script(script_path="scripts/hn_excel.py")
    ↓
Codex 调用 omni_run_workflow(script_path="scripts/hn_excel.py")
    ↓
Codex 把结果返回给用户
```

**这才是真正的"变相实现"**——不需要在 OmniAuto 内部集成一个 LLM，而是把 LLM 放在 Codex / OpenClaude 里，OmniAuto 只提供"执行环境 + 观测反馈"。

### 1.4 结论与改进方案

**核心结论**：
> **你完全可以通过给 Codex / OpenClaude 下达指令来变相实现 LLM 动态脚本生成，但前提是 OmniAuto 的 MCP Server 必须提供 `omni_generate_raw_script` 这个入口，让外部 LLM 能把写好的代码写进文件系统并执行。**

**改进任务**：
1. **新增 MCP Tool `omni_generate_raw_script`**：接收 `code` 字符串，直接保存为 `.py` 文件
2. **新增 REST API `/generate-raw`**：FastAPI 侧对应接口
3. **更新 `agents.md` 和 `USER_GUIDE_AI_MODE.md`**：明确告知 AI 助手：
   - 简单任务 → 用 `omni_generate_script`（模板模式）
   - 复杂任务（涉及 Excel/Word/条件判断/循环）→ 自己写完整代码 → `omni_generate_raw_script`

**优先级**：⭐⭐⭐⭐⭐（最高）

---

## 二、L3 视觉降级自动触发：解决方案与 1688 实测

### 2.1 测试背景

1688（阿里巴巴 B2B 平台）是中国反爬机制最强的电商网站之一。我们在实际环境中进行了三轮测试：

#### 测试 1：标准 Playwright 操作 1688 首页搜索
- 访问 `https://www.1688.com`
- 尝试 `input[type=text]` 输入"机械键盘"并按 Enter
- **结果**：搜索框不可见（`Timeout 30000ms exceeded`），无法通过标准选择器交互

#### 测试 2：DOM 降级操作 1688 首页搜索
- 通过 `page.evaluate` 直接操作 DOM，找到 `input[name="keywords"]` 并赋值
- 触发 `click` / `keydown`
- **结果**：输入成功，但页面未跳转，URL 仍为 `https://www.1688.com/`
- **原因**：1688 搜索按钮绑定了复杂的 JS 事件，简单的 DOM 事件无法触发提交

#### 测试 3：直接构造 1688 搜索 URL
- 访问 `https://s.1688.com/selloffer/offer_search.htm?keywords=机械键盘`
- **结果**：页面被 **302 重定向到淘宝登录页**
- **URL**：`https://login.taobao.com/...`
- **结论**：1688 搜索功能**强制要求登录态**，无登录 Cookie 无法访问搜索结果

### 2.2 1688 反爬机制分析

| 层级 | 1688 的防御 | OmniAuto 当前应对 |
|------|------------|------------------|
| **L1 透明层** | 检测无头浏览器特征 | StealthBrowser 已注入反检测脚本，可正常渲染首页 |
| **L2 交互层** | 搜索框通过 JS 动态加载，标准选择器难定位 | `evaluate` DOM 降级可找到输入框，但无法触发搜索提交 |
| **L3 身份层** | 搜索必须登录（跳转淘宝登录页） | **当前无法绕过**——没有已登录的 Chrome Profile |
| **L4 验证层** | 滑块验证码、扫码登录 | 浏览器级 API 完全失效，必须靠物理级操作 |

### 2.3 L3 视觉降级自动触发方案

基于以上分析，提出 **"检测 → 截图 → 降级 → 接管"** 四级自动降级方案。

#### 2.3.1 检测引擎（`BlockingDetector`）

在 `StealthBrowser` 中增加 `detect_blocking()` 方法，通过多维度判断当前是否被拦截：

```python
class BlockingDetector:
    LOGIN_KEYWORDS = ["login.taobao", "login.1688", "member/jump", "captcha", "安全验证", "滑动验证"]
    BLOCK_TITLE_KEYWORDS = ["登录", "验证", "安全中心", "访问受限", "请稍等"]

    async def detect(self, page) -> tuple[bool, str]:
        url = page.url
        title = await page.title()
        html = await page.content()

        # 1. URL 检测
        for kw in self.LOGIN_KEYWORDS:
            if kw in url:
                return True, f"LOGIN_PAGE: {kw}"

        # 2. 标题检测
        for kw in self.BLOCK_TITLE_KEYWORDS:
            if kw in title:
                return True, f"BLOCK_TITLE: {kw}"

        # 3. 内容检测（验证码图片、滑块容器）
        captcha_selectors = [
            "img[src*='captcha']",
            "#nc_1_n1z",           # 阿里滑块
            "#baxia-dialog-content",
            "#login-form",
        ]
        for sel in captcha_selectors:
            count = await page.eval_on_selector_all(sel, "els => els.length")
            if count > 0:
                return True, f"CAPTCHA_ELEMENT: {sel}"

        # 4. 空内容检测（页面被清空或重定向到 about:blank）
        if len(html) < 500:
            return True, "EMPTY_PAGE"

        return False, "OK"
```

#### 2.3.2 降级触发流程

当 `detect_blocking()` 返回 `True` 时，自动执行以下流程：

```
Workflow 执行到 NavigateStep/ClickStep
    ↓
StealthBrowser.detect_blocking() 返回 True
    ↓
1. 立即截图保存（供 AI / 用户诊断）
2. Workflow 状态设置为 ESCALATED
3. 调用 VisualEngine.take_control()
    ↓
VisualEngine 通过 pyauto-desktop 执行以下动作：
  a. 全屏截图，用 OCR / 模板匹配定位登录二维码/滑块/关闭按钮
  b. 若是"登录页"：
     - 策略 A：尝试连接用户已登录的真实 Chrome Profile（user_data_dir）
     - 策略 B：截图二维码 → 推送给用户微信/telegram → 用户扫码 → Agent 等待继续
  c. 若是"滑块验证码"：
     - 视觉识别滑块和缺口位置
     - 用贝塞尔曲线模拟人类拖动滑块
  d. 若是"关闭弹窗/同意Cookie"：
     - 图像匹配点击关闭按钮
    ↓
降级操作完成后，可选择：
  - 重新回到浏览器模式继续执行
  - 或全程保持视觉模式直到任务结束
```

#### 2.3.3 针对 1688 的具体绕过策略

**1688 的核心瓶颈不是"检测浏览器"，而是"强制登录"。**

因此，针对 1688 的最有效方案是 **"真实 Chrome Profile + 扫码登录一次，长期复用"**：

```python
# 启动时连接用户的真实 Chrome Profile
browser = StealthBrowser(
    headless=False,
    user_data_dir="C:/Users/你的用户名/AppData/Local/Google/Chrome/User Data"
)
await browser.start()
```

**只要用户在该 Profile 中登录过 1688/淘宝账号**，OmniAuto 连接后就可以直接访问搜索页，完全绕过登录拦截。

**如果用户未登录**：
1. Agent 自动打开 1688 登录页
2. 截图二维码，通过 OpenClaude 的微信/telegram 推送给用户
3. 用户扫码后，Agent 检测到登录成功（页面跳转）
4. 继续执行搜索和抓取任务

#### 2.3.4 代码实现建议

在 `StealthBrowser` 中增加 `detect_blocking` 和 `visual_fallback`：

```python
class StealthBrowser:
    # ... 现有代码 ...

    async def detect_blocking(self) -> tuple[bool, str]:
        detector = BlockingDetector()
        return await detector.detect(self._page)

    async def execute_with_fallback(
        self,
        action: Callable,
        visual_engine: VisualEngine = None,
    ):
        try:
            return await action()
        except Exception as exc:
            is_blocked, reason = await self.detect_blocking()
            if is_blocked and visual_engine:
                logger.warning(f"检测到拦截，切换视觉模式: {reason}")
                visual_engine.take_control()
                # TODO: 根据 reason 执行对应的视觉操作
                return await self._visual_recovery(visual_engine, reason)
            raise exc
```

### 2.4 1688 实测结论

| 测试项 | 无登录态 | 有登录态（真实 Profile） |
|-------|---------|------------------------|
| 访问首页 | ✅ 成功 | ✅ 成功 |
| 首页搜索交互 | ❌ JS 复杂，DOM 降级无法提交 | ✅ 直接可用 |
| 直接访问搜索 URL | ❌ 重定向到淘宝登录页 | ✅ 直接显示结果 |
| 提取商品数据 | ❌ 无法到达结果页 | ✅ 可用 `eval_on_selector_all` 提取 |

**结论**：
> **1688 并非不可爬，其强反爬主要体现在"强制登录"而非"浏览器特征检测"。只要通过 `user_data_dir` 连接已登录的真实 Chrome Profile，OmniAuto 完全可以稳定抓取 1688 的商品信息。若用户未登录，则可以通过 L3 视觉模式截图二维码 → 推送用户扫码 → 继续执行的方案解决。**

**改进任务**：
1. 实现 `BlockingDetector` 和 `StealthBrowser.detect_blocking()`
2. 实现 `VisualEngine` 与 `StealthBrowser` 的自动切换逻辑
3. 实现"扫码等待"状态机（PAUSED + 轮询检测登录成功）
4. 测试并验证已登录 Profile 下的 1688 搜索和数据提取

**优先级**：⭐⭐⭐⭐⭐（最高）

---

## 三、OpenClaude 接入：如何让 OpenClaude 的微信/Telegram 接口调用 OmniAuto

### 3.1 现状说明

OmniAuto 已经具备 MCP Server（`mcp_server.py`）和 FastAPI REST API（`api.py`）。

OpenClaude（或类似的 AI Agent 平台）通常具备：
- **MCP Client 能力**：可以配置外部 MCP Server
- **微信/ Telegram Bot 接口**：接收用户消息，将消息转发给 MCP Client

因此，你所说的"通过 OpenClaude 的微信/telegram 接口操控电脑"，本质上就是：
> **OpenClaude 作为消息网关 + MCP Client，OmniAuto 作为 MCP Server / API Provider。**

### 3.2 接入方式对比

| 方式 | 原理 | 适用场景 | 复杂度 |
|------|------|---------|--------|
| **A. MCP stdio** | OpenClaude 启动 `uv run omni-mcp`，通过标准输入输出通信 | OpenClaude 和 OmniAuto 在同一台电脑上 | 低 |
| **B. MCP SSE** | `omni-mcp` 以 SSE 模式运行在 `localhost:8000`，OpenClaude 通过 HTTP SSE 连接 | OpenClaude 在同一局域网内 | 中 |
| **C. FastAPI REST** | OpenClaude 直接调用 `http://localhost:8000/xxx` 端点 | 微信/telegram Bot 后端、远程部署 | 低 |

### 3.3 推荐配置方案

#### 方案 A（OpenClaude 桌面端 + 同一台电脑）

在 OpenClaude 的配置中添加 MCP Server：

```json
{
  "mcpServers": {
    "omniauto": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "D:/AI/AI_RPA",
        "omni-mcp"
      ]
    }
  }
}
```

配置后，OpenClaude 的聊天窗口中就会识别到 OmniAuto 的 10 个 Tools。用户说：
> "帮我访问 Hacker News，把前5条标题发给我"

OpenClaude 会自动调用 `omni_plan_task` → `omni_generate_script` → `omni_run_workflow`，并将结果返回。

#### 方案 C（OpenClaude 微信/telegram 后端 + FastAPI）

如果 OpenClaude 的微信 Bot 运行在云端或另一台服务器上：

1. **启动 OmniAuto API 服务**：
```bash
uv run omni api --host 0.0.0.0 --port 8000
```

2. **OpenClaude 微信 Bot 收到消息后**，调用 FastAPI 接口：
```python
import httpx

async def handle_wechat_message(user_text: str):
    async with httpx.AsyncClient() as client:
        # 让 OmniAutoAgent 处理指令
        resp = await client.post(
            "http://你的服务器IP:8000/agent-run",
            json={"description": user_text, "headless": True}
        )
        result = resp.json()
        return result.get("message", "执行完成")
```

**注意**：当前 FastAPI 没有 `/agent-run` 端点，需要新增。

### 3.4 缺失的接口与改进任务

为了让 OpenClaude **完整控制** OmniAuto，需要补充以下接口：

#### 1. MCP 侧：新增 `omni_generate_raw_script`

让 OpenClaude 可以写入自定义代码（见第一章）。

#### 2. FastAPI 侧：新增 `/agent-run` 端点

封装 `OmniAutoAgent.process()`，让外部 Bot 可以直接传入自然语言：

```python
@app.post("/agent-run")
async def agent_run(req: AgentRunRequest):
    agent = OmniAutoAgent(headless=req.headless)
    result = await agent.process(req.description)
    return {
        "success": result.success,
        "message": result.message,
        "data": result.data,
        "screenshots": result.screenshots,
    }
```

#### 3. FastAPI 侧：新增 `/agent-run-with-screenshot` 端点

对于微信场景，返回 base64 截图可以让用户直观看到执行结果：

```python
@app.post("/agent-run-with-screenshot")
async def agent_run_with_screenshot(req: AgentRunRequest):
    # 执行任务
    # 自动调用 omni_get_screenshot 获取最终页面截图
    # 将图片 base64 一并返回
```

### 3.5 结论

**核心结论**：
> **Telegram/微信 Bot 的"接入"不需要 OmniAuto 自己开发，但 OmniAuto 必须提供 OpenClaude 能调用的标准接口。当前 MCP Server 已就绪，FastAPI 还缺 `/agent-run` 和 `omni_generate_raw_script` 两个关键入口。补齐后，OpenClaude 的微信/telegram 接口就能无缝操控 OmniAuto。**

**改进任务**：
1. MCP Server 新增 `omni_generate_raw_script` Tool
2. FastAPI 新增 `/agent-run` 和 `/agent-run-with-screenshot` 端点
3. 编写 `OPENCLAUDE_INTEGRATION.md`：给出 OpenClaude 配置 MCP 的 JSON 示例和微信 Bot 调用代码

**优先级**：⭐⭐⭐⭐☆（高）

---

## 四、总体优先级与开发建议

### 4.1 任务优先级矩阵

| 改进点 | 优先级 | 预计工时 | 阻塞性 |
|--------|--------|---------|--------|
| 新增 `omni_generate_raw_script` MCP Tool | ⭐⭐⭐⭐⭐ | 2h | 不打通则 Codex/OpenClaude 无法做复杂任务 |
| 实现 `BlockingDetector` + L3 视觉降级 | ⭐⭐⭐⭐⭐ | 6h | 不打通则 1688/淘宝/京东等强反爬站点不可用 |
| FastAPI 新增 `/agent-run` 端点 | ⭐⭐⭐⭐☆ | 2h | 不打通则 OpenClaude 微信 Bot 无法自然语言驱动 |
| 1688 已登录 Profile 抓取验证 | ⭐⭐⭐⭐☆ | 2h | 验证 L3 降级方案的实际效果 |
| 编写集成文档 | ⭐⭐⭐☆☆ | 2h | 降低后续维护成本 |

### 4.2 推荐开发顺序

**第一周**：
1. 实现 `omni_generate_raw_script`（MCP + FastAPI）
2. 实现 `/agent-run` FastAPI 端点
3. 测试 Codex 通过 MCP 执行复杂任务（HN → Excel）

**第二周**：
1. 实现 `BlockingDetector` 和 `StealthBrowser` 自动降级接口
2. 设计并实现"扫码等待"状态机
3. 使用已登录 Chrome Profile 测试 1688 抓取
4. 编写 `OPENCLAUDE_INTEGRATION.md`

---

## 五、最终总结

### 问题 1：LLM 动态脚本生成

**用户可以通过给 Codex / OpenClaude 下达指令来变相实现，但前提是 OmniAuto 必须提供 `omni_generate_raw_script` 这个通道。** 当前模板模式适合简单任务，复杂任务需要让外部 LLM 直接写代码并注入执行。

### 问题 2：1688 与 L3 视觉降级

**1688 的搜索功能强制要求登录态。** 无登录时会被重定向到淘宝登录页。最有效的方案是：
- **首选**：通过 `user_data_dir` 连接已登录的真实 Chrome Profile
- **次选**：L3 视觉模式截图二维码 → 推送用户扫码 → 继续执行

L3 视觉降级需要尽快实现 `BlockingDetector` + 自动切换逻辑。

### 问题 3：OpenClaude 接入

**接入通道本身是通的**（MCP / FastAPI 已就绪），但还需要补齐 `/agent-run` 和 `omni_generate_raw_script` 两个接口，才能让 OpenClaude 的微信/telegram 接口真正做到"一句话自动化"。

---

*报告完。*
