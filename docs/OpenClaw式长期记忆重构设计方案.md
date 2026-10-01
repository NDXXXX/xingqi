# OpenClaw 式长期记忆重构设计方案

> 版本：v1.0  
> 日期：2026-10-01  
> 状态：设计稿，尚未实施  
> 上游文档：[记忆系统改进设计方案](记忆系统改进设计方案.md)  
> 参考：[OpenClaw Memory Architecture](https://docs.openclaw.ai/concepts/memory-architecture)、[Memory Search](https://docs.openclaw.ai/concepts/memory-search)、[Dreaming](https://docs.openclaw.ai/concepts/dreaming)

## 1. 结论

知语不应原样复制 OpenClaw 的文件布局，而应复制它的四个核心机制：

1. **分层**：把“刚发生过的事情”和“已经确认值得长期保留的知识”分开。
2. **晋升**：普通信息先进入情景记忆，经过确定性门槛和后台巩固后才能进入长期核心。
3. **可信来源**：来源、身份、会话类型和是否来自外部内容由代码记录，模型不能通过文本伪造。
4. **分级召回**：普通请求使用零额外模型调用的快速召回；只有涉及过去且快速召回不足时才使用深度召回。

本方案保留 SQLite 作为权威存储，不将 `MEMORY.md` 设为新的主数据库。原因是知语已经具备身份隔离、来源外键、生命周期、事务和 CLI 管理入口；改成 Markdown 权威存储会额外引入文件并发、身份目录、解析兼容和双向同步问题，却不会直接改善记忆质量。

用户可见性通过 CLI、TUI 和可导出的 Markdown 报告解决。Markdown 导出是视图，不是另一份可写数据源。

## 2. 当前基线

当前系统已经完成以下能力：

- 六种记忆类型：`profile / preference / goal / fact / relationship / project`。
- 生命周期：`active / completed / superseded / invalidated`。
- 按身份隔离，并支持只读共享记忆。
- 记录创建来源、状态变更来源和替换关系。
- 回答完成后创建持久化后台任务，不阻塞本轮回复。
- 提取器支持 `add / replace / complete / invalidate`。
- 用户可以查看、搜索、添加、纠正、完成和删除记忆。
- 新会话可以恢复最近会话末尾与未完成目标。

现有实现的主要问题不是缺少 CRUD，而是所有自动提取结果都被直接当成长期记忆：

```text
用户消息
  → 单轮模型提取
  → 直接写入 active 长期记忆
  → 后续对话按字符重叠召回
```

这会产生四类长期风险：

- 一次性信息过早固化。
- 同义重复和跨时间冲突逐渐积累。
- 旧记忆没有进入最多 20 条候选时无法被替换。
- 字符 bigram 检索无法稳定处理同义表达、时间问题和跨会话推理。

## 3. 目标与非目标

### 3.1 目标

改造完成后，应满足：

1. 普通对话产生的候选信息先进入情景层，不直接污染长期核心。
2. 明确的“请记住”与手动命令仍可以直接形成长期核心记忆。
3. 只有可信、被反复使用或跨时间重复出现的信息才自动晋升。
4. 新旧偏好冲突时只保留一个有效指令，旧值保留可审计状态。
5. 召回同时覆盖关键词与语义相似表达，并避免重复结果。
6. 外部网页、工具输出、系统提示和召回内容不能自行升级为长期用户事实。
7. 记忆服务失败时降低召回质量，但不能阻塞正常回答。
8. 用户能查看某条长期记忆为什么被保存、来自哪里、何时被召回和如何撤销。

### 3.2 非目标

第一轮不实施：

- 完整复制 OpenClaw 的 Light / REM / Deep 三阶段 Dreaming。
- Memory Wiki、知识图谱或 Obsidian vault。
- 多 Agent 共享记忆。
- 图片、音频等多模态记忆。
- 自动识别同一个人在 CLI、QQ 等渠道中的跨渠道身份。
- 将 SQLite 全部替换成 Markdown 文件。
- 为记忆引入独立向量数据库服务。
- 自动删除原始聊天记录。

这些能力只有在最小分层闭环验证有效后再评估。

## 4. 设计原则

### 4.1 写入比检索更重要

再强的检索也无法修复错误、冲突或无价值的长期记忆。系统必须先控制什么能够进入长期核心，再优化如何找到它。

### 4.2 确定性门槛包围模型判断

代码负责：

- 身份和来源校验。
- 信任等级。
- 晋升阈值。
- 候选范围。
- 生命周期。
- 事务、并发和预算。

模型只负责：

- 将自然语言整理成候选观察。
- 判断两个候选是否表达同一事实。
- 在受限候选中选择新增、合并、替换或忽略。

### 4.3 核心记忆必须小而稳定

核心层不是历史摘要仓库。它只保留后续经常需要、能够改变回答方式或代表持续状态的信息。

### 4.4 情景记忆允许多，核心记忆必须少

情景层可以保存细节和暂时不确定的信息；核心层必须经过晋升、去重和冲突处理。

### 4.5 失败不阻塞回复

提取、索引、巩固和深度召回都必须有超时或降级路径。聊天回答成功与记忆处理成功是两个独立结果。

## 5. 分层模型

知语使用四层记忆：

| 层级 | 主要内容 | 自动注入 | 权威存储 |
|---|---|---|---|
| 会话上下文 | 当前会话最近消息 | 是 | `messages` |
| 情景记忆 | 单轮观察、会话片段、暂时信息 | 否，只通过搜索 | `memories(tier=episodic)` |
| 长期核心 | 稳定偏好、画像、关系、长期事实、目标与项目 | 有预算地注入 | `memories(tier=core)` |
| 审查记录 | 巩固输入、决策、跳过原因、变更摘要 | 否 | `memory_consolidation_runs` |

未来的条件触发事项应建立独立的 intent/automation 模型，不混入长期事实。本方案不新增该层。

### 5.1 情景记忆

情景记忆记录“发生了什么”，允许存在尚未解决的重复或冲突。例如：

```text
2026-09-20 用户说最近开始尝试少喝咖啡
2026-09-28 用户说现在下午不再喝咖啡
2026-10-01 用户要求以后不要推荐咖啡
```

它们可以参与搜索和巩固，但不能作为强行为指令自动注入。

### 5.2 长期核心

核心记忆记录“以后应该持续使用什么”。例如：

```text
[preference] 不向用户推荐含咖啡因饮品
```

核心层沿用当前生命周期。偏好和画像更新时必须替换旧记录，不能追加两个互相冲突的 `active` 值。

## 6. 来源与信任模型

新增封闭的 `trust` 枚举：

| 值 | 含义 | 可自动晋升 |
|---|---|---|
| `owner` | 用户本人明确输入或手动命令 | 是 |
| `agent` | Agent 仅根据 owner 内容整理出的观察 | 是 |
| `untrusted` | 网页、搜索、工具输出、群聊其他成员或无法确认来源的内容 | 否 |
| `system` | system prompt、定时任务前言、内部维护文本 | 否 |

同时记录：

- `source_kind`：`message / manual / import / tool / system / consolidation`。
- `source_message_id` 和 `conversation_id`。
- `observed_at`。
- `source_memory_id`：由哪条情景记忆晋升而来。
- `query_origin`：召回内容不得重新作为提取证据。

安全规则：

1. 自动提取只能把本轮用户原文作为 owner 证据。
2. 助手回答、历史消息和工具结果只能帮助理解，不能单独生成 owner 事实。
3. 从记忆注入到上下文的文本带内部来源标记，提取器忽略这些标记范围。
4. `untrusted` 和 `system` 在构建巩固提示词之前就被代码排除。
5. 群聊中只有经过身份解析的 owner 消息可以产生 owner/agent 候选。

## 7. 数据模型

### 7.1 扩展 `memories`

在现有表上新增：

| 字段 | 类型 | 默认值 | 用途 |
|---|---|---|---|
| `tier` | string | `core` | `episodic / core` |
| `trust` | string | `agent` | 来源信任等级 |
| `source_kind` | string | `message` | 来源类别 |
| `conversation_id` | nullable FK | null | 来源会话 |
| `observed_at` | datetime | created_at | 事实观察时间 |
| `supersession_key` | nullable string | null | 同类事实冲突分组 |
| `trigger_text` | nullable text | null | 核心记忆的快速触发短语 |
| `project_key` | nullable string | null | 项目范围；第一版只存不启用自动判断 |
| `promotion_status` | string | `none` | `none / pending / promoted / rejected` |
| `promoted_to_id` | nullable FK | null | 情景记忆晋升到的核心记录 |

保留现有：

- `type`。
- `importance`。
- `status`。
- `source_message_id`。
- `status_source_message_id`。
- `supersedes_id`。
- `origin`。

### 7.2 新增 `memory_sources`

一条核心记忆可能由多个会话和多条情景观察共同支持，因此单个 `source_message_id` 不够。

```text
memory_sources
  id
  memory_id
  source_memory_id nullable
  source_message_id nullable
  conversation_id nullable
  trust
  observed_at
```

唯一约束防止同一来源重复关联。

### 7.3 新增 `memory_recall_events`

只记录真正提供给模型的结果，不记录搜索后被阈值过滤的候选：

```text
memory_recall_events
  id
  memory_id
  identity_id
  query_hash
  score
  recall_mode        # bootstrap / trigger / search / deep
  created_at
```

`query_hash` 使用归一化查询的不可逆哈希，用于计算不同查询数，不保存完整用户问题。

默认保留 90 天，聚合统计完成后允许清理明细。

### 7.4 新增 `memory_consolidation_runs`

```text
memory_consolidation_runs
  id
  identity_id
  status             # pending / processing / completed / failed / cancelled
  candidate_count
  promoted_count
  merged_count
  superseded_count
  skipped_count
  summary
  attempts
  last_error
  created_at
  finished_at
```

详细候选 ID 和模型操作使用 JSON 存储，但不得保存完整聊天正文。

## 8. 写入链路

### 8.1 普通对话

回答成功后仍创建持久化记忆任务，但任务行为改为“提取情景观察”，而不是直接创建核心记忆：

```text
用户消息 + 最近上下文
  → ObservationExtractor
  → 受约束的 observation 数组
  → 代码校验证据和来源
  → memories(tier=episodic, promotion_status=pending)
```

单轮最多五条观察。相比当前最多十条，降低碎片化风险。

以下内容直接返回空数组：

- 一次性闲聊。
- 助手建议。
- 引用、小说角色或第三方叙述。
- 工具和网页内容。
- 已从记忆中召回的内容。
- 没有持续价值的临时状态。

### 8.2 明确记住

以下入口可直接写入核心层：

- `zhiyu memory add`。
- TUI `/remember`。
- 后续受控的自然语言 `remember` 工具。

直接写入仍需：

- 类型与长度校验。
- 身份校验。
- 语义冲突检查。
- 来源记录。

“用户明确要求记住”可以跳过晋升频率门槛，但不能跳过冲突和权限校验。

### 8.3 压缩前 flush

当前知语还没有真正的会话压缩。只有实现 context compaction 后，才增加压缩前 flush：

1. 使用压缩前的私有会话副本。
2. 提取尚未落入情景层的重要观察。
3. 写入情景层后再执行压缩。
4. flush 失败不阻止压缩和回答。

本阶段不为尚不存在的 compaction 单独开发 flush。

## 9. 后台巩固

第一版只实现一个 Consolidation Sweep，不拆成 Light / REM / Deep 三阶段。

### 9.1 触发条件

满足任一条件即可创建巩固任务：

- 当前身份存在至少 20 条待处理情景记忆。
- 最旧待处理情景记忆超过 24 小时。
- 用户执行 `zhiyu memory consolidate`。
- `memory sync` 处理完提取任务后发现满足条件。

常驻 TUI/QQ 在后台空闲时执行；单次 CLI 不等待巩固完成。

这些阈值第一版使用代码常量，不新增配置项。

### 9.2 确定性晋升门槛

候选必须同时满足：

1. `tier=episodic`、`status=active`、`promotion_status=pending`。
2. `trust` 为 `owner` 或 `agent`。
3. 来源消息和身份仍然有效。
4. 未被用户忘记或手动否定。
5. 满足以下任一价值条件：
   - 被至少 3 次实际召回，且来自至少 2 个不同查询；
   - 在至少 2 个不同日期或会话中独立观察到同一语义；
   - 用户明确确认其长期有效；
   - 属于仍活跃的 goal/project，且至少被后续一次对话引用。

同义聚类需要 embedding 时才执行；没有 embedding 时只使用 `supersession_key`、类型、规范化文本和字符检索生成保守候选。检索不确定时宁可不晋升。

### 9.3 模型巩固协议

模型只能对通过门槛的候选和相关核心记忆产生以下操作：

```json
[
  {
    "action": "add_core",
    "candidate_ids": ["..."],
    "type": "preference",
    "content": "不向用户推荐含咖啡因饮品",
    "supersession_key": "diet.caffeine",
    "trigger_text": "咖啡, 饮料推荐, 下午饮品",
    "importance": 8
  },
  {
    "action": "supersede_core",
    "target_id": "...",
    "candidate_ids": ["..."],
    "content": "..."
  },
  {
    "action": "merge_core",
    "target_ids": ["...", "..."],
    "candidate_ids": ["..."],
    "content": "..."
  },
  {
    "action": "ignore",
    "candidate_ids": ["..."]
  }
]
```

模型不能提供任意来源 ID，只能引用本次输入中的候选。

### 9.4 提交校验

提交前由代码验证：

- 候选和目标仍属于同一身份。
- 候选仍为 pending，目标仍为 active。
- 更新时间与输入快照一致。
- `untrusted/system` 没有进入操作。
- 新内容长度、类型、importance 和 trigger 合法。
- preference/profile 的同一 `supersession_key` 最多有一个 active 核心记录。
- 一次重写不能意外使无关核心记忆失效。
- 所有变更与 consolidation run 完成状态在一个事务中提交。

失败时整批回滚。重试不得重复晋升已经处理的候选。

## 10. 召回设计

### 10.1 快速通道

默认通道不增加模型调用，顺序如下：

1. 注入预算内的核心 profile/preference。
2. 匹配核心记忆的 trigger，最多三条。
3. 对核心和情景记忆执行混合搜索。
4. 应用信任、层级、时间、重要度和项目范围排序。
5. 使用 MMR 去除近似重复结果。
6. 只把最终实际注入的结果记为 recall event。

默认限制：

- profile/preference：最多 6 条。
- trigger：最多 3 条。
- 相关搜索：最多 5 条。
- 总记忆预算：沿用当前 1600 字符上限，并受模型 context window 限制。
- 情景记忆只作为“历史证据”，不得被描述为稳定事实。

### 10.2 混合搜索

目标排序：

```text
hybrid_relevance
  = 0.65 × vector_similarity + 0.35 × lexical_score

final_score
  = hybrid_relevance × recency_factor × importance_factor × tier_factor
```

规则：

- 核心记忆不做时间衰减。
- 情景记忆使用 30 天半衰期。
- 核心层轻度加权，但不能让低相关核心记忆压过高相关情景证据。
- embedding 不可用时退化为 SQLite FTS5；FTS5 不可用时继续使用当前 bigram 检索。
- 明确配置了远程 embedding 但运行失败时，状态中必须显示降级原因。

实施顺序：先 FTS5，再接 embedding。第一阶段不能为了“混合检索”一次引入多个外部 Provider SDK。

### 10.3 MMR 去重

从初排候选中选择下一条时，同时考虑相关度和与已选结果的差异。固定 `lambda=0.7`，第一版不暴露配置。

### 10.4 深度召回通道

深度召回属于后续阶段。只有同时满足以下条件才触发：

1. 查询明显涉及过去、时间关系、先前决策或多个会话。
2. 快速通道没有超过强匹配阈值的可信结果。

深度召回由只读 `DeepRecallService` 执行：

- 可以搜索记忆和当前身份可见的会话。
- 可以按结果读取有限消息片段。
- 不能写记忆、调用外部工具或修改会话。
- 有独立的短超时和结果预算。
- 失败时继续使用快速通道结果回答。

第一版不实施深度召回，先收集“快速召回不足”的评估样例。

## 11. 用户模型

`profile` 和 `preference` 作为知语的 USER model，不再与普通事实完全相同地处理。

规则：

1. 内容写成可执行但不越权的偏好描述，例如“回答时优先给结论，再给解释”。
2. 必须记录观察时间和 active/superseded 状态。
3. 同一 `supersession_key` 只能存在一个 active 值。
4. 用户明确改口时可以立即替换，不需要等待后台巩固。
5. 模糊、一次性的表达只能进入情景层。
6. 用户当前消息中的明确要求永远优先于长期偏好。

为了避免模型自行创造 key，第一版 `supersession_key` 由代码根据类型和受控主题生成；无法安全归类时留空，不强行合并。

## 12. 查看、审查与纠正

保留现有命令，并增加：

```bash
zhiyu memory list --tier core
zhiyu memory list --tier episodic
zhiyu memory show <id> --sources
zhiyu memory search "咖啡" --all-tiers
zhiyu memory consolidate --dry-run
zhiyu memory consolidate --apply
zhiyu memory consolidation list
zhiyu memory export --format markdown
```

`consolidate` 默认 dry-run；自动后台任务可以 apply，但必须写审查记录。

Markdown 导出示例：

```markdown
# User Model

- [preference] 回答时优先给结论，再给解释
  - observed: 2026-10-01
  - status: active
  - source: conversation/.../message/...

# Durable Memory

- [project] 知语正在重构分层长期记忆
```

导出文件不参与运行时写入，避免双向同步。

## 13. 遗忘与删除

保留 `memory forget <id>`，但把语义改为可解释的两种模式：

```bash
zhiyu memory forget <id>                 # 删除指定记忆
zhiyu memory forget --conversation <id>  # 后续阶段：删除该会话派生记忆
```

按来源删除需要 `memory_sources`：

- 只有目标来源支持的核心记忆：删除或失效。
- 同时由其他来源支持的核心记忆：移除目标来源，保留记忆并重新计算状态。
- 情景记忆：按来源直接删除。
- 原始会话默认保留，除非用户单独删除会话。

为防止后台重新摄取，后续增加 forgotten source tombstone。第一阶段只支持按记忆 ID 删除，不提前实现不完整的会话级擦除。

## 14. 与现有代码的映射

| 当前模块 | 改造方向 |
|---|---|
| `core/memory/extractor.py` | 改为情景观察提取；新增 consolidation 协议 |
| `core/memory/manager.py` | 拆为 observation 写入与 core 生命周期应用 |
| `core/memory/retriever.py` | 抽象检索接口；bigram → FTS5 → hybrid |
| `application/memory_jobs.py` | 保留持久化处理；增加任务类型或独立 consolidation processor |
| `application/memories.py` | 增加 tier、sources、dry-run 和 export 用例 |
| `core/agent/context.py` | 分别注入用户模型、trigger 和相关结果 |
| `core/recall.py` | 与长期记忆按 ID 去重；不再承担深度历史搜索 |
| `infrastructure/database/models.py` | 增加 tier、trust、sources、recall events、consolidation runs |

不要同时保留两套 Agent 记忆编排。新服务稳定后，旧的“提取后直接写 core”路径必须删除。

## 15. 迁移

新增迁移 `0009_memory_tiers`：

1. 为现有 `memories` 增加新字段。
2. 现有记录统一迁移为 `tier=core`，确保升级后行为不突然改变。
3. `origin=manual` 映射为 `trust=owner`。
4. 有有效用户来源消息的 `origin=automatic` 映射为 `trust=agent`。
5. 无法确认来源的 legacy 记录仍保留为 core，但标记 `trust=agent` 与 `source_kind=import`，在详情中显示“迁移记录，来源不完整”。
6. 创建 sources、recall events 和 consolidation runs 表。
7. 建立 `(identity_id, tier, status)`、`(promotion_status, observed_at)` 索引。

迁移不调用模型、不重写内容、不自动合并旧记录。

上线新提取逻辑后：

- 新自动记忆进入 episodic。
- 旧 core 继续正常使用。
- 后续可通过手动 dry-run 对旧 core 做一次去重审查，但不自动执行。

## 16. 分阶段实施

### Phase A：分层与来源

实现：

- 数据迁移。
- tier/trust/source 查询接口。
- 自动提取改写入 episodic。
- 手动记忆仍写入 core。
- CLI 分层查看。

验收：普通对话不再直接增加 core；升级不丢旧记忆。

### Phase B：单阶段巩固

实现：

- consolidation run 和 processor。
- 确定性门槛。
- add/merge/supersede/ignore 协议。
- dry-run、apply 和审查记录。

验收：重复观察可以晋升；不可信内容不能进入巩固提示词；失败整批回滚。

### Phase C：检索升级

实现：

- SQLite FTS5。
- 可选 embedding 接口与缓存。
- 混合评分和 MMR。
- trigger 注入。
- recall event。

验收：同义查询 Recall@5 高于当前 0.95，且无关结果比例不高于 0.1364。

### Phase D：遗忘与深度召回

实现：

- 来源级 dry-run 删除。
- forgotten tombstone。
- recall intent 判断。
- 只读 DeepRecallService。

验收：跨会话时间问题得到改善；忘记后的来源不会被重新摄取。

每个 Phase 独立迁移、独立测试、独立提交。Phase A 和 B 未稳定前不进入 C。

## 17. 测试与评估

### 17.1 确定性测试

- 自动提取只创建 episodic。
- 手动 remember 创建 core。
- owner/agent 可以晋升，untrusted/system 不进入模型输入。
- 召回内容不会再次形成 observation。
- 晋升阈值不足时不创建 core。
- 多来源合并后保留全部 lineage。
- preference 改口只留下一个 active supersession key。
- consolidation 并发变更时拒绝覆盖。
- 失败回滚候选、核心变更和 run 状态。
- embedding 不可用时 FTS5/bigram 降级不影响回答。
- 实际未注入的候选不记录 recall event。
- 核心和 recall 目标按 ID 去重。

### 17.2 语义评估集

在现有样例基础上扩充到至少：

- 50 组 observation 提取。
- 40 组 consolidation。
- 50 组检索，其中至少 15 组纯同义表达。
- 20 组偏好变更与冲突。
- 15 组外部内容、引用和记忆反馈污染。
- 15 组时间性或跨会话问题，为 Phase D 建立基线。

关键指标：

| 指标 | 目标 |
|---|---|
| 错误核心写入率 | ≤ 2% |
| 明确偏好更新正确率 | ≥ 95% |
| 纯同义检索 Recall@5 | ≥ 90% |
| 整体 Recall@5 | ≥ 97% |
| 无关结果比例 | ≤ 12% |
| untrusted 自动晋升 | 0 |
| 回答被记忆任务阻塞 | 0 |

真实模型评估必须记录 Provider、模型、提示词版本和 embedding 模型。单元测试通过不能代替真实模型评估。

## 18. 可观察性

`memory status` 增加：

```text
core_active
episodic_pending
episodic_promoted
consolidation_pending
consolidation_failed
index_backend
embedding_provider
index_stale
last_consolidation_at
```

日志只记录 ID、计数、状态、耗时和跳过原因，不记录完整聊天正文或 API Key。

巩固任务应输出人类可读摘要，例如：

```text
处理 24 条候选：晋升 2，合并 3，替换 1，忽略 18。
```

## 19. 风险与取舍

### 19.1 成本增加

双阶段写入比当前单次提取多一次批量巩固调用。通过批处理、阈值和非实时执行控制成本；不能每轮执行 consolidation。

### 19.2 记忆生效变慢

普通信息不会立即成为核心记忆。这是有意取舍。明确“记住”仍提供即时路径。

### 19.3 SQLite 不是 OpenClaw 的 Markdown 权威源

这牺牲了直接用编辑器修改记忆的体验，但保留了知语现有事务、身份与来源模型。CLI 管理和 Markdown 导出提供足够透明度；除非真实用户持续要求文件直编，否则不增加双向同步。

### 19.4 embedding 供应商依赖

第一阶段必须能在完全没有 embedding 的情况下工作。embedding 是召回增强，不是聊天可用性的前置条件。

### 19.5 自动巩固仍可能出错

模型永远可能误判。安全来自候选边界、可信来源、阈值、结构校验、审查记录和人工纠正，而不是相信单次模型输出。

## 20. 完成标准

整个方案完成的标准不是“拥有向量数据库”，而是用户能观察到以下行为：

1. 随口提到的一次性信息不会立即永久影响后续回答。
2. 多次出现并确实有用的信息会逐渐进入长期核心。
3. 用户明确要求记住的内容可以立即生效。
4. 用户改口后，旧偏好不会与新偏好同时生效。
5. 同义表达能够找到相关记忆。
6. 网页、工具和召回内容不会污染长期用户画像。
7. 每条核心记忆都能解释来源和晋升原因。
8. 记忆系统故障不会阻止正常聊天。

只有这些行为通过固定评估集和真实使用验证后，才考虑完整 Dreaming、多模态、Wiki 或多 Agent 记忆。
