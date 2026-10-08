# AstrBot QQ 接入对照

更新：星栖已按 AstrBot 的连接方向改为 OneBot v11 反向 WebSocket，并将接收和业务处理拆开；发送回执、持久化去重、按会话并发和可选主人群聊文本已经实现。富媒体真实收发仍未实现。

核实日期：2026-09-29。范围：AstrBot `master` 的 OneBot v11 接入源码；星栖实施状态以本页“更新”和差异表为准。尚未对 QQ 真实账号进行联调。

## 已核实的实现

参考源码：

- [AiocqhttpAdapter](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py)
- [AiocqhttpMessageEvent](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/platform/sources/aiocqhttp/aiocqhttp_message_event.py)

AstrBot 这条路线通过 aiocqhttp 接入 OneBot v11。适配器以 `use_ws_reverse=True` 创建服务，配置监听 host、port 和 token，等待 OneBot 实现主动连接。QQ 登录由 NapCat 等外部实现承担，这两个文件并未提供星栖内扫码登录个人 QQ 的能力。

私聊和群聊分别注册事件处理函数，转换为统一消息对象后调用 `commit_event`，不在消息回调中直接等待模型生成。转换时保留机器人 ID、发送者、群 ID、消息 ID 和消息段；私聊 session_id 来自发送者，群聊来自群 ID。这里的 session_id 只是适配器层标识，不能据此推断整个系统最终的隔离策略。

发送侧将消息组件转换为 OneBot 消息段，分别调用 `send_private_msg` 或 `send_group_msg`；收到原始事件时会携带 self_id 进行路由。图片和录音支持转成 base64，引用消息可调用 `get_msg` 补全。事件回调捕获单条消息处理异常。

## 与星栖的差异

| 项目 | 星栖现状 | 建议 |
|---|---|---|
| WebSocket 方向 | 星栖监听地址，由 NapCat 主动连接 | 已与 AstrBot 的反向 WebSocket 方向一致 |
| 入站处理 | 同一会话串行、不同会话并行，并受全局并发上限保护 | 继续观察真实流量下的背压参数 |
| 业务异常 | 单条消息异常隔离；事件和投递状态持久化 | 后续按需要增加人工重放入口 |
| 会话映射 | 私聊按用户、群聊按群建立独立会话 | 多账号上线时再把账号维度加入会话键 |
| 消息格式 | 统一组件模型；QQ 已支持私聊文本和需 @ 的主人群聊文本 | 按需接通引用、图片和语音的真实协议转换 |
| 发件确认 | 已匹配 echo，校验返回码并设置超时 | 发送结果未知时继续避免自动重发 |
| 重连 | NapCat 断开后服务保持监听，等待客户端重连 | 增加心跳健康状态和连接审计 |

接收循环与回执必须一起设计：如果在当前接收循环内等待发送回执，循环就无法继续读取该回执，最终会超时。独立接收循环负责区分事件与 API 响应，再把事件交给业务队列。

## 建议实施顺序与验收

1. 已完成：稳定反向 WebSocket 私聊链路，增加发送回执、请求超时和连接健康状态。
   - 验收：慢 Agent 不阻塞响应读取；模型失败不触发连接重建；发送拒绝或超时可见；主动断开能清理任务。
2. 已完成首版：支持主人群聊文本，默认关闭；启用后默认要求 @，并保持群聊与私聊会话隔离。
   - 验收：同一用户在不同群不串会话；群与私聊不混用记忆；未满足触发条件不调用 Agent；旧私聊历史仍可访问。
3. 按实际需要增加引用、图片和语音。
   - 验收：每种消息分别有协议样例测试，并经真实 QQ 收发确认。

## 与现有设计方案的关系

`docs/QQ接入设计方案.md` 规划了官方 Bot 与 OneBot 双驱动。本次只验证 OneBot 路线，不改变官方 Bot 的产品取舍，也不把此前方案中的扫码、SDK、Gateway Resume 等描述视为已验证能力。

当前优先继续验证反向 OneBot 文本链路；富媒体、官方 Bot 和多账号均是独立的后续范围。无需引入整个 AstrBot 框架即可采用消息标准化、收发解耦和会话隔离的设计。
