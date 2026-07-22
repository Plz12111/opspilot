# 调查引擎

## 当前能力

第一版调查引擎采用显式 LangGraph 状态图：

```text
START -> plan -> execute --+-> synthesize -> END
                  ^        |
                  +--------+
```

计划固定包含两次指标查询、一次日志查询、一次 Trace 查询和一次 Runbook 检索。固定计划是可评测基线，后续模型规划器必须与它对照，不能只展示成功案例。

## 工具边界

| 工具 | 数据源 | 当前操作 |
| --- | --- | --- |
| `query_metrics` | Prometheus HTTP API | 时间范围查询 |
| `query_logs` | Loki HTTP API | LogQL 时间范围查询 |
| `query_traces` | Jaeger HTTP API | 按服务和时间查询 Trace |
| `search_runbooks` | Runbook 混合检索 | 关键词/向量检索与 RRF 重排 |

工具网关统一执行工具白名单、参数 Schema、超时、错误标准化和证据长度限制。工具只返回带 ID 的 Evidence，结论通过 Evidence ID 引用来源。

## 状态与预算

每次运行保存：计划、下一步、工具执行、证据、状态、步骤预算和诊断。默认预算为 6，当前基线计划使用 5 步。预算不足时状态为 `BUDGET_EXHAUSTED`，Incident 转入 `NEEDS_HUMAN`。

确定性总结器不会宣称已经找到根因，只总结数据源覆盖情况和失败工具。这避免在接入真实模型前制造虚假的智能效果。

## API

```text
GET  /api/v1/incidents/{incident_id}
POST /api/v1/incidents/{incident_id}/investigate
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs/{run_id}/events
```

`POST /investigate` 默认立即返回 `202 Accepted` 和运行 ID。`wait=true` 会等待终态并返回 `201 Created`，仅用于本地调试和确定性集成测试。

## 持久化任务与恢复

调查创建与执行已经分离：

```text
HTTP create -> InvestigationRun(PENDING) + InvestigationJob(PENDING)
            -> coordinator schedule -> RUNNING -> terminal state
application startup -> recover PENDING/RUNNING jobs
```

本地版本使用进程内协调器执行，但任务所有权和状态保存在数据库，不依赖内存队列保证恢复。优雅停机时正在执行的协程会被取消，任务保留为 `RUNNING`，下一次启动会重新执行。若运行已经进入终态，恢复器只修正任务状态，不重复执行工具。

这一实现面向单实例演示环境。扩展到多实例时，应使用数据库行锁或外部队列实现租约与抢占，现有 `InvestigationJob` 契约可以保持不变。

## 实时事件

每个运行按严格递增序号保存以下事件：

- `run.queued`、`run.started`
- `plan.created`
- `tool.started`、`tool.completed`
- `synthesis.completed`
- `run.completed` 或 `run.failed`

SSE 端点会先回放已持久化事件，再等待新事件，并在终态事件后关闭。客户端可使用 `Last-Event-ID` 请求头或 `after` 查询参数从指定序号继续，断线不会丢失调查轨迹。
