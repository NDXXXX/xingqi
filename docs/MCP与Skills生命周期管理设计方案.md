# MCP 与 Skills 生命周期管理设计方案

> 版本：v1.0  
> 日期：2026-10-06  
> 状态：第一版已实施；自动化及本地协议冒烟通过，真实第三方服务待用户环境验证  
> 范围：让用户可以通过 CLI 安全地配置和维护 MCP Server 与 Skills；现有聊天界面只展示只读状态，不在本方案建设完整 Web 管理后台。

## 1. 结论

当前知语已能运行 MCP stdio Server、把 MCP 工具加入 Agent，并从本地 Skills 目录读取 `SKILL.md`。但用户还不能完整检查连接、处理运行中断、配置秘密环境变量、使用 MCP Resources/Prompts，或安装和维护 Skill。

本方案把 MCP 和 Skills 做成可日常使用的本地能力管理：

1. MCP 支持 stdio、Streamable HTTP 和旧 SSE 兼容连接。
2. MCP 配置支持安全环境变量、凭据引用、工具权限、启停、测试、运行状态和持续重连。
3. MCP Tools、Resources、Prompts 都能从 CLI 发现和检查；资源不自动塞进模型上下文，Prompt 需显式运行或由 Agent 在允许时调用。
4. Skills 支持检查、从本地目录/Git 源安装、升级、启停、移除、版本和依赖检查。
5. Skill 包只作为说明和声明式元数据读取；安装和更新不会执行其中的代码或自动安装依赖。
6. Runtime 自动加载持久化配置，单个 MCP 连接失败不影响聊天、QQ 或其他 MCP Server。

管理入口以 CLI 为主；Web/API 只提供只读状态和诊断。第一版不建市场，不开放远程任意安装器，也不扩大工具权限边界。

## 2. 当前基线

### 2.1 MCP

已实现：

- 仅支持通过 stdio 启动 MCP Server。
- MCP 工具可以转换为 Agent Tool，并使用 `name.tool` 命名空间。
- MCP 配置可保存名称、启动命令、参数和工具白名单。
- `zhiyu serve` 启动时连接已启用配置，启动连接有两次有限重试。
- CLI 有 `zhiyu mcp add/list/disable`。

未实现：

- Streamable HTTP、SSE、HTTP 认证和服务端传输配置。
- 每 Server 独立环境变量及其 Keychain 秘密引用。
- 运行期状态持久展示、断线监测、退避重连和手动重连。
- 删除配置、修改全部配置字段、连接测试、调用诊断日志。
- MCP Resources 和 Prompts。
- Web 只读 MCP 状态页/API。

### 2.2 Skills

已实现：

- 扫描内置目录与 `~/.zhiyu/skills`（支持 `ZHIYU_SKILLS_DIR`）。
- 从每个目录的 `SKILL.md` 读取 frontmatter 和正文。
- 根据名称/描述匹配 Skill；Agent 可以按需通过 `read_skill` 读取正文。
- 支持 `enabled` 和 `required_tools` 两个基础字段。

未实现：

- CLI 列表、验证、安装、升级、卸载、启停与版本查看。
- 来源、版本、内容哈希、安装记录和回滚信息。
- 正式的工具/外部命令依赖声明与依赖检查。
- 文件完整性检查、更新预览和可恢复删除。
- Web 只读 Skills 状态 API。

## 3. 用户目标与完成标准

普通用户完成后应能：

1. 按 CLI 提示添加一个本机 stdio MCP 或远程 HTTP MCP，验证成功后启用。
2. 给 MCP 配置环境变量和秘密，不需要把 API Key 写入数据库、命令历史或日志。
3. 查看 Server 连接状态、工具列表、权限范围、Resources、Prompts 和最近错误。
4. 运行一次 MCP 连接测试；在 Server 断线后无需重启知语即可自动恢复或手动重连。
5. 从一个本地 Skill 文件夹或 Git 仓库安装 Skill，查看内容/依赖检查结果，再启用它。
6. 检查 Skill 更新差异，执行升级；升级失败时恢复到前一版本。
7. 禁用或卸载用户安装的 Skill；误删可以恢复，内置 Skill 不会被删除。
8. 知道每个 Skill 可调用哪些工具、缺少什么依赖、内容来自哪里、当前安装哪个版本。

