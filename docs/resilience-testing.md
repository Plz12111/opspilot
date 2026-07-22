# 高并发与韧性验证

## 验证目标

这套测试验证的是并发下的业务正确性，而不只是接口是否返回 2xx。测试通过公开 HTTP API 驱动完整 Docker Compose，覆盖 OpsPilot、PostgreSQL 和 `Gateway -> Order -> Inventory` 调用链。

核心不变量包括：

- 50 个相同告警只能创建一个 Incident，其余请求被识别为重复事件。
- 50 个不同 occurrence 必须合并到一个 Incident，`alert_count` 原子增加到 50。
- 200 个并发订单使用 20 个 `order_id` 时，只允许产生 20 个库存预留。
- 20 个相同 `Idempotency-Key` 的调查请求只能产生一个持久 Run 和 Job。
- 20 个并发提议、审批和执行请求只能产生一个 Action、Approval 和 Execution。
- Inventory 100% 故障时错误必须沿调用链稳定映射为 503；清除故障后请求恢复为 200。

## 运行方式

先启动完整环境，再执行正式或快速门禁：

```bash
make demo-up
make resilience-test
make resilience-quick
```

可用 `CONCURRENCY=100 make resilience-test` 调整并发度。测试开始前会验证三个服务的健康状态并清理上一次遗留的故障配置；故障注入阶段使用 `finally` 自动复位。

报告自动写入：

- `evals/reports/resilience-latest.json`：供 CI 和程序消费的结构化结果。
- `evals/reports/resilience-latest.md`：场景、RPS、P50/P95/P99、状态码与业务不变量。

进程退出码可直接作为 CI 门禁：任一传输错误、非预期状态码或业务不变量失败都会返回非零。

## 2026-07-22 Docker 实测

环境为 Docker Engine 29.6.1、ARM64，本机 50 并发正式测试共发送 415 个业务请求，六个场景全部通过。

| 场景 | 请求数 | RPS | P95 | 验证结果 |
| --- | ---: | ---: | ---: | --- |
| 重复告警风暴 | 50 | 233.12 | 213.26 ms | 1 Incident，49 duplicate |
| 不同告警合并 | 50 | 257.82 | 190.29 ms | `alert_count = 50` |
| 订单幂等风暴 | 200 | 721.59 | 94.86 ms | 20 order / 20 reservation |
| 调查幂等竞态 | 20 | 117.99 | 169.11 ms | 1 Run，达到终态 |
| 修复 exactly-once | 60 | 278.98 | 148.77 ms | 1 Action / 1 Execution |
| 依赖故障与恢复 | 35 | 614.07 | 45.65 ms | 30 次 503，复位后 5 次 200 |

压测完成后的 `docker stats --no-stream` 显示 OpsPilot 使用约 106 MiB 内存，PostgreSQL 约 57 MiB；应用、Gateway、Order、Inventory 日志中无 500、Traceback 或未处理异常。

PostgreSQL 会记录少量唯一约束冲突，这是高并发下由数据库作为最终串行化边界拦截重复写入，服务层捕获后重新读取已有记录并返回成功。它们不计为应用故障，但在生产告警规则中应与未处理数据库错误区分。

## 实现机制

### 告警合并

`active_dedupe_key` 和 `(source, external_id)` 唯一约束负责最终防重；服务在并发冲突时回滚并重试。已有 Incident 的计数使用数据库表达式 `alert_count = alert_count + 1`，避免读改写丢失更新。

### 调查创建

客户端通过 `Idempotency-Key` 标识一次逻辑调查，数据库唯一约束保证跨请求只存在一条 Run。冲突可能发生在 `flush` 或 `commit`，两条路径都会回滚并返回原 Run；相同键跨 Incident 使用返回 409。

### 修复执行

Action proposal 使用幂等键，Approval 和 Execution 分别对 `action_id` 唯一。执行前使用 `SELECT ... FOR UPDATE` 重新检查 Action 状态；重复执行返回原 Execution。生产环境仍被策略层禁止，压测只调用演示执行器。

### 故障隔离

Inventory 只暴露受 token 保护、参数有界的故障控制接口，不接受任意 Shell。Order 将上游 5xx 映射为 503，Gateway 保留该语义；复位之后以真实业务请求验证恢复，而不是只检查 health endpoint。

## 结果边界

本报告是单机 Compose 和单 OpsPilot 进程下的工程正确性与基线吞吐，不是生产容量承诺。当前协调器仍面向单实例；多副本部署还需要数据库租约或外部任务队列、跨进程限流、执行端幂等、认证/RBAC 和分布式压测。
