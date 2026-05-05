# 受控 DeepSeek 真人化回复优化报告 2026-05-03

## 目标

让 `deepseek-v4-pro` 更充分参与微信智能客服回复：能理解真实客户口语、上下文追问和RAG经验，回复更像真人销售；同时不能突破价格、库存、金融、车况、合同、售后、试驾/到店等边界。

## 已落地

- DeepSeek综合回复提示词升级：强调真实微信表达、RAG一等参与、上下文指代、少模板腔、严禁编造承诺。
- 高风险场景不再统一替换成旧模板；如果DeepSeek给出的转人工解释通过守卫，会保留自然文案。
- 旧式转人工模板被质量守卫拦截；兜底文案改为更自然的“不能直接替您拍板，交给负责同事核实”。
- DeepSeek调用增加受控重试，覆盖 `IncompleteRead`、timeout、429、5xx 等瞬时错误，审计记录 attempt/max_attempts。
- 知识匹配修正：普通“偶尔跑高速”不会误触“试驾安全”边界，只有明确试驾/试乘/开一圈等才触发。
- 边界守卫加强：自动回复中承诺试驾/试乘/预约，或承诺销售/同事/顾问后续联系、安排、对接时，自动改为 handoff。

## 覆盖测试

- 离线DeepSeek矩阵：13个二手车场景通过。
- 覆盖：家庭预算推荐、GL8商务接待、新能源电池边界、置换、看车预约、贷款包过、最低价、事故水泡火烧、合同发票异常、未知库存、无关请求、凯美瑞/雅阁上下文追问。
- 质量门：`formulaic_reply_count=0`。
- 回归：`run_llm_reply_synthesis_checks.py` 5/5，`run_workflow_logic_checks.py` 13/13，`run_rag_boundary_checks.py` 9/9，`run_knowledge_runtime_checks.py` 13/13，compileall通过。

## 当前阻塞

代表性 File Transfer Assistant 实盘测试未完成，原因不是微信或代码，而是 DeepSeek 返回：

```text
HTTP 402 Insufficient Balance
```

需要给 DeepSeek API 账户恢复余额，或配置可用的新API Key，然后重新运行：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_jiangsu_chejin_llm_synthesis_checks.py --live-wechat --delay-seconds 2.5
```

通过后即可把本轮目标标记为可交付。
