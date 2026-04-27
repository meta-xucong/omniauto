# 微信 AI 客服任务知识索引

本目录只存放微信 AI 客服任务的开发知识、调试经验和架构导引。运行中的 DeepSeek 客服不直接读取本目录。

## Codex 开发入口

开发或排错时优先阅读：

1. `docs/WECHAT_AI_CUSTOMER_SERVICE_OPTIMIZATION_GUIDE.md`
2. `docs/WECHAT_AI_CUSTOMER_SERVICE_IMPLEMENTATION_GUIDE.md`
3. `apps/wechat_ai_customer_service/README.md`
4. 本目录后续新增的任务专用经验文件

## 运行时业务知识入口

客服 workflow 和 DeepSeek advisory 应优先读取：

```text
apps/wechat_ai_customer_service/data/structured/manifest.json
```

再由 manifest 按 intent tags 选择需要的业务数据文件。

## 边界

- 通用 OmniAuto 能力经验进入 `knowledge/common/`、`knowledge/patterns/` 或 `knowledge/capabilities/`。
- 微信客服业务事实进入 `apps/wechat_ai_customer_service/data/structured/`。
- AI 生成的未审核候选进入 `apps/wechat_ai_customer_service/data/review_candidates/pending/`。
- 本目录只放任务开发导引和已确认经验，不放客户隐私和未审核业务事实。

