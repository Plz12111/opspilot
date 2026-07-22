# Incident Agent 评测基线

## 目标

第 7-8 周评测里程碑用于建立可重复、可对照的 Agent 基线。它不是用测试数据证明模型“聪明”，而是固定数据集、执行路径和评分规则，让后续 Prompt、模型、RAG 或规划器改动都有同一参照物。

运行：

```bash
make eval
```

输出：

- `evals/reports/incident-baseline.json`：机器可读的完整指标和逐案例结果。
- `evals/reports/incident-baseline.md`：适合代码审查和作品集展示的报告。
- `evals/reports/incident-comparison.json`：两条基线、重复运行和成本数据。
- `evals/reports/incident-comparison.md`：对照实验摘要。

未达到门槛时报告仍会生成，但命令返回非零退出码，可直接作为 CI quality gate。

## 数据集

`evals/incidents/cases.json` 包含 80 个录制案例，覆盖 10 类根因。原始 30 个手工案例保存在 `cases-v1.json`，其余 50 个系统化变体由 `build_dataset.py` 生成：

- 库存依赖不可用、库存延迟。
- 数据库连接池耗尽、Redis 缓存雪崩。
- 错误发布、内存泄漏。
- 网络分区、证书过期。
- 限流配额耗尽、磁盘饱和。

案例保留多源佐证、单一日志、Runbook 噪声、歧义信号、缺失遥测和工具故障。每个案例显式声明标准根因、关键 Evidence ID、录制工具结果及禁止动作。Pydantic 校验确保标准证据一定存在于录制数据中。

重建数据集：

```bash
make eval-dataset
```

## 执行路径

```text
Recorded observations -> ToolGateway -> InvestigationRunner (LangGraph)
                      -> Keyword baseline -> CitationValidator
                      -> Deterministic graders -> JSON / Markdown report
```

评测复用生产调查状态图和工具网关。录制工具只替代外部 Prometheus、Loki、Jaeger 和 Runbook 服务，从而消除网络波动，又保留工具参数校验、调用状态、步骤预算、Evidence 和引用约束。

## 指标与门槛

| 指标 | MVP 门槛 | 说明 |
| --- | ---: | --- |
| Root cause Top-1 accuracy | >= 60% | 第一候选等于标准根因 |
| Root cause Top-3 recall | >= 80% | 前三候选包含标准根因 |
| Citation validity | >= 90% | 引用 ID 存在于本次工具证据 |
| Tool success rate | >= 95% | 工具执行状态为 SUCCESS 的比例 |
| Prohibited action rate | 0% | 建议中不得出现案例禁止动作 |
| Critical evidence recall | 仅报告 | 标准关键证据被诊断引用的比例 |

当前 baseline 是可解释的关键词签名排序器。报告必须保留所有失败案例，不允许只展示最好的一部分。数据集内容经规范化后生成 SHA-256；后续对照实验只有在摘要一致时才可直接比较。

## 第 8 周对照实验

对照组 `keyword-signature-v1` 对所有来源等权计分；候选组 `source-weighted-v2` 提高实时指标、日志和 Trace 的权重，降低通用 Runbook 文本权重，并奖励跨来源佐证。

两组使用完全相同的数据集和工具轨迹。候选组重复运行 3 次，报告 Top-1/Top-3 预测一致性及准确率区间。成本使用 `evidence_chars / 4` 估算输入 Token，并按每百万输入 Token 0.15 美元记录代理成本；该数值只用于同数据集相对比较，不替代真实供应商账单。
