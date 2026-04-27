# 微信 AI 客服优化改造指导文档

## 1. 改造目标

本项目的目标不是只做一个能回复微信的临时脚本，而是以 OmniAuto 为底座，形成一个结构清晰、可持续扩展、可审计、可逐步学习的微信 AI 客服应用。

改造完成后应满足：

1. OmniAuto 继续作为通用自动化基础设施，沉淀桌面控制、运行状态、限流、审计、知识索引、LLM 调用等可复用能力。
2. 微信 AI 客服作为独立应用包存在，业务文件、话术、商品资料、客户数据、测试场景和运行配置不得混入 OmniAuto 底层或其他任务目录。
3. 通用知识和任务专用知识分开存放，并通过索引和导引文件按需加载，避免 Codex 开发和 DeepSeek 客服推理时读取无关记忆。
4. 业务事实、真实客服话术、策略边界、失败案例、人工审核候选内容分别管理，支持后续通过原始聊天记录和产品数据不断优化。
5. AI 生成的知识或优化建议默认进入候选区，经过人工确认后才能晋升为正式业务知识或开发知识。

## 2. 分层架构

整体采用三层结构：

```text
OmniAuto 通用底座
  -> 微信 AI 客服应用包
    -> 业务知识、运行数据、审核候选、测试场景
```

### 2.1 OmniAuto 通用底座

底座只存放可被多个任务复用的基础能力，不存放微信客服专用业务知识。

建议逐步沉淀到 `platform/src/omniauto/` 的能力：

| 能力 | 归属 | 说明 |
| --- | --- | --- |
| Windows 窗口发现、置顶、最大化、前台检查 | 底层 | 微信、ERP、桌面软件均可复用 |
| 鼠标、键盘、剪贴板、热键输入 | 底层 | OmniAuto RPA 基础能力 |
| UIAutomation / pywinauto 适配 | 底层 | 比纯坐标操作更稳定 |
| sidecar 进程管理 | 底层 | 外部 Python 版本、外部库、被控软件桥接均可复用 |
| 运行锁、心跳、状态文件 | 底层 | 防止重复监听和残留进程 |
| JSONL 审计日志 | 底层 | 便于回放、排错和训练数据提取 |
| 限流、冷却、调度器 | 底层 | 客服、群发、定时任务均需要 |
| LLM provider 抽象 | 底层 | DeepSeek、Kimi、OpenAI 等模型可切换 |
| 知识 manifest、按需加载、证据包构造 | 底层 | 控制 token 消耗和上下文边界 |
| AI 候选知识生成与人工审核流程 | 底层 | 只负责机制，不负责微信业务内容 |

### 2.2 微信 AI 客服应用包

微信客服专用内容集中放在：

```text
apps/wechat_ai_customer_service/
```

该目录用于承载：

- 微信连接适配器。
- 客服监听、回复、客户资料采集、定时触达等 workflow。
- 商品、物流、开票、公司信息、售后政策、FAQ。
- 真实客服话术风格样例。
- 原始聊天记录和产品资料导入区。
- AI 整理后的候选知识。
- 任务专用测试场景。

### 2.3 知识与数据层

知识分为三类：

| 类型 | 目录 | 用途 |
| --- | --- | --- |
| 通用 OmniAuto 知识 | `knowledge/common/`、`knowledge/patterns/`、`knowledge/capabilities/` | 给开发者和平台能力复用 |
| 微信客服开发知识 | `knowledge/tasks/desktop/wechat_ai_customer_service/` | 给 Codex 开发、排错、迭代读取 |
| 微信客服业务数据 | `apps/wechat_ai_customer_service/data/structured/` | 给客服 workflow 和 DeepSeek evidence pack 使用 |

运行时 DeepSeek 不应直接读取全局 `knowledge/`。它只接收本轮消息需要的精简证据包。

## 3. 目标目录结构

```text
D:/AI/AI_RPA/
  apps/
    wechat_ai_customer_service/
      README.md
      configs/
        default.json
        test_contact.example.json
      workflows/
        listen_and_reply.py
        approved_outbound_send.py
        preflight.py
      adapters/
        wechat_connector.py
        wxauto4_sidecar.py
        wechat_sidecar_runner.py
      prompts/
        persona.md
        reply_policy.md
        handoff_policy.md
        evidence_pack_template.md
      data/
        structured/
          manifest.json
          product_knowledge.example.json
          style_examples.json
        raw_inbox/
          chats/
          products/
          policies/
          erp_exports/
        review_candidates/
          pending/
          approved/
          rejected/
      tests/
        scenarios/
      docs/
        DEBUG_LESSONS.md
        OPERATIONS.md

  knowledge/
    tasks/
      desktop/
        wechat_ai_customer_service/
          INDEX.md
          architecture_notes.md
          debug_lessons.md
          knowledge_loading_policy.md

  runtime/
    apps/
      wechat_ai_customer_service/
        state/
        logs/
        test_artifacts/
```

## 4. 知识按需加载机制

### 4.1 Manifest 优先

正式业务知识文件必须由 manifest 描述，而不是由代码硬编码全部加载。

示例：

```json
{
  "version": 1,
  "scope": "wechat_ai_customer_service",
  "items": [
    {
      "id": "product_knowledge",
      "path": "product_knowledge.example.json",
      "kind": "business_data",
      "intent_tags": ["catalog", "quote", "discount", "shipping", "stock", "warranty", "spec"],
      "summary": "测试商品、FAQ、公司、开票、物流、售后政策",
      "token_budget": 3000
    }
  ]
}
```

### 4.2 运行时证据包

客服 workflow 的推荐链路：

```text
用户消息
  -> 轻量意图识别
  -> 根据 intent_tags 查询 manifest
  -> 加载最少业务知识
  -> 结合会话状态生成 evidence pack
  -> 规则系统优先判定
  -> DeepSeek advisory 只读取 evidence pack
  -> 可自动答则回复；证据不足则转人工
```

证据包应包含：

- 当前用户消息。
- 最近会话上下文摘要。
- 命中的商品、FAQ、政策片段。
- 客服人设和回复边界。
- 是否允许自动发送。
- 不足以回答时的转人工指令。

证据包不应包含：

- 全量知识目录。
- 无关任务记忆。
- 未审核候选知识。
- API key、账号密码等敏感信息。

## 5. 学习与审核闭环

微信 AI 客服不能让模型自由改正式知识。推荐闭环：

```text
真实聊天 / 测试聊天
  -> audit.jsonl
  -> 自动归纳失败点
  -> 生成候选修正
  -> 写入 review_candidates/pending
  -> 人工审核
  -> 晋升到 structured 数据、prompt 或测试场景
  -> 回归测试
```

候选内容必须保留证据来源，包括：

- 来源消息 id 或审计事件 id。
- 原始用户问题。
- 当前系统回复。
- 失败原因。
- 建议修改的知识文件或话术文件。
- 建议新增的测试场景。

## 6. 改造原则

1. 先保证现有微信客服原型继续可运行，再迁移目录。
2. 先建立应用边界，再抽象底层组件。
3. 先做 manifest 和 evidence pack，再扩大 DeepSeek 决策权。
4. 事实数据、话术风格、业务规则、人工接管策略必须分开。
5. 每章只做一组相关功能，每章完成后必须运行聚焦测试。
6. 全部章节完成后再做全量测试。
7. 任何 AI 生成知识默认是候选，不直接进入正式知识。

