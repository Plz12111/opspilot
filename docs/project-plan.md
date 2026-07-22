# OpsPilot 项目计划书

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 项目名称 | OpsPilot |
| 项目类型 | AI SRE 故障诊断与受控修复 Agent |
| 当前版本 | 0.1（设计基线） |
| 主要入口 | 飞书应用机器人、Alertmanager Webhook、Web 控制台 |
| 目标周期 | 10 周，每周约 15-20 小时 |
| 部署方式 | 本地 Docker Compose；后续支持 Kubernetes |

## 2. 项目目标

OpsPilot 的目标不是代替值班工程师，而是缩短“发现告警到形成可信判断”的时间，并把高风险动作放在明确的人工审批边界内。

项目需要同时证明以下能力：

- 设计可恢复、可观测的 Agent 工作流，而非单次模型调用。
- 把日志、指标、Trace、Git 和知识库封装为安全工具。
- 用证据引用和离线评测约束模型输出。
- 实现权限、审批、审计和幂等机制。
- 交付可部署、可测试、可演示的完整系统。

### 2.1 MVP 成功指标

首版评测集不少于 30 个可复现故障案例，正式作品集版本扩充到 80 个以上。

| 指标 | MVP 目标 | 作品集目标 |
| --- | ---: | ---: |
| 根因 Top-1 准确率 | >= 60% | >= 75% |
| 根因 Top-3 召回率 | >= 80% | >= 90% |
| 证据引用有效率 | >= 90% | >= 95% |
| 工具调用成功率 | >= 95% | >= 98% |
| 危险操作未审批执行次数 | 0 | 0 |
| 重复事件产生重复事故数 | 0 | 0 |
| 简单故障调查 P95 时延 | <= 120 秒 | <= 90 秒 |
| 单次调查成本 | 记录基线 | 较基线降低 30% |

所有指标必须由自动化评测或系统日志生成，不手工填写结果。

## 3. 用户与核心场景

### 3.1 用户角色

| 角色 | 主要诉求 | 权限 |
| --- | --- | --- |
| 值班工程师 | 快速获得调查结论和证据 | 查看、补充信息、审批低风险动作 |
| 服务负责人 | 确认影响、决定回滚 | 查看、审批所属服务的中高风险动作 |
| 平台管理员 | 配置工具、权限和模型 | 管理配置，不参与日常调查 |
| 面试官/访客 | 快速理解系统价值 | 使用演示环境只读体验 |

### 3.2 主流程

1. Alertmanager 发送结构化告警，系统创建或合并 Incident。
2. 飞书机器人在指定群发布事故卡片和调查入口。
3. Agent 根据告警生成调查计划，调用只读工具收集证据。
4. Agent 建立多个根因假设，并通过后续工具调用验证或排除。
5. Agent 输出影响范围、根因置信度、证据、建议动作和风险等级。
6. 需要变更系统状态的动作进入人工审批。
7. 执行器校验审批、权限、参数和幂等键后执行动作。
8. Agent 查询指标验证恢复，关闭事故并生成复盘报告。

### 3.3 明确不做

MVP 不包含：

- 无人值守的生产环境自动修复。
- 自研基础模型或大规模微调。
- 通用低代码 Agent 平台。
- 跨公司、多租户计费系统。
- 语音、移动端 App 和复杂 IM 富媒体。
- 为展示技术而引入 Kafka 或 Kubernetes。

## 4. MVP 范围

### 4.1 演练环境

搭建三个业务服务和基础依赖：

```text
Client -> API Gateway -> Order Service -> Inventory Service
                         |                |
                         PostgreSQL       Redis
```

接入 Prometheus、Loki 和 Jaeger，至少支持以下故障注入：

- Inventory Service 延迟或不可用。
- PostgreSQL 连接池耗尽。
- Redis 缓存失效导致请求放大。
- 错误配置发布。
- 新版本代码引入资源泄漏。

