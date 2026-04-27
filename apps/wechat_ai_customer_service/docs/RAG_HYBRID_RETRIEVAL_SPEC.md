# RAG 混合检索规格

## 设计目标

当前 RAG 检索是离线安全的词法检索。本轮不引入数据库或外部向量库，而是在本地索引中增加轻量语义项和重排评分，使它更接近企业 RAG 常用的“关键词 + 语义 + 重排”结构。

## 查询处理

查询进入检索前会构造 query profile：

- 原始问题。
- 归一化文本。
- token 集合。
- 业务同义扩展。
- 轻量语义项。

同义扩展示例：

- 公寓、民宿、酒店、酒店公寓。
- 预留电源、供电方式、电池、外接电源。
- 型号怎么看、型号命名、型号说明。
- 安装前、门厚、开孔、开门方向。

## 索引条目

每个 chunk 在索引中包含：

- `terms`：词法 token。
- `semantic_terms`：扩展后的轻量语义项。
- `risk_terms`：风险词。
- 原有 source、category、product_id、text 等字段。

## 评分结构

每条 hit 返回：

```json
{
  "score": 0.82,
  "retrieval_mode": "hybrid_lexical_semantic",
  "scoring": {
    "lexical": 0.42,
    "semantic": 0.2,
    "phrase": 0.08,
    "product": 0.15,
    "boost": 0.04,
    "risk_penalty": 0,
    "final": 0.89
  }
}
```

注意：`score` 只表示检索相关性，不代表可以自动承诺。

## 安全边界

RAG 检索可以命中风险资料，但 RAG 应答层必须继续阻断：

- 最低价
- 账期
- 月结
- 赔偿
- 退款
- 合同
- 盖章
- 安装费
- 先发货
- 虚开发票

## 后续可升级点

后续如果要接企业级向量库，应保持当前接口不变：

- `RagService.search(...)`
- `RagService.evidence(...)`
- hit 的 `scoring`
- hit 的 `risk_terms`
- `rag_can_authorize=false`

这样可以把底层检索从本地轻量语义替换成真正 embedding + reranker，而不影响上层工作流。
