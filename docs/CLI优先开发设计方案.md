# 知语 CLI 优先开发设计方案

> 版本：v1.3  
> 日期：2026-09-29  
> 状态：Phase 0–3 已执行，进入 CLI 功能迭代阶段

## 1. 决策

知语采用以下产品实现顺序：

```text
CLI 调试核心能力
    ↓
Web UI 验证完整产品体验
    ↓
桌面端封装与系统集成
```

当前阶段移除 Electron/React 桌面端，把 Python Agent Runtime 变成项目主体。CLI 是第一套交互界面，用来快速验证 Agent、模型、记忆、Skills、MCP 和 QQ 渠道。

CLI 只负责接收参数、展示结果和维护交互循环。业务逻辑必须放在可复用的应用服务中，QQ 渠道和未来 Web API 调用同一套服务，不能在 CLI 命令里重新实现聊天、模型选择或渠道管理。

已确认的实施约束：

- CLI 阶段删除 FastAPI；Web UI 阶段再增加薄 API 层。
- 默认数据目录使用 `~/.zhiyu`。
- 第一版 CLI 面向开发调试，默认通过 `uv run zhiyu` 使用。
- 第一版 CLI 同时支持 macOS、Windows 和 Linux。
- 现有 `COMPANION_*` 环境变量至少兼容一个版本，再迁移到 `ZHIYU_*`。

## 2. 为什么先做 CLI

当前同时维护 Electron 主进程、React 渲染端、FastAPI 和 Python Agent，会让一次功能修改跨越多个进程和接口。早期需求仍在变化，这种结构会放大调试成本。

CLI 优先有四个直接收益：

1. 一个 Python 进程即可观察完整调用链和异常堆栈。
2. 新功能可以先验证行为，再决定 Web UI 的交互形式。
3. Provider、Memory、Tool、Skill、MCP 和 QQ 可以单独执行和测试。
4. CLI 命令可以成为稳定的验收入口，方便自动化测试和故障排查。

代价是暂时没有图形化配置、会话浏览和桌面安装包。这些能力推迟到核心行为稳定以后实现。

## 3. 架构原则

### 3.1 一个核心，多种入口

```text
CLI ─────────┐
             ├── Application Services ── Core ── Infrastructure
QQ Channel ──┘

未来 Web API ── Application Services
```

- `cli` 和 QQ Channel 是当前输入输出层，未来的 Web API 也是输入输出层。
- 应用服务编排一次用例，例如“发送一条消息”或“启动 QQ 渠道”。
- Core 实现 Agent、模型、记忆和工具等核心能力。
- Infrastructure 实现数据库、密钥、配置和日志。
- CLI 不启动或调用本地 HTTP 服务。
- Web UI 阶段新增的 API 只能调用应用服务，不承载独有业务逻辑。

### 3.2 先解决真实需求

- 第一版不设计插件市场、多用户、远程管理和复杂主题。
- 第一版只有一个本地用户和一个默认数据目录。
- 第一版使用三平台共同支持的终端、路径、Keyring 和信号能力。
- 不为了未来 Web UI 提前创建空接口或空包。
- 新增抽象前必须至少存在两个真实调用方，或已明确服务于 CLI 与 API 两个入口。

### 3.3 数据和秘密独立于界面

- SQLite、日志和运行缓存统一保存在数据目录。
- API Key、Access Token 继续使用系统 Keychain。
- 不可用的 Keychain 后端必须由 `doctor` 明确报告；不得静默降级为明文文件。
- CLI 参数和日志不得输出完整密钥。
- 删除桌面端不能删除数据库、Keychain 条目和 Skills。

## 4. 目标目录

CLI 阶段移除 `apps` 层，让 Python 包成为仓库主体：

```text
知语/
├── pyproject.toml
├── src/
│   └── zhiyu/
│       ├── cli/
│       │   ├── main.py
│       │   └── commands/
│       ├── application/
│       │   ├── chat_service.py
│       │   ├── provider_service.py
│       │   └── channel_service.py
│       ├── core/
│       │   ├── agent/
│       │   ├── characters/
│       │   ├── memory/
│       │   ├── providers/
│       │   └── tools/
│       ├── channels/
│       │   └── qq/
│       ├── integrations/
│       │   ├── mcp/
│       │   └── skills/
│       └── infrastructure/
│           ├── config/
│           └── database/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── cli/
├── skills/
├── data/                        # 开发数据，Git 忽略
├── docs/
└── README.md
```

`channels` 从 `core` 中单独提出，因为 QQ 是外部消息入口，与 `cli` 和 `api` 属于同类边界；渠道收到消息后调用应用服务，不直接拼装 Agent 上下文。

