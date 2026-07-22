# Runbook RAG

## 数据流程

```text
Markdown -> heading-aware chunks -> tokens + embeddings -> PostgreSQL
                                                        |
Query -> keyword ranking + vector ranking -> RRF -> metadata/heading rerank -> Evidence
```

## 当前基线

- 使用 Markdown token 结构识别标题和正文，不按固定行数盲切。
- 分块最大 1200 字符、150 字符重叠。
- 英文词与中文字符/二元词组共同参与关键词检索。
- BM25 风格分数与余弦相似度分别排序，再使用 RRF 融合。
- 服务、环境和标题命中参与最后重排。
- 默认哈希向量可离线复现，仅作为工程与评测基线。

生产版本可将 `EmbeddingProvider` 替换为语义 embedding 服务，并把向量查询下推到 pgvector；导入、检索结果和 Agent 工具契约不需要改变。

## 引用约束

Runbook 检索结果转换为 `source_type=runbook` 的 Evidence，包含文档 URI、chunk ID、标题、章节、融合分数和内容校验和。

所有总结器生成的 `evidence_ids` 都经过服务端验证：

- 引用未知 Evidence ID 时拒绝保存诊断。
- 置信度高于 0.4 时必须至少引用一条证据。
- 模型只接收本次调查允许引用的证据集合。

## API

```text
POST /api/v1/runbooks
GET  /api/v1/runbooks/search?q=...&service=...&environment=...&top_k=5
```

## 离线评测

固定案例位于 `evals/runbooks/cases.json`，评测器计算 Recall@K 和 MRR。当前四案例基线在 Top-3 下达到 Recall 1.0、MRR 1.0；数据集规模很小，只用于防止工程回归，不能作为真实生产效果结论。
