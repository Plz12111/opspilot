# 演练环境

## 调用链

```text
Client -> API Gateway :8080 -> Order Service :8081 -> Inventory Service :8082
              |                    |                         |
              +--------------------+-------------------------+
                                   |
                          Prometheus + Jaeger
                                   |
                             Alertmanager
                                   |
                               OpsPilot
```

三个服务均提供 `/health/live`、`/health/ready` 和 `/metrics`，并使用 OpenTelemetry 将 Trace 发送到 Jaeger。出站调用传播 W3C Trace Context。

## 可复现故障

### 库存服务固定失败

```bash
sh demo/scenarios/inventory-error.sh
```

脚本注入故障并持续产生 25 秒流量，结束时自动复位。库存服务所有业务请求返回 503，错误沿 `Inventory -> Order -> Gateway` 传播，Prometheus 的 `DemoServiceHighErrorRate` 规则持续满足 15 秒后触发告警。

### 库存服务延迟

```bash
sh demo/scenarios/inventory-latency.sh
```

脚本注入故障并持续产生 25 秒流量，结束时自动复位。库存服务为每个业务请求增加 1 秒延迟，Prometheus 的 `DemoServiceHighLatency` 规则持续满足 15 秒后触发告警。

### 恢复

```bash
sh demo/faults/reset-inventory.sh
```

恢复操作只清除故障配置，不重置库存和幂等预留数据。重启容器会重置整个演练状态。

## 产生请求

```bash
curl --fail --silent --show-error \
  -X POST http://127.0.0.1:8080/api/v1/orders \
  -H 'Content-Type: application/json' \
  -d '{"sku":"SKU-001","quantity":1}'
```

为了让基于速率的告警规则取得样本，需要在故障期间持续产生请求。`demo/scenarios/` 下的脚本会注入故障、持续产生流量，并在结束时自动复位。

## 完整 Agent 工作流

```bash
make demo-seed
```

该命令不直接修改数据库，而是依次调用 Runbook、Alertmanager、Incident 调查和修复 API，生成可用于讲解的完整调查时间线。重复执行复用相同 Incident、调查和修复动作。

## 安全边界

- 故障接口不接受任意命令，只接受延迟和错误率两个有界参数。
- 故障接口必须携带 `X-Fault-Token`。
- 演练服务不连接生产基础设施。
- Compose 默认凭据仅适合本机演示，禁止部署到公网。
