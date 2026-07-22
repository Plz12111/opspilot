# 飞书集成设计

## 1. 目标与边界

飞书是 OpsPilot 的通知和人工协作入口，不是 Incident 状态的唯一存储。所有事故、审批和动作状态以 PostgreSQL 为准，飞书消息可以重发或重建。

MVP 使用企业自建应用机器人，支持：

- 将 Alertmanager 告警发布到指定事故群。
- 在群聊中 `@机器人` 发起调查、查询状态和补充信息。
- 在同一消息线程持续发布调查进展和最终结论。
- 通过交互卡片审批或拒绝建议动作。
- 更新原卡片，避免反复发送新消息刷屏。

首版不支持单聊建群、跨租户安装、飞书审批中心和通讯录全量同步。

## 2. 飞书应用配置

需要在飞书开放平台创建企业自建应用，并启用机器人能力。

### 2.1 配置项

服务端环境变量只保存引用或密钥，不提交仓库：

```text
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_VERIFICATION_TOKEN=
FEISHU_ENCRYPT_KEY=
FEISHU_DEFAULT_CHAT_ID=
FEISHU_BASE_URL=https://open.feishu.cn
```

生产环境使用 Secret Manager 或部署平台 Secret 注入。

### 2.2 最小权限原则

实际权限名称以创建应用时飞书开放平台展示为准，只申请完成以下操作所需权限：

- 接收群聊中提及机器人的消息。
- 获取必要的消息与会话标识。
- 以应用身份发送、回复和更新消息。
- 获取操作者最小身份信息，用于审批授权。

禁止为了省事申请全量通讯录、云文档或群管理权限。权限清单在实现阶段导出并提交脱敏截图到设计文档。

## 3. 总体交互流程

### 3.1 告警触发调查

```text
Alertmanager -> POST /api/v1/webhooks/alertmanager
             -> 创建/合并 Incident
             -> 写入 notification_outbox
             -> Worker 获取 tenant_access_token
             -> 飞书群发送事故卡片
             -> 启动 Agent 调查任务
             -> 更新卡片状态并在线程发布关键进展
```

### 3.2 用户发起调查

```text
用户 @机器人 investigate order-service 最近 15 分钟错误率
  -> 飞书事件回调
  -> 验签、解密、幂等记录、立即 ACK
  -> Worker 解析命令并校验群权限
  -> 创建 Incident/InvestigationRun
  -> 回复“已开始调查”
  -> Agent 异步执行
```

### 3.3 修复审批

```text
Agent 提出 rollback_deployment
  -> Approval Service 创建待审批记录
  -> 飞书卡片显示风险、证据、目标和有效期
  -> 授权用户点击批准/拒绝
  -> 卡片回调验签并立即 ACK
  -> 服务端按 action_id 重新读取动作并校验权限
  -> 原子写入审批决定
  -> Executor 消费一次性执行任务
  -> 验证恢复并更新卡片
```

## 4. 接收接口

### 4.1 事件订阅回调

`POST /api/v1/integrations/feishu/events`

职责：

1. 读取原始请求体，执行飞书要求的验签和解密。
2. 处理首次 URL 验证请求并返回 `challenge`。
3. 从事件头提取 `event_id`、`event_type`、`tenant_key` 和时间戳。
4. 使用 `tenant_key + event_id` 建立唯一键。
5. 将合法事件写入 `integration_events`，快速返回成功。
6. 由异步 Worker 处理消息，避免超过飞书回调时限。

内部标准化事件：

```json
{
  "provider": "feishu",
  "event_id": "evt_xxx",
  "event_type": "im.message.receive_v1",
  "tenant_key": "tenant_xxx",
  "occurred_at": "2026-07-21T10:30:00+08:00",
  "actor": {
    "open_id": "ou_xxx"
  },
  "conversation": {
    "chat_id": "oc_xxx",
    "chat_type": "group",
    "message_id": "om_xxx",
    "root_id": null,
    "parent_id": null
  },
  "message": {
    "message_type": "text",
    "text": "investigate order-service 最近 15 分钟错误率"
  }
}
```

只在群聊消息明确提及机器人时处理普通文本。机器人自身发送的消息和不支持的消息类型直接忽略并记录原因。

### 4.2 卡片动作回调

`POST /api/v1/integrations/feishu/card-actions`

支持动作：

| `action` | 用途 |
| --- | --- |
| `incident.view` | 打开事故详情链接 |
| `incident.refresh` | 刷新卡片状态 |
| `investigation.cancel` | 取消仍在运行的调查 |
| `remediation.approve` | 批准建议动作 |
| `remediation.reject` | 拒绝建议动作 |

按钮 `value` 仅携带不可变资源标识，不携带可被信任的权限或执行参数：

```json
{
  "action": "remediation.approve",
  "incident_id": "inc_01J...",
  "action_id": "act_01J...",
  "card_version": 3
}
```

服务端必须重新读取 `ProposedAction`，校验：

