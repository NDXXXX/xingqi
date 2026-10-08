# 知语对齐 OpenClaw 记忆机制设计方案

> 日期：2026-10-08
>
> 状态：分阶段实施中；本文的目标机制尚未全部实现。
>
> 基准：OpenClaw 当前默认 `memory-core`，以及与它配套的 Active Memory、Dreaming、会话压缩和前瞻性记忆。依据文末官方文档；OpenClaw 后续版本变化需重新核对。
>
> 范围：知语 CLI/TUI、Web、QQ 共用的本机个人 Agent 记忆。下文描述目标契约，实际进度见第 9 节。

## 1. 目标和边界

用户要求“完全按照他的那一套记忆机制”。本方案把它定义为**可观察行为对齐**：同一类信息进入相同层级，经过同类来源门槛、检索、后台整理、注入、遗忘和恢复流程。知语仍用现有 Python、SQLite、Markdown 和本机身份体系实现；复制 OpenClaw 的插件框架、TypeScript 类名或管理界面，不会使记忆行为更一致。

完成后应满足：

1. 助手身份、用户模型、精选长期记忆、每日观察、会话历史、待办触发器和梦境报告各有明确归属；无来源的文字不能靠自称“主人说的”取得信任。
2. 普通回答只自动加载受信任、预算内的精选记忆；日记和会话历史只能由显式搜索或符合条件的深度召回取得。
3. 对话中的可记忆事实先留下可追溯的观察；非用户明确要求的长期晋升必须经过确定性门槛和受约束的模型整理。
4. “你叫什么”能够从助手身份文件或用户明确改名记录回答；用户给助手起名属于助手身份变更，不能只依赖一次语义检索。
5. 文件可编辑，索引可重建；会话遗忘、文件编辑、并发修改和中途崩溃后不会复活已删除内容或跨身份串数据。
6. 记忆故障不吞掉聊天回复，且能够诊断本轮为什么召回、跳过或未晋升某条记忆。

已有的[文件记忆重构方案](OpenClaw式文件记忆系统重构设计方案.md)和[增量改进方案](记忆系统增量改进设计方案.md)仍是知语历史设计记录。它们的“仅供参考、不要求复制完整机制”和“暂不实现 REM”与本次目标冲突；**以后续实施以本文为准**。已上线的来源隔离、Mutation Journal、文件权威和安全边界不倒退。

## 2. 对照基线

