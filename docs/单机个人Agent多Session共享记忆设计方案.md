# 单机个人 Agent 多 Session 共享记忆设计方案

> 版本：v2.0  
> 日期：2026-10-04  
> 状态：已实施（2026-10-05）  
> 本文取代旧版《单机个人 Agent 主人渠道绑定与统一记忆设计方案》：目标是一个个人 Agent、多条独立对话、共享一份记忆，不再设计账号配对或多用户身份体系。

## 1. 一句话定义

**一个 Agent、一份记忆；本机和 QQ 可以有多个独立 Session；所有获准的 Session 读写同一份记忆。**

```text
本机 Session A ─┐
本机 Session B ─┼──> 星栖 Agent ──> 同一份个人记忆
QQ Session A ───┤
QQ Session B ───┘

每个 Session 保留自己的聊天记录和当前上下文；记忆跨 Session 共享。
```

Session 回答“这段对话的上下文是什么”；记忆回答“Agent 从不同对话中长期记住了什么”。两者不能再由同一个身份字段决定。

## 2. 实施前基线与问题

本节保留重构前的 identity 分配方式，用于说明方案动机；第 4 至第 8 节描述的共享记忆边界已经实施。

当前代码已有 `Conversation` 作为对话记录：每条会话有自己的消息历史。记忆文件也按 `identity_id` 分目录。

问题在于，当前实现把渠道用户映射为不同 identity：本机使用固定 local identity；QQ 按 `(channel, external_user_id)` 创建另一个 identity。聊天上下文、记忆写入任务和召回都沿用会话的 `identity_id`，因此一个 QQ 私聊虽然连接到同一个 Agent，实际却读写另一份记忆。

主要代码位置：

- [chat.py](../src/zhiyu/application/chat.py)：创建会话，并为本机/外部渠道分配 identity。
- [identity_repository.py](../src/zhiyu/infrastructure/database/repositories/identity_repository.py)：本机与外部渠道身份分别创建。
- [context.py](../src/zhiyu/core/agent/context.py)：按 `Conversation.identity_id` 加载并注入记忆。
- [memory_jobs.py](../src/zhiyu/application/memory_jobs.py)：后台提取任务沿用该 identity 写入记忆。
- [store.py](../src/zhiyu/core/memory/store.py)：记忆文件按 identity 分目录。

因此，问题不在“缺少更复杂的主人实体”，而是**Session 身份与记忆归属耦合了**。

## 3. 目标与边界

### 目标

1. 本机和获准的 QQ 私聊或主人群聊进入同一个个人 Agent。
2. 每条 Session 有独立消息历史；新开 Session 不继承另一条 Session 的完整聊天记录。
3. 所有获准 Session 使用同一份记忆：任一 Session 写入的记忆，其他 Session 都可召回。
4. 自动记忆仍保留来源会话和消息，方便解释、修改和遗忘。
5. 不增加 `Owner`、`Person`、渠道绑定表或一次性配对流程。

### 不在本次范围

- 多人各自使用同一个 Agent、每个人有私有记忆。
- 多人群聊记忆、联系人画像和记忆共享权限系统。
- 把不同 Session 的完整 transcript 自动拼接进当前对话。
- 重写现有记忆提取、巩固、检索算法。
- 接入微信；后续渠道复用同一条“获准 Session 使用 Agent 记忆”的规则。

## 4. 核心设计

### 4.1 记忆归属固定为本机 Agent

继续使用现有固定 local identity 作为这台机器上个人 Agent 的唯一记忆空间，不新增数据库实体，也不迁移现有本机记忆文件。

本机 Session 与获准的 QQ Session 创建/加载会话时，`Conversation.identity_id` 都指向这个固定 local identity。记忆 job、巩固、召回、遗忘继续沿用现有 `identity_id` 过滤逻辑，因此自然落到同一份记忆。

这里的 identity 表示“这台机器上的个人记忆空间”，不再表示“某个渠道上的某个发消息账号”。

### 4.2 Session 仍然彼此独立

每个 `Conversation` 仍保存自己的渠道、会话标识和消息记录。创建新 Session 只创建新的 Conversation，不创建新的记忆 identity。

- 本机新建对话：新建 Conversation，identity 使用 local identity。
- QQ 私聊：每条 QQ Session 新建/复用自己的 Conversation，identity 同样使用 local identity。
- 发给模型的普通上下文只包含当前 Conversation 的历史，加上共享记忆检索结果。

当前 QQ OneBot 私聊没有平台原生 thread/session ID，MVP 使用 `/new` 开始一条新的 QQ Session；旧 Conversation 和消息保留。没有 `/new` 时继续当前 QQ Session。Session 导航/恢复旧 QQ Session 不属于本方案的记忆改造要求。

### 4.3 记忆共享，不等于聊天记录串线

跨 Session 共享的是提取后的记忆条目，而不是把某个渠道的所有原始聊天记录直接塞给另一个渠道。

