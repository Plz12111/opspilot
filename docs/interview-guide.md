# OpsPilot 简历与面试讲解

## 简历项目描述

### 三行版本

**OpsPilot - 证据驱动 AI SRE Incident Agent｜Python / FastAPI / LangGraph / PostgreSQL**

- 设计可恢复的 Agent 调查状态图与安全工具网关，统一接入 Prometheus、Loki、Jaeger 和 Runbook RAG，通过 Evidence ID 与 CitationValidator 约束诊断引用。
- 实现 Alertmanager/飞书幂等接入、数据库 Job 恢复、SSE 事件回放及人工审批修复链路；服务端禁止 production、自审批和未授权动作，评测中危险动作率为 0%。
- 构建 80 案例/10 根因离线评测集与同数据摘要对照实验，将 Top-1 从 67.5% 提升至 93.8%（+26.2pp），Top-3 97.5%，引用有效率 100%，三次运行一致性 100%。
- 实现原子告警合并、调查幂等键与修复 exactly-once，构建 6 场景并发/故障测试；Docker 50 并发共 415 请求全部通过，订单链路基线 721.59 RPS、P95 94.86 ms。

### 单行精简版本

独立开发 AI SRE Incident Agent，完成告警去重、LangGraph 调查、Metrics/Logs/Traces/Runbook 工具、证据引用、任务恢复、飞书审批和 80 案例评测；同数据集 Top-1 由 67.5% 提升至 93.8%，危险动作率 0%。

不要写“生产落地”“自动修复线上集群”或“真实 LLM 成本降低 30%”。当前仓库没有这些证据。

## 60 秒项目介绍

> 我做的是 OpsPilot，一个面向微服务故障响应的 Agent。它解决的不是聊天，而是告警之后如何可靠地完成一段长流程：先对 Alertmanager 事件去重，再由 LangGraph 按预算调用 Prometheus、Loki、Jaeger 和 Runbook 工具，工具结果统一成 Evidence，诊断必须引用 Evidence ID。调查任务和事件都落 PostgreSQL，所以请求可以先返回 202，前端通过 SSE 看进度，应用重启还能恢复。修复动作不由模型直接执行，而是经过环境和动作白名单、人工审批、禁止自批、过期和幂等检查。为了证明优化有效，我做了 80 个固定案例，v2 在相同数据摘要上把 Top-1 从 67.5% 提升到 93.8%，并保留失败案例。当前在线总结器和执行器都是保守的可替换基线，我会明确说明边界。

## 五层讲解结构

1. **业务问题**：值班人员在多个观测与协作系统间切换，判断慢且缺少统一证据链。
2. **Agent 工作流**：显式状态图、步骤预算、结构化工具、Evidence、引用校验。
3. **可靠性**：Job 落库、启动恢复、SSE replay、告警与飞书幂等、Outbox。
4. **安全性**：模型只提议，服务端策略与人工审批决定执行，production 永久禁用。
5. **可验证性**：同数据集摘要、确定性评分、失败案例、稳定性和成本代理。

## 高频追问

### 为什么用 LangGraph，不自己写循环？

状态图把计划、执行、总结和终态变成显式节点，便于限制预算、保存状态、插入人工中断和评测节点。简单循环也能完成当前固定计划，但随着恢复和人工审批加入，图的边界更容易测试和解释。

### 这算真正的 Agent 吗？

它具备状态、目标、工具调用、环境反馈、预算和终态判断，但在线默认规划与总结是确定性基线。这样做是为了先验证系统可靠性和评测方法，再接模型 Provider。不能把“用了 LangGraph”直接等同于智能程度。

### 为什么没有直接接大模型？

直接接模型容易得到漂亮但不可复现的 Demo。我先固定工具契约、Evidence、引用校验和 80 案例评测。接入模型时只替换 `StructuredDiagnosisProvider`，然后在同一数据集比较准确率、成本、延迟和波动，不改安全策略。

### Top-1 为什么能提升 26.2pp？

