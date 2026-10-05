# QQ 接入设计方案

> 版本：v1.2
> 日期：2026-10-05
> 目标：把当前“手填 OneBot WebSocket 地址”升级为类似 OpenClaw 的“扫码绑定、自动连接、可控权限、可恢复会话”QQ 渠道。
> 当前边界：已实现 OneBot 反向 WebSocket 私聊和可选主人群聊文本；官方 Bot、扫码与富媒体仍为后续规划。本地 Web API 和最小 WebUI 已落地。
> 个人 Agent 的 Session 与共享记忆边界见[单机个人 Agent 多 Session 共享记忆设计方案](单机个人Agent多Session共享记忆设计方案.md)。

## 1. 结论

当前项目已经能通过 OneBot v11 收发 QQ 私聊文本，但它还是一个最小可用适配器，不是 OpenClaw 式的完整渠道。

本方案采用“双驱动”：

1. **QQ 官方机器人（默认、推荐）**：通过 QQ 开放平台扫码绑定，使用官方 Gateway 和 OpenAPI。
2. **OneBot 兼容模式（高级选项）**：保留现有 NapCat/Lagrange 连接，供个人 QQ 号和扩展能力使用。

不建议用 NapCat 模拟“OpenClaw 官方 QQ”。OpenClaw 当前的官方通道是 QQ Bot API；NapCat/OneBot 是另一条社区兼容路线，两者的账号模型、用户 ID、群权限和媒体 API 都不相同。

## 2. 当前项目如何连接 QQ

### 2.1 实际链路

```text
QQ 客户端
  ↕
NapCat / Lagrange（项目外部）
  ↕ OneBot v11 Reverse WebSocket（NapCat 主动连接）
QQAdapter
  → ChannelRouter
  → Conversation / Identity / Memory
  → Agent Runtime
  → send_private_msg / send_group_msg
  → NapCat / Lagrange
  → QQ
```

对应代码：

- `src/zhiyu/cli/main.py`：提供 `qq configure/listen/status` 命令。
- `src/zhiyu/application/channels.py`：保存配置，Token 放系统 Keyring，管理监听生命周期。
- `src/zhiyu/channels/manager.py`：创建 QQAdapter，管理监听和连接状态。
- `src/zhiyu/channels/qq/adapter.py`：监听 OneBot 反向 WebSocket，处理私聊文本和受策略控制的主人群聊文本。
- `src/zhiyu/channels/router.py`：将消息交给共享 ChatService。

### 2.2 现有能力

- OneBot v11 私聊文本收发。
- Access Token 鉴权。
- NapCat 断开后继续监听，等待其自动重连。
- 监听、连接和错误状态展示。
- 配置持久化和启动自动重连。
- 单主人 QQ 白名单；未配置或发送者不匹配时拒绝访问 Agent。
- `/new` 创建独立 QQ Session，旧消息保留。
- 获准 QQ Session 与本机 Session 共用 local identity 的长期记忆，原始聊天记录仍按 Session 隔离。
- 统一文本、图片、语音、文件、@ 和引用消息组件；QQ 当前只接通文本与 @ 解析。
- OneBot `echo` 回执、超时、发送结果持久化和入站事件去重。
- 同一会话串行、不同会话并行，并设置全局并发上限。
- 群聊默认关闭；启用后仅主人可用且默认必须 @ 机器人。

### 2.3 当前问题

1. 当前采用反向 WebSocket，只允许一个 NapCat 客户端连接。
2. QQ 只真正收发文本；图片、语音、文件和引用目前只有统一组件结构，尚未接通协议转换。
3. 私聊和群聊已有独立会话键，但尚未覆盖多账号维度。
4. 一个 `channel` 只能有一份配置，无法支持多 QQ Bot/多账号。
5. 群聊只有“主人 + 可选启用 + 默认需 @”的基础策略，没有群白名单和按群工具限权。
6. 入站事件与发送结果已持久化，但尚无进程崩溃后自动恢复未完成 Agent 工作的持久队列。
7. `send_message` 已等待 OneBot `echo` 并校验返回码；发送结果未知时不会自动重发。
8. 没有 Gateway session/resume、完整心跳审计、长消息分片和限流。

## 3. OpenClaw 可借鉴的部分

OpenClaw 官方 QQ 插件目前使用 QQ 开放平台 Bot，支持两种配置方式：

- 手工输入 `AppID + AppSecret`。
- 由桌面端/向导发起扫码绑定，成功后持久化返回的凭据。

值得直接吸收的能力：

