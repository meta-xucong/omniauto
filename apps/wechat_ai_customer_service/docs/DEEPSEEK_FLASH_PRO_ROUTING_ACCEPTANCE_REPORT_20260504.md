# DeepSeek Flash/Pro 分流与成本控制验收报告 2026-05-04

## 结论

本轮已经把微信智能客服的 DeepSeek 调用从“尽量都用 Pro”调整为“质量优先的 Flash/Pro 双模型体系”：

- 常规客服回复、自然语言理解、一般商品推荐、软性比较、置换流程说明等场景默认走 `deepseek-v4-flash`。
- 高风险边界、强承诺、金融/发票/合同/售后、必须转人工、RAG 作为唯一权威依据的回答、正式知识生成、RAG 经验解释、共享公共知识判断等场景继续走 `deepseek-v4-pro`。
- 成本控制已经加入，但默认不牺牲回复质量。系统仍会优先保证不乱答、不越界、不绕过人工确认链路。

代表性离线测试和微信“文件传输助手”实盘测试均已通过，可以进入用户验收。

## 模型分工

### Flash 负责的场景

这些场景需要自然表达和一定理解能力，但风险相对可控，适合用 Flash 降低日常成本：

- 微信智能客服的最终自然回复合成。
- 客户意图辅助判断。
- 常规商品咨询，例如预算、车型、用途、库存初筛。
- 软性比较，例如“GL8 和奥德赛哪个更适合商务接待”。
- 置换流程、资料准备、看车前沟通等非承诺型流程说明。
- 完全无关问题的礼貌拒答或转人工提示。

Flash 路径仍然会读取正式知识、商品库、RAG 经验和近期上下文。它不是回到关键词模板，而是在现有证据包上做受控表达。

### Pro 负责的场景

这些场景继续使用 Pro，避免因为省 token 降低判断质量：

- 金融、贷款、分期、最低价、包过、合同、发票、售后、事故/水泡/火烧等高风险内容。
- 自动回复中可能形成承诺的场景，例如预约试驾、安排销售联系、保证车况、保证价格。
- 需要转人工、必须转人工、证据不足但用户要求明确结论的场景。
- 只有 RAG 经验能支持、缺少正式结构化知识兜底的权威回答。
- 资料导入后的知识抽取、RAG 经验解释、候选知识生成。
- customer 正式知识向共享公共知识候选池的提炼。
- 服务端共享公共知识候选的 AI 辅助审核建议。

一句话规则：能影响客户决策、交易承诺、合规边界、知识入库质量的地方，用 Pro；普通沟通表达和低风险理解，用 Flash。

## 成本控制

本轮已加入 5 类控制，并保持“质量第一，成本第二”：

1. 模型分流：常规回复走 Flash，高风险和知识决策走 Pro。
2. 证据包压缩：Flash/Pro 分别有更紧凑的 evidence profile，减少无关上下文进入提示词。
3. 调用审计：回复审计里记录 `model_tier`、`model`、`prompt_estimate`、`llm_usage`，便于后续核算 token。
4. 测试降重：新增 `--live-only`，实盘测试时不再重复跑一遍完整离线大模型矩阵。
5. 单轮调用上限：支持 `max_llm_calls_per_run`，防止异常测试或循环逻辑把接口打爆。

另有“确定性跳过 LLM”的配置，但默认关闭。原因是你明确要求不能明显降低回复质量，所以该选项只适合临时排障或极端节流，不作为常规运行策略。

## 已验证结果

### 静态与配置检查

```powershell
.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\llm_config.py apps\wechat_ai_customer_service\workflows\llm_reply_synthesis.py apps\wechat_ai_customer_service\workflows\reply_evidence_builder.py apps\wechat_ai_customer_service\workflows\customer_intent_assist.py apps\wechat_ai_customer_service\workflows\generate_review_candidates.py apps\wechat_ai_customer_service\admin_backend\services\knowledge_generator.py apps\wechat_ai_customer_service\admin_backend\services\rag_experience_interpreter.py apps\wechat_ai_customer_service\tests\run_llm_reply_synthesis_checks.py apps\wechat_ai_customer_service\tests\run_jiangsu_chejin_llm_synthesis_checks.py apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
```

