# OpenClaw 式文件记忆系统重构设计方案

> 版本：v1.2
> 日期：2026-10-05
> 状态：核心方案已实施并通过自动化验收；兼容层清理与扩展压测待后续版本  
> 适用范围：知语 CLI、TUI、QQ 渠道的长期记忆、情景记忆、检索、巩固与遗忘  
> Session 与记忆归属以[单机个人 Agent 多 Session 共享记忆设计方案](单机个人Agent多Session共享记忆设计方案.md)为准；本文负责文件存储、索引、生命周期与遗忘机制。

## 1. 结论

知语可以采用 OpenClaw 式文件记忆，但必须完整采用它的边界，而不是继续维护“全局 Markdown 行与业务数据库记录逐条双写”的结构。

本方案确定以下架构：

1. **Markdown 是记忆正文的权威来源**：`USER.md`、`MEMORY.md` 和每日记忆文件保存人可读、可编辑、可备份的正文。
2. **SQLite 是安全元数据和派生索引的权威来源**：身份、可信来源、会话谱系、召回统计、晋升记录、遗忘墓碑和向量索引不允许由 Markdown 文本自行声明。
3. **记忆空间按 Agent identity 隔离**：本机与获准的主人 QQ Session 都映射到同一个 local identity；其他身份不能自动读取该空间。
4. **文件和索引不按行号绑定**：索引按文档、稳定条目标识和内容哈希建立；删除或移动 Markdown 行不会覆盖其他记忆。
5. **所有程序化文件修改通过可恢复的 Mutation Journal 执行**：系统不声称文件系统和 SQLite 具备单事务能力，而是用幂等操作实现最终一致和崩溃恢复。
6. **短期观察不会直接变成稳定事实**：普通对话进入每日情景记忆，达到确定性门槛后才能晋升至 `USER.md` 或 `MEMORY.md`。
7. **召回必须有相关度门槛**：零分或弱相关结果不得注入；快速召回不足时才进入深度历史召回。
8. **遗忘按身份和来源图执行**：删除来源后，只有失去全部有效来源的核心记忆才删除或失效。

该方案不是把 SQLite 移除。它把 SQLite 从“另一份正文数据库”改为“身份、安全、谱系和检索引擎”，避免正文双权威。

## 2. 背景与已验证问题

重构前的实现已经具备分层、embedding、巩固、深度召回和 Markdown 文件，但存储边界不完整。针对当时代码执行的隔离测试确认了以下问题：

| 场景 | 当前实际结果 |
|---|---|
| QQ 身份写入日期文件后重建索引 | QQ 私密事实被复制到 local 身份 |
| 删除文件第一条记忆后重建 | 原第一条数据库记录被覆盖成第二条，产生两条相同 active 记录 |
| 文件写入成功、数据库写入失败 | 数据库回滚，但文件残留孤儿条目 |
| 自动提取出 episodic 记忆 | 普通后续对话只查 core，完全不召回该观察 |
| 存在任意无关 core 记忆 | 零相关结果仍被返回，并阻断本可命中的深度召回 |
| 遗忘已产生核心记忆的来源会话 | episodic 被删，派生 core 仍保持 active |
| local 遗忘一个 QQ 会话 ID | 写入全局遗忘墓碑，未校验身份归属 |
| completed 目标从文件重建 | 生命周期丢失，重新变成 active |

重构前 113 项测试全部通过，说明当时的测试集中缺少多身份、崩溃恢复、索引重建、弱相关过滤和来源级遗忘场景，而不是上述行为正确。

现有检索评估也会高估效果：固定集只有 20 条，其中同义表达仅 2 条；每次只放入目标和约 7 条通用干扰项，却使用 Recall@5 判断成功。该评估得到 0.95，并不能代表真实记忆库中的排序质量。补充 6 条自然改写压力样例后，当前无 embedding 词法路径全部漏召回：

| 查询 | 应命中记忆 |
|---|---|
| 早上锻炼怎么安排 | 用户习惯晨跑 |
| 给我推荐不含肉的晚餐 | 用户偏好素食饮食 |
| 接着做那个桌面助手 | 用户正在开发知语个人 AI 助手 |
| 我对象最近怎么样 | 李梅是用户的女朋友 |
| 别给我太啰嗦 | 用户喜欢简洁回答 |
| 搬家前我住哪儿 | 用户曾居住在北京 |

因此本方案不把旧评估的 0.95 作为基线，而是重新规定候选规模、hard negatives、分层指标、开发集/留出集和端到端验收。

## 3. 目标与非目标

### 3.1 目标

改造完成后必须满足：

1. 用户可直接阅读、编辑和备份自己的长期记忆文件。
2. 获准的本机与主人 QQ Session 共享 local identity 记忆空间，其他身份保持隔离。
3. 文件任意增删、移动行后，索引重建不会篡改其他记忆。
4. 任一阶段崩溃后，文件与数据库能够自动收敛到同一操作结果。
5. 普通对话产生的观察可被相关问题召回，但不会被当作稳定核心事实。
6. 明确“记住”和明确纠正可以立即修改核心记忆。
7. 自动晋升必须同时通过代码门槛和受约束的模型判断。
8. 无关记忆不能因为 `top_k` 未填满而注入上下文。
9. 每条自动核心记忆都能解释来自哪些会话和观察。
10. 遗忘某来源后不会重新摄取，也不会误删仍有其他来源支持的记忆。
11. embedding、索引或记忆文件故障不得阻塞正常聊天。

### 3.2 非目标

第一版不实现：