验收定义：上述操作有明确成功/失败消息和可操作原因；重启 `zhiyu serve` 后配置仍在；工具权限不能通过 MCP/Skill 声明自行扩大。

## 4. 产品边界

### 4.1 本方案包含

- CLI 作为完整配置与维护入口。
- MCP 三种传输：stdio、Streamable HTTP、兼容性 SSE。
- MCP 静态认证凭据、安全环境注入、工具白名单、运行状态与重连。
- MCP Tools、Resources、Prompts 的发现与显式使用。
- 用户 Skills 的本地/Git 安装、版本、更新、验证、依赖和删除。
- Runtime 自动启动与服务状态只读 API。

### 4.2 本方案不包含

- Skill/MCP 在线市场、评分、自动推荐和远程任意代码插件。
- Skill 脚本执行、依赖自动安装、容器沙箱或操作系统权限隔离。
- OAuth 浏览器授权流程；HTTP MCP 第一版使用静态 Bearer/API Key 凭据引用。
- 多用户、多租户隔离和远程 Web 配置写接口。
- Agent 自行添加 MCP Server、安装 Skill 或修改工具权限。
- 把 MCP Resource 全量索引或整个 Skill 正文预注入上下文。
- 自动安装/升级 MCP Server 的 Node、Python、uv、npm 或系统包依赖。

## 5. MCP 用户流程

### 5.1 stdio Server

```text
zhiyu mcp add stdio filesystem --command npx --arg -y --arg @modelcontextprotocol/server-filesystem --arg /Users/me/Documents
zhiyu mcp env set filesystem HOME /Users/me
zhiyu mcp env secret filesystem API_TOKEN
zhiyu mcp test filesystem
zhiyu mcp tools filesystem
zhiyu mcp enable filesystem
```

`env secret` 使用隐藏输入读取值并写入系统 Keychain，只把引用存入数据库。支持从受控环境变量导入的流程，但日志和错误中不能回显值。

### 5.2 Streamable HTTP

```text
zhiyu mcp add http docs --url https://mcp.example.com/mcp
zhiyu mcp auth set docs --bearer
zhiyu mcp test docs
zhiyu mcp enable docs
```

对 HTTP 端点默认要求 HTTPS；允许明文 HTTP 的情况只限 loopback 地址。认证信息从 Keychain 引用注入 HTTP Client，不能作为普通 CLI 参数传递。重定向遵循 MCP SDK 的同源限制，不跟随到任意第三方主机。

### 5.3 旧 SSE

旧 SSE Server 通过显式 `--transport sse` 添加。CLI 标明“兼容传输”，建议新 Server 使用 Streamable HTTP。若 SDK 版本不再支持该旧 transport，则 `doctor` 给出迁移指引，不自行拼写非标准 SSE 协议。

### 5.4 日常维护命令

```text
zhiyu mcp list [--all]
zhiyu mcp show NAME
zhiyu mcp test NAME
zhiyu mcp enable NAME
zhiyu mcp disable NAME
zhiyu mcp reconnect NAME
zhiyu mcp remove NAME --confirm
zhiyu mcp tools NAME
zhiyu mcp resources NAME
zhiyu mcp resource read NAME URI
zhiyu mcp prompts NAME
zhiyu mcp prompt show NAME PROMPT [--arg key=value]
zhiyu mcp logs NAME
zhiyu mcp doctor
```

`disable` 保留配置并关闭运行连接；`remove` 删除配置和与之关联的 Keychain 凭据引用，必须显式确认。它不卸载用户自行安装的外部 Server 程序。

## 6. MCP 配置、运行状态与权限

### 6.1 配置模型

扩展当前 `mcp_server_configs`，不再用 stdio 的 `command` 字段承载所有传输：

