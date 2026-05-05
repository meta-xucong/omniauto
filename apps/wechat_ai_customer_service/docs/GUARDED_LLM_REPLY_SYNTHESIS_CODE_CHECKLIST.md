# 受控 LLM 客服综合回复代码落地清单

## 1. 文档

- [ ] 完成开发文档。
- [ ] 完成代码清单。
- [ ] 完成拟人化二手车问题测试材料。

## 2. 运行时模块

- [ ] 新增 `reply_evidence_builder.py`。
- [ ] 新增 `llm_reply_synthesis.py`。
- [ ] 新增 `llm_reply_guard.py`。
- [ ] 证据包包含 RAG 命中明细。
- [ ] 证据包包含最近聊天上下文。
- [ ] 证据包包含现有规则回复和安全判断。
- [ ] LLM 输出经过结构化校验。
- [ ] 安全 guard 阻止 RAG 独立授权敏感承诺。
- [ ] 安全 guard 阻止模型覆盖现有 handoff。

## 3. 主链路接入

- [ ] 在 `listen_and_reply.py` 中新增可选 hook。
- [ ] hook 位于现有规则/RAG/旧 LLM advisory 之后。
- [ ] hook 位于最终发送/人工兜底之前。
- [ ] 配置关闭时旧逻辑不变。
- [ ] LLM 失败时旧逻辑不变。
- [ ] unsafe 时旧逻辑或人工兜底接管。

## 4. 配置

- [ ] `default.example.json` 新增 `llm_reply_synthesis`。
- [ ] 本地客服控制台开关能同步启停 synthesis。
- [ ] DeepSeek 默认模型继续使用 `deepseek-v4-pro`。
- [ ] 支持 `manual_json` 供离线测试。

## 5. 测试

- [ ] 新增离线综合回复测试。
- [ ] 测试证明 RAG 参与 prompt。
- [ ] 测试证明 RAG 不能越权承诺。
- [ ] 测试自然语言二手车问法。
- [ ] 测试多轮上下文。
- [ ] 测试模型非法输出回退。
- [ ] 测试 LLM 关闭时旧路径不变。
- [ ] 运行 `py_compile`。
- [ ] 运行 focused workflow checks。
- [ ] 运行 RAG boundary checks。
- [ ] 运行 used-car checks。
- [ ] 离线全部通过后再进入实盘测试。