结果：通过。

```powershell
.\.venv\Scripts\python.exe -m json.tool apps\wechat_ai_customer_service\configs\default.example.json
```

结果：通过。

### 聚焦逻辑测试

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_llm_reply_synthesis_checks.py
```

结果：6/6 通过，覆盖 Flash/Pro 分流、调用审计和保护规则。

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_llm_reply_synthesis_deepseek_probe.py
```

结果：真实 `deepseek-v4-flash` 调用通过，回复使用了正式商品证据和 RAG 经验。

### 二手车真实问题矩阵

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_jiangsu_chejin_llm_synthesis_checks.py
```

结果：13 个真实 DeepSeek 用例通过，覆盖：

- 家用预算推荐。
- GL8 商务接待。
- 新能源电池边界。
- 置换咨询。
- 看车预约边界。
- 贷款包过和最低价边界。
- 事故/水泡/火烧边界。
- 合同发票异常。
- 未知库存。
- 无关请求。
- 凯美瑞、雅阁等上下文追问。

质量指标：`formulaic_reply_count=0`，说明没有退回到旧式模板化回答。

### 回归测试

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_rag_boundary_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_knowledge_runtime_checks.py
.\.venv\Scripts\python.exe -m compileall -q apps\wechat_ai_customer_service\workflows apps\wechat_ai_customer_service\admin_backend apps\wechat_ai_customer_service\vps_admin apps\wechat_ai_customer_service\tests apps\wechat_ai_customer_service\llm_config.py
```

结果：全部通过。

### 微信实盘测试

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\workflows\preflight.py --target 文件传输助手 --json
```

结果：微信在线，当前账号 `Meta_xc`，文件传输助手可见。

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_jiangsu_chejin_llm_synthesis_checks.py --live-wechat --live-only --delay-seconds 2.5
```

结果：3/3 通过。

- 2 条正常咨询使用 Flash 生成可发送回复。
- 1 条金融/最低价敏感咨询使用 Pro 并转人工。
- 未出现旧模板化回复。
- 未出现越界承诺。

## 与上一轮 Pro 全量调用相比

上一轮调试中 token 消耗高，主要原因是：

- 大量测试矩阵反复调用真实 DeepSeek。
- 当时正常回复也倾向使用 Pro。
- 实盘测试前还会先跑离线预检，形成重复调用。
- RAG 证据包偏大，部分问题会带入较多上下文。

本轮调整后，日常运行不会像调试阶段那样密集烧 token。正常客户消息主要走 Flash，高风险和知识决策才走 Pro。不过它仍然是“充分使用 LLM 的客服系统”，不是零成本关键词系统，所以后续应通过审计数据持续观察真实业务流量下的成本。

## 运维建议

上线或长测时建议关注三类数据：

- `model_tier`：正常咨询应以 `flash` 为主，高风险和知识决策应看到 `pro`。
- `llm_usage`：观察输入 token 是否异常偏大，若偏大优先压缩 RAG/历史证据包。
- `handoff_reason`：若大量普通问题被转人工，说明证据匹配或提示词边界过紧；若高风险问题没有转人工，则必须优先修复。

可配置项：

- `DEEPSEEK_FLASH_MODEL`：默认 `deepseek-v4-flash`。
- `DEEPSEEK_PRO_MODEL`：默认 `deepseek-v4-pro`。
- `DEEPSEEK_MODEL`：兼容旧配置，默认视为 Pro 路径。
- `llm_reply_synthesis.model_routing`：控制回复合成的分流规则。
- `llm_reply_synthesis.cost_controls`：控制单轮调用上限、审计、可选节流。

## 交付状态

当前状态：可交付。

仍建议在正式客户演示前保留一轮短观察：让二手车账号持续接收一小批真实口语化问题，检查 `model_tier`、`llm_usage`、转人工原因和用户可读回复质量。若没有异常，即可作为当前版本基线。
