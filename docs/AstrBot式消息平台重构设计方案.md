# AstrBot 式消息平台重构设计方案

> 版本：v1.0
> 日期：2026-10-05
> 状态：已实施（2026-10-05）
> 参考范围：AstrBot `4.29.0-beta.1`，提交 `42972e932a64f01d96e2e0708579b0f79dd6f792`

## 1. 决策

星栖借鉴 AstrBot 的消息平台骨架，但不改造成 AstrBot 的缩小复刻。

本次重构只吸收五类已经被 AstrBot 验证有效的能力：

1. 统一的富媒体消息模型。
2. 有明确顺序、可测试的消息处理流水线。
3. 统一管理渠道、后台任务和应用服务的常驻运行宿主。
4. 可靠的消息接收、去重、并发控制、发送回执与失败记录。
5. 面向聊天、记忆和运行状态的最小 Web 管理界面。

星栖继续以“单用户 Personal Agent”为边界，并保留自己的核心优势：

- Markdown-first 长期记忆。
- core / episodic 分层与混合召回。
- 记忆整合、遗忘、纠正和召回证据。
- 本机与获准渠道 Session 共享个人身份，但不共享原始 transcript。

本方案不直接复制 AstrBot 源码。AstrBot 使用 AGPL-3.0-or-later；实现时只参考架构思想和公开接口行为，所有代码在星栖中独立实现。

## 2. 实施前基线问题

本节记录 2026-10-05 重构前的代码基线，便于解释后续设计取舍；其中列出的核心问题已由第 11 节对应阶段处理。

### 2.1 消息模型过窄

当前 `IncomingMessage` 只有渠道、用户、会话、文本和无结构 `metadata`，无法稳定表达：

- 群聊和私聊。
- 多渠道账号。
- 图片、语音、视频和文件。
- @、引用、回复和消息 ID。
- 渠道事件时间、机器人账号和投递目标。

继续向 `metadata` 填充字段会让渠道差异泄漏到 `ChannelRouter` 和 `ChatService`。

### 2.2 渠道抽象仍然硬编码 QQ

`ChannelManager`、`ChannelRouter.new_session()` 和 `ChatService` 中存在 QQ 特判。当前抽象可以支撑一个 OneBot 私聊入口，但还不能支撑第二种渠道或第二个 QQ 账号。

### 2.3 接收与发送没有可靠闭环

当前 OneBot 实现只有 WebSocket `send()`，没有：

- `echo` 请求与响应关联。
- 发送返回码检查。
- 消息 ID 持久化去重。
- 同一会话串行、不同会话并行。
- 失败投递记录和有限重试。
- 进程异常后的事件状态恢复。

### 2.4 Agent 调用期间持有数据库 Session

`ChatService.run()` 在模型请求和工具执行期间保留同步 SQLAlchemy Session。单用户 CLI 阶段影响有限，但进入 Web、群聊或多渠道并发后，会延长连接占用和事务生命周期。

### 2.5 扩展和上下文能力仍是最小实现

- Skills 通过 bigram 匹配后把完整正文注入 system prompt，容易误触发和浪费上下文。
- MCP 连接只存在于进程内，没有持久化配置、自动恢复和权限策略。
- Provider 没有 fallback 链和标准重试。
- 上下文按字符数估算并丢弃旧消息，没有摘要压缩。

## 3. 目标与非目标

### 3.1 目标

完成本方案后，星栖应满足：

1. CLI、TUI、QQ 和 Web 共用同一个消息与 Agent 应用协议。
2. 新增消息类型时不修改 `ChatService` 的核心签名。
3. QQ 收发具备去重、回执、超时和按会话并发控制。
4. 网络调用期间不长期持有数据库 Session。
5. 常驻进程统一管理渠道、记忆 Worker、MCP 和退出清理。
6. WebUI 能完成聊天、会话、记忆和运行状态管理。
7. 现有 CLI、QQ 私聊和长期记忆语义保持兼容。

### 3.2 非目标

本轮不实现：

