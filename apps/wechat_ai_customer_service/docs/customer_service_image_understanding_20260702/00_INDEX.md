> [!WARNING]
> **文档状态：旧架构索引已废止（2026-07-18）。** 本文包关于图片落盘、截图裁切、`image-save`、Sidecar 图片入口以及散落 `customer_image_*` 流水线的实施方案不得继续开发。原始需求和历史证据仅供复盘；现行唯一方案是 [完全独立图像识别模块改造方案](../customer_service_absolute_independent_vision_module_refactor_plan_20260718.md)。

> Customer-service development baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md).

# 微信智能客服识图方案索引

本文档包用于在 `apps/wechat_ai_customer_service` 落地“客户发图识别 + 商品库匹配 + Brain First 回复”能力。

核心决策已经冻结：

- 采用“专用识图模块 -> 结构化结果 -> Brain”路线。
- 当前仓库已有 `customer_image_*` 识图流水线，这是唯一识图流水线；后续只在这条流水线上扩展，不另起第二套识图模块。
- 新增的 `wechat_image_save_capture.py` 只负责把微信真实图片保存成本地资产，是采集适配器，不调用 LLM、不做商品匹配、不给 Brain 传消息、不生成客户回复。
- 保持现有主结构冻结，不重写现有 Brain / history / evidence 主链路。
- 不把识图模块做成客户可见回复 owner。
- 不把图片 OCR 或识图摘要粗暴塞进普通文本 history。
- `customer_service_brain` 仍然是唯一客户可见回复作者。
- V1 只允许三处旧代码窄接点改动：
  - 图片消息从“自动忽略”改成“转交识图模块”
  - 给 Brain 增加一个最小可选内部桥接参数
  - 给 Win32 OCR sidecar 增加 `image-save` 图片保存 action
- 非识图链路零影响：没有图片信号时，普通文字客服、发送、商品库、RAG、学习、云门禁、录音、加好友等路径必须保持旧行为。

## 文档清单

- [01_REQUIREMENTS_AND_ARCHITECTURE.md](01_REQUIREMENTS_AND_ARCHITECTURE.md)
  目标、边界、模块职责、分层架构和阶段策略。
- [02_DATA_AND_INTERFACE_CONTRACT.md](02_DATA_AND_INTERFACE_CONTRACT.md)
  数据契约、接口清单、事件字段、配置字段和样例结构。
- [03_PRECODE_FILE_LIST_AND_IMPLEMENTATION_CHECKLIST.md](03_PRECODE_FILE_LIST_AND_IMPLEMENTATION_CHECKLIST.md)
  代码清单、改动范围、预创建文件、实施顺序和落代码前检查项。
- [04_TEST_ACCEPTANCE_AND_AUDIT_PLAN.md](04_TEST_ACCEPTANCE_AND_AUDIT_PLAN.md)
  单测、集成、验收、性能和审计计划。
- [05_ALCHEMYOS_DOUBAO_REFERENCE_AUDIT.md](05_ALCHEMYOS_DOUBAO_REFERENCE_AUDIT.md)
  `D:\AI\AlchemyOS` 参考审计、可复用经验和不可直接照搬部分。
- [06_WECHAT_IMAGE_SAVE_CLOSED_LOOP_DESIGN.md](06_WECHAT_IMAGE_SAVE_CLOSED_LOOP_DESIGN.md)
  微信端“点开会话 + 保存微信压缩图 + 识图 + Brain 回复”闭环设计、接口清单、测试清单和审计结论。
- [07_BRAIN_PREFLIGHT_LIGHTWEIGHT_PLUGIN_DESIGN.md](07_BRAIN_PREFLIGHT_LIGHTWEIGHT_PLUGIN_DESIGN.md)
  Brain 轻量 Preflight 外挂增强设计：用 LLM 判断证据需求，防止图片车型线索被低权威快路径跳过。

## 样例文件

- [examples/customer_image_understanding_request.example.json](examples/customer_image_understanding_request.example.json)
- [examples/customer_image_understanding_result.example.json](examples/customer_image_understanding_result.example.json)
- [examples/brain_visual_bridge_input.example.json](examples/brain_visual_bridge_input.example.json)
- [examples/customer_image_understanding_config.example.json](examples/customer_image_understanding_config.example.json)
- [examples/brain_preflight_output.example.json](examples/brain_preflight_output.example.json)

## 建议实施顺序

1. 先复核并复用既有 `customer_image_*` 识图流水线。
2. 对微信真实图片消息优先落地 `06_WECHAT_IMAGE_SAVE_CLOSED_LOOP_DESIGN.md` 中的直接保存闭环。
3. 把保存结果接入既有 `customer_image_asset_store.py`，统一产出 `saved_image_path` 资产。
4. 沿用既有 `customer_image_understanding -> customer_image_catalog_assist -> customer_image_brain_bridge -> customer_service_brain` 链路。
5. 在 `customer_service_brain` 内接入 `07_BRAIN_PREFLIGHT_LIGHTWEIGHT_PLUGIN_DESIGN.md`，让视觉车型线索先补齐商品库证据，再交给 Brain 生成回复。
6. 最后补审计、回归测试和 live 验收脚本。

## 当前结论

- 当前代码库的 Brain 主链路是纯文本中心，直接让 Brain 多模态看图会牵涉大量核心路径，不符合“主结构冻结”的边界。
- 专用识图模块方案更符合现有 Brain First 架构，也更适合复用 `AlchemyOS` 中“文本模型和多模态模型分路、独立 key、独立 timeout、独立审计”的实践经验。
- 本次设计包的目标是“代码开工前边界冻结”，不是在文档阶段引入任何客户可见回复的新 owner，也不是重构现有 Brain 结构。