- 跨渠道自动判断两个身份是同一个人。
- 多个身份默认共享私人记忆。
- 知识图谱、Memory Wiki 或完整 REM 多阶段推理。
- 图片、音频等多模态记忆正文。
- 让模型直接决定文件路径、身份、可信等级或删除范围。
- 实时强一致的分布式文件系统。
- 自动修改用户手写的任意 Markdown 文档。

## 4. 核心概念与权威边界

### 4.1 两类权威，不重复保存同一种事实

| 数据 | 权威来源 | 是否可重建 |
|---|---|---|
| 记忆正文 | Markdown 文件 | 不从索引反向覆盖 |
| 文档结构、条目位置、全文索引 | SQLite 索引表 | 可从文件重建 |
| embedding | SQLite 索引表 | 可重新计算 |
| 身份归属 | 目录解析 + SQLite 身份映射 | 目录不能跨身份扫描 |
| 可信来源、来源会话、来源消息 | SQLite provenance 表 | 不允许从正文推断 |
| 召回次数与查询多样性 | SQLite recall events | 可过期清理，不写入正文 |
| 晋升、替换和遗忘记录 | SQLite lifecycle 表 | 不由 Markdown 注释伪造 |
| 待执行文件操作 | SQLite mutation journal | 完成后可清理 |

关键规则：SQLite 不再保存一份需要与 Markdown 逐字同步的 `Memory.content` 业务副本。索引表可以缓存 chunk 文本以便搜索，但缓存永远从文件刷新，不能反向覆盖文件。

### 4.2 Agent 记忆空间模型

第一版采用：

```text
一个 personal Agent = 一个 local identity = 一个私人记忆空间
```

- 本机 Session 与通过主人白名单校验的 QQ Session 都使用 local identity 的 vault。
- Conversation 继续隔离每条 Session 的消息历史；共享 identity 不代表可以跨 Session 注入原始 transcript。
- 未获准的渠道用户在进入 Agent 前拒绝，不能创建会话或读写 local vault。
- 旧 QQ identity 与 vault 不自动合并；需要导入时必须由用户明确确认来源。
- 如果未来支持多用户或多 Agent，每个独立主体必须使用不同 identity/vault，不能只依赖会话筛选。

## 5. 文件布局

默认目录继续位于 `settings.memory_dir`：

```text
memory/
├── identities/
│   ├── <identity-id>/
│   │   ├── USER.md
│   │   ├── MEMORY.md
│   │   ├── DREAMS.md
│   │   └── daily/
│   │       ├── 2026-10-01.md
│   │       └── 2026-10-02.md
│   └── <another-identity-id>/
│       └── ...
├── shared/
│   └── MEMORY.md
└── quarantine/
    └── ...
```

路径规则：

1. `identity-id` 使用数据库 UUID，不使用昵称或外部平台账号作为目录名。
2. 所有路径通过 `resolve()` 后必须仍在目标 vault 内。
3. 不跟随符号链接。
4. 默认只扫描 `USER.md`、`MEMORY.md` 和 `daily/*.md`。
5. `DREAMS.md` 仅用于审查，不自动作为稳定记忆注入。
6. 任意其他 `.md` 文件不会因为位于 `memory_dir` 就自动进入索引。
7. 日期按应用配置时区生成，当前默认 `Asia/Shanghai`，不能使用 UTC 日期作为本地日记名。

## 6. Markdown 语义

### 6.1 `USER.md`

保存稳定且可执行的用户模型：

- 沟通风格偏好。
- 稳定饮食、语言和内容偏好。
- 基本身份资料。
- 对未来回答有长期影响的关系信息。

示例：

```markdown
# User Model

## Communication

- 回答时先给结论，再解释理由。

## Preferences

- 不推荐含咖啡因的饮品。
```

### 6.2 `MEMORY.md`

保存稳定事实、活跃项目和长期目标：

```markdown
# Durable Memory

## Projects

- 正在开发个人 AI 助手“知语”。

## Goals

- 完成 QQ 渠道的可靠接入。
```

已完成目标从活动章节移除；如需保留审计历史，由 SQLite lifecycle 和来源记录承担，不在核心注入文件中继续作为 active 内容存在。

### 6.3 每日情景记忆

每日文件保存可检索但未经长期确认的观察：

```markdown
# 2026-10-02

- [14:32] 用户提到最近开始学习 Rust。
- [16:10] 用户说下午不再喝咖啡。
```

程序写入的条目可以携带不可见的稳定操作 ID：

```markdown
- [16:10] 用户说下午不再喝咖啡。 <!-- zhiyu:id=2bb7... -->
```

规则：

- `zhiyu:id` 只用于稳定寻址，不代表身份、可信等级或生命周期。
- 缺少 ID 的用户手写条目仍可索引，索引器为其生成基于文档和内容的派生 ID。
- 用户编辑正文但保留 ID 时视为同一条目的新版本。
- 用户删除条目时视为正文删除，不允许用下一行内容覆盖原条目。

## 7. SQLite 数据模型

### 7.1 `memory_documents`

记录受管文档，不保存另一份权威正文：

```text
id
identity_id
vault_kind              # private / shared
relative_path
document_kind           # user / core / daily / dreams
content_hash
mtime_ns
index_status             # ready / stale / indexing / failed
last_indexed_at
last_error
```

唯一约束：`(identity_id, vault_kind, relative_path)`。

### 7.2 `memory_chunks`

可重建检索缓存：

```text
id
document_id
entry_key
chunk_index
text_cache
text_hash
heading_path
line_start
line_end
tier                     # core / episodic
importance nullable
trigger_text nullable
observed_at nullable
```

唯一约束：`(document_id, entry_key, chunk_index)`。

`line_start/line_end` 仅用于展示和引用，绝不能作为记录身份。

### 7.3 `memory_embeddings`

```text
id
chunk_id
provider
model
dimensions
vector
text_hash
created_at
```