| 字段 | 含义 |
|---|---|
| `id` | 内部稳定 ID |
| `name` | 用户给出的唯一名称 |
| `transport` | `stdio`、`streamable_http` 或 `sse` |
| `command` / `args_json` | stdio 启动程序和参数；其他传输为空 |
| `url` | HTTP/SSE 端点 |
| `env_json` | 非秘密环境变量，仅限 stdio |
| `secret_refs_json` | 环境变量名/认证头到 Keychain ref 的映射 |
| `tool_allowlist_json` | 允许运行的 MCP 工具名；空表示无工具权限，不表示全部开放 |
| `resource_allowlist_json` | 可读取的 URI 前缀或显式资源 URI |
| `prompt_allowlist_json` | 可运行的 Prompt 名称 |
| `enabled` / `auto_connect` | 启用及随 Runtime 自动连接 |
| `created_at` / `updated_at` | 创建和更新时间 |

升级兼容：已有记录映射为 `transport=stdio`，保留名称、命令、参数、工具白名单和启停状态。

权限默认值：新建 Server 的工具白名单为空即“无 Agent 工具权限”。旧版空白名单曾表示“允许全部工具”；迁移时转换为显式兼容标记 `legacy_all` 并在 `mcp list/doctor` 警告。用户执行 `mcp tools NAME --allow-all` 确认后可保留全开；执行 `mcp tools NAME --allow ...` 后改为精确白名单。升级不得默默扩大权限，也不得让旧用户不知情地失去现有工具。

新增 `mcp_runtime_states` 或等价状态快照，按 `server_config_id` 存：`status`、`connected_at`、`last_success_at`、`last_error_code`、脱敏 `last_error`、`retry_count`、`next_retry_at`、Server 名称/版本、协商协议版本、已发现能力和更新时间。运行状态是可重建快照，不作为配置事实源。

### 6.2 环境变量与秘密

- 环境变量名必须符合系统变量命名规则，值默认不显示。
- 普通变量可以写入配置数据库，但 `list/show/logs` 只显示变量名和“已设置”。
- 标记为 Secret 的值通过隐藏输入写入 Keychain，数据库只存 `secret_ref`。
- 绝不继承知语进程的全部环境变量给 stdio 子进程；使用显式最小环境 allowlist，再加用户配置的变量。
- HTTP 凭据以受控 Secret Header 或 Bearer Token 形式传入；禁止将秘密拼接到 URL、命令或日志。
- Keychain 不可用时拒绝保存 Secret；不能降级为明文文件或数据库。
- 更新/删除秘密遵循事务顺序：先写入新 Secret，再提交配置引用；失败回滚旧配置；移除时先解除引用再安全删除旧 Keychain 项。

### 6.3 工具权限

- 首次连接默认不授权任何 MCP 工具；CLI 展示工具说明、参数 Schema 和 Server 来源。
- 用户通过 `zhiyu mcp tools NAME --allow tool_a --allow tool_b` 明确授权。
- allowlist 按 Server 稳定 ID + 工具原名保存；Server 更新后新增工具不会自动获得权限。
- 同名工具总是映射成 `server_name.tool_name`，不能覆盖内置工具或其他 Server。
- MCP Server 的 `instructions`、工具描述、资源内容和 Prompt 内容均视为外部数据，不得覆盖知语系统策略。
- 有副作用的 MCP 工具必须在工具元数据/CLI 诊断中可见；第一版仍由全局 Agent 工具调用策略限制，不增加隐式自动审批。
- Server 被禁用或失联时，Agent 可用工具集合立即移除其工具，不使用过期连接对象。

### 6.4 Resources 与 Prompts

- `resources` 命令只列出名称、描述、MIME 和 URI；读取必须显式授权并请求单个资源。
- Agent 不自动加载完整资源列表或资源正文。
- 如要把资源开放给 Agent，用户将明确 URI 加入 resource allowlist；通过内部只读 MCP Resource Tool 按需读取，并执行字节上限与超时限制。
- `prompts` 命令列出 Server 暴露的 Prompt；`prompt show` 检查参数，`prompt render` 显式渲染供用户查看。
- 被授权的 Prompt 才可由 Agent 通过 namespaced 工具按需渲染；渲染结果放在普通上下文内容中，仍作为不可信外部内容处理。
- 第一版不支持 MCP Sampling、Roots、Elicitation、Subscriptions 或自动资源订阅。