OpenClaw 的默认 Memory Core 将 `MEMORY.md` / `USER.md` 作为精选核心，`memory/YYYY-MM-DD.md` 和会话记录作为情景层，`DREAMS.md` 作为只供人审阅的报告；来源等级存入 SQLite。普通回合先走无需模型调用的核心加载、混合搜索与可信触发器；历史问题且快速通道没有强命中时，Active Memory 才升级到深度搜索。Dreaming 按 light → REM → deep 整理，deep 通过分数、召回次数、不同查询次数三道门槛后再调用模型合并或替换。[官方架构](https://docs.openclaw.ai/concepts/memory-architecture)、[内置引擎](https://docs.openclaw.ai/concepts/memory-builtin)、[Dreaming](https://docs.openclaw.ai/concepts/dreaming)。

| 环节 | 知语当前代码 | 对齐后的行为 |
| --- | --- | --- |
| 文件与索引 | `store.py` 管理按 identity 隔离的 `USER.md`、`MEMORY.md`、`daily/*.md`、`DREAMS.md`；`Memory` 表缓存正文与状态 | 保留文件权威和身份隔离；增加可重建的 FTS5 chunk 索引、来源与阶段状态；正文缓存不反向覆盖文件 |
| 助手身份 | 默认名字写在 `context.py` 提示词；用户改名可能留在一条情景记忆 | 独立 `IDENTITY.md`，明确改名直接更新身份，回答名称先读身份，避免 Harry 这类漏召回 |
| 写入 | `chat.py` 成功后入队；`memory_jobs.py` 从本轮用户文字抽取最多 5 条观察 | 保留后台任务，补会话结束摄取与压缩前 flush；保留消息来源、污染标记和幂等游标 |
| 自动注入 | `context.py` 预取最多 6 条 profile/preference，又从核心和未晋升情景记忆中取 top 6 | 仅受信任核心按文件预算刷新；强 trigger 最多 3 条；情景层不自动注入 |
| 检索 | `retriever.py` 使用字词 n-gram、向量、RRF、时态和 MMR；候选仍由内存扫描 | SQLite FTS5/BM25（中文 trigram）与向量并行，合并后按相关度、时间、写入时重要度排序，再 MMR；无 embedding 时词法可用 |
| 深度召回 | `deep_recall.py` 在历史意图且快速召回弱时查日记和旧消息 | 作为独立受限召回回合，支持时间与跨会话问题，只搜索有权访问的私人会话，返回带来源的证据摘要 |
| 晋升 | `consolidation_jobs.py` 以 20 条或 24 小时触发，存在主人可信、3 种查询、活跃工作或重复证据任一条件就可交给模型 | 定时 light/REM/deep；deep 的分数、召回次数、独立查询数需**同时**达标，模型只处理通过来源门槛的候选 |
| 遗忘 | `memory_lifecycle.py` 支持按记忆和来源会话遗忘、墓碑和恢复 | 按会话来源图预览与删除，混合来源条目按 OpenClaw 的整条删除语义处理，并阻止未来重新摄取 |
| 压缩 | `context.py` 已有会话摘要检查点 | 压缩前先持久化未写入的可记忆信息，再压缩当前会话；摘要不是跨会话长期记忆 |

以上现状以 2026-10-08 的源码为准，尤其要注意现有代码的 `trust` 和 `MemorySource` 已有基础，但并不等于完整的来源污染传播或会话类型门槛。

## 3. 记忆层级与文件契约

沿用 `settings.memory_dir/identities/<identity-id>/`，不强迫用户搬迁已有文件：

```text
<identity-id>/
├── IDENTITY.md             # 助手名称与稳定自我身份
├── USER.md                 # 用户稳定偏好、称呼、沟通规则
├── MEMORY.md               # 精选事实、项目、关系与长期目标
├── DREAMS.md               # 阶段报告；永不自动注入或作为晋升证据
├── daily/YYYY-MM-DD.md     # 观察、压缩前 flush、会话摄取
└── dreaming/               # 可选的人类可读阶段报告；不作晋升输入
```

| 层 | 写入者 | 普通会话如何读取 |
| --- | --- | --- |
| `IDENTITY.md` | 初始化和主人明确改名 | 受预算约束的身份引导，名称变更下一轮生效；角色配置冲突时以用户当前显式设置为准 |
| `USER.md` | 主人明确要求或人工编辑；后台只提出可审阅的偏好建议 | 受信任、预算内的指令式偏好；新偏好原位替代旧偏好，不并列矛盾说法 |
| `MEMORY.md` | 主人明确“记住”或 deep 阶段 | 受信任、预算内的精选事实；项目/目标有时间和替代关系 |
| `daily/*.md` | 后台观察、会话摄取、压缩前 flush | 只经 `memory_search` 或深度召回；不自动注入 |
| 会话原文 | 当前 `messages` 表 | 当前会话按检查点读取；其他会话仅经获准历史检索 |
| 站立意图 | SQLite 的确定性 trigger 状态 | 满足时间/事件触发条件时最多注入 3 项；不把“提醒我”当普通事实 |
| `DREAMS.md` | 整理器 | 仅管理页、CLI 和文件阅读；不喂回整理器 |

文件条目保留现有 `zhiyu:id` 稳定寻址，并增加与 OpenClaw 相同语义的行尾 `trigger`、`importance`、`project` 注释；正文由 Markdown 掌握，来源类别、会话类型、可信状态、遗忘墓碑只能由 SQLite 掌握。自动写入的核心条目必须附来源锚点和时间；人工编辑可以改变文字，但不能靠注释提升来源等级。助手名称属于身份文件，即使尚未晋升，明确的“你以后叫 Harry”也应成为当前有效身份；旧名留在审计历史而不与新名并列加载。[官方用户模型](https://docs.openclaw.ai/concepts/user-model)、[官方工作区文件](https://docs.openclaw.ai/concepts/agent)。

## 4. 写入、来源与信任

### 4.1 来源分类

每个候选保留 `identity_id`、`conversation_id`、`message_id`、会话类型、渠道发送者、观察时间、内容哈希、`origin_class` 和 `supersession_key`。`origin_class` 仅允许 `owner`、`agent`、`untrusted`、`system`。入口适配层根据已验证身份和消息类型赋值；模型、网页、工具输出和 Markdown 自述都不能自行赋值。无法确认的外部内容按 `untrusted`，脚手架按 `system`。

只有互动会话中的主人原文和由它提炼的 agent 观察可参加晋升。QQ群中非主人、网页、MCP/Skill 返回及被网络结果污染的助手后续文本可作为可搜索证据，但不得进入精选核心。被召回后注入的文字带结构化标记，后台提取器跳过它，避免“想起一次就再写一遍”。现有 QQ 主人校验、白名单和本机 identity 绑定仍先于记忆入口执行。[官方来源边界](https://docs.openclaw.ai/concepts/memory-architecture)、[来源与删除](https://docs.openclaw.ai/concepts/memory-provenance)。

### 4.2 写入流程

1. 当前回合先完成回复；明确“记住”“忘记”“纠正”“给你改名”在同一已验证主人请求里进入对应的直接操作。直接操作也记录来源与 Mutation Journal。
2. 普通回复成功后，后台作一次有证据约束的观察提取。只从本轮主人原文建立事实；助手回复仅帮助解指代，不能作为事实来源。`source_message_id + 内容哈希` 确保重试幂等。
3. 会话结束、重置或长会话压缩前，将尚未保存的主人事实写入当天文件；摄取游标使短会话与长会话都能进入同一个情景层。重复来源只增加独立证据，不在普通回答中重复显示。
4. 文件修改通过现有可恢复 Mutation Journal，索引异步增量同步。提取、嵌入或索引失败只留下可诊断状态，原聊天回复继续完成。

压缩前 flush 的顺序是：确认当前会话身份 → 提取未持久化内容 → 文件与来源提交 → 写会话摘要检查点。flush 失败可继续压缩，但必须保留原始会话记录和待重试任务，不能报告“已经记住”。[官方会话压缩](https://docs.openclaw.ai/concepts/compaction)。

## 5. 检索与注入

### 5.1 索引和搜索

沿用当前索引同步入口，新增 Alembic Migration 管理 `memory_fts`（SQLite FTS5），按条目或长文 chunk 存储可重建的正文、路径与中文 trigram 词项。英文和标识符保留词法精确匹配。向量按 embedding 模型版本缓存；模型变化只重建向量，不重写 Markdown。默认 chunk 目标 400 token、重叠 80 token，中文按实际 tokenizer 校准；条目级来源保持不变。文件外部编辑、删除、移动后先按哈希增量同步；失败标记 stale，不用过时索引重新放出遗忘条目。[官方内置索引](https://docs.openclaw.ai/concepts/memory-builtin)。

`memory_search(query)` 并行取 BM25 和向量候选，有限查询扩展后合并；评分采用 OpenClaw 的“混合相关度 × 时间衰减 × 写入时重要度”，再经 MMR 去重。每日记忆按 30 天半衰期衰减，精选核心不衰减；无重要度则为中性。排名必须保留精确文件名、专有名词和标识符命中。搜索结果包含来源文件、条目 ID、时间、层级、可信类别和分数；外部来源文本以“不可信资料”包装。显式配置的 embedding 服务故障应给出明确诊断，自动模式可退回 BM25；无论哪一种都不能超时卡住聊天。[官方搜索规则](https://docs.openclaw.ai/concepts/memory-search)。

同时提供按受管路径和条目 ID 读取原文的 `memory_get`，供模型在搜索命中后核查上下文。两个工具共享身份、来源可见性和遗忘过滤；搜索摘要不代替原文证据。CLI/Web 的搜索和“查看来源”也复用这条读取路径。

### 5.2 两级召回

**快速通道**每个合格互动回合执行，零额外模型调用：按预算加载 `IDENTITY.md`、受信任 `USER.md` 与 `MEMORY.md`，文件更新下一轮可见；`USER.md` 按官方独立的 4,000 字符上限管理。私人直接会话可加载精选私人记忆，群聊和渠道会话不默认加载私人核心；知语现有 QQ 主人权限校验不能替代这个上下文边界。再对核心条目的短 trigger 运行词法/向量预筛，强命中阈值默认 0.65，最多补 3 条。项目记忆只有在当前项目匹配时才可触发；没有项目身份时不推断项目。核心文件超过预算时按明确的文件级规则省略并告警，不靠静默截断产生半条指令。情景记忆无论相似度多高都不进此通道。

**深度通道**仅在用户问过去、时间顺序、以前的决定或跨会话信息，且快速通道无强匹配时运行。用独立、无工具写权限的召回回合读取 `memory_search`、相关 daily 条目和被授权的私人会话历史，返回带引用的简短证据；需要时可再读完整条目。当前 QQ 群和非主人会话不能借此访问主人私人历史。设置总时限与结果预算；超时则回答已查到的内容或明确不确定，不编造“没有记录”。[官方 Active Memory](https://docs.openclaw.ai/concepts/active-memory)、[官方记忆架构](https://docs.openclaw.ai/concepts/memory-architecture)。

### 5.3 项目作用域与会话上下文

CLI/TUI 在可信工作目录内可用仓库 `origin` 归一化项目键；没有 `origin` 时用绝对仓库路径。项目注释只由运行时写入，不接纳模型输出的路径。每会话保留最近 4 个活动项目键；检索对匹配项目加权，触发注入只接受活动项目；`USER.md` 和助手身份始终是用户级。Web/QQ 没有明确项目上下文时只使用全局记忆。当前会话摘要继续只是当前 Session 的派生检查点，不得作为跨会话核心事实。[官方项目记忆](https://docs.openclaw.ai/concepts/memory-architecture)。

## 6. Dreaming：light → REM → deep

使用后台定时任务，默认以应用时区每日 03:00 扫描；手动命令可预览、执行和解释。沿用现有 `ConsolidationProcessor` 与来源关系，不另建平行“第二套记忆”。阶段状态、摄取游标、候选证据和运行结果在 SQLite，摘要在 `DREAMS.md`；`DREAMS.md` 和阶段报告都不能成为下一轮候选。

| 阶段 | 处理 | 对核心文件的影响 |
| --- | --- | --- |
| Light | 合并当天观察、召回事件和已脱敏互动会话来源；对重复信号建组，记录增强证据 | 无 |
| REM | 从有来源的多日材料提炼主题与可能的长期更新；只记录反思和可复核的候选 | 无 |
| Deep | 先确定性排序，再验证三道门槛；对通过者重新读取最新文件，再让无工具模型决定新增、合并、替代或忽略 | 仅通过校验后改写 `MEMORY.md`；对 `USER.md` 可产出待审阅建议，不由 Dreaming 自动改写 |

Deep 使用官方默认的信号权重作为初值：相关性 0.30、频率 0.24、不同查询 0.15、时间 0.15、跨日重复 0.10、概念丰富度 0.06；light/REM 强化只作小幅加分。自动晋升同时要求分数 ≥ 0.75、有效召回 ≥ 3 次、不同互动查询 ≥ 3 个。`owner` 与 `agent` 是必要来源门槛，不能替代这三项；`untrusted` 和 `system` 在组装模型输入之前直接排除。现有“主人可信或重复出现即可让模型晋升”的条件必须改掉。[官方 Dreaming](https://docs.openclaw.ai/concepts/dreaming)、[官方 CLI 晋升默认值](https://docs.openclaw.ai/cli/memory)。

模型只提交结构化决策和基于已给证据的短文，不得自行选择身份、信任等级、文件路径或创建无来源事实。应用决策前再次核查文件哈希、候选正文、身份、来源、遗忘状态、冲突与核心预算；写入前保存旧文件 pre-image，并经原子替换与 Mutation Journal 完成。改写不得删除超过既有条目的 25%；校验失败时尝试受同样来源与预算约束的追加方案，否则保留候选待下次重试。每条晋升写来源锚点、最多 3 个 trigger、1–10 的 importance，报告新增/合并/替代数量和拒绝原因。明确的主人直接记忆不等待三个召回查询，但也必须有来源并可撤销。

## 7. 用户模型、身份与前瞻性记忆

`USER.md` 保存“回答请先给结论”“以后不要推荐香菜”这种可执行的稳定偏好；状态包括观察日期、active/superseded。更新同一主题时原位替换并保留审计来源。`MEMORY.md` 保存“正在学 Rust”“猫叫 mini”这类事实。用户给助手改名更新 `IDENTITY.md`，比历史中的旧名称优先；角色系统显式选定的角色名称按该角色设置处理，不能让普通观察覆盖用户当前选择。这样“你叫什么”不依赖语义搜索能否命中“给助手起名”。[官方用户模型](https://docs.openclaw.ai/concepts/user-model)、[官方 Agent 工作区](https://docs.openclaw.ai/concepts/agent)。

“周五提醒我”和“下次聊部署时提醒检查变更日志”属于前瞻性记忆。时间事件交给既有/新增调度任务，成功投递后完成；消息事件存 SQLite 的确定性 trigger、渠道和发送者范围、到期时间、冷却时间、触发次数及取消状态。消息事件冷却 24 小时、最多触发 3 次、90 天到期、每轮最多注入 3 项。不能仅把它写成 `MEMORY.md` 普通事实，因为普通检索无法保证按时触发或取消。[官方 Standing intents](https://docs.openclaw.ai/concepts/standing-intents)。

## 8. 遗忘、迁移与恢复

**遗忘语义。** `memory forget --conversation` 先列出被选会话、其 daily 观察、晋升条目、混合来源和将保留的无关内容；执行后把来源会话写入墓碑，删除受影响的受管条目、索引、向量和阶段状态，并阻止后续会话回填。对同时合并了被删来源与未删来源的单条核心文字，按 OpenClaw 语义**整条删除**，避免模型猜测如何从合并句里减去一位来源；未删来源可在以后重新形成一条独立事实。当前知语“尚有其他来源就保留核心”的规则在此处需要变更。文件备份、未受管的手写文件和用户另存的导出不在自动删除覆盖内，应在预览里明确列出。[官方来源与删除](https://docs.openclaw.ai/concepts/memory-provenance)、[官方 memory CLI](https://docs.openclaw.ai/cli/memory)。

**迁移顺序。**

1. 在临时 `ZHIYU_DATA_DIR` 和真实目录的只读副本上盘点文件、SQLite 索引、身份映射及已有墓碑；先做可恢复备份，不要求删除数据库。
2. Alembic 增加来源分类、会话类型、摄取游标、阶段状态、FTS5、站立意图及必要的索引；现有 `Memory` / `MemorySource` ID 和关系保留。未知旧来源保守设为待复核，不自动提升到 `owner`。
3. 读取现有 `USER.md`、`MEMORY.md`、daily 文件，按稳定 ID / 文件哈希重建词法索引；向量异步重算。旧 `USER.md` 中的陈述句先生成指令化预览，待核对后改写，避免迁移时改变用户偏好原意。无法确认来源的已有核心保留在管理列表并标注待复核，不自动注入；迁移不得直接删用户文件。
4. 从当前角色设置和已验证的主人改名记录生成 `IDENTITY.md`；若两者冲突，保留两边并给出可见的迁移诊断，不能从任意聊天文本猜名字。
5. 先切换普通注入边界，再接入 FTS5、深度召回、会话摄取、Dreaming 和站立意图；每一步可关闭新路径回退到保守的只读核心，但不能回退到让情景层无门槛自动注入。
6. 上线前对同一备份重复执行迁移，核对文件哈希、记录数、身份隔离、来源关系、遗忘墓碑和可重复性；任何失败停在旧版本可读状态。

索引重建只派生搜索数据；外部删除或修改以文件为准，SQLite 中的遗忘墓碑与可信来源不能从 Markdown 注释重新创造。每次文件写入继续使用现有 `MemoryMutation` 恢复路径。Web/CLI 的编辑、删除、搜索、状态和 Dreams 视图调用同一 Application 用例，保持 `/api` 本机 Host、Origin 和写标记校验。[官方索引恢复](https://docs.openclaw.ai/concepts/memory-builtin)。

## 9. 实施阶段与验收

| 阶段 | 主要改动位置 | 可验证完成条件 |
| --- | --- | --- |
| A. 身份与注入边界 | `core/agent/context.py`、`core/memory/store.py`、角色/记忆应用用例 | “你以后叫 Harry”后“你叫什么”答 Harry；普通回合提示词不含未晋升 daily；受信任核心在预算内更新下一轮可见 |
| B. 来源与写入 | `application/chat.py`、`memory_jobs.py`、`core/memory/extractor.py`、Alembic | 主人/外部/系统来源正确分级；召回内容不回写；短会话结束与压缩前 flush 幂等；中断恢复不重复记忆 |
| C. 索引与召回 | `core/memory/indexer.py`、`retriever.py`、`deep_recall.py` | 中文、英文、专有名词与时间问题在固定留出集中命中；无 embedding 可用 BM25；不同身份和 QQ 群无越权结果；索引坏掉不阻塞聊天 |
| D. 三阶段 Dreaming | `application/consolidation_jobs.py`、`core/memory/consolidation.py`、管理入口 | light/REM 不改核心；deep 三门槛同时通过；无来源候选绝不晋升；并发编辑不丢旧记忆；报告和 pre-image 可查看 |
| E. 意图、遗忘和运维 | `application/memory_lifecycle.py`、CLI/API/Web、Alembic | 定时/事件意图按范围与冷却触发；忘记会话后索引重建与回填不复活；预览准确列出混合来源整条删除；现有数据可迁移与回滚 |

### 2026-10-08 实施记录

| 阶段 | 已落地 | 后续缺口 |
| --- | --- | --- |
| A | `IDENTITY.md` 直接改名、历史私人改名回填；普通提示词仅自动加载受信任核心，`USER.md` 与 `MEMORY.md` 分别设预算；QQ 仅明确私人会话可读私人记忆 | 角色切换与身份文件冲突的管理界面 |
| B | 明确“记住”同回合提取；上一轮持久化提取任务在构建下一轮上下文前尝试完成；群聊和未知会话类型不建私人提取任务；未知文件导入不自动提升信任 | 完整来源污染传播、独立会话结束摄取游标 |
| C | Alembic FTS5 trigram/BM25、显式 `memory_search`/`memory_get`、CLI/Web 查询共用混合排序；私人跨会话深度召回且原文限同渠道，未核实导入观察不自动深召回；隔离的 10,000 条基准检索 p50 约 315 ms | 长文 400/80 chunk、项目作用域、留出集检索质量评估 |
| D | 定时 Light/REM/Deep、三个晋升门槛并取、模型前来源与文件版本检查；Deep 仅写 `MEMORY.md`，替换前校验目标文件版本 | 25% 改写上限和受约束追加回退、完整阶段持久化与审阅操作 |
| E | 混合来源整条遗忘、直接记忆与改名的会话级遗忘；中断后按删除计划继续清理核心和提醒；显式“下次聊…时提醒我…”和“明天/后天/周几提醒我…”进入 SQLite，事件提醒 24 小时冷却且最多 3 次，定时提醒投递一次后完成，90 天到期；QQ 定时私聊投递及接收人范围内取消，本机定时提醒写回来源会话，已打开的 Web 页面轮询展示最近提醒 | 更丰富的自然语言时间解析 |

此表是实现状态，不改变前文目标契约；未列为“已落地”的行为不能作为已经完成的功能宣传。

采用仓库现有 `tests/fixtures/memory_retrieval_cases.json`、`tests/test_memory_retrieval_v2.py`、`tests/test_memory_lifecycle.py`、`tests/test_consolidation.py` 等建立迁移前基线，再增加 Harry 改名、普通回合情景层不注入、毒化来源、三门槛、跨会话授权、混合来源遗忘、并发文件编辑和压缩前 flush 的行为用例。检索质量用目标命中率和错误注入率共同验收，不只看 Recall@K；10,000 条规模下记录 p50/p95 与现有基准比较。实施时按改动范围运行 Python 测试、前端检查和 `git diff --check`，所有带数据的验证使用临时 `ZHIYU_DATA_DIR`。

## 10. 官方依据

- [Memory architecture](https://docs.openclaw.ai/concepts/memory-architecture)：层级、来源、两级召回、项目作用域、用户模型与前瞻性记忆。
- [Builtin memory engine](https://docs.openclaw.ai/concepts/memory-builtin) 与 [Memory search](https://docs.openclaw.ai/concepts/memory-search)：文件索引、FTS5/BM25、向量、排序、触发器与降级。
- [Dreaming](https://docs.openclaw.ai/concepts/dreaming) 与 [Memory CLI](https://docs.openclaw.ai/cli/memory)：三阶段巩固、晋升门槛、预览和诊断。
- [Active Memory](https://docs.openclaw.ai/concepts/active-memory)、[Compaction](https://docs.openclaw.ai/concepts/compaction)、[Memory provenance and deletion](https://docs.openclaw.ai/concepts/memory-provenance)：深度召回、压缩前保存与来源删除。