- 插件市场和远程插件自动安装。
- 十几个聊天渠道。
- 企业多租户和复杂角色权限。
- OpenClaw 式手机节点、远程桌面和设备控制。
- 多 Agent swarm。
- 全量复制 AstrBot 的配置系统与历史插件 API。
- 第一阶段直接支持所有富媒体的真实收发。

统一消息模型会预留富媒体结构，但每种渠道能力仍按实际需求逐项实现。

## 4. 总体架构

```text
CLI / TUI ───────────────┐
QQ / future channels ────┼── RuntimeHost
Web API / WebUI ─────────┘       │
                                 ├── ChannelManager
                                 ├── MemoryJobProcessor
                                 ├── MCPManager
                                 └── InboundPipeline
                                          │
                     policy → dedup → session → command/agent
                                          │
                                      ChatService
                                          │
                     Provider · Tools · Skills · Memory
                                          │
                                  render → delivery
```

### 4.1 RuntimeHost

新增 `RuntimeHost` 作为生命周期容器，负责：

- 创建和持有 Manager、Service 与 Worker。
- 按顺序启动数据库检查、Skills、MCP、记忆 Worker 和渠道。
- 统一处理退出信号和资源清理。
- 暴露健康状态快照。

它不是全局 Service Locator。业务对象仍通过构造函数显式注入，避免继续增加 `default_manager` 一类隐藏全局状态。

CLI 在早期可以继续直接调用应用服务；`zhiyu serve` 和 Web API 使用 `RuntimeHost`。不要求第一阶段把 CLI 强制改成 HTTP 客户端。

### 4.2 线性流水线

不复制 AstrBot 的递归洋葱调度器。星栖采用有序、线性的异步 Stage：

```python
class InboundStage(Protocol):
    async def process(self, context: InboundContext) -> StageDecision: ...
```

`StageDecision` 只有三种结果：

- `continue`：进入下一阶段。
- `respond`：跳过 Agent，直接生成回复，例如 `/new`。
- `stop`：拒绝或忽略事件，不发送回复。

首期固定顺序：

```text
PolicyStage
→ DedupStage
→ SessionStage
→ CommandStage
→ AgentStage
→ RenderStage
→ DeliveryStage
```

新增 Stage 必须对应真实需求，不提供运行时任意排序和复杂依赖图。

## 5. 统一消息模型

### 5.1 入站事件

```python
class InboundEvent(BaseModel):
    event_id: str
    channel: str
    account_id: str
    conversation_id: str
    conversation_type: Literal["private", "group", "channel"]
    sender_id: str
    sender_name: str | None = None
    message_id: str | None = None
    reply_to_id: str | None = None
    mentioned_agent: bool = False
    parts: list[MessagePart]
    received_at: datetime
    raw: dict = Field(default_factory=dict)
```

`event_id` 是星栖内部事件 ID；`message_id` 是渠道提供的原始消息 ID。渠道没有消息 ID 时，Adapter 使用稳定字段计算幂等键，并明确标记其可靠级别。

### 5.2 消息组件

第一阶段定义以下组件：

```text
TextPart
ImagePart
AudioPart
FilePart
MentionPart
QuotePart
```

第一阶段只有 `TextPart` 必须完成端到端收发；其他组件需要完成解析、序列化和“不支持时安全降级”，不要求立即接入模型多模态。

文件和媒体统一使用受控资源引用，不允许 Adapter 把任意本地路径直接交给 Agent：

```python
class MediaRef(BaseModel):
    source: Literal["remote", "managed_file", "inline"]
    value: str
    mime_type: str | None
    size: int | None
```

### 5.3 出站消息与回执

```python
class OutboundMessage(BaseModel):
    conversation_id: str
    reply_to_id: str | None = None
    parts: list[MessagePart]

class DeliveryReceipt(BaseModel):
    delivery_id: str
    status: Literal["sent", "failed", "unknown"]
    provider_message_id: str | None = None
    error: str | None = None
```

`ChannelDriver.send()` 返回 `DeliveryReceipt`，不再以 WebSocket 写入成功等同于渠道发送成功。

## 6. 渠道接口

```python
class ChannelDriver(Protocol):
    account_id: str
    channel: str

    async def start(self, emit: Callable[[InboundEvent], Awaitable[None]]) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, message: OutboundMessage) -> DeliveryReceipt: ...
    def health(self) -> ChannelHealth: ...
```