### 4.2 Agent 能力

- 告警分类与 Incident 去重。
- 基于显式状态图的计划、调查、判断和验证。
- 工具超时、重试、结果截断和结构化错误。
- 最多轮数、Token 预算和时间预算。
- 调查中断后从持久化检查点恢复。
- 结论必须引用工具结果中的证据 ID。
- 低置信度时主动请求人工补充信息或升级处理。

### 4.3 首批工具

| 工具 | 类型 | 默认风险等级 |
| --- | --- | --- |
| `query_metrics` | 查询 Prometheus 指标 | 只读 |
| `query_logs` | 查询 Loki 日志 | 只读 |
| `query_traces` | 查询 Jaeger Trace | 只读 |
| `search_runbooks` | 检索运维文档 | 只读 |
| `get_deployment_history` | 查询部署历史 | 只读 |
| `inspect_git_diff` | 检查指定提交差异 | 只读 |
| `restart_service` | 重启演练环境服务 | 低风险、需审批 |
| `rollback_deployment` | 回滚演练环境版本 | 中风险、需审批 |

工具不能接受任意 Shell 命令。所有变更工具使用服务端定义的参数 Schema、动作白名单和目标白名单。

## 5. 系统架构

```text
Alertmanager ----> Integration API ----> Incident Service ----> PostgreSQL
                         ^                       |
Feishu Events -----------|                       v
Feishu Card Actions -----|                Agent Orchestrator
                                                 |
                    +----------------------------+-------------------------+
                    |              |             |             |          |
                 Metrics         Logs          Traces        Git/RAG   Action Executor
                    |              |             |             |          |
                Prometheus        Loki         Jaeger       pgvector   Demo Services

Agent events -> Outbox/Worker -> Feishu Adapter -> Feishu group/thread/card
Agent traces --------------------> OpenTelemetry/Langfuse
```

### 5.1 核心组件

| 组件 | 职责 |
| --- | --- |
| Integration API | 接收飞书事件、卡片动作和 Alertmanager 告警 |
| Incident Service | Incident 生命周期、去重、权限和领域规则 |
| Agent Orchestrator | 状态图、预算控制、工具选择、检查点和恢复 |
| Tool Gateway | 参数校验、调用、超时、审计、结果标准化 |
| Knowledge Service | Runbook 导入、混合检索、重排和引用 |
| Approval Service | 创建审批、校验审批人、处理过期和重复点击 |
| Action Executor | 仅执行已批准的白名单动作，并验证结果 |
| Notification Worker | 异步发送和更新飞书消息，处理限流重试 |
| Evaluation Runner | 执行故障数据集并生成指标与对比报告 |

### 5.2 技术选型

| 层次 | MVP 选型 | 说明 |
| --- | --- | --- |
| 语言/API | Python 3.12 + FastAPI + Pydantic | Agent 生态成熟，Schema 清晰 |
| Agent 编排 | LangGraph | 显式状态图、检查点和人工中断 |
| 数据库 | PostgreSQL + pgvector | 领域数据与向量数据先统一存储 |
| 缓存/队列 | Redis + Dramatiq | 异步任务、限流和短期状态 |
| 检索 | PostgreSQL 全文检索 + pgvector + Reranker | MVP 避免额外维护搜索集群 |
| 可观测性 | OpenTelemetry + Langfuse | 系统 Trace 与 LLM Trace 分层记录 |
| 演练环境 | Docker Compose | 一条命令启动，便于面试演示 |
| 前端 | React + TypeScript | 第二阶段提供调查时间线和评测面板 |

模型访问通过统一 `ModelProvider` 接口封装。业务代码不直接依赖某一家模型 SDK。

## 6. Agent 状态设计

### 6.1 Incident 状态