- 官方 WebSocket Gateway 连接、心跳、重连和 Resume。
- C2C 私聊、群 @ 和频道消息的统一目标格式。
- `allowFrom` / `groupAllowFrom` 和 open / allowlist / disabled 策略。
- 每群是否必须 @、历史条数、提示词和工具黑白名单。
- 每个 peer 独立队列，群消息短时合并，防止并发回复串台。
- 入站事件先落库再推进 Gateway sequence，使未处理事件可恢复。
- 消息去重、媒体统一通道、长文分块、语音 STT/TTS。
- 多 Bot 账号隔离：连接、Token cache、OpenID 和日志均按账号分开。

官方参考：

- [OpenClaw QQ Bot 文档](https://docs.openclaw.ai/channels/qqbot)
- [Tencent OpenClaw QQ Bot 插件](https://github.com/tencent-connect/openclaw-qqbot)
- [Tencent qqbot-agent-sdk](https://github.com/tencent-connect/qqbot-agent-sdk)
- [OneBot 11 兼容插件参考](https://github.com/xucheng/openclaw-onebot)

## 4. 后续产品体验

### 4.1 首次连接

```text
设置 → Channels → QQ
  → 选择“QQ 官方机器人（推荐）”
  → 点击“扫码绑定”
  → 弹窗显示二维码和 120s 倒计时
  → 手机 QQ 扫码并确认
  → 后端获得 AppID / AppSecret / owner OpenID
  → AppSecret 写入系统钥匙串
  → Gateway 自动连接
  → UI 显示 Bot 名称、AppID 尾号和“已连接”
```

同时保留“手动输入 AppID/AppSecret”作为备用方式。

### 4.2 旧 OneBot 入口

放在“高级连接”中：

- 驱动：OneBot v11。
- WebSocket Server URL。
- HTTP API URL（媒体和某些扩展 API 需要）。
- Access Token。
- “我已了解这是非官方个人号方案”提示。

### 4.3 连接后设置

- 私聊策略：开放 / 白名单 / 禁用。
- 群聊策略：开放 / 白名单 / 禁用。
- 群默认触发：必须 @ / 始终监听。
- 允许的用户和群。
- 每群的 Character、Model、System Prompt 和 Tool Policy。
- 图片/文件/语音、流式回复、主动消息开关。

## 5. 目标架构

```text
┌────────────────── CLI ───────────────────┐
│ Configure / Listen / Status / Policy     │
└──────────────────┬───────────────────────┘
                   Application Services
┌──────────────────▼───────────────────────┐
│            Channel Runtime              │
│  PairingService   ChannelAccountManager │
│         │                 │           │
│  ┌──────▼─────┐     ┌─────▼──────────┐  │
│  │ QQ Official│     │ OneBot Adapter  │  │
│  │ Adapter    │     │ (compatibility) │  │
│  └──────┬─────┘     └─────┬──────────┘  │
│         └──────────┬──────────┘             │
│              Inbound Pipeline            │
│  normalize → policy → dedup → durable queue│
│        → peer lock → Agent → delivery      │
└──────────────────┬───────────────────────┘
             ┌───────┴────────┐
             ▼                ▼
     QQ Official API    NapCat / Lagrange
```

### 5.1 SDK 选型

官方驱动直接引入 `qqbot-agent-sdk`，不引入 Node sidecar。

原因：

- 项目的 ChannelManager、Agent Runtime、数据库和密钥管理已在 Python 后端。
- SDK 已包含扫码 Onboard、Gateway 心跳/重连/Resume、OpenAPI、事件解析、媒体和 session store。
- 保持单一 Python 进程，方便 CLI 阶段调试。

锁定一个已验证版本，不使用无上限的版本范围；在 PyInstaller 构建中增加 SDK 的 hidden imports 和资源检查。

### 5.2 核心接口

```python
class ChannelDriver(Protocol):
    async def start(self, account: ChannelAccount) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, target: ChannelTarget, content: OutboundContent) -> DeliveryReceipt: ...
    async def health(self) -> ChannelHealth: ...
```

具体实现：

- `QQOfficialDriver`：`qqbot-agent-sdk`。
- `OneBotDriver`：由当前 `QQAdapter` 演进而来。

Manager 必须从“每 channel 一个 adapter”改为“每 account 一个 driver”：

```text
drivers[account_id]
tasks[account_id]
states[account_id]
```

## 6. 统一消息模型

```python
class ChannelEnvelope:
    event_id: str
    channel: str                 # qq
    driver: str                  # official / onebot
    account_id: str
    conversation_id: str         # c2c:<openid> / group:<openid> / guild:<id>
    conversation_type: str       # private / group / guild
    sender_id: str
    sender_name: str | None
    message_id: str
    reply_to_id: str | None
    mentioned_bot: bool
    parts: list[MessagePart]      # text / image / audio / video / file / quote
    raw: dict
    received_at: datetime
```

会话键：

```text
(channel, account_id, external_conversation_id)
```

未来支持多用户或多账号时的主体键：

```text
(channel, account_id, external_user_id)
```

该键不直接等于当前个人 Agent 的记忆归属。当前获准主人 Session 统一映射到 local identity；未来若支持多用户或多 Agent，才按账号与外部用户建立独立主体和 vault。

## 7. 数据模型

### 7.1 ChannelAccount

```text
id
channel                 qq
driver                  official / onebot
name
external_account_id     AppID 或 OneBot self_id
endpoint                可空，官方 Gateway 由 API 获取
secret_ref              Keychain 中 AppSecret / Access Token 的引用
config_json             非秘密策略
enabled
auto_connect
created_at
updated_at
```

唯一约束：`(channel, driver, external_account_id)`。

### 7.2 ChannelEvent

```text
id
account_id
provider_event_id       UNIQUE(account_id, provider_event_id)
conversation_key
payload_json
status                  received / processing / completed / retryable / dead
attempts
last_error
received_at
completed_at
```

作用：去重、崩溃恢复、失败重试和审计。

### 7.3 ChannelDelivery

```text
id
event_id
target
provider_message_id
status                  pending / sent / failed
attempts
last_error
created_at
sent_at
```

### 7.4 现有表迁移

- `conversations` 增加 `channel_account_id` 和 `external_conversation_id`。
- `identities` 增加 `channel_account_id`，更新唯一约束。
- 现有 `channel_configs` 数据迁移成一个 `driver=onebot` 账号。
- 旧会话的 `external_conversation_id` 先回填 `external_user_id`，不破坏私聊历史。

## 8. 入站流程

```text
Gateway event
  → 解析为 ChannelEnvelope
  → 验证 account + sender/group policy
  → 按 provider_event_id 去重
  → ChannelEvent 落库
  → 按 conversation_key 进入串行队列
  → 载入/下载附件
  → 处理命令或调用 ChannelRouter
  → Agent Runtime
  → OutboundContent
  → 分块 / 媒体上传 / 限流
  → QQ API
  → DeliveryReceipt 落库
  → ChannelEvent completed
```

并发原则：

- 不同会话可并行。
- 同一会话严格串行，防止上下文乱序。
- 普通文本可设 1.0–1.5s debounce 合并；命令不合并。
- 只有已落库的事件才允许推进 Gateway resume sequence。

## 9. 权限和安全

### 9.1 默认策略

- 新账号默认 `dm_policy=allowlist`，扫码操作人自动加入白名单。
- 新账号默认 `group_policy=disabled`，由用户明确开启。
- 群聊默认 `require_mention=true`。
- 群聊默认禁用高风险工具：`exec` / `read` / `write` 及任意本地文件系统能力。
- 管理命令必须是非通配白名单用户；`*` 只能允许普通聊天。

### 9.2 凭据

- AppSecret / Access Token 只保存在 Keychain。
- SQLite 仅保存 `secret_ref`。
- API 返回值和日志不包含完整凭据。
- 二维码绑定 session 仅存内存，超时立即销毁。
- 连接成功后再原子替换旧 secret，避免绑定失败破坏已有账号。

### 9.3 媒体安全

- 所有媒体限制在应用专用目录。
- 校验 MIME、大小、下载超时和重定向次数。
- 远程 URL 下载阻止 localhost、内网地址和非 HTTP(S) 协议，防止 SSRF。
- 清理临时文件时仅操作已验证的应用媒体目录。

## 10. Web UI 阶段的 API 草案

以下接口不属于当前 CLI 版本。只有开始 Web UI 后，才根据届时的交互需求实现薄 API 层。

```text
GET    /api/channels/qq/accounts
POST   /api/channels/qq/pairing/start
GET    /api/channels/qq/pairing/{session_id}
DELETE /api/channels/qq/pairing/{session_id}
POST   /api/channels/qq/accounts/manual
PATCH  /api/channels/qq/accounts/{account_id}
POST   /api/channels/qq/accounts/{account_id}/connect
POST   /api/channels/qq/accounts/{account_id}/disconnect
DELETE /api/channels/qq/accounts/{account_id}
GET    /api/channels/qq/accounts/{account_id}/groups
```

### 10.1 扫码启动响应

```json
{
  "session_id": "uuid",
  "qr_url": "https://...",
  "expires_at": "2026-09-28T12:00:00Z",
  "status": "waiting_scan"
}
```

### 10.2 绑定状态

```text
created
waiting_scan
scanned
confirming
connected
expired
cancelled
failed
```

前端短期可每 1s 轮询 pairing 状态；连接状态和新消息应通过 SSE 推送，不再长期依赖页面轮询。

## 11. 状态机

```text
unconfigured
  → pairing
  → configured
  → connecting
  → connected
  → reconnecting
  → connected

pairing → expired / failed / cancelled
connecting / reconnecting → auth_error / error / disconnected
auth_error → rebind / replace_secret
```

状态输出包含：

- `last_connected_at`
- `last_event_at`
- `last_heartbeat_at`
- `last_error_code`
- `last_error_message`
- `retry_count`
- `gateway_session_resumable`

## 12. 分阶段实施

### Phase 1：修正现有 OneBot 边界

- 反向 WebSocket 监听、Token 鉴权和断线后继续监听已完成。
- 接收与业务处理已拆成两个任务，单条业务异常不会停止监听。
- 会话查找已使用 `external_conversation_id`。
- 增加群聊文本和 @ 触发。
- 增加 `echo` 响应关联、超时和发送错误。

验收：私聊历史不丢失，不同群不串会话，发送失败可见。

### Phase 2：账号模型与官方 Bot MVP

- 增加 ChannelAccount 和数据迁移。
- 接入 `qqbot-agent-sdk`。
- 完成手动 AppID/AppSecret 配置。
- 完成 C2C 文本收发、心跳、重连和 Resume。

验收：重启应用后自动恢复，断网恢复后不需重新配置。

### Phase 3：OpenClaw 式扫码绑定

- PairingService 和超时/取消。
- 二维码弹窗、倒计时、扫码状态。
- 成功后凭据原子写入 Keychain 并自动连接。
- 绑定失败不覆盖旧账号。

验收：新用户不手填 URL/Token，仅扫码即可连接。

### Phase 4：可靠入站与权限

- ChannelEvent / ChannelDelivery。
- 去重、同 peer 串行队列、崩溃恢复。
- DM/群白名单、默认 @、每群 Tool Policy。
- `/bot-ping`、`/bot-me`、`/new`、`/reset`、`/stop`。

验收：重复事件不重复回复，同会话不并发乱序，未授权用户无法使用 Agent 或管理命令。

### Phase 5：富媒体和多账号

- 图片、引用、文件和语音。
- STT/TTS。
- 长文分块、流式块回复和发送限流。
- 多 Bot 账号和按账号的状态/日志。

验收：文本和媒体均可双向使用，两个 Bot 的 OpenID、会话、记忆和凭据不串台。

## 13. 测试策略

### 单元测试

- QQ 事件 → ChannelEnvelope 解析。
- 私聊/群聊策略矩阵。
- 会话键与记忆归属分别验证。
- 去重、peer lock、debounce、长文分块。
- 凭据替换的原子性。

### 集成测试

- 伪 Gateway：HELLO → IDENTIFY → HEARTBEAT → ACK → RESUME。
- 断线后重放同一 event ID，只产生一次 Agent Run。
- Agent 成功但发送失败，Delivery 可重试。
- Keychain 写入失败时不启用新账号。
- 旧 OneBot 配置迁移后仍可自动连接。

### 真实 E2E

- 扫码绑定。
- QQ 私聊发送文本，桌面端出现同一会话。
- 群里未 @ 不回复，@ 后回复。
- 重启桌面应用，Bot 自动上线。
- 断网 30s 后恢复，会话继续且不重复回复。

## 14. 完成标准

1. 用户可以通过扫码完成 QQ 官方 Bot 绑定，无需手填 WebSocket 地址。
2. AppSecret 不落入 SQLite、日志或前端状态。
3. 私聊、群聊、多 Bot 之间的会话记录保持隔离；记忆是否共享由明确的 Agent/主体归属决定。
4. 群聊默认必须 @，高风险工具默认不可用。
5. 同一 Gateway 事件重放不会触发两次 Agent 回复。
6. 断网、进程重启和 Gateway Resume 后能自动恢复。
7. 发送失败有回执、可观测、可重试，不会被误标为成功。
8. 现有 OneBot 配置和私聊历史能无损迁移。

## 15. 范围边界

- “扫码绑定”是绑定 **QQ 开放平台机器人**，不是把用户的个人 QQ 账号登录到本应用。
- 个人 QQ 号自动化继续由 OneBot/NapCat 模式承担，但应明确标为高级兼容能力。
- 第一版不实现群管、QQ 空间、好友操作和任意 QQ 控制工具，先完成可靠、安全的消息通道。