`ChannelManager` 改为按 `account_id` 管理实例：

```text
drivers[account_id]
states[account_id]
tasks[account_id]
```

当前 OneBot 配置迁移为一个固定账号 `qq-onebot-default`。真正的多账号配置推迟到出现第二个实际账号需求时再开放 UI。

## 7. 可靠消息处理

### 7.1 数据表

新增 `channel_events`：

```text
id
channel
account_id
external_event_id
conversation_key
payload_json
status              received / processing / completed / failed
attempts
last_error
received_at
completed_at
```

唯一约束：

```text
(channel, account_id, external_event_id)
```

新增 `channel_deliveries`：

```text
id
event_id
request_id
provider_message_id
status              pending / sent / failed / unknown
attempts
last_error
created_at
completed_at
```

消息正文仍保存在现有 `messages` 表。`channel_events` 只负责渠道幂等、处理状态和故障诊断，不复制完整会话模型。

### 7.2 并发模型

- 不同会话可以并行处理。
- 同一 `conversation_key` 严格串行。
- 使用进程内 per-key lock，不引入 Redis。
- 设置一个小型全局并发上限，默认 4。
- 同一事件重复到达时只允许产生一个 Agent Run。

第一版只保证单进程一致性；不支持多个星栖进程同时消费同一个渠道账号。

### 7.3 OneBot 回执

QQ Adapter 的接收循环必须同时分发：

- 入站事件。
- 带 `echo` 的 API 响应。
- 生命周期和心跳事件。

发送流程：

```text
创建唯一 echo
→ 注册 Future
→ WebSocket send
→ 等待对应响应
→ 检查 status / retcode
→ 写入 DeliveryReceipt
→ 超时后标记 unknown 或 failed
```

不能在业务消息处理协程中独占 WebSocket 接收循环，否则响应将无法被读取。

### 7.4 失败策略

- 模型调用失败：事件标记 `failed`，不自动无限重试，允许用户显式重试。
- 确认未发送的临时渠道错误：最多重试 2 次，指数退避。
- 发送结果未知：不得自动重发，避免用户收到重复消息。
- 重复入站事件：返回已处理状态，不再次调用 Agent。

## 8. ChatService 事务边界

把当前一次长 Session 改成三个短阶段：

```text
事务 A：加载/创建会话，写入用户消息，创建 AgentRun
关闭 Session

无数据库事务：构造上下文，调用模型和工具

事务 B：写入助手消息、Run 结果和记忆任务
关闭 Session

事务 C：更新渠道事件与投递状态
关闭 Session
```

上下文构造所需数据在事务 A 中读取成不可变输入。确实需要异步检索数据库时，使用独立短 Session，不把原 Session 跨越模型网络请求。

提交语义：

- 用户消息与 AgentRun 必须在调用模型前提交。
- 助手消息、Run 完成状态与记忆任务在同一事务提交。
- Agent失败时保留用户消息和失败 Run，不能留下伪造的助手消息。

## 9. 常驻服务与 Web API

### 9.1 服务入口

新增：

```bash
zhiyu serve
```

默认只监听 `127.0.0.1`。远程监听不属于首期；若以后开放，必须先增加认证、TLS部署说明和跨站请求防护。

### 9.2 最小 API

```text
GET    /api/health
POST   /api/chat
POST   /api/runs/{id}/cancel
GET    /api/conversations
GET    /api/conversations/{id}/messages
GET    /api/runs/{id}
GET    /api/memories
GET    /api/memories/search
PATCH  /api/memories/{id}
GET    /api/providers
GET    /api/channels
```

`POST /api/chat` 使用 SSE 输出现有 `run / step / tool / chunk / final / done` 事件，不再定义第二套 Agent流协议。

### 9.3 最小 WebUI

第一版只提供：

1. 对话列表与流式聊天。
2. Provider和当前模型状态。
3. QQ连接与最近错误。
4. 长期记忆列表、搜索、编辑和遗忘。
5. Agent Run步骤、工具调用和失败信息。