- 动作处于 `PENDING_APPROVAL`。
- 未过期且未被其他人处理。
- 操作者映射到有效的系统用户。
- 操作者对目标环境和服务具有审批权限。
- `card_version` 未过期，或返回当前状态而不执行。
- 提议者与审批者满足分权规则。

数据库对 `action_id` 的有效审批建立唯一约束。重复点击返回当前结果，不产生第二次执行。

## 5. 飞书客户端适配器

领域层依赖以下接口，不直接引用飞书 SDK 数据结构：

```python
class ChatNotifier(Protocol):
    async def publish_incident(self, incident: IncidentView) -> MessageRef: ...
    async def reply_progress(self, ref: MessageRef, event: ProgressEvent) -> MessageRef: ...
    async def update_incident(self, ref: MessageRef, incident: IncidentView) -> None: ...
    async def request_approval(self, ref: MessageRef, request: ApprovalView) -> MessageRef: ...
    async def publish_report(self, ref: MessageRef, report: ReportView) -> MessageRef: ...
```

飞书实现负责将领域模型转换成文本或交互卡片。测试使用 `FakeChatNotifier`，不依赖真实网络和凭据。

### 5.1 访问令牌

应用身份调用飞书开放接口前，通过应用凭据获取 `tenant_access_token`。适配器应：

- 按租户缓存令牌，并在官方过期时间前预留刷新窗口。
- 使用单飞锁避免并发刷新风暴。
- 收到明确的令牌失效响应时只强制刷新一次。
- 不在日志、Trace、异常或数据库中记录令牌。

MVP 单租户仍保留 `tenant_key` 维度，避免以后重构主键和缓存键。

### 5.2 消息操作

适配器封装飞书 OpenAPI 的具体版本和路径，至少提供：

- 按 `chat_id` 发送交互卡片。
- 按 `message_id` 回复消息，保持事故线程上下文。
- 更新原事故卡片。
- 必要时发送纯文本降级消息。

调用飞书 API 时记录请求 ID、HTTP 状态、业务错误码、延迟和重试次数，但不记录令牌或完整敏感消息。

首版适配器计划封装的飞书接口如下。路径在开发接入前以开放平台当前文档和测试应用返回结果复核：

| 操作 | 计划使用的 OpenAPI | 适配器方法 |
| --- | --- | --- |
| 获取应用访问令牌 | `POST /open-apis/auth/v3/tenant_access_token/internal` | `get_tenant_access_token` |
| 向群聊发送消息 | `POST /open-apis/im/v1/messages?receive_id_type=chat_id` | `send_message` |
| 回复指定消息 | `POST /open-apis/im/v1/messages/{message_id}/reply` | `reply_message` |
| 更新已发送消息 | `PATCH /open-apis/im/v1/messages/{message_id}` | `update_message` |

消息发送请求由适配器构造，领域层不拼接飞书的双重编码 `content` 字符串。适配器先用 Pydantic 模型生成卡片对象，再由 JSON 序列化器完成协议转换。

## 6. 机器人命令

MVP 使用严格命令语法，避免让大模型决定权限相关意图。

| 命令 | 示例 | 行为 |
| --- | --- | --- |
| `investigate` | `@机器人 investigate order-service 最近15分钟 5xx` | 创建调查 |
| `status` | `@机器人 status INC-1024` | 返回当前状态 |
| `add-context` | `@机器人 add-context INC-1024 刚完成库存服务发布` | 添加人工上下文 |
| `cancel` | `@机器人 cancel INC-1024` | 请求取消调查 |
| `report` | `@机器人 report INC-1024` | 返回复盘报告链接 |
| `help` | `@机器人 help` | 返回可用命令 |

命令解析流程：先移除机器人 mention，再用确定性解析器识别命令和 Incident ID；只有自然语言调查描述交给模型提取服务、环境和时间范围。缺少关键参数时回复简短问题，不猜测生产环境。

## 7. 卡片设计

### 7.1 事故卡片

固定展示：

- Incident 编号、严重级别、环境和服务。
- 当前状态和最近更新时间。
- 告警摘要、开始时间和重复次数。
- 调查阶段、已用时间和预算状态。
- 最新结论或下一步。
- “查看详情”“刷新”“取消调查”操作。

更新频率限制为关键状态变化或固定节流窗口，普通工具调用不逐条刷群。

### 7.2 诊断卡片

展示：

- 根因结论及置信度。
- 影响范围。
- 最多五条关键证据及可追溯链接。
- 已排除的重要假设。
- 建议动作、风险等级和预期影响。

### 7.3 审批卡片

审批按钮上方必须明确展示：

- 执行动作和目标环境。
- 具体服务、版本或实例范围。
- 风险等级、超时时间和回滚方式。
- 触发该建议的证据。
- 审批有效期。

处理后原卡片改为不可操作状态，并显示审批人、决定和时间。飞书更新失败不回滚数据库中的真实审批结果，Worker 将继续重试更新消息。

## 8. 身份、权限与群绑定

### 8.1 身份映射

`feishu_identities` 保存：