### 6.5 持续重连

MCP Server 运行状态：

```text
disabled → stopped → connecting → ready
                         ↓          ↓
                      degraded ← disconnected
```

- `RuntimeHost` 为每个启用且 auto-connect 的 Server 持有独立 supervisor Task。
- 连接失败或意外断开后采用指数退避，起始 1 秒、上限 5 分钟、加入随机抖动；手动 reconnect 立即清除退避并尝试一次。
- 连续失败不阻塞其他 Server、QQ 或 Web；健康接口对该 Server 显示 degraded。
- 每次连接恢复后重新 initialize 并重新发现 Tools/Resources/Prompts；工具授权按名字保留，未知的新工具仍未授权。
- Server 版本或能力变化写入状态；不将资源内容缓存成过期权限。
- shutdown 时取消 supervisor，等待有限时间关闭 MCP Session 与 stdio 子进程。
- `last_error` 脱敏，状态只保存最近一次错误和重试时间，不持久保存全量 stdin/stdout。

### 6.6 配置热应用

- CLI 修改配置先完整验证并提交数据库，再递增 `integration_config_revision`。
- Runtime 内的轻量 reconciler 每 5 秒读取 revision；只为变更项启动、停止或重连，不碰无变化连接。
- 启用配置在 Runtime 在线时立即连接；禁用时立即断开并从 Agent 工具集撤下。
- 配置更新连接失败时保留新配置但标记 degraded；既有有效连接只有在新配置验证通过后才替换。
- `mcp test` 使用一次性临时连接，不改变常驻连接和 Agent 的工具集合。
- CLI 输出“已保存，当前服务将在数秒内应用”或“服务未运行，下次启动生效”。

## 7. Skills 生命周期

### 7.1 安装位置和身份

- 内置 Skills 位于程序包目录，只读，由知语发布版本管理。
- 用户 Skills 放在 `ZHIYU_SKILLS_DIR`（默认 `~/.zhiyu/skills`）。
- 安装目录使用 Skill 唯一 `name`，禁止路径穿越、软链接逃逸和覆盖内置 Skill。
- 不允许两个来源提供同名 Skill；`show` 明确指出冲突与来源。
- 用户 Skill 安装成功后记录来源、版本、内容哈希、安装时间和当前状态。

新增 `installed_skills` 元数据表：`name`、`source_type`、`source_locator`、`source_ref`、`resolved_revision`、`content_hash`、`installed_path`、`manifest_json`、`enabled`、`installed_at`、`updated_at`、`last_error`。正文仍存放文件系统，不复制进数据库。

### 7.2 来源类型

第一版只允许：

1. 本地目录：目录中必须恰有一个有效 `SKILL.md` 根 Skill，复制到受管目录。
2. Git 仓库：用户指定仓库 URL，可选 `--ref` 和仓库内 Skill 子目录；仅下载 Git 内容，不执行 clone hook、构建脚本或包安装脚本。

本地 ZIP、URL 任意压缩包、市场源和依赖自动安装留待后续。Git 源默认要求 HTTPS 或本地路径；SSH 私钥认证不由知语代管。首次安装展示源地址、解析 commit、文件列表和权限声明，再确认安装。

### 7.3 Skill manifest

继续兼容现有 `SKILL.md` frontmatter，明确支持字段：

```yaml
name: example
description: 简短描述
version: 1.2.0
enabled: true
required_tools:
  - calculator
requires_bins:
  - git
permissions:
  - web.read
```

- `name` 必须符合小写字母、数字和连字符规则。
- `version` 可选；缺少时使用已解析 Git commit 或本地内容哈希标识，不虚构语义版本。
- `required_tools` 表示运行所需知语工具；缺失时 Skill 标记为 unavailable，并列出缺失工具。
- `requires_bins` 只做 PATH 存在性检查，不自动安装和执行。
- `permissions` 是 Skill 对能力的声明，不能自行授予权限；安装者/管理员还须在知语全局权限中批准，实际可用权限取交集。
- 未知 frontmatter 字段在验证报告中警告，不影响加载；损坏的 YAML、重复字段和非法名阻止安装或更新。
- Skill 正文和来源 README 视为不可信指令，不能成为 system prompt，不可要求 Agent 忽略上层策略。