前端首期采用无构建或最小构建的静态应用，不为了模仿 AstrBot 引入复杂组件体系。界面确认需要复杂状态管理后再选择前端框架。

## 10. Agent、Skills 与 MCP 后续加固

这部分在消息平台稳定后实施，不阻塞前四个阶段。

### 10.1 Agent Runtime

- 为模型调用增加有限重试，只重试明确的瞬时错误。
- 支持有序 Provider fallback。
- 步骤预算耗尽时生成明确终止事件，不返回空回复。
- 记录输入、输出 token、耗时、Provider切换和工具耗时。
- 暂不实现通用 Subagent；深度召回继续使用现有专用路径。

### 10.2 上下文压缩

处理顺序：

```text
保留 system 与最近完整轮次
→ 超过阈值时摘要旧轮次
→ 摘要失败时按完整轮次截断
→ 最终仍超限时拒绝请求并返回可诊断错误
```

摘要作为会话派生数据保存，不写入个人长期记忆，也不替换原始消息。

### 10.3 Skills

从“自动注入完整正文”改为渐进加载：

1. system prompt 只展示 Skill 名称和简短描述。
2. Agent 通过内部 `read_skill(name)` 工具获取正文。
3. Skill 可以启用或禁用。
4. Skill声明所需工具和权限；缺失时不进入可用列表。

第一版不提供远程安装和依赖自动执行。

### 10.4 MCP

- 持久化 server配置，但秘密仍存 Keyring。
- RuntimeHost启动时连接启用的服务器。
- 断开后有限重连并展示健康状态。
- 按服务器设置工具 allowlist。
- 记录每次调用属于哪个 MCP Server。

## 11. 分阶段实施

### Phase 1：统一消息模型与线性 Pipeline

状态：已完成。

变更范围：

- 新增 `channels/messages.py`。
- 新增 `channels/pipeline.py`。
- 改造 `ChannelAdapter`、`ChannelRouter` 和 QQ文本映射。
- 保持 CLI/TUI 的 `ChatRequest(message=str)` 兼容入口。

验收：

- 现有 QQ私聊文本行为不变。
- 文本、图片、语音、文件、@和引用组件可序列化往返。
- Pipeline阶段顺序、短路和异常传播有单元测试。
- `ChatService` 不再判断 QQ消息格式。

### Phase 2：QQ可靠收发与并发

状态：已完成。

变更范围：

- 增加 `channel_events`、`channel_deliveries` 和迁移。
- OneBot接收循环支持事件/响应分流。
- 实现 `echo` 回执、超时、去重和 per-conversation lock。
- 增加群聊文本和 @触发，但默认关闭。

验收：

- 同一个 OneBot事件重复发送两次，只产生一个 Agent Run。
- 慢 Agent不阻塞发送回执读取。
- 同一会话消息严格有序，不同会话可以并行。
- `retcode != 0`、超时和断线在投递状态中可见。
- 未授权群聊不会调用 Agent或高风险工具。

### Phase 3：RuntimeHost 与事务缩短

状态：已完成。

变更范围：

- 新增应用生命周期宿主。
- 移除新增路径中的全局默认 Manager依赖。
- 重构 ChatService事务边界。
- 统一记忆 Worker、MCP和渠道的启动停止。

验收：

- 模型和工具执行期间没有长期占用的数据库 Session。
- 连续启动和停止不会遗留后台 Task或连接。
- CLI、TUI和QQ仍使用同一个 ChatService行为。
- 进程退出时渠道、MCP和记忆 Worker有序关闭。

### Phase 4：本地 API 与最小 WebUI

状态：已完成首版。

变更范围：

- 增加 `zhiyu serve`。
- 增加薄 API层和静态 WebUI。
- 复用现有 ChatService、Memory服务和 Agent事件。

验收：

- Web聊天可以流式显示正文、工具调用和错误。
- CLI创建的会话能在 Web查看并继续。
- Web能够搜索和修正长期记忆。
- 默认只监听回环地址，页面和 API不暴露完整密钥。

### Phase 5：上下文与扩展可靠性

状态：已完成首版。

变更范围：

- 上下文摘要压缩。
- Provider fallback与使用量记录。
- Skills渐进加载。
- MCP配置持久化、重连和工具策略。