唯一约束：`(chunk_id, provider, model, text_hash)`。

查询时只能读取当前 provider/model/dimensions 兼容的向量。修改 embedding 配置后索引标记 stale，在重建完成前退化到 FTS/BM25，不能混用旧模型向量。

### 7.4 `memory_sources`

保存不可由 Markdown 伪造的来源谱系：

```text
id
identity_id
target_entry_key
source_entry_key nullable
source_conversation_id nullable
source_message_id nullable
trust                    # owner / agent / untrusted / system
source_kind              # manual / message / consolidation / import
observed_at
created_at
```

一条核心记忆可以拥有多个来源。一条来源删除后，只有不存在其他有效来源时，核心记忆才进入删除或人工复核流程。

### 7.5 `memory_lifecycle`

记录不应写进正文的状态变化：

```text
id
identity_id
entry_key
event                    # created / edited / promoted / superseded / completed / forgotten
supersedes_entry_key nullable
operation_id
created_at
```

### 7.6 `memory_recall_events`

只记录真正注入模型的结果：

```text
id
identity_id
chunk_id
query_hash
score
recall_mode              # bootstrap / trigger / search / deep
created_at
```

不保存完整用户查询。明细默认保留 90 天，聚合后可清理。

### 7.7 `forgotten_sources`

```text
id
identity_id
source_kind
source_id
created_at
```

唯一约束：`(identity_id, source_kind, source_id)`。所有提取、回填、巩固和索引入口必须先检查墓碑。

### 7.8 `memory_mutations`

用于跨 SQLite 与文件系统的可恢复操作：

```text
id
identity_id
operation                # append / replace / remove
relative_path
entry_key
expected_file_hash nullable
new_entry_text nullable
new_entry_hash nullable
status                   # prepared / file_applied / completed / failed
attempts
last_error
created_at
updated_at
```

## 8. 文件修改与崩溃恢复

SQLite 与文件系统无法共享真正的 ACID 事务。本方案不再用 `try/rollback` 制造“已经回滚文件”的假象，而采用可恢复状态机。

### 8.1 修改流程

```text
1. 校验身份、路径、目标条目和 expected_file_hash
2. 在 SQLite 写入 mutation(status=prepared) 并提交
3. 获取该 vault 的文件锁
4. 重新读取并校验文件哈希
5. 写临时文件、fsync、原子 replace
6. 更新 mutation(status=file_applied) 并提交
7. 重建受影响文档索引、写来源和生命周期
8. 更新 mutation(status=completed) 并提交
```

### 8.2 启动恢复

- `prepared` 且文件没有目标变更：安全重试文件操作。
- `prepared` 但文件已经包含目标操作 ID：进入 `file_applied`，不重复追加。
- `file_applied`：重建索引并完成元数据提交。
- 文件哈希冲突：停止自动覆盖，标记 `failed` 并提示用户重新审查。
- 文件有未知手工修改：正常重新索引；未知内容不能继承已有自动来源的 trust。

### 8.3 并发

- 每个 identity vault 使用独立锁，不阻塞其他身份。
- 同一文件使用 `expected_file_hash` 做乐观并发控制。
- UI 编辑和后台巩固冲突时保留用户文件，不让后台覆盖。
- mutation 操作必须幂等；重试不能产生重复条目。

## 9. 写入链路

### 9.1 普通对话

```text
用户消息
  → 回答成功并提交消息
  → 创建持久化 observation job
  → 模型只提取有当前用户原文证据的观察
  → 写入该 identity 的 daily/YYYY-MM-DD.md
  → 建立 message/conversation 来源
  → 更新情景索引
```

普通观察不能直接写 `USER.md` 或 `MEMORY.md`。

以下内容不得进入观察：

- 助手建议和猜测。
- 工具输出、网页正文和系统提示。
- 引用、小说角色和第三方陈述。
- 已召回记忆的简单复述。
- 一次性寒暄和没有后续价值的临时状态。

### 9.2 明确记住

以下入口可直接写核心文件：

- `zhiyu memory add`。
- TUI `/remember`。
- 后续经过权限控制的自然语言 remember 工具。

直接写入仍需：

1. 身份和目标 vault 校验。
2. 类型、长度和文件预算校验。
3. 精确重复检查。
4. preference/profile 冲突候选检查。
5. mutation journal。
6. owner 来源记录。

### 9.3 明确纠正

用户明确表达“不是 A，而是 B”“以后不要 A”等纠正时：

1. 从当前身份的核心记忆中检索少量冲突候选。
2. 模型只能在给定候选内提出 `replace` 或 `invalidate`。
3. evidence 必须来自当前用户消息。
4. 高置信的单目标纠正立即修改核心文件，不等待后台巩固。
5. 目标不明确时只写 daily observation，不自动覆盖。

这保证旧偏好不会在已明确改口后继续注入数天。

## 10. 索引与检索

召回不是单一相似度函数，而是一条端到端链路：

```text
记忆是否被正确写入
  × 索引是否及时且完整
  × 查询是否表达了真实意图
  × 候选生成是否包含目标
  × 排序和过滤是否保留目标
  × 上下文预算是否真正注入
  × 回答模型是否正确使用
```

任一环节只有 90% 成功率，七个环节相乘后整体成功率约为 48%。因此评估不能只测一个 `retrieve()` 函数。

### 10.1 Entry-aware 索引器

索引器按文档执行：

