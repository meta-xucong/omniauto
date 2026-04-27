# 智能知识摄入代码实现指导

## Chapter 1：统一摄入质检层

新增 `workflows/knowledge_intake.py`：

- 输入：`category_id`、schema、候选 item、原始文本、分类置信度。
- 输出：标准化后的 item 与 intake 报告。
- 职责：
  - 保留未知字段到 `additional_details`。
  - 检测缺失字段。
  - 生成补充问题。
  - 识别风险。
  - 给出 `ready` 或 `needs_more_info` 状态。

完成后先用直接 Python 断言验证商品缺价、政策完整、额外字段保留。

## Chapter 2：知识生成器接入质检层

改造 `knowledge_generator.py`：

- DeepSeek prompt 明确要求分类、缺失字段、额外信息保留。
- `normalize_data_for_schema` 不再丢弃未知字段，而是转入 `additional_details`。
- `_validate_generated_item` 改为调用统一质检层。
- session 增加 `intake` 报告，便于前端展示和调试。

完成后跑 generator 章节测试。

## Chapter 3：文件导入候选接入质检层

改造 `generate_review_candidates.py`：

- 所有候选在生成前进入质检层。
- 支持 `use_llm=true` 时调用 DeepSeek 按整份文件抽取多条候选；模型不可用或输出异常时自动退回确定性解析。
- LLM 候选必须通过来源锚定检查，原文中找不到依据的商品名、政策内容或话术需要被丢弃。
- TXT/MD 中的“商品资料 / 政策规则 / 客服话术 / ERP 记录”标签段落需要先按段拆分，再分别进入对应 builder。
- Excel/CSV 未知列进入 `additional_details`。
- 缺关键字段的候选仍写入 pending，但 `review.completeness_status=needs_more_info`。
- 内容门类明显与上传门类不一致时，以内容分类结果为准。

完成后增加文件导入测试：错误门类政策、缺价商品、额外列保留。

## Chapter 4：候选应用保护与前端提示

改造 `candidate_store.py` 和 `static/app.js`：

- `needs_more_info` 候选禁止应用。
- 候选列表显示“待补充”。
- 候选详情展示缺失字段、补充提示、风险提示。
- 可应用候选保持现有审核入库流程。

完成后跑 candidates 章节测试。

## Chapter 5：schema 与运行时证据适配

改造默认知识库 schema/resolver/compiler：

- `products/chats/policies/erp_exports` 增加 `additional_details` 字段。
- resolver 将 `additional_details` 加入匹配或回复字段。
- compiler 将商品/政策/话术的补充信息带入兼容缓存摘要。

完成后跑 knowledge runtime、compiler、admin 全量测试。

## Chapter 6：DeepSeek 边界兜底

改造 `customer_intent_assist.py`：

- 当 DeepSeek 已返回但不是合法 JSON，且启发式判断为 `approval_required` 或 `handoff_request` 时，生成合规的转人工候选。
- 当 DeepSeek 候选未通过 schema 校验，且启发式判断必须请示/转人工时，同样使用转人工兜底。
- 兜底候选必须保留 `needs_handoff=true`、`safe_to_auto_send=true`、`recommended_action=handoff_for_approval|handoff`。

完成后跑 workflow logic 与 DeepSeek boundary probe。

## Chapter 7：全量验证与交付

执行：

- `python -m compileall -q apps/wechat_ai_customer_service`
- `node --check apps/wechat_ai_customer_service/admin_backend/static/app.js`
- `python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter all`
- `python apps/wechat_ai_customer_service/tests/run_knowledge_runtime_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_knowledge_compiler_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`
- `python apps/wechat_ai_customer_service/tests/run_deepseek_boundary_probe.py`

通过后重启本地管理台服务，并更新 long-running task 状态。