```text
OPEN -> INVESTIGATING -> DIAGNOSED -> AWAITING_APPROVAL
  |          |               |                 |
  |          v               v                 v
  +------> NEEDS_HUMAN     MITIGATED <----- EXECUTING
                              |
                              v
                           RESOLVED -> CLOSED

任意处理中状态 -> CANCELLED / FAILED
```

### 6.2 Agent 状态字段

- `incident_id`
- `alert_snapshot`
- `conversation_context`
- `investigation_plan`
- `hypotheses[]`
- `evidence[]`
- `tool_call_history[]`
- `token_budget`、`time_budget`、`step_budget`
- `diagnosis`
- `proposed_actions[]`
- `approval_state`
- `recovery_verification`
- `errors[]`

每个节点只接受和返回结构化状态。模型生成内容先经过 Pydantic 校验，不合法结果最多修复一次，仍失败则进入可解释的降级路径。

## 7. 领域数据模型

| 实体 | 关键字段 |
| --- | --- |
| `Incident` | id、fingerprint、severity、service、status、started_at、resolved_at |
| `Alert` | id、source、external_id、labels、annotations、raw_payload |
| `InvestigationRun` | id、incident_id、status、model、budgets、started_at、ended_at |
| `InvestigationJob` | id、run_id、status、attempts、locked_at、completed_at |
| `RunEvent` | id、run_id、sequence、event_type、payload、created_at |
| `ToolCall` | id、run_id、tool、arguments_hash、status、latency、evidence_id |
| `Evidence` | id、source_type、source_uri、time_range、content、checksum |
| `Hypothesis` | id、statement、confidence、supporting_ids、contradicting_ids |
| `ProposedAction` | id、type、target、parameters、risk_level、status |
| `Approval` | id、action_id、requester、approver、decision、expires_at |
| `AuditEvent` | id、actor、event_type、resource、payload_digest、created_at |
| `ConversationBinding` | incident_id、tenant_key、chat_id、root_message_id |

告警去重键默认由 `source + environment + service + alertname + normalized_labels` 生成，重复告警追加到已有 Incident 并更新计数。

