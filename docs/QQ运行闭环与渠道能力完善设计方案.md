# QQ 运行闭环与渠道能力完善设计方案

> 版本：v1.1  
> 日期：2026-10-06  
> 状态：阶段 1–5 已实施并验证；多账号并行与官方 QQ Bot 待后续实施  
> 范围：只处理当前最高的两个优先级——运行闭环与 QQ 渠道能力；不扩展为通用插件平台或多租户系统。
> 后续：多账号、群消息调度、合并转发、STT/TTS 与官方 Bot 见[QQ 高级能力与多账号设计方案](QQ高级能力与多账号设计方案.md)。

## 1. 结论

当前 QQ 链路已经完成真实端到端验证：NapCat Docker 能连接知语，真实消息可以触发 Agent，并把回复成功发送回 QQ。下一步不应继续增加外围功能，而应先把这条链路变成可长期运行、可恢复、可管理的产品能力。

本方案作出以下决定：

1. `zhiyu serve` 成为唯一推荐的常驻进程，统一托管 Web、QQ、后台任务和优雅退出。
2. 入站事件改为带租约的持久状态机；进程重启后可恢复未完成工作，但不会冒险自动重发结果未知的 QQ 消息。
3. NapCat Docker 是 macOS 上 OneBot 接入的标准测试与部署方式，并提供可复现、固定版本的 Compose 配置。
4. 在现有统一消息组件上真正接通 QQ 图片、语音、文件、@、引用和长消息，而不是再建一套消息模型。
5. 数据模型和内部接口先补齐账号命名空间，但当前里程碑只启用一个 QQ 账号，不提前建设多账号管理界面。
6. 群聊采用显式白名单和按群工具权限，默认拒绝，不改变“单用户 Personal Agent”的产品边界。
7. QQ 官方 Bot 与 OneBot 共用应用层协议，但使用独立驱动。当前只定义驱动边界，不实现未经真实凭据验证的官方协议。

`zhiyu qq listen` 暂时保留为诊断命令，但不得与 `zhiyu serve` 同时监听同一端口。后续稳定一个版本后再考虑废弃。

### 1.1 本版确认的产品边界

用户没有另行指定时，本方案按以下默认值实施：

- 部署目标是当前 macOS 单机；NapCat 运行在 Docker Desktop，知语运行在宿主机。
- QQ 渠道只允许已配置的主人使用，包括群聊场景；不向群成员开放个人 Agent。
- 图片需要在所选模型支持视觉输入时被模型理解；语音第一版只收发，不做 STT/TTS。
- 当前只运行一个 NapCat/QQ 账号，但所有新增记录带账号命名空间，避免未来破坏性迁移。
- WebUI 只读展示运行状态和错误；配置变更、事件 replay、失败投递重试由 CLI 完成。
- 临时媒体默认保留 7 天，且总量上限为 1 GiB；超限时优先删除最早且未被长期资产引用的文件。
- QQ 官方 Bot 和真正的多账号并行运行进入后续待办，不属于本轮完成条件。

## 2. 当前基线

### 2.1 已经可用

- OneBot v11 反向 WebSocket 私聊文本收发。
- Token 鉴权、事件去重、OneBot `echo` 回执和投递记录。
- 单主人权限、可选群聊和群内必须 @。
- 同会话串行、不同会话并行。
- QQ Session 与本机 Session 共享 local identity 的长期记忆。
- NapCat Docker 到知语的真实链路已经验证，事件、投递和 Agent Run 均成功落库。
- 统一消息层已经定义文本、图片、语音、文件、@ 和引用组件。

### 2.2 初稿时尚未完成（历史基线）