v1 对所有来源等权，通用 Runbook 文本容易压过实时证据。v2 提高 Metrics、Logs、Traces 权重，降低通用 Runbook 权重，并奖励跨来源佐证。两者使用相同数据摘要和相同工具轨迹，因此差异来自排序策略。

### 93.8% 是否过拟合？

存在这个风险。数据集是录制且根因类别有限，因此该指标只代表当前数据分布，不代表生产泛化能力。仓库保留五个 Top-1 失败案例，并加入噪声、缺失遥测和工具失败。下一步应增加时间外切分、未知根因和真实事故回放。

### 为什么数据库而不是 Redis/Kafka 保存任务？

当前是单实例作品集，数据库已经承担系统记录，使用 Job 表可以用较低复杂度实现恢复与审计。多实例会需要租约、行锁或外部 worker，但领域契约不需要推倒重来。没有吞吐证据时引入 Kafka 只会增加演示和部署成本。

### SSE 为什么不使用 WebSocket？

调查进度是服务端单向事件流，SSE 原生支持事件 ID、浏览器重连和代理友好语义。审批等命令仍走普通 HTTP，职责更清楚。

### 如何防 Prompt Injection？

Runbook、日志和 Trace 都标为不可信数据；模型只看到裁剪后的 Evidence；输出必须符合 Pydantic Schema；引用只能来自本次 Evidence。更关键的是模型没有 Shell 和执行凭据，高风险动作由确定性策略与审批服务控制。

### 如何保证不会重复执行修复？

提议有 idempotency key，审批表与执行表对 action ID 有唯一约束，同进程使用按动作锁，执行前再次查询状态。重复请求返回已有结果或冲突。多实例下仍需要数据库锁和执行端幂等共同保证。

### 工具挂了怎么办？

Tool Gateway 把超时和异常转换为结构化执行结果，图继续运行剩余工具。总结器降低置信度并列出失败工具；证据不足时 Incident 转入 `NEEDS_HUMAN`，不制造根因。

### 高并发下如何避免重复 Incident、Run 和修复执行？

进程内锁只能减少冲突，数据库约束才是最终一致性边界。Incident 使用活跃去重键和告警事件唯一键，计数通过数据库表达式原子递增；Investigation Run 使用客户端幂等键唯一约束；Action、Approval、Execution 分层唯一，执行前再加行锁。50 并发、415 请求的 Docker 测试会直接校验这些业务不变量，而不是只看成功率。

### 如果部署到生产还缺什么？

真实身份认证与 RBAC、Secret 管理、多实例任务租约、真实模型 Provider、生产级 OpenTelemetry、供应商成本数据、备份恢复、限流、Kubernetes 执行适配器和更大规模真实事故回放。当前 production 修复明确禁用。

## 代码讲解入口

| 主题 | 文件 |
| --- | --- |
| Agent 状态图 | `src/opspilot/agent/graph.py` |
| 结构化状态与 Evidence | `src/opspilot/agent/models.py` |
| 引用校验与模型接口 | `src/opspilot/agent/synthesis.py` |
| 工具网关 | `src/opspilot/tools/gateway.py` |
| 持久任务恢复 | `src/opspilot/services/investigation_coordinator.py` |
| 调查结果持久化 | `src/opspilot/services/investigations.py` |
| 修复策略 | `src/opspilot/remediation/policy.py` |
| 审批与幂等执行 | `src/opspilot/remediation/service.py` |
| 离线基线 | `src/opspilot/evaluation/baseline.py` |
| 对照实验 | `src/opspilot/evaluation/experiment.py` |

## 面试演示纪律

- 先讲问题和工程边界，再展示技术栈。
- 用失败案例或依赖降级证明系统不是只走成功路径。
- 指标同时说明数据集范围和局限，不把离线结果外推为生产 SLA。
- 被问到未实现能力时直接说明扩展接口和缺失验证，不临场扩大项目范围。
- 能现场运行 `make test`、`make eval`、`make demo-seed`，比展示静态截图更有说服力。