1. 读取限定路径中的文件。
2. `USER.md`、`MEMORY.md` 和 daily 文件中的单条 bullet 优先作为原子 entry，不把多个独立事实拼进同一 chunk。
3. 只有长段落或单条内容超过预算时，才按 400 tokens、80 tokens overlap 切块。
4. 索引文本可以附加受控标题路径，例如 `Preferences / 饮食`，但展示正文保持不变。
5. 优先使用稳定 `entry_key`；缺少时使用文档路径、标题路径和内容哈希生成派生键。
6. 在一个 SQLite 事务中 upsert 新 chunks，并删除本次扫描未出现的旧 chunks。
7. 不根据“相同行号”修改既有条目。
8. 不根据一个哈希字典合并文件中真实存在的重复条目。
9. embedding 在后台批量补齐；失败不影响 FTS/BM25 索引可用性。

程序写入文件后立即更新受影响文档的词法索引，不等待文件监听器；文件监听器只负责发现外部手工修改。新记忆即使尚未生成 embedding，也必须可以通过精确、trigger 和中文词法通道被找到。

### 10.2 中文规范化与词法索引

SQLite FTS5/BM25 的默认 tokenizer 不能作为中文召回质量的隐含假设。索引和查询必须共享同一套规范化：

1. Unicode NFKC 规范化。
2. 拉丁字母转小写，全角/半角统一。
3. 折叠空白和无语义标点，但保留日期、小数、版本号等结构。
4. 中文建立字符 bigram/trigram 索引；如引入中文分词器，仍保留 n-gram 作为召回兜底。
5. 英文缩写、产品名和中英文别名进入受控 alias 表，例如 `MCP ↔ Model Context Protocol`。
6. 人物称谓只在当前身份的已知关系范围内扩展，例如 `对象 ↔ 女朋友/男朋友/伴侣`，不能全局猜测具体人物。
7. 日期表达归一化为结构化时间范围，同时保留原词，例如 `上个月`、`搬家前`、`2026 年 9 月`。

词法后端必须分别评估中文、英文、混合语言、专有名词和短查询，不能只报告一个总体分数。

### 10.3 Retrieval Query Builder

检索不能只使用当前一条用户消息。`RetrievalQueryBuilder` 输入：

- 当前用户消息。
- 最近 2～4 轮对话的用户侧主题信息。
- 当前会话已识别的人物、项目和地点实体。
- 当前项目或角色作用域。
- 时间意图和是否明确要求回忆。

输出受限的检索计划：

```json
{
  "original": "接着做那个桌面助手",
  "normalized": "继续 桌面 AI 助手 项目",
  "aliases": ["知语", "个人 AI 助手"],
  "entities": ["project:知语"],
  "temporal_intent": "current",
  "recall_intent": true
}
```

规则：

- 确定性规范化和已有 alias 优先，不为每轮增加模型调用。
- “那个、她、以前”等指代必须利用近期上下文；无法消解时保留多个受限查询，不自行确定唯一事实。
- 只有明确 recall intent 且快速通道不足时，才允许使用小模型或当前模型生成最多 3 个查询改写。
- 查询改写只能改变检索表达，不能生成新的用户事实。
- 完整查询不写日志；调试信息使用脱敏文本或不可逆 hash。

### 10.4 多路候选生成

候选生成和最终注入必须分离：

| 通道 | 初始候选上限 | 作用 |
|---|---:|---|
| 精确短语与 alias | 20 | 人名、项目名、日期、专有名词 |
| trigger | 10 | 已晋升核心记忆的高精度触发 |
| 中文 n-gram / BM25 | 30 | 无 embedding 时的主要召回通道 |
| vector | 30 | 同义表达和语义改写 |

各通道先独立生成候选，再合并成约 30～80 条候选池。`max_results=6` 只表示最终注入上限，不能限制早期候选生成。

### 10.5 排名融合

BM25、n-gram 和 cosine 分数范围不同，不直接执行 `0.65 × vector + 0.35 × lexical`。第一版使用 Reciprocal Rank Fusion：

```text
rrf_score(entry) = Σ 1 / (60 + rank_in_channel)
```

融合后按以下顺序处理：

1. 身份与 vault 硬过滤。
2. forgotten source 硬过滤。
3. 生命周期和来源有效性过滤。
4. 时间意图和项目作用域调整。
5. tier、可信等级、recency 和 importance 轻度加权。
6. MMR 去重。
7. 校准后的置信度门槛。
8. 取最终 Top 6，并应用字符/token 预算。

初始参数：

| 参数 | 初始值 |
|---|---:|
| 每个词法/向量通道候选数 | 30 |
| 精确通道候选数 | 20 |
| trigger 候选数 | 10 |
| RRF `k` | 60 |
| 最终 `max_results` | 6 |
| daily 半衰期 | 30 天 |
| MMR lambda | 0.7 |
| 最终 trigger 注入上限 | 3 |
| 总记忆预算 | 1600 字符或模型窗口的 10%，取较小值 |

不得直接照搬固定 `min_score=0.35`。置信度阈值必须分别在以下模式的开发集上校准，并在留出集上验收：

- vector + lexical。
- 纯 lexical 降级。
- 短查询与长查询。
- 中文、英文和中英混合。

无候选超过对应模式的阈值时返回空结果，不能为了填满 Top K 注入弱相关内容。

### 10.6 生命周期、时态与冲突

检索到内容不代表内容当前有效：

- `superseded/completed/forgotten` 核心条目默认不进入当前状态回答。
- 当前 active core 与旧 daily observation 冲突时，当前 core 优先。
- 查询包含“以前、当时、搬家前”等历史意图时，允许返回对应时间范围的旧观察，并明确标注历史状态。
- 查询包含“现在、目前、以后”等当前意图时，旧冲突观察必须降权或过滤。
- 项目记忆优先匹配当前项目；低相关项目不能仅凭高 importance 压过当前上下文。
- 同一事实的 core、daily 和消息片段按 entry/source ID 去重，不能只按文本近似去重。

