# 部署与演示手册

## 目标

在一台安装了 Git、Docker Desktop 的新机器上，15 分钟内启动 OpsPilot，并生成一条可讲解的完整 Incident 工作流。Compose 默认配置只用于本机演示，不应直接暴露到公网。

## 快速开始

```bash
git clone <repository-url> opspilot
cd opspilot
make demo-up
make demo-seed
```

确认以下结果：

- `docker compose ps` 中 `opspilot`、`postgres`、`redis` 和三个演练服务为 healthy。
- `curl http://127.0.0.1:8000/health/ready` 返回 `ready` 或 `degraded`。
- `make demo-seed` 输出 `run_status: COMPLETED`、`approval: APPROVED`、`execution: SUCCESS`。
- 打开命令输出的 `workspace_url`，可看到调查时间线、证据和修复动作。

若只需要开发 API，可安装 Python 3.12 与 uv：

```bash
make install
make migrate
make dev
```

## 演示顺序

1. 打开 Workspace，介绍告警形成 Incident 以及指纹去重。
2. 展开 Investigation timeline，说明 LangGraph 的计划、工具调用、SSE 和持久任务恢复。
3. 切换 Evidence，展示 Metrics、Logs、Traces、Runbook 的证据 ID 与引用约束。
4. 展示 Remediation，说明 requester 不能自批、审批过期、动作白名单和幂等执行。
5. 切换 Evaluation，展示同一 80 案例集上的 v1/v2 对照、失败案例和安全指标。
6. 运行真实故障场景，观察 Prometheus 告警如何进入相同闭环。

```bash
sh demo/scenarios/inventory-latency.sh
```

## 健康检查

`/health/live` 仅判断 API 进程存活。`/health/ready` 始终检查数据库；当 `OPSPILOT_READINESS_CHECK_EXTERNAL=true` 时，还会检查 Redis、Prometheus、Loki 和 Jaeger。

- `ready`：所有已配置依赖可用。
- `degraded`：数据库可用，但一个或多个可降级观测依赖不可用，API 仍返回 200。
- `not_ready`：核心依赖不可用，API 返回 503。数据库请求失败时由 FastAPI 返回 5xx。

当前调查任务以数据库为系统记录，因此 Redis 和观测后端都按可降级依赖报告。它们不可用会降低证据质量，但不会阻止查看已有 Incident。

## 数据库迁移

容器入口先运行 `alembic upgrade head`，成功后才启动 Uvicorn；Compose 设置 `OPSPILOT_DB_AUTO_CREATE=false`，避免运行时 schema 漂移。

开发时使用：

```bash
make migrate
make migration name=add_example_field
PYTHONPATH=src uv run alembic check
PYTHONPATH=src uv run alembic downgrade -1
```

升级生产或共享数据库前必须先备份，并在相同数据库引擎的临时实例验证 upgrade/downgrade。首次迁移已经通过 SQLite 升级、元数据一致性检查和回滚测试；Compose 的 PostgreSQL 首次启动迁移也已实际验证。

## 验证与排障

```bash
make smoke
make test
make lint
make eval
docker compose logs opspilot
docker compose config --quiet
```

常见问题：

- Docker API 连接失败：启动 Docker Desktop，等待状态显示 Engine running。
- 8000 端口占用：停止已有服务，或修改 `compose.yml` 的宿主机端口并设置 `OPSPILOT_BASE_URL`。
- 就绪状态为 degraded：查看返回 JSON 中标记为 `down` 的依赖，再查看对应 Compose service 日志。
- demo seed 调查失败：确认 Prometheus、Loki、Jaeger 已启动；失败的工具也会作为结构化限制写入调查结果。

## CI 门禁

`.github/workflows/ci.yml` 包含三个任务：

- Quality：锁定依赖安装、Ruff、pytest、Python 包构建、Compose 配置验证。
- Container smoke：构建镜像，以 SQLite 启动独立容器，验证 ready endpoint 和 Workspace HTML。
- Resilience smoke：启动完整 Compose，以并发请求验证告警、订单、调查、修复和故障恢复不变量，并上传报告与容器日志。

CI 不需要飞书真实凭据，也不会执行生产环境修复。

## Docker 验证记录

2026-07-22 在 Docker Engine 29.6.1 上完成 ARM64 本机验证：

- 10 个 Compose 服务全部启动，OpsPilot、PostgreSQL、Redis 与三个演练服务通过健康检查。
- Alembic 在 PostgreSQL 上升级到 `2f69600ac7b9`，创建 16 张业务表并为调查请求加入幂等唯一约束。
- `make demo-seed` 完成调查、审批和执行，重复运行复用同一 Incident、Run 与 Action。
- Metrics、Logs、Traces 与 Runbook 五次工具调用成功，持久化 7 条 Evidence 与 15 个 RunEvent。
- `make smoke` 验证 live/ready、Workspace、OpenAPI 和 Evaluation API。
- Inventory 固定失败场景沿 Order/Gateway 传播 503，Prometheus/Alertmanager 产生三条服务级告警并进入 OpsPilot；脚本退出后订单恢复为 200。
- PostgreSQL 外键验证暴露并修复 Run/Job、ToolCall/Evidence 插入顺序；SQLite 测试现默认启用外键约束防止回归。
- OpsPilot 容器重启后数据保持，重复 seed 仍返回原有 Run 与已执行 Action。
- 50 并发正式韧性测试发送 415 个请求，六个场景全部通过；订单链路基线 721.59 RPS、P95 94.86 ms，详情见 `docs/resilience-testing.md`。
