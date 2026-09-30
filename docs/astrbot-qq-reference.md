# AstrBot QQ 接入对照

更新：知语已按 AstrBot 的连接方向改为 OneBot v11 反向 WebSocket，并将接收和业务处理拆开。收发回执、群聊和富媒体仍未实现。

日期：2026-09-29。范围：AstrBot `master` 的 OneBot v11 接入源码与知语现有实现；这是参考结论，不代表功能已经实现。未对 QQ 真实账号进行联调。

## 已核实的实现

参考源码：

- [AiocqhttpAdapter](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/platform/sources/aiocqhttp/aiocqhttp_platform_adapter.py)
- [AiocqhttpMessageEvent](https://github.com/AstrBotDevs/AstrBot/blob/master/astrbot/core/platform/sources/aiocqhttp/aiocqhttp_message_event.py)

AstrBot 这条路线通过 aiocqhttp 接入 OneBot v11。适配器以 `use_ws_reverse=True` 创建服务，配置监听 host、port 和 token，等待 OneBot 实现主动连接。QQ 登录由 NapCat 等外部实现承担，这两个文件并未提供知语内扫码登录个人 QQ 的能力。

私聊和群聊分别注册事件处理函数，转换为统一消息对象后调用 `commit_event`，不在消息回调中直接等待模型生成。转换时保留机器人 ID、发送者、群 ID、消息 ID 和消息段；私聊 session_id 来自发送者，群聊来自群 ID。这里的 session_id 只是适配器层标识，不能据此推断整个系统最终的隔离策略。

发送侧将消息组件转换为 OneBot 消息段，分别调用 `send_private_msg` 或 `send_group_msg`；收到原始事件时会携带 self_id 进行路由。图片和录音支持转成 base64，引用消息可调用 `get_msg` 补全。事件回调捕获单条消息处理异常。

## 与知语的差异

| 项目 | 知语现状 | 建议 |
|---|---|---|
| WebSocket 方向 | 知语监听地址，由 NapCat 主动连接 | 已与 AstrBot 的反向 WebSocket 方向一致 |
| 入站处理 | 独立接收任务写入有界队列，业务任务消费 | 后续按会话增加串行队列，让不同会话可以并行 |
| 业务异常 | 单条消息异常被隔离并记录，监听服务继续运行 | 增加可查询的失败状态和重试策略 |
| 会话映射 | ChatService 分别接收外部用户 ID 和外部会话 ID | 群聊上线时增加群会话键和发送者身份的组合测试 |
| 消息格式 | 仅提取私聊文本 | 先支持规范文本段；再按需增加 @、引用、图片 |
| 发件确认 | 只调用 WebSocket send，无 echo 匹配 | 增加 echo、返回码校验、超时；断线时结束未完成请求 |
| 重连 | NapCat 断开后服务保持监听，等待客户端重连 | 增加心跳健康状态和连接审计 |

接收循环与回执必须一起设计：如果在当前接收循环内等待发送回执，循环就无法继续读取该回执，最终会超时。独立接收循环负责区分事件与 API 响应，再把事件交给业务队列。

## 建议实施顺序与验收

1. 稳定现有反向 WebSocket 私聊链路：增加发送回执、请求超时和连接健康状态。
   - 验收：慢 Agent 不阻塞响应读取；模型失败不触发连接重建；发送拒绝或超时可见；主动断开能清理任务。
2. 支持群聊文本：迁移会话键，保留旧私聊映射，新增群目标和 @ 识别；明确启用群聊及工具权限后再放行群消息。
   - 验收：同一用户在不同群不串会话；群与私聊不混用记忆；未满足触发条件不调用 Agent；旧私聊历史仍可访问。
3. 按实际需要增加引用、图片和语音。
   - 验收：每种消息分别有协议样例测试，并经真实 QQ 收发确认。

## 与现有设计方案的关系

`docs/QQ接入设计方案.md` 规划了官方 Bot 与 OneBot 双驱动。本次只验证 OneBot 路线，不改变官方 Bot 的产品取舍，也不把此前方案中的扫码、SDK、Gateway Resume 等描述视为已验证能力。

当前优先完善反向 OneBot 私聊；官方 Bot、群聊和多账号均是独立的后续范围。无需引入整个 AstrBot 框架即可采用消息标准化、收发解耦和会话隔离的设计。