解析器须使用成熟 YAML 解析器并限制文件大小、别名展开和嵌套深度；禁止用简单的逐行冒号解析来处理用户安装包。

### 7.4 安装、更新和删除

```text
zhiyu skills list [--all]
zhiyu skills show NAME
zhiyu skills validate PATH
zhiyu skills install PATH
zhiyu skills install https://github.com/owner/repo --ref v1.2.0 --subdir skills/example
zhiyu skills update NAME [--ref REF]
zhiyu skills diff NAME
zhiyu skills enable NAME
zhiyu skills disable NAME
zhiyu skills remove NAME --confirm
zhiyu skills restore NAME
zhiyu skills reload
```

生命周期规则：

- `validate` 只检查，不写文件。
- `install` 先下载/复制到临时目录，完整验证后原子 rename；失败时删除临时目录。
- `update` 先解析来源新版本并显示摘要/hash/依赖变化；必须确认后切换到新版本。
- 更新之前把旧版本复制/归档到 `~/.zhiyu/skills/.history/<name>/<revision>/`，保留最近 3 个版本；失败可自动恢复。
- `remove` 只允许用户管理的 Skill；先禁用并搬到 `~/.zhiyu/skills/.trash/`，保留 30 天；`restore` 可恢复。
- 内置 Skill 只能在 `show` 查看，不允许 CLI 更新/删除。
- Skills 文件变化后立即原子 reload registry；reload 失败时维持旧快照，并报告具体文件错误。
- 工具运行中的 Agent 使用开始时捕获的 registry 快照，防止更新 Skill 后中途行为改变。
- 包含可执行脚本的 Skill 可以安装和阅读，但知语不执行脚本、不自动将脚本加入 PATH。
- CLI 安装/更新/启停成功后递增 `skills_registry_revision`；Runtime reconciler 发现变化后原子替换 Registry 快照，正在运行的 Agent 保留旧快照直到本次运行结束。

### 7.5 使用与运行诊断

`zhiyu skills show NAME` 显示：来源、版本/commit/hash、启用状态、描述、已声明工具、缺失工具/二进制、最后更新时间和文件路径。`list` 默认不打印 Skill 正文。

Skill 匹配与按需读取保持现有路径：system prompt 只列可用名称/简述，Agent 用 `read_skill` 读取正文。注册表增加来源校验和 install metadata，不改变 ChatService 消息语义。关闭的 Skill、依赖不满足的 Skill、校验失败的 Skill 不参与匹配，也不能经 `read_skill` 绕过状态。

## 8. API 和 Web 可见性

本阶段提供只读 API：

- `GET /api/mcp/servers`：配置概要、运行状态、能力和最近错误，不含 env 值、headers 或 secret refs。
- `GET /api/mcp/servers/{name}/tools`：工具名、描述、schema 摘要和 enabled 状态。
- `GET /api/skills`：名称、版本、来源、状态、依赖检查和描述，不含正文。

现有 WebUI 可显示 MCP 连接摘要和 Skills 数量/失败数量；不新增写操作表单。全部变更只通过 CLI 本机执行。接口继续沿用当前 loopback 部署约束。

## 9. 安全边界

| 风险 | 处理 |
|---|---|
| stdio 配置启动任意命令 | 明确告知命令将以当前用户权限启动；首次添加显示完整命令并要求确认 |
| 意外继承密钥 | 子进程仅得到最小环境白名单；Keychain Secret 不写日志 |
| HTTP Token 泄漏 | 隐藏输入、Keychain 引用、HTTPS、日志过滤和同源重定向 |
| 恶意 Skill 安装包 | 不运行代码/依赖脚本，路径限制，文件体积限制，原子安装和内容哈希 |
| Skill Prompt Injection | Skill 与 MCP 内容按不可信输入处理，不赋予系统策略优先级 |
| MCP Server 返回恶意工具 | 默认无授权；用户逐 Server 授权；新工具不自动放行 |
| 重连后权限变化 | 重新枚举能力，只保留原 allowlist，未知能力保持关闭 |
| 删除导致不可恢复 | Skill 进回收站保留 30 天；MCP 删除前显示影响并确认 |
| 多 Server 同名工具 | 命名空间为 `server.tool`；绝不覆盖内置工具 |
| 依赖命令执行 | 只做存在性检查；不自动安装或执行 Skill 自带脚本 |

