# Brain 回合语义与质量边界（2026-07-13）

本说明遵循：

- `customer_visible_reply_ownership_baseline.md`
- `customer_service_external_contract_and_optional_plugin_baseline.md`

## 目标

客户消息可能同时包含招呼、追问、图片噪音、口语、省略表达和真实业务诉求。不能因为本地规则把其中某个片段识别成“在吗/你好”，就把 Brain 已生成的正常回复拦成已读不回。

本次调整只改变 Brain 契约与质量审计的边界，不改变调度器、RPA、会话绑定、发送接口或外部 Brain 证据合同。

## 回合语义

`BrainPlan.understanding` 保持开放对象，并新增可选的、向后兼容的字段：

```json
{
  "turn_semantics": {
    "kind": "business | social | mixed | uncertain",
    "basis": "current_message | context | mixed",
    "current_request": "本轮客户的简短诉求"
  }
}
```

它由 `customer_service_brain` 输出。质量层只读取和记录该语义；不根据车型、账号、关键词或本地话术替 Brain 决定客户意图。缺失字段的旧 Plan 仍可正常运行，语义记为 `uncertain`。

当 Brain 明确为 `business` 或 `mixed` 且依据为 `current_message` 时，短招呼文本不能触发本地“社交消息”复核。该元数据从不授权价格、库存、车况、政策或任何事实。

## 硬边界与软复核

以下仍是硬边界：空回复、内部信息/AI 身份泄露、危险承诺、未经授权的产品或政策事实、会话/发送目标安全，以及 Guard 的事实和安全约束。

以下改为 `quality_verification.warnings` 中可审计的 `social_context_review:*`：旧上下文被主动带回、没有未答上下文时的自述式承接、社交疲劳后的业务拉回、招呼后收集信息、延迟承接形态不理想。这些是相关性或自然度信号，不足以单独导致不发送。

带有该警告的 Plan 会进入现有语义复核路径；语义审查不可用或未发现硬问题时，保留原始 Brain 回复并写入审计。质量层、语义审查、Guard 都不能生成、替换或拼接客户可见文字。

## 可观察性与兼容性

`verify_brain_reply_quality` 和运行时压缩后的 `quality_verification` 都以附加字段保留 `turn_semantics`。既有 `ok`、`errors`、`warnings`、`repair_instruction` 字段和调用方式不变。

本地启发式仍可发现可疑上下文，但只提供复核信号；它不能阻塞无关图片、简短问候或混合表达的正常 Brain 回复。上游事实、敏感字段筛选、会话绑定和物理发送确认的既有职责不受影响。

## 验收

契约检查覆盖：

- 带“在不？”的真实业务请求由 Brain `turn_semantics` 直接保留；
- 无支撑或陈旧上下文被记录为警告但不造成无回复；
- 社交疲劳、自述式历史承接、图片/信息采集相关性问题同样为可审计软复核；
- 高风险承诺、事实授权和其他既有硬边界继续失败。