未来加入界面时再建立：

```text
apps/
├── web/                         # 第二阶段
└── desktop/                     # 可选的最终封装，需要时重新创建
```

Python 包继续保留在根目录的 `src/zhiyu`，以后无需再次搬迁后端。

## 5. CLI 命令设计

可执行命令统一为 `zhiyu`。

### 5.1 第一批必须实现

```bash
zhiyu doctor
zhiyu chat
zhiyu provider list
zhiyu provider add
zhiyu provider test <name>
zhiyu provider default <provider/model>
zhiyu qq configure
zhiyu qq listen
zhiyu db upgrade
```

命令职责：

| 命令 | 作用 | 完成标准 |
|---|---|---|
| `doctor` | 检查 Python、数据库、Keychain、默认模型、Skills 和端口 | 每项给出通过、失败和明确修复建议 |
| `chat` | 启动流式终端聊天 | 支持连续对话、工具调用和安全退出 |
| `provider list` | 查看 Provider 和模型 | 不显示完整密钥 |
| `provider add` | 交互式添加模型服务 | 密钥写入 Keychain，配置写入数据库 |
| `provider test` | 发起最小模型请求 | 区分鉴权、限流、网络和模型名错误 |
| `provider default` | 设置默认模型 | 下次聊天和 QQ 消息立即使用 |
| `qq configure` | 配置监听地址和 Token | Token 使用隐藏输入并写入 Keychain |
| `qq listen` | 启动 OneBot 反向 WebSocket | 显示监听、连接、断开和消息错误状态 |
| `db upgrade` | 执行数据库迁移 | 可重复执行且不破坏已有数据 |

### 5.2 交互式聊天

`zhiyu chat` 默认进入交互循环：

```text
知语 · default-model · 新会话
你 > 帮我总结今天的任务
知语 > ...流式输出...
```

第一版支持以下本地命令：

```text
/new                 新建会话
/history             显示当前会话最近消息
/model               显示当前模型
/model <id>          切换当前会话模型
/character           显示当前角色
/character <id>      切换角色
/tools               显示可用工具
/clear               清理终端显示，不删除历史
/exit                 安全结束当前进程
```

斜杠命令只控制本地会话，不发送给模型。第一版不实现复杂补全、终端 UI 框架或多窗格界面。

### 5.3 后续调试命令

核心链路稳定后再增加：

```bash
zhiyu conversation list
zhiyu conversation show <id>
zhiyu memory list
zhiyu memory search <query>
zhiyu skill list
zhiyu skill inspect <name>
zhiyu mcp list
zhiyu mcp test <name>
zhiyu qq status
```

所有非交互命令最终应支持 `--json`，便于测试脚本和未来管理工具消费；第一批先保证人类可读输出。

CLI 必须识别 TTY。密码和 Token 只允许在交互式终端中隐藏输入；管道或 CI 环境必须通过明确的环境变量或参数传入。非 TTY 输出默认关闭颜色和动态刷新，避免污染日志。

## 6. 应用服务

当前部分聊天编排位于 FastAPI 路由和 ChannelRouter 中。删除 FastAPI 前先提取最小应用服务，避免丢失或复制业务逻辑；确认 CLI 和 QQ 已接管后再删除路由层。

### ChatService

```python
class ChatService:
    async def send_message(
        self,
        conversation_id: str | None,
        text: str,
        *,
        channel: str = "cli",
    ) -> AsyncIterator[ChatEvent]: ...
```

统一处理：

- 创建或加载 Conversation。
- 选择 Provider 与 Model。
- 写入用户消息。
- 构造 Agent Context。
- 执行模型和工具。
- 以事件形式返回 step、tool、token、final 和 error。
- 写入助手消息、Agent Run 和 Memory。

CLI 和 QQ ChannelRouter 都调用该服务；未来 Web API 继续调用该服务。

本地用户的稳定渠道标识统一为 `local`。迁移时将原有 `desktop` 本地会话映射到 `local`；CLI、Web UI 和未来桌面端不得分别创建 `cli`、`web`、`desktop` 三套身份与记忆。

### ProviderService

负责 Provider、Model、Keychain 和默认模型的增删查改及连接测试。CLI 不直接操作 Repository 和 Keychain。

### ChannelService

负责 QQ 配置、监听生命周期和状态查询。进程信号退出时必须停止监听并关闭连接。

## 7. 配置与数据目录

默认数据目录：

```text
~/.zhiyu/
├── companion.db
├── logs/
└── cache/
```

支持环境变量覆盖：