### 10.7 Trigger 生成与维护

trigger 只用于高精度核心召回，不用于 daily observation：

1. 手动核心记忆可由用户显式提供 trigger；未提供时使用实体、标题和受控 alias 确定性生成。
2. 自动晋升时，模型只能从核心正文和已知实体中提出最多 5 个 trigger。
3. trigger 在提交前经过长度、重复、停用词和跨身份校验。
4. 用户编辑核心正文后重新生成派生 trigger；用户显式 trigger 保留，除非用户删除。
5. supersede、complete 或 forget 时同步失效关联 trigger。
6. trigger 命中仍需通过身份、来源和生命周期硬过滤。

### 10.8 embedding 降级

- 查询 embedding 改为异步调用。
- 设置独立短超时；超时后立即使用 n-gram/BM25，不阻塞正常回答。
- 远程 embedding 失败必须在 `memory status` 中显示降级原因。
- 同一规范化查询可使用短期缓存。
- 索引向量严格按 provider、model、dimensions 和 text hash 匹配。
- embedding 配置变化后旧向量标记 incompatible，不参与新查询。
- 新内容的词法索引同步可用，embedding 允许后台最终补齐。

### 10.9 快速召回与注入

顺序：

1. 使用 Query Builder 生成检索计划。
2. 在独立小预算内加载 `USER.md` 的稳定用户模型；超出预算时按当前查询选择相关 entry，不截断半条记忆。
3. 执行四路候选生成和 RRF。
4. 应用身份、来源、生命周期、时态和项目过滤。
5. 应用重排、MMR 和置信度门槛。
6. 分别标注 core 为稳定信息、episodic 为历史证据。
7. 按 entry/source ID 与 bootstrap 内容去重。
8. 只记录最终实际注入的 recall event。

上下文裁剪必须保证当前用户消息优先于记忆内容；模型窗口不足时先减少召回条数，不能删除当前问题来保留历史记忆。

### 10.10 深度召回

只有同时满足以下条件才执行：

1. 查询包含过去、先前决定、时间关系、模糊指代或跨会话意图。
2. 快速通道没有超过强匹配门槛的结果，或结果无法覆盖查询中的主要实体。

深度召回流程：

1. 基于近期上下文生成最多 3 个受限查询改写。
2. 搜索当前记忆空间的 daily，以及当前 Session 中已被普通上下文裁剪的早期消息；不跨 Session 读取原始 transcript。
3. 命中消息后读取前后有限窗口，而不是只返回孤立单句。
4. 按会话、时间和来源去重，并应用 forgotten tombstone。
5. 返回带日期和来源类型的历史片段，明确它不是当前稳定事实。
6. 仍无强匹配时返回空，让回答明确表示不确定，不选取最像的一条强答。

深度召回不能读取其他身份、修改记忆或调用外部工具；必须有独立短超时和结果预算。

### 10.11 召回诊断

新增：

```bash
zhiyu memory recall-explain "接着做那个桌面助手"
```

默认输出脱敏诊断：

```text
query plan
index version / stale state
各通道候选 ID、排名和原始分数
RRF 分数
身份、来源、生命周期、时态过滤原因
recency / importance / project 调整
MMR 淘汰原因
置信度门槛
最终注入 ID 与预算
是否触发 deep recall
```

`--show-content` 只允许当前身份的本地管理入口使用。生产日志不记录完整查询和记忆正文。

## 11. 后台巩固

### 11.1 调度

满足任一条件时调度当前身份的 consolidation job：

- 新增 observation 后 pending 数量达到 20。
- 最旧 pending observation 超过 24 小时。
- `memory sync` 完成提取任务后达到门槛。
- TUI/QQ 常驻进程进入空闲时段。
- 用户手动运行 `memory consolidate`。

单次 CLI 不等待巩固，但任务必须持久化，不能只依赖裸 `asyncio.create_task`。

### 11.2 确定性候选门槛

候选必须属于当前身份，且同时满足：

- 来源未被遗忘。
- trust 为 `owner` 或 `agent`。
- 观察正文仍存在于当前文件版本。
- 尚未晋升或拒绝。
- 满足以下至少一项：
  - 被实际召回至少 3 次，来自至少 3 个不同查询；
  - 在至少 2 个日期或会话中出现语义一致的独立观察；
  - 用户明确确认长期有效；
  - 活跃 goal/project 被后续对话再次引用。

未通过代码门槛的候选不发送给巩固模型。

### 11.3 模型协议

模型只能返回：

```json
[
  {
    "action": "add_core",
    "candidate_ids": ["..."],
    "target_file": "USER.md",
    "section": "Preferences",
    "content": "不推荐含咖啡因的饮品",
    "importance": 0.8
  },
  {
    "action": "supersede_core",
    "target_entry_key": "...",
    "candidate_ids": ["..."],
    "content": "用户目前居住在杭州"
  },
  {
    "action": "ignore",
    "candidate_ids": ["..."]
  }
]
```

模型不能提供 identity、任意文件路径、trust、来源消息或遗忘范围。

### 11.4 应用

1. 模型调用前结束数据库事务。
2. 返回后重新读取候选、文件哈希和目标条目。
3. 任一候选过时则拒绝对应操作。
4. 同一目标在一批操作中最多修改一次。
5. mutation journal 应用文件变更。
6. 建立所有 candidate → core 来源关系。
7. 在同一 SQLite 事务中完成 lifecycle、promotion 和 consolidation run。
8. 文件冲突时不覆盖用户编辑，任务进入 failed/review 状态。

## 12. 遗忘与删除

### 12.1 删除单条记忆

`memory forget <entry-id>`：