## 8. 内部 HTTP API 草案

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/v1/webhooks/alertmanager` | 接收 Alertmanager 告警 |
| `POST /api/v1/integrations/feishu/events` | 接收飞书事件订阅 |
| `POST /api/v1/integrations/feishu/card-actions` | 接收飞书卡片交互 |
| `POST /api/v1/incidents` | 手工创建调查任务 |
| `GET /api/v1/incidents/{id}` | 查询事故详情 |
| `POST /api/v1/incidents/{id}/messages` | 向调查补充上下文 |
| `POST /api/v1/incidents/{id}/cancel` | 取消调查 |
| `POST /api/v1/actions/{id}/approve` | 审批建议动作 |
| `POST /api/v1/actions/{id}/reject` | 拒绝建议动作 |
| `GET /api/v1/runs/{id}/events` | SSE 获取调查过程 |
| `GET /health/live` | 进程存活检查 |
| `GET /health/ready` | 依赖就绪检查 |

飞书协议、消息卡片和安全校验见 [飞书集成设计](feishu-integration.md)。

## 9. 安全与可靠性

- 飞书密钥、模型密钥和数据源凭据仅从 Secret/环境变量读取。
- 日志默认脱敏 Authorization、Cookie、Token、手机号和邮箱。
- 所有外部事件使用事件 ID 幂等处理，并保留原始载荷摘要。
- 写操作采用审批令牌、短有效期、单次消费和数据库事务。
- 执行时重新检查动作状态、审批人权限和目标环境，不信任卡片参数。
- Prompt 中的数据源内容均标记为不可信数据，不能覆盖系统策略。
- 工具按最小权限配置独立凭据；查询工具与执行工具隔离部署。
- 模型输入设长度上限，工具结果先过滤再进入上下文。
- 调查任务具有最大步数、最大时间、最大成本和取消机制。

## 10. 可观测性与评测

### 10.1 线上观测

每次调查使用统一 `trace_id` 串联：

- HTTP 请求和异步任务。
- Agent 节点、模型调用与工具调用。
- 飞书消息发送和卡片动作。
- Token、成本、延迟、重试、限流和异常。

禁止在 Trace 中记录完整凭据和未经处理的敏感日志。

### 10.2 离线评测

每个案例包含：故障注入脚本、告警、允许使用的数据源、标准根因、关键证据、可接受动作和禁止动作。

评测分为四层：

1. 工具单测：Schema、边界、超时和错误映射。
2. 检索评测：Recall@K、MRR、引用准确率。
3. Agent 轨迹评测：工具选择、无效调用、预算和安全违规。
4. 端到端评测：根因、恢复结果、耗时和成本。

模型裁判只能作为辅助指标；根因、证据和危险动作使用确定性规则或人工标注复核。

## 11. 仓库规划

```text
opspilot/
├── apps/
│   ├── api/                 # FastAPI 入口
│   ├── worker/              # 异步任务
│   └── web/                 # React 控制台
├── packages/
│   ├── domain/              # 领域实体与状态机
│   ├── agent/               # Agent 图与模型适配器
│   ├── tools/               # 工具网关及工具实现
│   ├── integrations/        # 飞书、Alertmanager 等适配器
│   ├── knowledge/           # 文档处理与检索
│   └── observability/       # 日志、指标和 Trace
├── demo/
│   ├── services/            # 演练微服务
│   ├── faults/              # 故障注入脚本
│   └── runbooks/            # 演示运维手册
├── evals/
│   ├── cases/               # 故障案例
│   ├── graders/             # 确定性和模型评分器
│   └── reports/             # 自动生成，不提交敏感结果
├── tests/
├── deploy/
│   ├── compose/
│   └── migrations/
└── docs/
```

先保持一个 Python 单体仓库和独立 worker，不提前拆微服务。组件边界由包、数据库事务和接口保证。

## 12. 里程碑

| 周次 | 交付物 | 验收标准 |
| --- | --- | --- |
| 第 1 周 | 仓库骨架、领域模型、Compose 基础依赖 | CI 通过；API、数据库、Redis 可启动 |
| 第 2 周 | 演练服务、监控链路、2 个故障 | 能注入并在 Grafana/Jaeger 观察故障 |
| 第 3 周 | Incident API、飞书事件和告警卡片 | 重复告警只产生一个 Incident |
| 第 4 周 | Agent 状态图、前三个只读工具 | 可完成一次端到端只读调查 |
| 第 5 周 | Runbook RAG、证据引用、部署/Git 工具 | 结论可回溯到原始证据 |
| 第 6 周 | 审批、执行器、恢复验证 | 未审批动作始终不能执行 |
| 第 7 周 | 30 个评测案例、基线报告 | 一条命令运行评测并生成报告 |
| 第 8 周 | 稳定性、成本优化、80 个案例 | 有对照实验，不只报告最好结果 |
| 第 9 周 | Web 时间线、部署和演示脚本 | 新环境按文档 15 分钟内运行 |
| 第 10 周 | README、架构文档、视频和简历材料 | 陌生人可独立复现实例 |

### 第 9 周完成记录（2026-07-22）

- Incident Workspace 已支持异步调查 SSE 时间线和 Incident 深链接。
- Alembic 管理 16 张业务表的首个版本，容器启动前强制升级到 `head`。
- `make demo-seed` 通过公开 API 幂等生成告警、调查、证据、审批和执行闭环。
- `/health/ready` 检查数据库，并可选报告 Redis、Prometheus、Loki、Jaeger 状态；可选依赖异常时返回 `degraded`。
- GitHub Actions 执行 lint、66 项测试、构建、Compose 配置检查和容器冒烟测试。
- 已在 Docker Engine 29.6.1 上验证完整 Compose、PostgreSQL 迁移、依赖健康检查、幂等 demo seed、Workspace 与 Evaluation API。

### 第 10 周完成记录（2026-07-22）

- README 已重构为作品集入口，覆盖问题、架构、真实指标、五分钟演示、安全边界和已知限制。
- 架构文档补齐运行时视图、模块所有权、调查状态、证据/模型边界、修复安全模型和五项 ADR。
- 五分钟视频脚本提供逐段画面、操作与讲解，并准备失败恢复、幂等和评测摘要等备用镜头。
- 简历与面试材料提供三行/单行项目描述、60 秒介绍、讲解框架、高频追问和代码入口。
- 所有公开指标均回溯到自动生成评测报告；未把演示执行器、成本代理或确定性总结器描述为生产能力。

### 最终工程化闭环（2026-07-22）

- 告警合并使用数据库原子计数，并在唯一键竞争时回滚重试；50 个并发 occurrence 精确得到 `alert_count = 50`。
- 调查 API 支持 `Idempotency-Key`，新增版本化迁移 `2f69600ac7b9`；20 个并发请求只生成一个持久 Run。
- 新增六场景韧性测试器，输出 JSON/Markdown 的 RPS、P50/P95/P99、状态码和业务不变量。
- Docker 50 并发正式验证共 415 个请求全部通过，依赖 100% 故障稳定传播 503，复位后恢复 200。
- Makefile 提供快速/正式入口，CI 启动完整 Compose 运行快速韧性门禁并上传报告和日志。

## 13. 第一迭代任务（第 1 周）

### P0

- 初始化 Python 工程、代码检查、测试和 CI。
- 建立 PostgreSQL、Redis 的 Compose 配置。
- 定义 Incident、Alert、ConversationBinding 和 AuditEvent。
- 实现 Alertmanager Webhook 的请求模型与去重逻辑。
- 实现飞书回调 URL 校验、事件验签、事件幂等存储。
- 建立统一配置和 Secret 读取规则。

### P1

- 实现飞书访问令牌缓存和消息发送适配器。
- 收到告警后创建 Incident，并向测试群发送基础卡片。
- 加入结构化日志和 `trace_id`。
- 编写端到端测试：告警 -> Incident -> 飞书适配器调用。

### 第 1 周完成定义

- `make dev` 或等价命令能启动依赖和 API。
- `make test` 能运行单元与集成测试。
- 相同告警投递三次，数据库只有一个活跃 Incident。
- 飞书回调重复投递不会重复触发业务动作。
- 不配置真实飞书凭据时，可用 Fake Adapter 完整测试。

## 14. 主要风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| 范围失控 | 项目长期无法形成闭环 | 每阶段只增加一种能力，MVP 冻结非目标 |
| 演示数据过于理想 | 面试时可信度低 | 加入噪声、缺失数据、重复告警和工具失败 |
| Agent 结果不可复现 | 指标波动过大 | 固定数据快照、记录模型版本和参数，多次运行报告方差 |
| 飞书限流或回调重试 | 重复消息和状态错乱 | 快速 ACK、异步处理、幂等键、退避和 Outbox |
| 模型错误触发操作 | 安全事故 | 模型只提出动作，服务端策略和人工审批决定执行 |
| 基础设施过重 | 开发时间被运维消耗 | MVP 使用 Compose、PostgreSQL 和 Redis，按证据扩容 |

## 15. 架构决策基线

- 使用单 Agent 状态图加确定性节点，暂不采用自由协作的多 Agent。
- 使用领域事件和 Outbox 保证数据库状态与飞书通知最终一致。
- 飞书只是交互适配器，不保存系统真相；数据库是状态唯一来源。
- 模型不直接持有执行凭据，也不直接调用 Shell。
- 先建立可运行的基线评测，再进行 Prompt、模型或 RAG 优化。
- 每个里程碑都必须产生可演示的纵向功能，不接受只完成底层框架。