```text
ZHIYU_DATA_DIR
ZHIYU_LOG_LEVEL
ZHIYU_DATABASE_URL
ZHIYU_SKILLS_DIR
```

兼容期同时读取原有变量：

```text
COMPANION_DATA_DIR
COMPANION_API_TOKEN
```

新变量优先；使用旧变量时打印一次弃用提示，但不得在日志中输出变量值。

Skills 分为两类：

- 随程序发布的内置 Skills 作为 Python package data 安装。
- 用户 Skills 默认放在 `~/.zhiyu/skills`，可以通过 `ZHIYU_SKILLS_DIR` 覆盖。

安装后的 CLI 不得依赖仓库根目录才能发现内置 Skills。

迁移时必须检查所有可能的旧数据位置：

```text
环境变量 COMPANION_DATA_DIR 指定的位置
~/Library/Application Support/Desktop AI Companion/
%APPDATA%\Desktop AI Companion\
~/.config/Desktop AI Companion/
apps/server/data/
```

如果发现多个数据库，先比较修改时间、Alembic 版本和关键表记录数，不允许自行选择并覆盖。确认来源后执行：

1. 停止所有知语进程。
2. 备份原数据库。
3. 复制到新数据目录，不直接移动原文件。
4. 执行 Alembic upgrade。
5. 对比关键表和记录数。
6. CLI 验证成功后再保留原文件作为人工回滚备份。

旧数据迁移不得与删除 `apps/desktop` 混在同一个不可恢复操作中。

### 7.1 多进程访问

CLI 阶段允许 `zhiyu chat` 与 `zhiyu qq listen` 同时运行：

- SQLite 启用 WAL。
- 设置合理的 busy timeout。
- 每个进程和任务创建独立 Session，不跨线程共享 Session。
- 数据库写入保持短事务。
- 迁移命令执行前检测长期运行的知语进程，避免迁移期间继续写入。

第一阶段 `zhiyu qq listen` 是 QQ 渠道唯一宿主，避免两个进程争抢同一监听端口。Web UI 阶段再决定是否需要统一的 `zhiyu run` 进程。

## 8. 日志、错误与退出码

正常输出写入 stdout，错误和诊断信息写入 stderr。详细调用链写入日志文件。

约定退出码：

| 退出码 | 含义 |
|---:|---|
| 0 | 成功 |
| 1 | 未分类运行错误 |
| 2 | 参数或配置错误 |
| 3 | Provider 鉴权或模型配置错误 |
| 4 | 网络或外部服务不可用 |
| 5 | 数据库或迁移失败 |

用户按 `Ctrl+C` 时，聊天和 QQ 监听应完成资源清理后退出，不打印 Python traceback。使用 `--debug` 时才显示完整异常。

第一阶段同时在 macOS、Windows 和 Linux 验证。数据路径只通过 `Path.home()` 和跨平台路径逻辑构造；不在核心服务中写死平台路径。Keyring 后端不可用时，`doctor` 必须说明如何通过环境变量提供秘密，不能自动保存明文。

开发入口统一为：

```bash
uv sync
uv run zhiyu doctor
uv run zhiyu chat
```

CI 使用 macOS、Windows、Linux 三平台矩阵执行单元测试和 CLI 冒烟测试。第一阶段发布 Python wheel，支持 `uv tool install` 和 `pipx install`；独立可执行文件按各平台分别构建，不能在 macOS 上交叉产出其他系统安装包。

## 9. 测试策略

### 单元测试

- ChatService 的会话、消息、Agent Run 和 Memory 编排。
- ProviderService 的 Keychain 与默认模型行为。
- CLI 参数解析和退出码。
- 斜杠命令不进入模型上下文。
- `desktop` 本地身份迁移成 `local` 后会话与记忆不丢失。
- 新旧环境变量优先级和弃用提示。

### 集成测试

- 使用临时 SQLite 和假 Provider 运行完整 `zhiyu chat`。
- `provider add → test → default → chat` 完整链路。
- OneBot 模拟客户端连接 `zhiyu qq listen` 并完成私聊收发。
- 同时运行聊天和 QQ 写入，验证 WAL、busy timeout 和 Session 隔离。
- 迁移旧数据库后保留会话、Provider 和 QQ 配置。
- 安装成 CLI 后，在仓库目录之外仍能加载内置和用户 Skills。

### 验收测试

每个新功能必须先提供 CLI 验收路径。例如新增 Tool 时，至少能够通过 `zhiyu chat` 触发，并从输出或日志确认输入、调用和结果。

## 10. 分阶段实施

### Phase 0：冻结基线

状态：已完成。