验收：

- 长会话超过阈值后仍能保留近期完整上下文和旧历史摘要。
- 主 Provider瞬时失败时按配置切换，Run记录切换原因。
- 未被读取的 Skill正文不进入上下文。
- MCP重连或失败不会拖垮聊天主流程。

## 12. 文件改动规划

目标结构：

```text
src/zhiyu/
  application/
    runtime.py                 # RuntimeHost
    chat.py                    # 缩短事务边界
    inbound.py                 # 渠道事件用例
  channels/
    messages.py               # 统一消息组件
    pipeline.py               # 线性 Stage
    delivery.py               # 回执与投递策略
    manager.py                # 按 account 管理 Driver
    qq/
      adapter.py              # OneBot协议解析与事件/响应分流
  infrastructure/database/
    repositories/
      channel_event_repository.py
      channel_delivery_repository.py
  api/                        # 本地 FastAPI 与 SSE
  web/                        # 无构建静态 WebUI
```

## 13. 兼容与迁移

- 原 `IncomingMessage` 在 Phase 1保留一个版本的兼容转换器，内部立即转换成 `InboundEvent`。
- 现有 QQ配置自动映射为 `qq-onebot-default`，不要求用户重新配置 Token。
- 现有 Conversation、Identity、Message和Memory ID不变。
- 本机、TUI与主人 QQ继续共享 local identity。
- 数据库迁移只能新增表和可空字段，不重写已有聊天记录。
- 每个 Phase单独提交迁移和测试；前一阶段验收通过后才开始下一阶段。

## 14. 风险与控制

### 14.1 抽象过度

控制：只实现 OneBot和本地入口当前需要的接口。没有第二个真实实现前，不建立 Provider式插件工厂或运行时依赖图。

### 14.2 一次重构范围过大

控制：先增加兼容转换器，再逐步迁移 QQ；不同时重写消息模型、WebUI和插件系统。

### 14.3 重复消息或重复回复

控制：先落库去重，再调用 Agent；发送结果未知时不自动重发。

### 14.4 富媒体带来的文件安全

控制：媒体必须进入应用管理目录，限制大小、类型、下载时间和来源；在对应功能实施前单独补充威胁模型。

### 14.5 参考项目许可证

控制：不复制 AstrBot代码和测试；设计文档记录参考版本，实施代码保持独立来源。

## 15. 总体验收

全部阶段完成后：

- `uv run pytest -q` 和 `uv build` 通过。
- CLI、TUI、QQ和Web共用同一套应用服务与 Agent事件。
- QQ支持可靠私聊文本、可控群聊文本、消息去重和发送回执。
- 同一会话有序、不同会话并行，重复事件不会重复调用模型。
- 数据库 Session不跨越模型和工具的长时间网络调用。
- WebUI可以管理聊天、记忆、Provider、渠道状态和 Agent Run。
- 长会话具有摘要压缩，Skills按需加载，MCP能够恢复连接。
- 不破坏现有长期记忆、身份映射和历史消息。

## 16. 与现有文档的关系

- [QQ接入设计方案](QQ接入设计方案.md)继续描述 QQ官方 Bot和 OneBot双驱动的渠道产品设计；本方案提供其共用的平台基础。
- [AstrBot QQ接入对照](astrbot-qq-reference.md)保留为 OneBot源码核实记录。
- [运行可靠性优化设计方案](运行可靠性优化设计方案.md)已经完成的模型能力、记忆任务重试和 QQ监听鉴权继续有效。
- [CLI优先开发设计方案](CLI优先开发设计方案.md)仍然有效；Phase 4 已按其边界重新引入薄 Web API 层。

## 17. 实施结果

截至 2026-10-05，五个阶段均已完成首版：统一消息组件和 Pipeline、OneBot 可靠收发、RuntimeHost、短数据库事务、本地 WebUI、上下文摘要、Provider fallback、Skills 按需加载，以及 MCP 配置恢复和工具白名单均已落地。

富媒体目前只完成统一数据结构，尚未接通 QQ 真实图片、语音和文件收发；插件市场、多账号、官方 QQ Bot 与远程管理仍保持在非目标范围。