## 10. 分阶段实施

### 阶段 1：MCP 配置和用户维护

- 扩展配置模型，兼容现有 stdio 记录。
- 补齐 add/show/edit/enable/disable/remove/test、环境变量和秘密管理。
- 接入 Streamable HTTP；增加旧 SSE 兼容。
- 增加每 Server 运行状态和只读 CLI/API。

验收：已有 MCP 无需重配；stdio 和 HTTP 各连通一个真实/测试 Server；环境变量与 Secret 不泄漏。

### 阶段 2：MCP 稳定性和完整协议能力

- 加入独立 supervisor、退避重连、健康诊断和 shutdown 清理。
- MCP Tools allowlist 默认收紧为无工具授权。
- 加入 Resources/Prompts 列表、显式读取/渲染及授权边界。

验收：断开、杀死和重启 MCP Server 后状态正确恢复；工具权限不扩大；资源和 Prompt 只能按授权访问。

### 阶段 3：Skills 校验和本地生命周期

- frontmatter schema、依赖诊断、CLI list/show/validate/install/enable/disable/remove/restore。
- 原子安装、用户目录隔离、立即 reload 和失败回滚。

验收：本地 Skill 可安装、启用、读取、禁用、恢复；损坏 Skill 不影响其他 Skill。

### 阶段 4：Git 来源与版本升级

- 固定 commit 记录、安装变更预览、更新差异、三版本历史、失败回滚。
- Git 下载不执行钩子和构建脚本；只读取指定子目录。

验收：固定 tag 安装、远端更新检测、更新后 diff 确认、升级失败自动恢复均通过。

### 阶段 5：体验收尾

- Web 只读摘要、doctor 报告、文档示例、旧 MCP CLI 兼容提示。
- 完整迁移回归和用户手册。

验收：新用户照文档完成一个 MCP 安装和一个 Skill 安装；重启后全部配置可用。

## 11. 数据迁移

1. 为 MCP 配置增加 transport、URL、环境变量和各能力 allowlist 字段；迁移旧记录到 stdio。
2. 新增 MCP 运行状态表；Runtime 启动后可重建，不迁移临时连接状态。
3. 新增 `integration_config_revision` 和 `skills_registry_revision`（可用现有 AppSetting 记录实现），供运行中配置协调使用。
4. 新增 MCP Secret Keychain 引用映射；不把明文环境变量迁入秘密字段。
5. 新增 Skill 安装元数据表；现有磁盘用户 Skills 首次扫描时只登记、不移动、不自动启用来源不明脚本。
6. 对已有 Skills 自动校验 frontmatter；校验失败只标记 unavailable，不删除文件。
7. 数据库迁移前自动备份；Keychain 项不随 DB backup 导出。
8. 配置删除时检查 Secret 引用是否仍被其他配置使用，避免误删共享 Secret。

## 12. 测试与验收矩阵