| 字段 | 说明 |
| --- | --- |
| `tenant_key` | 飞书租户标识 |
| `open_id` | 应用内用户标识 |
| `user_id` | OpsPilot 内部用户 ID |
| `display_name` | 展示名，可选缓存 |
| `status` | ACTIVE / DISABLED |

权限由 OpsPilot 服务端角色和服务归属配置决定，不把飞书群管理员等同于系统审批人。

### 8.2 群绑定

`chat_bindings` 配置群聊允许操作的环境与服务：

```json
{
  "chat_id": "oc_xxx",
  "allowed_environments": ["demo", "staging"],
  "allowed_services": ["order-service", "inventory-service"],
  "notification_severity": ["P0", "P1", "P2"]
}
```

MVP 默认禁止从飞书触发任何 production 动作。

## 9. 幂等、顺序与重试

- 入站事件唯一键：`provider + tenant_key + event_id`。
- 告警唯一键：Alertmanager fingerprint 加环境和来源。
- 出站消息使用 Outbox；数据库提交后 Worker 才能发送。
- Outbox 任务包含业务幂等键，例如 `incident:{id}:state:{version}`。
- 429 和可恢复的 5xx 使用指数退避加随机抖动，并尊重服务端重试提示。
- 4xx 参数错误进入死信状态并产生运维告警，不无限重试。
- 同一 Incident 的卡片更新按领域版本处理，旧版本任务不能覆盖新状态。
- 回调可以乱序；所有状态变更都校验当前状态与资源版本。

## 10. 安全校验

实现阶段必须依据飞书当前官方文档完成签名、时间戳、随机数、验证 Token 和加密载荷校验，并以官方测试请求建立固定测试样例。

通用规则：

- 验签使用原始请求体，验签前不重新序列化 JSON。
- 拒绝超出允许时间窗口的请求，降低重放风险。
- 使用常量时间比较验证签名或 Token。
- 未通过校验的请求不进入事件表，不回显具体失败细节。
- 卡片值、用户输入、群消息和 Runbook 都属于不可信输入。
- 外部链接只允许系统配置的域名，避免在卡片中输出危险链接。
- 审批动作必须留下不可变审计记录。

## 11. 可观测性

### 11.1 指标

- `feishu_events_total{type,result}`
- `feishu_event_processing_seconds{type}`
- `feishu_api_requests_total{operation,result}`
- `feishu_api_request_seconds{operation}`
- `feishu_api_rate_limited_total{operation}`
- `feishu_outbox_pending`
- `feishu_card_action_total{action,result}`
- `approval_decision_total{decision,risk}`

### 11.2 结构化日志字段

`trace_id`、`event_id`、`tenant_key_hash`、`chat_id_hash`、`message_id`、`incident_id`、`operation`、`result`、`latency_ms`。

群消息正文默认不写普通日志；调试环境如需记录，必须显式开启并执行脱敏。

## 12. 测试计划

### 12.1 单元测试

- URL 验证、签名和解密的成功/失败样例。
- mention 清理和六种命令解析。
- 卡片动作 Schema 与未知动作拒绝。
- 访问令牌缓存、提前刷新和并发单飞。
- 飞书错误码到内部错误的映射。

### 12.2 集成测试

- 同一事件投递三次，只创建一个任务。
- 相同告警多次触发，只更新同一事故卡片。
- 429 后按策略重试，最终只出现一条业务消息。
- 两人同时审批，只有一个决定生效。
- 过期卡片按钮不会执行动作，并返回当前状态。
- 数据库提交成功、飞书暂时失败时，Outbox 最终补发。

### 12.3 沙箱验收

- 测试群中 `@机器人 help` 能在 3 秒内响应或确认接收。
- 告警触发后出现一张事故卡片，调查结果保持在同一线程。
- 审批前执行器调用数为零。
- 审批后动作只执行一次，卡片显示最终状态。
- 撤销机器人权限后，系统产生清晰告警而非静默丢消息。

## 13. 实施顺序

1. 建立 `FeishuEventEnvelope`、标准化事件和 Fake Adapter。
2. 完成 URL 验证、验签/解密与事件幂等落库。
3. 实现令牌提供器和发送文本消息，验证最小权限。
4. 实现事故卡片及消息引用持久化。
5. 接入机器人命令和线程回复。
6. 实现卡片动作、身份映射和审批事务。
7. 加入 Outbox、限流重试、卡片版本控制和指标。
8. 用真实飞书测试群完成端到端验收并固定请求样例。

## 14. 待验证项

以下细节在编码前以飞书开放平台当前文档和测试应用为准，并通过适配器隔离变化：

- 事件回调加密模式下的具体请求包格式。
- 当前交互卡片版本、更新消息接口及响应结构。
- 应用所需权限的准确权限标识。
- 各消息接口的限流配额和可重试业务错误码。
- 线程回复中 `root_id`、`parent_id` 的具体行为。

这些待验证项不影响领域模型和内部接口设计，但属于飞书适配器进入完成状态前的强制验收内容。