- 记录当前测试结果。
- 确认桌面端没有未迁移的唯一业务逻辑。
- 检查环境变量、桌面应用数据目录和开发数据目录，确认实际数据库来源。
- 备份数据库，记录 Keychain 引用。
- 为当前可运行状态建立独立 Git 提交或标签，确保删除桌面端后可追溯。

验收：后端测试、数据库迁移、QQ 模拟连接均通过。

### Phase 1：抽取应用服务

状态：已完成。CLI 与 QQ 统一调用 ChatService，Provider 和渠道操作已抽到应用服务。

- 从 FastAPI Chat 路由和 ChannelRouter 提取 ChatService。
- 提取 ProviderService 和 ChannelService。
- 让现有路由和 ChannelRouter 临时调用应用服务，用原测试确认行为未变。

验收：API 和 QQ 对相同输入产生一致的持久化结果，聊天编排不再位于路由文件中。

### Phase 2：删除旧界面并提升 Python 项目

状态：已完成。活动源码已移到根目录 `src/zhiyu`，Electron、React 和 FastAPI 已移出当前工程。

- 删除 `apps/desktop`、FastAPI 路由和 FastAPI 运行依赖。
- 不在仓库内保留 Desktop 归档副本，通过 Git 基线追溯旧实现。
- 将 `apps/server` 的配置、迁移、测试和包提升到仓库根目录。
- 使用标准 `src/zhiyu` 包布局。
- 更新 CI、打包配置、README 和所有导入。
- 将本地渠道标识从 `desktop` 迁移为 `local`。
- 保留旧环境变量兼容读取和弃用提示。

验收：仓库不依赖 Electron、Node.js 或 FastAPI；Python 测试和三平台 CLI 冒烟测试通过；旧数据仍可读取。

### Phase 3：CLI MVP

状态：已完成。首版命令、迁移、测试、CI 和 wheel 打包已落地。

- 增加 `zhiyu` console script。
- 实现 doctor、chat、provider、qq configure、qq listen 和 db upgrade。
- 添加信号处理、退出码和 CLI 集成测试。

验收：全新环境无需 Web UI 即可配置模型、聊天和启动 QQ。

### Phase 4：以 CLI 迭代核心功能

状态：进行中。

- 每项 Agent、Memory、Skill、MCP 和 QQ 新能力先提供 CLI 路径。
- 稳定 ChatEvent 和应用服务接口。
- 补充 `--json` 输出，供自动化调用。

验收：核心功能不依赖 HTTP 服务或 GUI 才能开发、测试和诊断。

### Phase 5：Web UI

- 新建 `apps/web`。
- 根据 Web UI 的实际需求重新引入 FastAPI。
- FastAPI 仅负责鉴权、序列化、SSE/WebSocket 和调用应用服务。
- Web UI 覆盖已经通过 CLI 验证的能力。

验收：同一数据库中，CLI 与 Web 创建的会话可以互相读取，核心行为一致。

### Phase 6：可选桌面端

- 只有 Web UI 稳定且确实需要托盘、通知、自动启动或离线安装包时，才重新创建轻量 `apps/desktop`。
- 优先复用 Web UI，不重新维护一套业务界面。
- 完成签名、自动更新和平台数据目录适配。

验收：如决定实现，桌面端只是可靠的本地产品外壳，Agent 功能仍可独立通过 CLI 验证；如没有明确桌面需求，本阶段可以取消。

## 11. 暂不实施

- 全屏终端 UI、复杂动画和鼠标交互。
- 平台专属 GUI 集成。
- CLI 插件市场。
- 多用户与远程账号系统。
- 同时运行多个 QQ 账号。
- 为尚未出现的客户端设计通用 RPC 框架。
- Web UI 或桌面端组件库。

## 12. 完成标准

CLI 优先阶段完成时应满足：

1. 仓库以 `src/zhiyu` Python 包为主体，不再依赖 Electron 和 Node.js。
2. 用户能完全通过 CLI 配置 Provider、选择模型、进行流式聊天并启动 QQ。
3. CLI 和 QQ 使用同一应用服务；未来 Web API 无需复制聊天编排。
4. API Key 和 QQ Token 不以明文写入数据库、配置文件或日志。
5. 旧数据库和配置能够迁移并验证，不因删除桌面端丢失。
6. 新核心功能都有 CLI 验收路径和自动化测试。
7. 后续 Web UI 可以调用稳定的应用服务或 API，而无需重写 Agent Runtime。
8. CLI 在仓库目录之外运行时仍能找到数据、迁移文件和内置 Skills。
9. `zhiyu chat` 与 `zhiyu qq listen` 可以安全地并发读写 SQLite。
