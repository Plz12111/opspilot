# Incident Workspace

工作台入口为 `http://127.0.0.1:8000/`，直接读取 OpsPilot API 和数据库状态。

## 主要视图

- Incident 列表与状态筛选。
- 当前事故诊断、置信度、引用数和调查步骤。
- 调查排队、计划、工具执行、综合和终态的实时事件时间线。
- Evidence 来源、内容与 Runbook 引用。
- Runbook 混合检索。
- 修复动作提议、审批、拒绝和执行。
- 活跃事故、等待人工、待审批动作和 Runbook 数量摘要。

## 聚合 API

```text
GET /api/v1/dashboard/summary
GET /api/v1/incidents
GET /api/v1/incidents/{incident_id}/workspace
GET /api/v1/runs/{run_id}/events
```

工作台是面向值班工程师的操作界面，不保存独立业务状态。开始调查后，页面立即连接 SSE 并显示 LIVE 状态；终态事件到达后自动刷新完整诊断和 Evidence。刷新页面后所有内容都从后端重新读取，活动运行会从最后已知事件序号继续订阅。