- 校验当前身份拥有该条目。
- 默认先 dry-run 展示文件修改和派生影响。
- 通过 mutation journal 删除正文。
- 删除对应 chunks 和 embeddings。
- 写入 lifecycle 记录。

### 12.2 遗忘会话

`memory forget --conversation <id>`：

1. 验证会话属于当前身份。
2. dry-run 枚举该来源支持的 daily 条目和 core 条目。
3. 删除该会话直接产生的 daily 条目。
4. 从 core 条目移除该来源关系。
5. core 仍有其他有效来源：保留正文。
6. core 已无有效来源：删除正文或进入人工复核，取决于其是否有 owner 手工来源。
7. 写入带 `identity_id` 的 forgotten source tombstone。
8. 之后的任务、回填和索引不能重新摄取该来源。

遗忘一个身份的会话绝不能影响其他身份。

## 13. 用户编辑文件

用户可以直接编辑自己的 vault。文件监听器执行防抖重建：

- 新增 core 内容：作为 owner-curated 内容建立索引。
- 编辑 core 内容：更新 chunk，不创建旧内容的第二条 active 记录。
- 删除 core 内容：删除索引；生命周期记录为 manual deletion。
- 编辑 daily 内容：更新情景索引，但不自动提高 trust。
- 删除 daily 内容：删除索引，并阻止使用旧快照继续晋升。
- 非法编码、超大文件或解析失败：保留原文件，索引标记 failed，不阻塞聊天。

来源元数据不能通过在 Markdown 中写入 `trust=owner` 等文本进行提升。

## 14. 运行时降级与可观察性

`zhiyu memory status` 至少显示：

```text
identity
vault_path
documents_ready
documents_stale
index_backend
embedding_provider
embedding_model
embedding_degraded_reason
episodic_pending
consolidation_pending
consolidation_failed
mutations_pending
mutations_failed
last_indexed_at
last_consolidation_at
last_recall_mode
last_recall_candidate_count
last_recall_injected_count
```

降级规则：

- Markdown 不可写：聊天继续，记忆任务进入 failed，可重试。
- embedding 不可用：退化到 FTS/BM25。
- 索引 stale：使用仍兼容的词法索引并提示状态，不返回不兼容向量结果。
- 单个文件解析失败：跳过该文件，不清空其他文件的有效索引。
- mutation 冲突：保护用户文件，不自动强制覆盖。

日志只记录 identity ID、文档 ID、操作 ID、计数、耗时和错误类型，不记录完整聊天正文或 API Key。

`memory status` 用于健康检查，`memory recall-explain` 用于单次查询诊断。两者不能互相替代。

## 15. 与当前模块的映射

| 当前模块 | 调整方向 |
|---|---|
| `core/memory/store.py` | 改为 identity-scoped vault、受限路径、稳定 entry、文件锁和原子替换 |
| `core/memory/indexer.py` | 移除行号匹配；改为 entry-aware 文档快照 → chunk upsert/delete；同步生成中文 n-gram 索引 |
| `core/memory/manager.py` | 只编排 observation 与 mutation，不直接执行不可恢复双写 |
| `core/memory/extractor.py` | 保留证据协议，增加召回反馈污染标记 |
| `core/memory/retriever.py` | 拆为 query builder、四路候选生成、RRF、时态/生命周期过滤、MMR 和阈值校准 |
| `core/memory/consolidation.py` | 增加代码门槛、来源图、文件哈希快照和幂等 mutation |
| `core/memory/deep_recall.py` | 增加受限查询改写、命中消息窗口读取和当前长会话早期消息 |
| `core/agent/context.py` | 异步召回；分别标记 core 与 episodic 的可信语义 |
| `application/memory_jobs.py` | 提取完成后按身份调度索引与巩固 |
| `application/consolidation_jobs.py` | 支持任意 identity，不再固定 local |
| `application/memories.py` | 按 entry/source 管理，提供 recall-explain，所有删除默认支持 dry-run |
| `infrastructure/database/models.py` | 新增 documents、chunks、sources、recalls、mutations、forgotten sources |

## 16. 迁移方案

迁移必须分阶段，任一阶段都可回滚到只读旧系统。

### Phase 0：冻结与备份

1. 暂停当前 Markdown 反向重建命令。
2. 备份数据库和现有 memory 目录。
3. 输出按 identity 分组的现有 active/core/episodic 报告。
4. 检测重复内容、跨身份相同文件引用和孤儿文件条目。

验收：备份可恢复；报告不修改任何数据。

### Phase 1：身份 vault 与只读索引

1. 创建 `identities/<identity-id>/` 目录。
2. 按数据库现有身份导出 `USER.md`、`MEMORY.md` 和 daily 文件。
3. 为新文件建立只读 document/chunk 索引。
4. 新旧召回并行评估，但回答仍使用旧召回。

验收：未获准或独立身份的内容不会出现在 local vault；文件增删行后索引结果正确。

### Phase 2：切换召回

1. 上线中文规范化、n-gram/BM25 和 entry-aware 索引。
2. 上线 Query Builder、精确/alias/trigger/词法四路候选生成。
3. 后台补齐当前 embedding 模型向量，并加入 vector 通道。
4. 上线 RRF、身份/生命周期/时态过滤、MMR 和分模式阈值。
5. 上线 `memory recall-explain`，以 shadow 模式对比新旧召回。
6. 使用开发集调参，在未参与调参的留出集达到门槛后切换 Agent 上下文。
7. 保留旧检索只读开关用于回滚。

验收：同义改写、模糊指代和时间问题达到分层指标；无关结果不注入；embedding 故障不增加明显回答延迟。

### Phase 3：切换写入