| 场景 | 必须结果 |
|---|---|
| 从旧数据库启动 | 现有 stdio MCP 配置保留并能继续连接 |
| stdio Server 初始化失败 | 限时重试，状态显示错误，不拖垮 Runtime |
| HTTP Streamable Server | TLS、认证、initialize 和 tools/list 工作 |
| 旧 SSE Server | 显式兼容模式连接；失败时给迁移建议 |
| Keychain 缺失/写入失败 | 不落明文，配置不误标为已验证 |
| 子进程环境继承 | 未显式列出的秘密环境变量不可见 |
| MCP Server 运行中退出 | 自动退避重连；手动 reconnect 可立即执行 |
| 重连后出现新工具 | 未授权新工具不会加入 Agent Registry |
| MCP Resource 越权 URI | 未在 allowlist 的 URI 拒绝读取 |
| MCP Prompt 参数错误 | 显示缺少/非法参数，不传入 Agent |
| Server 工具名冲突 | namespaced 工具不覆盖内置或其他 Server |
| 本地 Skill 非法路径 | install 阶段拒绝路径穿越和符号链接逃逸 |
| 无效/过大 Skill | 验证失败，registry 保持旧快照 |
| Skill 工具依赖缺失 | 显示 unavailable 和缺失项，Agent 不可读取 |
| Skill 更新内容变化 | 展示 source/ref/hash/diff，确认后原子切换 |
| Skill 升级失败 | 自动还原前一版本 |
| Skill 删除内置项 | 明确拒绝 |
| Git Skill 含 install hook | 不执行 hook、脚本和包管理器 |
| Skill/MCP Prompt Injection 文本 | 不覆盖系统指令与工具权限 |
| Web/API 输出 | 不包含秘密值、环境变量值、Skill 正文或 MCP Resource 正文 |

每阶段必须通过完整现有测试集、新增单元和集成测试，以及相应真实 MCP Server 冒烟测试。模拟服务器只能证明协议逻辑，不能证明具体第三方 Server 的命令、权限和部署配置正确。

## 13. 完成定义

只有同时满足以下条件，才可标记“已完成”：

1. 用户可通过 CLI 配置并诊断 stdio、Streamable HTTP；旧 SSE 兼容行为清楚。
2. Secret 始终只在 Keychain 中保存，环境继承符合最小权限。
3. MCP 在运行期可监测、重连、展示错误，并支持 Tool/Resource/Prompt 的受控使用。
4. Skill 有来源、版本/hash、启停、依赖状态、原子更新、回滚和可恢复删除。
5. 未经用户授权的 MCP 工具、Resource、Prompt、Skill 权限不会进入 Agent 可用能力。
6. 旧配置和已有 Skill 目录升级无损。
7. 文档能让没有开发背景的用户完成一个 MCP Server 和一个 Skill 的添加、测试、启用与移除。
8. 测试和真实冒烟通过；仓库和日志不含真实密钥。

## 14. 预计代码落点

- `src/zhiyu/integrations/mcp/connection.py`：多传输连接、Tools/Resources/Prompts 接口。
- `src/zhiyu/integrations/mcp/manager.py`：Server supervisor、运行状态、重连和能力刷新。
- `src/zhiyu/application/mcp.py`：配置、Secret 生命周期、test/reconnect、CLI 展示模型。
- `src/zhiyu/infrastructure/database/models.py` 与新迁移：传输配置、状态、env/secret 引用。
- `src/zhiyu/infrastructure/database/repositories/integration_repository.py`：持久化配置和状态。
- `src/zhiyu/integrations/skills/loader.py`：严格 manifest 解析、体积/路径校验。
- `src/zhiyu/integrations/skills/registry.py`：安装元数据、版本/hash、原子 reload。
- `src/zhiyu/application/skills.py`：Skill 生命周期用例和来源管理。
- `src/zhiyu/cli/main.py`：`mcp` / `skills` 子命令。
- `src/zhiyu/api/app.py`：MCP 与 Skills 只读状态接口。
- WebUI 已迁至 `web/src/app.tsx`；MCP 与 Skills 页面在站内管理生命周期和授权操作。此处只约束 MCP/Skills 后端边界，不再依赖旧 `static/app.js`。

实现时按现有项目风格微调；不借此重构整个 Tool Registry、Provider 或 WebUI。

## 15. 外部协议依据

- [MCP 官方 Python SDK 客户端文档](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/index.md)：SDK 的统一 Client 支持 stdio、Streamable HTTP，并暴露服务器 Tools、Resources、Prompts 等能力。
- [MCP 官方 Python SDK 传输文档](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/client/transports.md)：Streamable HTTP 是新部署优先选项；旧 SSE 仍作为兼容客户端入口。
- [MCP 官方 Python SDK 授权文档](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/authorization.md)：HTTP MCP 应按 Web 服务授权边界处理。

