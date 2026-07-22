# 受控修复与审批

## 状态流

```text
PENDING_APPROVAL -> APPROVED -> EXECUTING -> EXECUTED
         |                            |
         +-> REJECTED                 +-> FAILED
         +-> EXPIRED
```

## 安全边界

- 仅允许 `restart_service` 和 `rollback_deployment`。
- 默认只允许 `demo` 与 `staging` 环境，策略层拒绝 production。
- 每种动作使用独立 Pydantic 参数 Schema，不接受任意 Shell。
- approver 必须在服务端 allowlist，客户端或飞书卡片不能声明角色。
- 提议人不能审批自己的动作。
- 未审批、已拒绝或已过期动作不能执行。
- 提议、审批和执行均具备幂等约束。
- 同进程并发请求使用按动作锁，多实例部署仍由数据库唯一约束保护。

当前 `DemoActionExecutor` 只返回模拟执行结果，不连接真实部署系统。接入 Kubernetes 或发布平台时替换 `ActionExecutor`，审批和状态机无需改变。

## API

```text
POST /api/v1/actions
GET  /api/v1/actions/{action_id}
POST /api/v1/actions/{action_id}/approve
POST /api/v1/actions/{action_id}/reject
POST /api/v1/actions/{action_id}/execute
```

HTTP API 使用 `X-Actor-Id` 标识当前演示身份。正式部署必须由认证中间件注入，不能直接信任公网请求头。

飞书卡片动作 `remediation.approve` 和 `remediation.reject` 会复用相同服务端审批状态机，重复回调不会产生第二条审批。