1. 上线 mutation journal 和启动恢复。
2. 普通 observation 写入 identity daily 文件。
3. 手动 remember/edit 写入核心文件。
4. 禁止旧 `memories.content ↔ Markdown 行` 双写路径。

验收：在 prepared、file_applied 和索引提交阶段分别注入崩溃，重启后均不重复、不丢失、不串号。

### Phase 4：巩固与来源遗忘

1. 上线 sources、recall events 和确定性晋升门槛。
2. TUI、QQ 和 `memory sync` 按身份调度巩固。
3. 上线来源级 forget dry-run/apply。
4. 删除旧的全局 `forgotten_conversations` 行为。

验收：晋升可解释；遗忘唯一来源会删除派生 core；多来源 core 保留。

### Phase 5：清理旧结构

1. 旧 `memories` 表改为只读归档或迁移后删除正文列。
2. 删除行号驱动的重建逻辑。
3. 删除全局 `USER.md/MEMORY.md/日期.md` 写入路径。
4. 更新 CLI、文档和 doctor 检查。

验收：运行时只有一条文件正文写入路径和一套召回编排。

## 17. 测试策略

### 17.1 必须新增的确定性测试

- 本机与获准主人 QQ Session 写入后都能从 local vault 召回。
- 不同 Session 的原始 transcript 不会因共享记忆空间而互相注入。
- 未获准或独立身份写入后不能召回 local vault 的私人记忆。
- 删除第一条 Markdown 后，第二条索引仍只有一条且内容不变。
- 两条正文完全相同时仍保留两个独立 entry，不因 hash 相同丢失。
- 数据库在 mutation 各阶段失败后能够恢复。
- 手工编辑与后台巩固并发时保护用户版本。
- 自动 observation 普通相关查询可以召回，并被标记为历史证据。
- 零相关 core 不注入，也不阻断深度召回。
- “那个项目、她、以前那个方式”等查询可以利用近期上下文构建检索计划。
- 纯中文同义表达在无 embedding 模式下可通过 alias 或 n-gram 召回合理候选。
- 每个候选通道先生成足量候选，最终 `max_results` 不会截断早期候选池。
- BM25、n-gram 和 cosine 不直接混合原始分数，RRF 结果可重复。
- trigger 可生成、更新和随生命周期失效。
- 当前状态查询过滤旧冲突观察，历史状态查询可以返回带时间标记的旧观察。
- 当前长会话早期消息可以被深度召回。
- 深度召回读取命中消息前后窗口，并在没有强匹配时返回空。
- 上下文不足时先减少记忆注入，不删除当前用户消息。
- embedding 超时后在限定时间内退化到 FTS/BM25。
- embedding 模型切换后不读取旧模型向量。
- 明确偏好纠正立即替换旧 core。
- 未达到频率和来源门槛的观察不能晋升。
- 遗忘会话必须验证 identity。
- 遗忘唯一来源后删除派生 core；仍有其他来源时保留。
- 已遗忘来源不能被 session backfill 重新摄取。
- completed 目标不会通过重建重新变成 active。
- 标题、普通说明和 `DREAMS.md` 不会被错误当作 core 条目。
- 上海时间凌晨写入当天而不是前一天的 daily 文件。

### 17.2 故障注入

至少覆盖：

- 文件锁超时。
- 临时文件写入失败。
- `os.replace` 前后进程退出。
- mutation `file_applied` 后数据库不可用。
- embedding 连接超时、返回错误维度和无效 JSON。
- 文件被外部编辑造成 expected hash 冲突。
- 两个后台任务同时修改同一核心文件。

### 17.3 语义评估

评估分为开发集和留出集。开发集用于选择阈值和权重，留出集只用于最终验收；不得在看到留出集结果后继续调参。

每个检索查询必须与 30～100 条候选一起评估，候选优先使用同一用户、同一主题或相邻时间的 hard negatives，不能只使用随机无关句子。固定评估集至少包含：

- 50 组 observation 提取。
- 40 组晋升、合并与冲突更新。
- 120 组检索，其中至少：
  - 25 组同义表达；
  - 20 组模糊指代和多轮上下文；
  - 20 组时间状态与新旧冲突；
  - 15 组人物、项目和中英文别名；
  - 20 组应返回空的纯干扰查询；
  - 20 组跨会话或当前长会话早期消息。
- 20 组身份隔离。
- 20 组来源遗忘。
- 15 组召回反馈污染。

评估必须调用生产使用的统一 `MemoryRecallService`，不能只测试未被运行时调用的旧 `retrieve()`。以下模式分别报告，不能用一种模式的结果替代另一种：

- embedding 正常。
- embedding 超时后的纯词法降级。
- 新记忆尚未生成 embedding。
- 索引刚完成外部文件编辑后的增量更新。

召回链路分层统计：

| 层级 | 指标 |
|---|---|
| Observation | 应写信息提取覆盖率、错误写入率 |
| Index | 可索引正文覆盖率、增量索引延迟 |
| Candidate | Candidate Recall@30、各通道独立召回率 |
| Ranking | Recall@1/3/6、MRR、nDCG@6 |
| Injection | Precision@6、空结果准确率、预算丢弃率 |
| Answer | 正确使用率、错误引用率、明确不确定率 |

目标指标：

| 指标 | 目标 |
|---|---:|
| 跨身份泄漏 | 0 |
| 错误核心写入率 | ≤ 2% |
| 明确偏好更新正确率 | ≥ 95% |
| Observation 应写信息提取覆盖率 | ≥ 95% |
| Candidate Recall@30 | ≥ 99% |
| Recall@1 | ≥ 85% |
| Recall@3 | ≥ 94% |
| Recall@6 | ≥ 97% |
| MRR | ≥ 0.90 |
| 无关结果注入率 | ≤ 8% |
| 应返回空查询准确率 | ≥ 95% |
| 新记忆词法可检索延迟 | ≤ 1 秒 |
| untrusted 自动晋升 | 0 |
| 遗忘来源重新摄取 | 0 |
| embedding 故障导致聊天失败 | 0 |