SDK 与协议版本在实施前必须按项目依赖锁文件核对；本设计不假设仓库可以直接采用 Python SDK 主分支的最新 API。

## 16. 第一版实施记录（2026-10-06）

### 已落地

- 新增 `0018_mcp_skills_lifecycle` 迁移，项目当前 SQLite 已升级到该版本；迁移前自动备份位于 `~/.zhiyu/backups/`，包含数据库、记忆目录和迁移清单。
- MCP 客户端按锁定的 `mcp==2.2.0` 实现 stdio、Streamable HTTP 和旧 SSE；支持 Tools、Resources、Prompts、Keychain Secret 引用、stdio 环境变量、明确能力白名单、持续重连和运行状态快照。
- Runtime 每 5 秒协调 MCP 配置修订；失败的 Server 独立退避重试，不阻塞其他集成。连接测试使用临时客户端，不改动常驻连接。
- CLI 已提供 MCP add/list/show/test/doctor/enable/disable/remove、环境变量和 Header 凭据维护、工具/Resource/Prompt 检查与授权、显式读取/渲染、reconnect 和 logs。stdio 启用会提示命令将以当前用户权限运行；非交互必须显式确认。
- Skills 使用安全 YAML 解析，拒绝重复字段、别名、深层嵌套、非法名、符号链接和超限包；单个坏包不会阻止其他 Skill 加载。
- 首次启动只登记已有用户 Skills 的来源、Hash 和 Manifest 元数据，不搬动或改写文件；损坏目录会在 Skills 状态中报告，已有内容与登记 Hash 不同会标记为已修改。
- Skills CLI 支持 validate、安装本地目录/Git、更新预览与确认、diff、启停、回收和恢复。更新保留最近三个版本；回收站保留 30 天，恢复时保留删除前启停状态。Git Skill 不运行脚本或安装依赖。
- 新增只读 API：`/api/mcp/servers`、`/api/mcp/servers/{name}/tools`、`/api/skills`。WebUI 运行摘要显示 MCP 与 Skills 概况，不提供写配置表单。

### 验证结果与边界

- 完整自动化测试：213 项通过；真实本地 SDK Server 协议测试覆盖 stdio、Streamable HTTP、SSE，HTTP 同时验证工具调用、Resource 读取和 Prompt 渲染；不可达 HTTP 端点也验证为可重试连接错误。
- 已验证当前数据库迁移至 `0018_mcp_skills_lifecycle`，且迁移备份存在。旧 MCP 空工具白名单会以 `legacy_all_tools` 显式保留原授权，并在 CLI 列表提醒用户检查。
- 尚未验证任何真实第三方 MCP 服务、真实 Keychain 凭据或用户的 Git 源；这些需要具体服务端点、凭据和网络环境。不要把本地协议测试等同于某个第三方 Server 已配置成功。
- Skills 首版只支持本地目录与 HTTPS Git 仓库，不支持 ZIP、OAuth、市场、依赖自动安装、脚本执行或远程 Web 写管理。更新预览提供文件变更清单与前后 Manifest，不提供逐行代码 diff。
- `mcp test/doctor` 会真实启动配置的 Server 或连接远端 URL；只应对用户信任的配置执行。新 MCP 默认禁用且无工具授权，旧版兼容全开配置可通过 `zhiyu mcp tools NAME --deny-all` 或精确 `--allow` 收紧。

### 常用命令补充

```text
zhiyu mcp add http docs --url https://mcp.example.com/mcp
zhiyu mcp auth set docs --bearer
zhiyu mcp test docs
zhiyu mcp tools docs --allow search
zhiyu mcp enable docs

zhiyu skills validate ./my-skill
zhiyu skills install ./my-skill
zhiyu skills update my-skill        # 只预览
zhiyu skills update my-skill --apply
```

交互式 Skill 安装会展示来源、固定 revision、Hash、文件清单和权限声明后请求确认；非交互使用时需检查预览后显式追加 `--yes`。
