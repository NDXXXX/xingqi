# 星栖

星栖是一个本地运行的个人 AI Agent。它通过终端、Web UI 或 QQ 与模型对话，支持多个独立智能体、工具、MCP Server 和本地长期记忆。

应用和数据运行在自己的设备上；聊天内容仍会发送给你配置的模型服务商处理。星栖不会替你托管模型。

## 功能

- **多种使用入口**：命令行聊天、终端 TUI、本机 Web UI，以及通过 NapCat 接入的 QQ OneBot v11。
- **多个模型服务商**：内置 DeepSeek、OpenAI、Anthropic、MiniMax 和 Kimi Provider；支持配置自定义 API 地址、模型能力和故障切换顺序。
- **Agent 工具**：内置计算器和日期时间工具；可以按需读取 Skill，并调用经用户授权的 MCP 工具。
- **本地长期记忆**：记忆文件以 Markdown 保存在本机，SQLite 保存索引和状态；支持后台提取、检索、编辑、遗忘及索引恢复。
- **多智能体**：自行创建智能体，配置名称、背景、性格、系统提示词和默认模型；角色会话、关系与剧情记忆、Skills 授权和 MCP 配置按角色隔离，用户事实与偏好可跨角色共享。角色支持设定模板导入导出。
- **插件**：Web 中统一管理 MCP 服务与 Skills；管理 MCP 工具、Resources、Prompts 和凭据，从本地或 Git 来源安装、检查和维护 Skills。MCP 工具需明确授权；Skill 安装不会执行其中的脚本。
- **运行诊断**：检查 Python、数据库、数据目录、密钥存储和 Skills 状态。

## 快速开始