所有召回指标同时报告总体值和各类别值。总体达标但同义、指代、时间或纯词法任一关键类别低于 90% 时，仍视为未通过。

## 18. 完成标准

本重构完成的标准不是“文件能写、向量能搜”，而是以下行为全部通过自动测试和真实使用验证：

1. 用户能在独立目录中看到和编辑自己的记忆。
2. 不同身份绝不会因索引重建互相复制记忆。
3. 移动或删除 Markdown 行不会篡改其他条目。
4. 崩溃恢复不会产生孤儿、重复或半次替换。
5. 普通观察可被相关查询找到，但不会冒充稳定事实。
6. 明确记住立即生效，明确改口立即覆盖。
7. 同义改写、模糊指代、人物别名和时间问题达到各自验收指标。
8. 无关结果不会为了凑满数量而注入，应返回空时不会强行猜测。
9. `recall-explain` 可以解释目标在哪一阶段被找到、过滤或丢弃。
10. 自动核心记忆可以解释全部有效来源。
11. 会话遗忘按身份和来源正确传播，并阻止重新摄取。
12. 记忆、索引和 embedding 任一故障都不会阻止正常回答。

达到以上标准后，知语才算真正采用了 OpenClaw 式文件记忆，而不是仅采用相似的文件命名。

## 19. 实施记录与验证结果

### 19.1 已落地范围

截至 2026-10-02，以下核心链路已经进入运行代码：

- 身份隔离的 Markdown vault、稳定 entry ID、原子写入和文件锁。
- 升级前数据库与记忆目录快照；旧全局正文迁移后从活动目录移除。
- `prepared → file_applied → completed/failed` mutation journal，以及启动/索引时的幂等恢复。
- 外部 Markdown 编辑后的索引同步、重复 ID 拒绝、失效 embedding 清理和生命周期保护。
- 中文查询归一化、受控别名、字符 n-gram、exact/trigger/lexical/vector 多通道、RRF 与 MMR。
- 当前状态冲突过滤、近期上下文指代展开、情景记忆召回和历史消息深度召回。
- owner/agent 信任分层、确定性巩固门槛、来源谱系和多来源核心保留。
- 身份级遗忘墓碑、来源级级联删除，以及 CLI 默认 dry-run、`--apply` 才实际删除。
- `memory recall-explain`、召回事件、mutation 状态和 embedding 降级状态可观测性。

### 19.2 有意保留的兼容实现

第一版没有立即新增独立的 `memory_documents` 与 `memory_chunks` 正文表，而是把现有
`memories` 表收敛为“一条 Markdown entry 对应一条派生索引记录”。Markdown 仍是正文
权威，SQLite 中的正文列只是可重建的检索缓存。这样可以在不进行第二次大规模数据迁移
的前提下解决身份串写、行号错绑、低召回和来源遗忘问题。若后续需要段落级、多文档级
索引，再按第 7 节拆表；当前原子粒度是 Markdown 列表条目。

旧 `memories` API 暂时保留为应用层兼容接口，运行时已经不再依赖全局 Markdown 写入。
这是 Phase 5 唯一有意延期的结构性清理，不影响本次行为目标。

### 19.3 自动化与真实命令验收

本次实现的最终验证结果：

| 检查 | 结果 |
|---|---:|
| 全量测试 | 150 passed |
| Python 编译检查 | passed |
| Git whitespace 检查 | passed |
| 固定检索用例 | 202 |
| Candidate Recall@30 | 1.000 |
| Recall@1 | 0.967 |
| Recall@3 / Recall@6 | 1.000 / 1.000 |
| MRR / nDCG@6 | 0.9808 / 0.9857 |
| 应返回空查询准确率 | 1.000 |

检索数字来自生产 `hybrid_rank` 的纯词法降级路径，候选池为 53。固定集合强制包含
25 条同义改写、20 条模糊指代、20 条时态查询、15 条实体别名、20 条跨会话查询和
20 条应返回空的查询。旧的 120 条集合因困难类别不足，在扩大候选池与类别覆盖后曾
暴露出总体 Recall@3 仅 80.2%、同义类 44%、实体别名类 33.3% 的问题；上述最终数字
是在修正查询构建器后重新得到的。集合包含开发与留出分区，但本轮开发过程中查看过
两边的失败样例，因此它只能作为可重复回归基准，不能冒充从未见过的盲测结果。
embedding 正常路径仍应在配置真实服务后单独报告。

另使用隔离的临时数据目录完成真实 CLI 烟测：数据库升级、手动添加、列表、
`recall-explain` 同义改写命中、遗忘默认预览、确认应用和删除后空列表均符合预期。

### 19.4 后续验证边界

本轮没有声称完成以下环境型验证：真实 embedding 服务的质量/超时压测、进程在
`os.replace` 指令级被强杀、网络文件系统锁行为、以及长时间真实用户 A/B 召回评估。
这些项目需要受控外部环境或长期样本，不应由本地确定性测试结果替代。

## 20. 参考

- [OpenClaw Builtin memory engine](https://docs.openclaw.ai/concepts/memory-builtin)
- [OpenClaw Memory configuration reference](https://docs.openclaw.ai/reference/memory-config)
- [OpenClaw Memory CLI](https://docs.openclaw.ai/cli/memory)
- [OpenClaw User model](https://docs.openclaw.ai/concepts/user-model)
- [OpenClaw Multi-agent routing](https://docs.openclaw.ai/multi-agent)