以下内容记录本方案实施前的问题，不代表当前实现状态。当前阶段完成情况以[第 14 节实施结果](#14-实施结果)为准。

- `RuntimeHost.start()` 不会自动启动已配置渠道；Web 状态与独立 `qq listen` 进程的真实连接状态不一致。
- 事件只有 `claim / complete / fail`，进程崩溃可能让事件永久停在 `processing`。
- Agent 已完成、投递未确认时，没有可恢复的中间状态；直接重试可能重复调用模型或重复发 QQ。
- `ChannelManager`、`ChannelConfig` 和会话查询都按单个 `qq` 设计，不能安全支持多个账号。
- QQ 入站只提取文本，纯图片或纯文件事件会被丢弃；出站也只能发送文本。
- 群聊缺少群白名单、群级提示词和工具权限。
- Docker 当前依赖手工命令与 `latest` 镜像，无法稳定复现。

## 3. 目标与非目标

### 3.1 目标

完成后必须满足：

1. 运行 `zhiyu serve` 后，启用且设置自动连接的 QQ 账号自动启动，Web 与 CLI 显示同一份真实状态。
2. 在事件处理任意关键点杀死进程并重启，不丢失事件，也不重复创建 Agent Run。
3. 明确失败的投递可以人工重试；状态未知的投递不会自动重发。
4. 新机器按照仓库文档可启动固定版本 NapCat，扫码后完成真实 QQ 收发。
5. 图片、语音、文件、@、引用和长文本能经过统一消息协议处理；视觉模型能够接收图片，文本模型和音频场景有明确降级文本。
6. 每个群可单独启停、设置是否需要 @，并限制可用工具。
7. 渠道配置、会话、事件、投递和密钥均带账号命名空间，为后续多账号保留无破坏扩展路径。
8. OneBot 驱动不侵入 `ChatService`，未来官方驱动可以复用同一应用层接口。

### 3.2 非目标

- 不建设 AstrBot 式插件市场、通用工作流、多租户或陌生人公共机器人。
- 不让知语自动安装、升级或控制 Docker Desktop。
- 不承诺外部 QQ 平台上的严格 exactly-once；只能保证知语内部的幂等执行和保守投递。
- 不把 NapCat 二维码登录嵌入知语 WebUI，登录仍在 NapCat WebUI 完成。
- 第一里程碑不实现语音转写和语音合成供应商；先完整传输语音并提供稳定降级。STT/TTS 作为独立后续能力接入。
- 没有官方 AppID、密钥和已确认的开放平台权限前，不伪造或猜测官方 QQ Bot 协议实现。
- 本轮不实现多个 QQ 账号同时在线、账号切换或账号管理页面。
- 本轮不支持 Linux/NAS/服务器部署；迁移到无桌面环境前必须单独设计密钥存储和进程守护。

## 4. 总体架构

```text
zhiyu serve / RuntimeHost
├── Web API
├── ChannelManager
│   └── OneBotDriver(default) ← NapCat Docker
├── InboundPipeline
│   ├── 持久事件状态机
│   ├── 会话级串行队列
│   └── ChatService
├── DeliveryService
└── RecoveryWorker
```

不新增第二套 Runtime 或消息总线。现有 `RuntimeHost`、`ChannelManager`、`ChannelRouter` 和 `ChannelReliabilityService` 在原位置扩展职责：

- `RuntimeHost` 负责组件启动顺序与退出。
- `ChannelManager` 按 `channel_config_id` 管理适配器和状态。
- 渠道驱动只负责协议转换与收发，不直接操作 Agent。
- `InboundPipeline` 负责权限、幂等、排队和调用 Agent。
- `RecoveryWorker` 只扫描到期租约和可安全恢复的状态。
- Web、CLI 只调用同一应用服务，不各自维护连接状态。

未来增加第二个 OneBot 账号或官方驱动时，只向 `ChannelManager` 注册新的账号级驱动实例，不改变 Pipeline 和 `ChatService`。当前实现不得为了尚未启用的驱动引入插件发现或动态加载机制。

## 5. 优先级一：真实运行闭环

### 5.1 RuntimeHost 统一托管

启动顺序：

1. 初始化数据库和应用服务。
2. 加载 Skills、MCP 与记忆后台任务；单项失败记录为降级，不阻止 QQ 启动。
3. 查询 `enabled=true AND auto_connect=true` 的渠道账号。
4. 为每个账号创建驱动并独立启动；一个账号失败不影响其他账号。
5. 启动事件恢复任务。
6. Web 健康接口读取当前 Runtime 中的渠道快照。

退出顺序与启动相反。停止接收入站消息后，先给正在执行的任务一个有限的排空窗口，再取消任务、关闭连接和数据库资源。

`zhiyu qq listen` 复用同一个渠道应用服务，只作为前台诊断入口。端口被占用时必须立即输出占用地址、可能运行中的命令和解决方式，而不是静默等待。

### 5.2 事件状态机

事件状态调整为：

```text
pending → processing → responded → completed
               └──────→ failed
```

- `pending`：事件已落库，尚未领取。
- `processing`：Worker 已领取并持有租约，Agent 正在处理。
- `responded`：Agent 输出和待发送载荷已经持久化。
- `completed`：投递已得到明确成功或明确失败结果，事件处理闭环结束。
- `failed`：不可重试错误，或重试次数达到上限。

新增字段：

| 表 | 字段 | 用途 |
|---|---|---|
| `channel_events` | `channel_config_id` | 明确事件属于哪个渠道账号 |
| `channel_events` | `attempt_count` | Agent 处理尝试次数 |
| `channel_events` | `lease_owner` | 当前 Worker 标识 |
| `channel_events` | `lease_expires_at` | 崩溃后的恢复依据 |
| `channel_events` | `response_message_id` | 复用已生成的回复 |
| `channel_events` | `outbound_message_json` | 保存规范化后的待发送消息，重启后无需重新生成 |
| `channel_events` | `last_error` | 诊断与人工处理 |
| `agent_runs` | `channel_event_id` | 与事件一对一幂等关联，允许为空 |
| `channel_deliveries` | `retry_of_id` | 记录人工重试链 |
| `channel_deliveries` | `message_json` | 保存本次投递的不可变消息快照 |

`agent_runs.channel_event_id` 建唯一索引。重启后若事件已有成功的 Agent Run，系统直接读取已持久化回复，不能再次请求模型。

### 5.3 领取与恢复规则

1. 收到消息时先在短事务中插入 `pending` 事件，唯一键仍使用渠道、账号和外部事件 ID。
2. Worker 原子地领取 `pending` 或租约已过期的 `processing` 事件，写入租约和次数。
3. Agent 完成后，在同一事务中保存助手消息、结构化消息组件、待发送快照、关联 Agent Run，并把事件标记为 `responded`。
4. 发送成功后记录外部消息 ID并完成事件。
5. 外部平台明确返回失败时，记录 `failed` delivery 并完成事件；允许人工重试该 delivery。
6. 连接在发送后断开或超时时，delivery 标记为 `unknown`。它不会自动重发，因为平台可能已经收到消息。
7. 只有 Agent 调用前的临时故障和明确未发送的故障可以自动重试，最多三次；业务错误直接进入 `failed`。

内部保证是“一个事件最多对应一个有效 Agent Run”。外部 QQ 投递仍可能因网络边界出现重复或未知，这是协议事实，不能用不安全的自动重发掩盖。

### 5.4 运维接口

最小接口如下：

- CLI：`zhiyu channels status`、`zhiyu channels events`、`zhiyu channels replay EVENT_ID`。
- API：只读的渠道账号状态、事件列表与事件详情；本轮不暴露配置变更和重试写接口。
- `unknown` 投递只能在展示风险并显式确认后人工重试。
- 所有重试创建新的 delivery 记录并关联原记录，不覆盖历史。

本阶段不开发完整管理后台，只让现有 WebUI 能显示账号连接状态、最近错误和待处理/失败数量。Web API 和 WebUI 默认只绑定 loopback；在增加认证、CSRF 防护和审计前，程序必须拒绝把渠道管理接口暴露到非 loopback 地址。

### 5.5 Docker 固化

仓库新增 `deploy/napcat/compose.yaml` 和配套说明：

- 镜像使用实施时验证过的版本与 digest，不使用 `latest`。
- NapCat WebUI 仅绑定 `127.0.0.1`，默认端口 `6099`。
- 当前默认账号使用独立持久目录；未来增加账号时，每个账号必须使用独立数据目录、服务名和 WebUI 端口。
- Reverse WebSocket 指向 `ws://host.docker.internal:<port>/ws`。
- 知语监听非 loopback 地址时必须启用高强度 Token，并明确本机防火墙要求。
- Compose 配置健康检查和 `restart: unless-stopped`，登录数据放在持久卷中。
- 提供 `zhiyu qq doctor` 做只读检查：Docker 可达性、WebUI、反向 WS 地址、Token 配置和知语监听状态。它不执行 Docker 管理命令。

## 6. 优先级二：QQ 渠道能力

### 6.1 账号命名空间

继续使用现有 `channel_configs` 表，避免无必要的新表体系，但做如下迁移：

- 新增稳定的 `account_id`、`driver`、`display_name`、`enabled` 和 `auto_connect`。
- 删除 `channel` 单列唯一约束，改为 `(channel, account_id)` 唯一。
- 现有 QQ 配置迁移为 `account_id=qq-onebot-default`、`driver=onebot_reverse_ws`，行为不变。
- 当前 macOS 部署继续使用系统 Keychain（通过 Keyring 访问），Keyring key 加入 `channel_config_id`，数据库不保存明文 Token。

`Conversation` 新增 `channel_config_id` 和 `external_conversation_type`。渠道会话查询由原来的渠道与外部 ID，改为：

```text
(channel, channel_config_id, external_conversation_type, external_user_id)
```

为减少破坏，现有 `external_user_id` 字段暂不重命名；新代码将它解释为“外部会话键”。事件去重、群策略、媒体缓存和投递也必须携带 `channel_config_id`。

当前只允许一条启用的 QQ 配置。创建或启用第二条配置时，CLI 返回“当前版本尚不支持多账号并行”，不能静默覆盖默认账号。收到事件后还要校验 `self_id` 与配置账号一致，不匹配则拒绝处理并报警。

未来开放多账号时，每个 OneBot 账号使用单独监听端口。由于当前只支持 macOS 宿主机运行，Keychain 不可用时应直接给出可操作错误；不得自动回退到数据库明文或无加密配置文件。Linux/NAS 的 Secret Service、环境变量或密钥文件方案留到对应部署设计中决定。

### 6.2 结构化消息持久化

现有 `messages.content` 只能保存纯文本，不能作为富媒体恢复依据。本轮新增：

- `messages.parts_json`：可空的统一消息组件数组；旧消息为空时按单个 `TextPart(content)` 读取。
- `channel_media_assets`：保存媒体 ID、渠道配置、来源事件、受管相对路径、MIME、大小、SHA-256、创建和过期时间。
- `channel_events.outbound_message_json`：Agent 完成时生成的规范化出站消息快照。
- `channel_deliveries.message_json`：每次实际投递的不可变快照，长消息分片后每片单独记录。

`content` 继续保存可搜索、可展示的纯文本降级内容，不能删除。`parts_json` 只保存受管媒体 ID，不保存临时下载 URL、绝对路径、base64 正文或凭据。这样在 `responded` 状态重启后，可以原样恢复回复而不是再次调用模型。

### 6.3 富媒体协议转换

OneBot 入站段映射：

| OneBot 段 | 统一组件 | 处理规则 |
|---|---|---|
| `text` | `TextPart` | 保留原文本 |
| `at` | `MentionPart` | 保留目标 ID，识别是否 @ 当前机器人 |
| `reply` | `QuotePart` | 记录引用消息 ID，按需读取摘要 |
| `image` | `ImagePart` | 下载到受管媒体目录后引用 |
| `record` | `AudioPart` | 保存媒体并附带时长/格式；无 STT 时降级为描述 |
| `file` | `FilePart` | 保存安全元数据和受管文件引用 |

纯媒体消息不得因 `text` 为空而被丢弃。不支持的 OneBot 段忽略其危险载荷，但在诊断信息中保留段类型。

图片进入 Agent 前，根据所选 `ModelConfig.supports_vision` 决定处理方式：视觉模型接收规范化的文本与图片内容；不支持视觉的模型只接收安全占位描述。若模型被标记为支持视觉但 Provider 无法编码图片，请求必须明确失败并记录能力配置错误，不能静默丢图。

模型能力不通过名称猜测。确认 Provider 的模型确实支持 OpenAI 兼容图片输入后，使用 `zhiyu provider vision <provider名称> <model名称> --enabled` 显式开启；可用 `--no-enabled` 关闭。

出站时进行反向映射。模型只返回纯文本时仍按文本发送；应用层明确产生图片、音频或文件组件时才发送对应段。引用回复在驱动支持时添加 `reply` 段，不支持时降级为普通文本。

长文本在渠道驱动层按平台限制分片，优先在段落和句号处分割，顺序发送并分别记录 delivery。部分成功时不能把整组伪装成成功。

### 6.4 媒体安全

新增受管目录 `~/.zhiyu/media/<channel-config-id>/`，任何本地文件发送都必须来自该目录或经过显式导入。第一版采用固定安全上限，不提供无必要的配置项：

- 图片：20 MiB。
- 音频：50 MiB。
- 其他文件：100 MiB。

下载必须限制超时和重定向次数，校验 MIME 与实际文件头，清理文件名并计算 SHA-256。禁止协议载荷读取任意本机路径。日志和数据库不保存 base64 正文、访问 Token 或带凭据 URL。

数据库只保存媒体元数据、哈希、受管相对路径和过期时间。临时媒体默认保留 7 天，总量限制为 1 GiB；定时清理先按过期时间，再按最久未使用顺序删除。被未完成事件、未完成投递或长期资产引用的文件不得清理。作为长期记忆附件保留的文件必须单独提升为持久资产。

若当前模型不支持图片输入，`ChatService` 使用诸如“用户发送了 1 张图片”的安全文本说明，并向渠道状态暴露能力降级；不能把二进制或临时 URL 直接塞进提示词。语音在本轮一律以安全占位说明进入 Agent，但原始音频仍可按权限转发或下载。

### 6.5 群级策略

新增 `channel_group_policies`：

| 字段 | 含义 |
|---|---|
| `channel_config_id` | 所属账号 |
| `external_group_id` | QQ 群 ID |
| `enabled` | 是否允许使用 |
| `require_mention` | 是否必须 @ 机器人 |
| `tool_allowlist` | 允许的工具名集合 |
| `system_prompt` | 可选群级补充规则 |

唯一键为 `(channel_config_id, external_group_id)`。

执行规则：

1. 群聊默认拒绝，只有显式启用的群才进入 Agent。
2. 第一版仍只允许配置的主人 QQ 使用，避免把个人记忆暴露给群成员。
3. 群级工具集合必须与全局可用工具取交集，不能通过群策略扩大权限。
4. 群级提示词作为受信配置加入系统上下文，群消息正文永远不被解释为策略。
5. `/new`、`/stop`、`/status` 只对主人有效，并作用于当前账号和群会话。

CLI 提供 `zhiyu qq groups allow/deny/list`。WebUI 只读展示生效策略，不提供修改入口，也不增加复杂角色权限模型。

### 6.6 驱动边界与官方 QQ Bot

定义小型驱动协议，不建立通用插件系统：

```python
class ChannelDriver(Protocol):
    async def start(self, on_event: InboundHandler) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, target: DeliveryTarget, message: UnifiedMessage) -> DeliveryReceipt: ...
    def status(self) -> ChannelStatus: ...
```

现有 QQ Adapter 成为 `onebot_reverse_ws` 驱动。后续 `qq_official` 驱动只实现：

- 官方 Gateway 鉴权、心跳、重连和 Resume。
- 官方事件到统一消息的映射。
- 官方目标与媒体发送 API。
- AppID/Secret 和 Token cache 的账号级隔离。

官方 OpenID、OneBot QQ 号和内部 identity 是不同命名空间，禁止直接互换。当前 QQ 主人仍直接使用 local identity。实施官方驱动前，必须新增 `external_identity_bindings`，以 `(driver, channel_config_id, external_user_id)` 唯一定位外部身份，并显式关联内部 `identity_id`；不得继续依赖现有 `(channel, external_user_id)` 唯一约束。只有用户完成授权绑定后，才允许两个外部身份关联到同一个 local identity。

官方驱动的实施依赖真实开放平台凭据、已开通的事件权限和实施时有效的官方文档；这些条件不阻塞 OneBot 运行闭环上线。

## 7. 数据迁移

迁移必须兼容现有数据，步骤如下：

1. 为现有渠道配置补齐默认账号与驱动字段。
2. 重建 SQLite 的渠道配置唯一索引，从 `channel` 改为 `(channel, account_id)`。
3. 为现有 QQ 会话补写默认 `channel_config_id`；会话类型优先从现有会话键和已保存事件推断，无法可靠判断时停止迁移并输出记录 ID，不得擅自按私聊处理。
4. 为消息补充可空 `parts_json`；旧记录按纯文本兼容读取，不批量重写历史消息。
5. 为事件、投递和 Agent Run 增加关联字段、消息快照与索引。
6. 旧的 `completed` / `failed` 事件保持终态；迁移时遗留的 `processing` 事件转为 `pending`，由新 Worker 安全检查后领取。
7. 迁移前自动备份 SQLite 数据库；迁移脚本必须可在备份副本上重复验证。

不删除旧消息，不改变已有 Session ID，也不重写长期记忆文件。

## 8. 分阶段实施

### 阶段 1：Runtime 所有权与状态一致

改动：

- `RuntimeHost` 自动启动和停止渠道。
- `ChannelManager` 按配置 ID 管理实例与状态。
- `serve`、CLI 和 Web 共用状态来源。
- `qq listen` 增加端口冲突的明确错误。

验证：启动 `serve` 后 NapCat 自动连接；Web 和 CLI 均显示 connected；停止进程后端口释放且任务退出。

### 阶段 2：可恢复事件执行

改动：

- 增加事件租约、响应持久化、Agent Run 幂等关联和 RecoveryWorker。
- 增加失败事件查看与人工 replay。
- 区分 `failed` 与 `unknown` delivery。

验证：分别在领取后、模型完成后、发送中杀死进程，重启后事件状态正确且不重复调用模型；未知投递不自动重发。

### 阶段 3：NapCat Docker 固化

改动：

- 增加固定镜像的 Compose、环境模板和操作文档。
- 增加只读 `qq doctor`。

验证：清空测试部署后，仅按文档即可重新启动、扫码、重启容器并保持登录，完成真实私聊往返。

### 阶段 4：富媒体与长消息

改动：

- 接通 OneBot 多段消息解析与发送。
- 增加结构化消息持久化、媒体缓存、安全校验、视觉模型输入、能力降级和长消息分片。

验证：文本+图片和纯图片可被视觉模型理解；文本模型收到明确降级内容；语音、文件、@、引用和超长文本分别完成单元测试与真实 QQ 冒烟测试；重启后仍能从消息快照恢复富媒体回复。

### 阶段 5：群级策略

改动：

- 群白名单、必须 @、工具白名单和群级命令。
- 在 Chat 请求中传递经过验证的工具集合。

验证：未授权群不创建 Agent Run；授权群只暴露允许工具；两个群的会话和规则互不影响。

### 后续阶段 6：多账号（本轮不实施）

改动：

- 完成配置、会话、事件、投递、密钥和状态的账号隔离。
- Compose 支持多个账号实例。

验证：两个真实或一个真实加一个协议模拟账号并行运行，同一个外部消息 ID 不冲突，回复不会发错账号。

### 后续阶段 7：官方 QQ Bot（本轮不实施）

改动：

- 在获得凭据后实现官方驱动及身份绑定。
- 使用与 OneBot 相同的 Pipeline、状态机和策略模型。

验证：Gateway 断线恢复、私聊/群聊、媒体和身份隔离均通过官方测试环境与真实账号验证。

## 9. 测试与验收矩阵

| 场景 | 必须结果 |
|---|---|
| `serve` 启动 | 自动连接启用账号，状态可从 Web/CLI 查询 |
| 单个账号启动失败 | 其他服务继续运行，健康状态为 degraded 并显示原因 |
| 重复收到同一事件 | 只存在一个事件和一个有效 Agent Run |
| `processing` 时崩溃 | 租约到期后恢复 |
| `responded` 时崩溃 | 复用已保存回复，不再次调用模型 |
| 发送超时 | delivery 为 `unknown`，不自动重发 |
| 明确发送失败 | 可人工重试，保留完整重试链 |
| 纯图片事件 | 视觉模型收到图片；文本模型收到明确降级说明 |
| 富媒体回复后崩溃 | 从持久化组件和媒体引用恢复，不重复调用模型 |
| 恶意文件路径/超大媒体 | 在进入 Agent 前被拒绝并留下安全日志 |
| 媒体过期或超过 1 GiB | 只清理未被运行中事件、投递或长期资产引用的文件 |
| 未授权群或成员 | 不创建会话和 Agent Run |
| 群工具白名单 | Agent 看不到白名单外工具 |
| 尝试启用第二个 QQ 账号 | CLI 明确拒绝，不覆盖当前账号 |
| 非 loopback 管理访问 | 在尚无认证时拒绝启动或拒绝暴露管理接口 |
| Keychain 不可用 | 明确失败，不把 Token 降级保存为明文 |
| 旧数据库升级 | 历史会话、消息和记忆仍可访问 |

每个阶段都必须通过现有完整测试集，并新增对应单元测试、数据库迁移测试和至少一次真实 QQ 冒烟测试。真实测试日志必须脱敏，不提交 Token、二维码、QQ 号或消息正文。

## 10. 预计代码落点

- `src/zhiyu/application/runtime.py`：渠道与恢复任务生命周期。
- `src/zhiyu/application/channels.py`：账号级配置、启动和状态服务。
- `src/zhiyu/application/inbound.py`：租约状态机与恢复入口。
- `src/zhiyu/channels/manager.py`：多实例管理。
- `src/zhiyu/channels/qq/adapter.py`：OneBot 富媒体转换和账号校验。
- `src/zhiyu/channels/`：小型驱动协议、媒体与投递公共类型。
- `src/zhiyu/infrastructure/database/models.py` 与新迁移：账号、消息组件、媒体、事件、投递和群策略关联。
- 现有 API 路由目录：只读状态与事件查询接口。
- `deploy/napcat/`：固定版本 Compose 与操作说明。

文件名在实施时可以按现有项目风格微调，但不得借本方案进行无关目录重构。

## 11. 风险与取舍

- **外部 exactly-once 不可实现**：发送请求成功但回执丢失时，只能标记未知并让用户决定是否重发。
- **SQLite 并发边界**：当前单机个人 Agent 可继续使用 SQLite；若将来扩展为多进程 Worker，再单独评估 PostgreSQL，不提前引入。
- **媒体安全与隐私**：媒体比文本更容易携带敏感信息和恶意内容，必须限制来源、大小、类型和保留时间。
- **视觉模型差异**：图片理解取决于当前 Provider 和模型能力；必须通过显式能力字段选择编码路径，不能靠模型名称猜测。
- **Docker 供应链**：固定 digest 可复现，但升级必须人工验证 QQ/NapCat 兼容性。
- **官方 API 变化**：官方驱动只依赖驱动接口，不让 Gateway 细节扩散到应用层。
- **共享个人记忆**：多账号只是多个入口，不是多个用户。未绑定且未授权的发送者永远不能访问 local identity。
- **部署范围**：本方案验证 macOS + Docker Desktop；无桌面 Linux 上的密钥后端、守护进程和网络暴露不在本轮保证范围内。

## 12. 与现有文档的关系

- 本文覆盖并细化[QQ 接入设计方案](QQ接入设计方案.md)中尚未完成的 OneBot 运行闭环、富媒体、群策略和多账号部分；冲突时以本文为准。
- 本文延续[AstrBot 式消息平台重构设计方案](AstrBot式消息平台重构设计方案.md)已经实现的统一消息、Pipeline、回执和并发基础，不重复建设。
- Personal Agent 的身份、Session 和记忆边界仍以[单机个人 Agent 多 Session 共享记忆设计方案](单机个人Agent多Session共享记忆设计方案.md)为准。

## 13. 完成定义

前两个优先级只有同时达到以下条件才算完成：

1. `zhiyu serve` 可以长期托管真实 QQ 链路，不依赖另开 `qq listen`。
2. 三个崩溃注入测试证明事件可恢复、Agent 不重复执行、未知投递不自动重发。
3. NapCat Docker 部署可以在干净环境按文档复现，并固定镜像版本。
4. QQ 富媒体、图片理解、群策略和账号命名空间通过自动化测试与真实冒烟测试。
5. 迁移不丢失现有会话、消息、记忆、渠道事件和投递记录。
6. 仓库不包含任何真实凭据或未脱敏的 QQ 数据。
7. Web 管理能力保持 loopback 只读，Keychain 不可用时不会降级保存明文密钥。

真正的多账号并行运行和 QQ 官方 Bot 由后续阶段单独验收，不作为本轮完成条件。

## 14. 实施结果

2026-10-06 已完成阶段 1–5：

- `zhiyu serve` 已统一托管 QQ，实际 NapCat Reverse WebSocket 状态为 connected，不再需要独立 `qq listen`。
- 数据库已迁移到 `0017_qq_runtime_closure`，迁移前自动备份保留；原有事件与会话数据未丢失。
- 事件租约、过期恢复、Agent Run 幂等复用、出站快照、未知投递保护和人工 replay/retry 已实现。
- OneBot 图片、语音、文件、@、引用及长文本分片已接入统一消息；图片可按显式模型能力进入视觉模型，语音按本版边界降级为说明。
- 群白名单、必须 @、工具白名单与群级系统提示已实现，Web 保持只读、CLI 负责修改。
- NapCat Compose 已固定为真实验证过的镜像 digest，`qq doctor` 可只读检查配置、监听与容器状态。
- 自动化测试共 201 项通过，Compose 配置校验、Python 编译检查和真实运行健康检查通过。
