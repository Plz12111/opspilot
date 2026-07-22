# OpsPilot 5 分钟演示视频脚本

## 录制前准备

```bash
make demo-up
make demo-seed
make smoke
```

准备浏览器标签：Workspace、OpenAPI、Prometheus、Jaeger。终端停留在 `make eval` 的结果。录制时隐藏飞书密钥、环境变量和本机个人路径。

## 0:00-0:30 问题与定位

画面：README 顶部与项目结果表。

讲解：

> OpsPilot 是一个证据驱动的 AI SRE Incident Agent。它不是把告警拼进 Prompt，而是把告警去重、工具调查、证据引用、任务恢复、人工审批和离线评测组成一条可运行链路。项目重点是 Agent 在真实工程约束下如何可信地工作。

## 0:30-1:10 告警与 Incident

画面：Workspace 左侧 Incident 列表和摘要指标。

操作：刷新页面，选择 `Inventory p95 latency exceeds the demo SLO`。

讲解：

> Alertmanager 事件按环境、服务、告警名和指纹生成去重键。重复事件追加到同一个活跃 Incident，不重复触发业务副作用。数据库是系统记录，飞书和 Web 都只是交互入口。

## 1:10-2:10 Agent 调查轨迹

画面：Overview 的 Investigation timeline。

操作：从 `run.queued` 滚动到 `run.completed`。

讲解：

> 调查由 LangGraph 显式状态图执行，每个节点只读写结构化状态。默认计划查询两次指标、日志、Trace 和 Runbook；工具网关负责 Schema、白名单、超时、结果截断和错误标准化。每一步形成持久化事件，通过 SSE 实时展示。浏览器断线可按事件序号回放，应用重启会恢复数据库中的未完成 Job。

## 2:10-2:50 Evidence 与可信结论

画面：Evidence 标签与诊断摘要。

操作：切换 Evidence，展示来源 URI、内容和 Evidence ID。

讲解：

> 所有工具结果统一为 Evidence。诊断只能引用本次运行真实存在的 Evidence ID，未知引用会被 CitationValidator 拒绝。外部日志与 Runbook 都是不可信数据，不能覆盖系统策略。在线默认总结器故意保守；接入真实模型后仍经过同一结构化校验。

## 2:50-3:35 人工审批与安全边界

画面：Remediation 已执行动作；必要时新建一个动作但不最终执行。

讲解：

> Agent 不能直接修系统。它只能提出 `restart_service` 或 `rollback_deployment`，且只允许 demo 和 staging。审批人来自服务端 allowlist，请求人不能自批，审批会过期，执行有数据库幂等和动作锁。Production 在策略层被明确拒绝，不依赖 Prompt 自觉。

## 3:35-4:25 离线评测

画面：Evaluation 页面和 80-case matrix。

操作：切换 Evaluation，指向 Baseline vs candidate 与五个失败格。

讲解：

> 评测覆盖 80 个案例、10 类根因，包含噪声、缺失遥测和工具失败。v1 与 v2 使用相同数据摘要和相同工具轨迹。数据源加权后 Top-1 从 67.5% 提升到 93.8%，Top-3 为 97.5%，引用有效率 100%，危险动作率为 0。三次运行预测一致性 100%。失败案例仍保留在报告中。

## 4:25-5:00 工程化与收尾

画面：架构图、终端测试结果。

操作：展示 `62 passed`、Alembic migration、CI workflow。

讲解：

> 项目使用 Alembic 管理 16 张业务表，容器启动前迁移；健康检查区分数据库和可降级观测依赖；CI 覆盖静态检查、测试、包构建、Compose 配置与容器冒烟。当前修复执行器是演示适配器，真实模型和 Kubernetes 执行器是明确的扩展点。这些限制都写在 README，而不是隐藏在演示之外。

## 备用追问镜头

- 重复运行 `make demo-seed`，展示相同 Incident、Run、Action ID。
- 关闭一个观测依赖，展示工具失败被记录而调查继续。
- 打开 `/api/v1/runs/{id}/events`，说明 SSE replay。
- 打开 `evals/reports/incident-comparison.md`，展示相同 dataset digest。
- 打开 `src/opspilot/remediation/policy.py`，展示 production 拒绝来自代码策略。