自动记忆记录仍保留 `conversation_id`、`source_message_id` 等来源信息。普通记忆召回只查询共享记忆库。深度召回若搜索原始聊天历史，应限制在当前 Session；跨 Session 的历史内容应先经过现有记忆提取流程进入共享记忆，不能仅因共用 identity 就无条件把其他 Session 的 transcript 注入当前对话。

## 5. QQ 访问边界

当前 QQ 适配器是个人 Agent 的入口，但目前私聊发送者会被当成外部用户自动创建 identity。改为共用 local identity 之前，必须避免任意私聊者因此获得本机私人记忆。

首版采用单机单主人白名单：QQ 渠道配置一个主人发送者 QQ ID；只有该 ID 的私聊可以调用 Agent 并访问共享记忆。群聊默认关闭；显式启用后仍只接受主人消息，并默认要求 @ 机器人。其他发送者、未启用群聊或未满足 @ 条件的消息，在调用模型、创建 Conversation 或排入记忆任务之前拒绝。

这只是入口访问控制，不建立主人领域模型、不做配对协议。QQ 登录账号与消息发送者 ID 是两个概念；白名单校验使用 OneBot 入站消息中的发送者 `user_id`。

## 6. 现有代码的最小改造

1. 在 QQ 渠道设置中保存单一 `owner_user_id`（可空；未配置时拒绝 QQ 私聊访问共享记忆）。
2. 在 QQ 入站消息进入 ChatService 的边界校验私聊发送者；未授权消息不调用模型、不创建会话、不生成记忆任务。
3. 调整 `ChatService._prepare()`：本机和已授权 QQ Conversation 都赋值固定 local identity，不再为 QQ 创建新的记忆 identity。
4. 保持 `Conversation.channel` 与外部会话标识，保持每条 Session 各自的消息历史。
5. 增加 QQ `/new` Session 入口：创建新 Conversation，但 identity 仍是 local identity；旧消息不删除。
6. 确认记忆 job 与检索始终使用规范 local identity；深度历史检索不因 identity 共享而跨 Session 注入原始 transcript。
7. 保留 `IdentityRepository.get_or_create()` 兼容旧数据，但新 QQ 主人 Session 不再使用它分配记忆空间。

不需要改造记忆文件格式、重写 retriever，也不需要新增绑定表或身份解析服务。

## 7. 历史数据与迁移

- local identity 和本机记忆文件保持原样，作为共享记忆的主空间。
- 旧 QQ identity、记忆文件和消息不删除、不自动合并。部署新版本后，获准 QQ Session 从新消息开始读写 local 记忆。
- 若确认旧 QQ identity 属于当前主人，后续可提供人工审阅后导入；不根据“只有一个 QQ 账号”或消息内容静默合并。
- 已有旧 QQ Session 可以保留其历史 Conversation。重新接入时应确保当前获准 Session 的 `identity_id` 使用 local identity；不要重写历史来源或伪造新记忆来源。
- 迁移只新增 QQ 主人配置字段及必要 schema 版本；不修改现有 local identity 主键，不搬动本机记忆文件。

## 8. 验收标准

### Session 独立

- 本机新建两个 Session 后，两者具有不同 Conversation ID 和各自独立的消息历史。
- QQ `/new` 后创建新的 Conversation；旧 Session 的消息仍存在。
- 普通上下文不包含其他 Session 的完整 transcript。

### 记忆共享

- 本机添加的核心记忆可由获准 QQ Session 召回。
- 获准 QQ 对话产生的记忆可由本机 Session 召回。
- 来自不同 Session 的自动记忆都归属 local identity，来源仍能追踪到原 Conversation/Message。
- 不同 Session 的记忆巩固、纠正、遗忘仍限定在同一共享记忆空间且不破坏来源关系。
- 深度召回不会仅因 Session 共用 identity 而把其他 Session 的原始聊天窗口注入当前对话。

### QQ 访问控制与兼容

- 未配置主人 QQ ID、发送者 ID 不匹配、群聊未启用或未满足 @ 条件时，不调用模型、不读写共享记忆。
- 本机 CLI/TUI 现有会话与记忆不受影响。
- 升级后 local identity ID 和本机记忆文件不变。
- 旧 QQ identity 数据仍可查，不自动并入共享空间。

## 9. 实施顺序

1. 写身份/Session/共享记忆集成测试，覆盖跨入口读写、Session transcript 隔离和未授权 QQ 拒绝。
2. 增加 QQ owner 配置与入口校验。
3. 将获准 QQ Session 统一路由到 local identity，确保后台写入和召回随之共享。
4. 增加 `/new` 并验证 Conversation 独立性。
5. 处理深度召回的 transcript 范围，跑相关单元与集成测试。
6. 更新 CLI/渠道使用说明；历史 QQ 记忆导入另立任务，不阻塞新 Session 共享记忆。

## 10. 最终决策

星栖按 OpenClaw 单机个人 Agent 的方式工作：**一个 Agent workspace/记忆空间，多个对话 Session。**渠道和 Session 负责消息入口与对话上下文；它们不再生成各自的私人记忆空间。主人校验只负责保护这个个人 Agent 的入口，不扩展成一套身份绑定系统。
