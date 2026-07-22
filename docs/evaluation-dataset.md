# 评测集构造与评分口径

## 目标

OpsPilot 的评测集用于比较 Agent 规划、证据选择和根因排序的改动，不用于训练模型。所有候选版本必须使用相同案例摘要和录制工具轨迹，避免通过更换数据获得虚假的指标提升。

## 数据来源与组成

数据集位于 `evals/incidents/`：

- `cases-v1.json`：30 个手工策划案例，用于定义故障类别、关键证据和噪声边界。
- `build_dataset.py`：确定性变体生成器，不调用模型或外部服务。
- `cases.json`：最终 80 个案例，由 30 个策划案例和 50 个系统化变体组成。

覆盖的 10 类根因包括：

1. Inventory 依赖不可用；
2. Inventory 高延迟；
3. 数据库连接池耗尽；
4. Redis 缓存雪崩；
5. 错误版本发布；
6. 内存泄漏；
7. 网络分区；
8. TLS 证书过期；
9. 限流配额耗尽；
10. 磁盘空间耗尽。

## 案例 Schema

每个案例至少包含：

| 字段 | 含义 |
| --- | --- |
| `id` / `title` | 稳定案例标识和可读标题 |
| `service` / `environment` | 事故上下文 |
| `expected_root_cause` | 确定性评分使用的标准根因 |
| `expected_evidence_ids` | 必须被诊断引用的关键证据 |
| `observations[]` | 录制的工具名、来源类型、内容和调用轮次 |
| `failed_tools[]` | 模拟不可用或超时的数据源 |
| `prohibited_actions[]` | 当前场景禁止建议的修复动作 |

Pydantic 在评测开始前验证 Schema，并确保关键 Evidence ID 确实存在于录制观测中。

## 变体生成矩阵

生成器为每类根因构造五种固定变体：

| 变体 | 目的 |
| --- | --- |
| `corroborated` | Metrics 与 Logs 等多来源证据相互佐证 |
| `single-log` | 只有一个强日志信号，测试最低证据条件 |
| `runbook-noise` | 实时证据与误导性历史 Runbook 同时存在 |
| `telemetry-gap` | 部分遥测工具失败，测试降级能力 |
| `ambiguous-noise` | 当前信号与其他根因噪声混合 |

生成过程是确定性的，因此同一版本的 `build_dataset.py` 始终得到相同案例集合。数据集规范化后计算 SHA-256；摘要不同的两次实验不得直接比较。

## 回放与评分

```text
Recorded observations -> ToolGateway -> LangGraph InvestigationRunner
                      -> Diagnosis baseline -> CitationValidator
                      -> Deterministic graders -> JSON / Markdown
```

录制适配器只替换 Prometheus、Loki、Jaeger 和 Runbook 外部请求，其余 Tool Gateway、步骤预算、Evidence 建模、引用校验及 Agent 状态图均复用线上代码。

评分指标包括：

- Root Cause Top-1 accuracy；
- Root Cause Top-3 recall；
- Citation validity；
- Critical evidence recall；
- Tool success rate；
- Prohibited action rate；
- 三次重复运行的 Top-1/Top-3 一致性。

## 防止指标失真

- v1/v2 使用相同 `cases.json` 和相同工具轨迹。
- 报告保留全部失败案例，不删除错误预测。
- 评分器使用标准根因与 Evidence ID 做确定性判断，不使用 LLM-as-a-Judge 作为核心指标。
- 成本仅用 `evidence_chars / 4` 估算输入 Token，用于相对比较，不声明为供应商真实账单。
- 当前数据是录制案例且类别有限，93.8% Top-1 只代表该分布，不外推为生产泛化能力。

## 复现

```bash
make eval-dataset
make eval
```

生成报告：

- `evals/reports/incident-baseline.json`
- `evals/reports/incident-baseline.md`
- `evals/reports/incident-comparison.json`
- `evals/reports/incident-comparison.md`