需要 Python 3.12 或更新版本、[uv](https://docs.astral.sh/uv/) 和模型服务商的 API Key；本机或局域网兼容模型可不配置 API Key。

```bash
# 在仓库目录执行
uv sync
uv run zhiyu doctor
```

创建云端 Provider 时，星栖会交互式读取 API Key 并存入系统密钥存储。也可以从环境变量读取；本机或局域网 OpenAI 兼容服务可只填写 Base URL：

```bash
export DEEPSEEK_API_KEY="你的 API Key"
uv run zhiyu provider add deepseek --type deepseek --api-key-env DEEPSEEK_API_KEY
uv run zhiyu provider default deepseek deepseek-chat
uv run zhiyu provider test deepseek

# 本机或局域网 OpenAI 兼容服务可省略 Key
uv run zhiyu provider add local --type openai --base-url http://127.0.0.1:11434/v1
```

添加本机 Provider 后，在 Web UI 的「模型服务」中配置本机实际提供的模型标识，再设为默认模型。

配置完成后，在终端启动聊天。交互式终端默认进入 TUI；发送单条消息则直接返回：

```bash
uv run zhiyu chat
uv run zhiyu chat "帮我整理今天的学习计划"
```

TUI 中输入 `/stop` 可停止当前回复，输入 `/help` 查看其他命令。

支持的 Provider 类型：`deepseek`、`openai`、`anthropic`、`minimax`、`kimi`。添加 Provider 时可用 `--base-url` 指定兼容 API 地址；配合本机服务时可省略 API Key。执行 `uv run zhiyu --help` 或 `uv run zhiyu <命令> --help` 查看全部选项。

## Web UI

启动本机 Web UI 和 API：

```bash
uv run zhiyu serve
```

打开 <http://127.0.0.1:8765>。Web UI 默认只允许绑定本机回环地址，不应通过未经认证的反向代理暴露到公网。

侧栏「智能体」可以创建、编辑智能体，设置角色和默认模型。通过「当前智能体」选择器切换，最近会话只显示该智能体的会话；历史会话的归属保持固定。可导出角色 JSON 模板或导入模板创建新角色；模板不包含聊天记录、记忆和密钥。

选好智能体后，「关于彼此」「日记」「插件」管理它的角色资料、记忆、Skills 与 MCP。用户事实和偏好可在默认助手及各角色间共享；角色关系和剧情记忆保持私有。清空角色记忆不会删除共享用户资料，也不会删除聊天记录。CLI / QQ 暂时沿用默认助手，尚无智能体选择入口。

直接从本机脚本调用 `/api` 时，写请求（POST、PUT、PATCH、DELETE）需带 `X-Zhiyu-Request: 1` 请求头；GET 不需要。API 只接受本机回环连接与本机 Host，带 Origin/Referer 的写请求还需与页面同源。该请求头用于阻止浏览器跨站写入，不是身份认证。

## 长期记忆

聊天产生的记忆提取任务会持久化，并由后台处理。可以用 CLI 查看和管理记忆：

明确给默认助手改名会写入独立的 `IDENTITY.md`，当轮直接生效；给自建智能体改名只修改它自己的角色配置。普通对话自动读取受信任的长期核心；每日观察需要显式搜索或历史召回。QQ 只有明确的私人会话可访问个人记忆。记忆搜索使用 FTS5/BM25 与现有语义排序，来源遗忘会删除合并了该来源的自动核心条目。

```bash
uv run zhiyu memory list
uv run zhiyu memory search "咖啡"
uv run zhiyu memory add --type preference --content "喜欢简洁回答"
uv run zhiyu memory edit <记忆 ID> --content "更正后的内容"
uv run zhiyu memory status
```

遗忘操作默认先显示影响预览，确认后再执行：

```bash
uv run zhiyu memory forget <记忆 ID>
uv run zhiyu memory forget <记忆 ID> --apply
```

如果要遗忘某个会话派生的记忆，使用 `uv run zhiyu memory forget --conversation <会话 ID>` 预览，再追加 `--apply` 执行。更多命令包括 `memory sync`、`memory retry`、`memory index`、`memory export` 和 `memory recall-explain`。

## Provider 故障切换

可以设置主要 Provider 的备用顺序。发生可切换的请求错误时，星栖会按配置尝试备用 Provider：

```bash
uv run zhiyu provider fallback deepseek backup-a backup-b
uv run zhiyu provider fallback deepseek
```

第二条命令清除该 Provider 的备用列表。备用 Provider 必须已配置并启用。

## MCP 与 Skills

MCP Server 和 Skill 配置保存在本机。Web 中的配置归属当前选中的智能体：MCP 配置、连接、凭据和工具授权独立；Skill 安装包可以共用，但关联及启用状态分别管理。移除某个智能体的 Skill 关联不会删除其他智能体使用的安装包；安装包更新在默认助手的管理入口维护。以下 CLI 命令管理默认助手的集成。新 MCP Server 默认没有 Agent 工具权限，需要明确授权：

```bash
uv run zhiyu mcp add filesystem npx \
  --arg=-y \
  --arg=@modelcontextprotocol/server-filesystem \
  --arg="$PWD" \
  --allow-tool read_file

uv run zhiyu mcp list
uv run zhiyu mcp tools filesystem
```

运行环境需要预先安装 `npx` 及目标 MCP Server。通过 `zhiyu serve` 启动的运行时会自动连接已启用的 MCP Server。不要把不可信的服务器加入白名单；被授权的 MCP 工具会以星栖进程权限运行。

Skills 支持从本地目录或 Git 来源安装。安装前会展示来源和内容预览；非交互安装需显式追加 `--yes`。星栖读取 Skill 说明，但不会执行其中的脚本或自动安装其依赖。

```bash
uv run zhiyu skills list
uv run zhiyu skills validate ./my-skill
uv run zhiyu skills install ./my-skill
uv run zhiyu skills show <skill 名称>
```

## QQ OneBot（可选）

QQ 接入使用 NapCat 和 OneBot v11 反向 WebSocket。当前版本支持单个 QQ 配置、主人私聊和可选的主人群聊；群聊默认关闭，启用后默认要求 @ 星栖。需要在 NapCat 中扫码登录并创建 WebSocket 客户端。

macOS + Docker Desktop 的完整部署步骤见 [`deploy/napcat/README.md`](deploy/napcat/README.md)。配置 QQ 主人 ID 后，`zhiyu serve` 会托管已配置渠道：

```bash
uv run zhiyu qq configure \
  --endpoint ws://0.0.0.0:6199/ws \
  --owner-user-id <你的 QQ 号> \
  --token-env ZHIYU_QQ_TOKEN
uv run zhiyu serve
uv run zhiyu qq doctor
```

先在环境变量或 `.env` 中设置 `ZHIYU_QQ_TOKEN`，并在 NapCat 配置相同 Token。`0.0.0.0` 仅用于 Docker Desktop 访问宿主机，必须配置强 Token 并使用防火墙限制访问。群聊可以通过 `zhiyu qq groups allow <群号>` 启用。

QQ 图片可在明确启用模型视觉能力后发送给支持视觉输入的模型；语音会以说明文本提供给模型，不包含语音转写。多 QQ 账号和官方 QQ Bot 尚不支持。

## 数据与配置

默认数据目录为 `~/.zhiyu`：

| 内容 | 默认位置 |
|---|---|
| SQLite 数据库 | `~/.zhiyu/companion.db` |
| Markdown 记忆 | `~/.zhiyu/memory/` |
| 用户 Skills | `~/.zhiyu/skills/` |
| 角色头像 | `~/.zhiyu/avatars/` |
| 日志 | `~/.zhiyu/logs/zhiyu.log` |

侧栏「数据」可下载数据库、Markdown 记忆和角色头像的备份。API Key、Token、Keychain 内容和本机 Skill 文件不包含在备份中。恢复时先在终端运行：

```bash
uv run zhiyu data restore /path/to/xingqi-backup.zip --target /path/to/xingqi-restored
ZHIYU_DATA_DIR=/path/to/xingqi-restored uv run zhiyu serve
```

恢复会创建一个新的数据目录，不会覆盖当前数据；跨设备恢复后需重新配置密钥并重新安装本机 Skill。

可通过环境变量配置：

- `ZHIYU_DATA_DIR`：数据目录。
- `ZHIYU_DATABASE_URL`：SQLAlchemy 数据库 URL；默认使用本地 SQLite。
- `ZHIYU_SKILLS_DIR`：用户 Skills 目录。
- `ZHIYU_LOG_LEVEL`：日志级别。

将 `.env.example` 复制为 `.env` 可以让 CLI 启动时加载本地环境变量。`.env` 可能包含密钥，不要提交或分享。Provider API Key 和 MCP Secret 可存入系统密钥存储；环境变量方式只将变量名引用保存在配置中。

数据库 schema 通过 Alembic 管理：

```bash
uv run zhiyu db upgrade
```

## 开发

```bash
uv sync
uv run pytest -q
```

项目使用 `src/` 布局，主要代码位于 `src/zhiyu/`：

```text
api/             FastAPI 路由与请求模型
application/     可复用应用用例和运行时
channels/        消息渠道与 OneBot 适配器
cli/             命令行入口和命令处理
core/            Agent、模型、工具和记忆能力
infrastructure/  配置、数据库和密钥存储
integrations/    MCP 与 Skills 集成
web/             Web UI 静态资源
```

## 文档

- [文档目录](docs/README.md)：按 PRD、技术设计、验收与基准、参考资料分类。
