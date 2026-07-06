# 微信客服 Prompt 留档说明

## 目标

`customer_service_prompt_archive` 是一个旁路审计模块，只做本地 JSONL 追加留档，不参与识图、Brain 判断、质量审核或微信发送决策。归档失败会被吞掉，不能影响实际客服工作流。

## 默认归档内容

- `customer_image_understanding_prompt`: 识图模块发给视觉模型的提示词、图片路径、视觉本地画像、商品库轻量候选。
- `customer_image_understanding_retry_prompt`: 识图模型返回非 JSON 后的重试提示词。
- `customer_image_understanding_result`: 识图结构化结果。
- `customer_image_understanding_error`: 识图失败时的结构化诊断。
- `customer_image_turn_bridge`: 识图完成后传给 Brain 的视觉桥接包。
- `customer_service_brain_prompt`: Brain 实际发给 LLM 的 system/user messages、brain_input、prompt_pack、prompt_estimate。默认只在当前 Brain 输入包含 `visual_bridge_input` 时记录，避免普通文字聊天全量膨胀。

## 存放位置

默认路径：

```text
runtime/apps/wechat_ai_customer_service/tenants/<tenant_id>/customer_service/prompt_archive/YYYYMMDD.jsonl
```

例如 `chejin` 租户：

```text
runtime/apps/wechat_ai_customer_service/tenants/chejin/customer_service/prompt_archive/
```

每行是一条 JSON 事件，包含：

```json
{
  "schema_version": 1,
  "created_at": "2026-07-06T12:00:00+00:00",
  "kind": "customer_service_brain_prompt",
  "tenant_id": "chejin",
  "payload": {}
}
```

## 安全边界

- 自动打码字段名包含 `api_key`、`authorization`、`access_token`、`refresh_token`、`secret`、`password`、`sendkey`、`x-api-key` 等敏感片段。
- 不保存图片二进制或 base64，只保存本地图片路径和结构化上下文。
- 不改变任何 customer-visible reply 的生成、审核、发送路径。
- 不读取归档内容做实时决策。

## 开关

环境变量关闭全部留档：

```powershell
$env:CUSTOMER_SERVICE_PROMPT_ARCHIVE_ENABLED = "0"
```

指定归档根目录：

```powershell
$env:CUSTOMER_SERVICE_PROMPT_ARCHIVE_ROOT = "D:\AI\omniauto\runtime\prompt_archive_debug"
```

如需让普通文字 Brain prompt 也全量留档，可在运行配置中打开：

```json
{
  "prompt_archive": {
    "include_all_brain_prompts": true
  }
}
```
