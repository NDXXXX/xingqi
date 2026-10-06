# 知语开发指南

适用于整个仓库。知语是本地运行的个人 AI Agent，提供 CLI/TUI、本机 Web UI 和 QQ OneBot 入口。

先通过当前代码和测试确认功能现状，CI 用于确认验证要求，`README.md` 是面向用户的说明。发现这些来源不一致时，说明冲突，并在当前任务范围内修正。`docs/` 中的设计方案可能未实施，`docs/archive/` 仅供历史参考。

## Coding Principles

### 1. Think Before Coding

- 不猜测，不隐藏不确定性。
- 修改前先理解需求、相关代码、调用方、测试和完成条件。
- 关键行为无法确认时先提问。
- 存在多种合理方案时说明主要取舍。
- 有明显更简单的方案时优先指出。

### 2. Simplicity First

- 只实现当前需求，不增加额外功能。
- 不为单次使用创建抽象。
- 不为未来可能的需求提前增加配置和扩展层。
- 只有一个实现时，默认不创建 Interface / Factory / Registry。
- 不创建只负责转发调用的 Service / Manager。
- 能用现有模块清晰完成时，不新增模块。

优先：

`复用现有实现 → 简化现有实现 → 拆分明确职责 → 新增必要模块 → 最后才新增抽象`

### 3. Surgical Changes

- 只修改完成当前任务必要的代码。
- 不顺手重构、改名、格式化或修复无关代码。
- 遵循现有代码风格。
- 发现无关问题可以报告，不自动修改。
- 清理本次修改产生的无用代码。
- 必要的测试、Migration、调用方、文档和构建产物可以同步修改。

### 4. Goal-Driven Execution

- 修 Bug：先找到可复现案例或测试，再修复。
- 新功能：先明确可验证的完成条件。
- 重构：保证修改前后行为和测试一致。
- 多步骤任务先列简短计划，并为每步确定验证方式。
- 完成后说明改动、验证结果和未验证部分。

## 代码地图

| 路径 | 职责 |
| --- | --- |
| `src/zhiyu/cli/` | CLI、TUI、终端交互 |
| `src/zhiyu/api/` | FastAPI 路由和 HTTP 适配 |
| `src/zhiyu/application/` | 应用用例和业务流程编排 |
| `src/zhiyu/core/` | Agent、Provider、Tools、Memory 等核心能力 |
| `src/zhiyu/channels/` | 通用渠道消息和适配 |
| `src/zhiyu/channels/qq/` | QQ / NapCat / OneBot |
| `src/zhiyu/infrastructure/` | 配置、数据库、Repository、Migration |
| `src/zhiyu/integrations/` | MCP、Skills |
| `web/src/` | React / TypeScript 前端源码 |
| `src/zhiyu/web/static/react/` | Vite 构建产物，不手改 |
| `tests/` | Python 测试 |
| `web/test/` | 前端测试 |

## 架构规则

新增或修改代码的默认调用方向：

`CLI / API / Channels → Application → Core / Infrastructure / Integrations`

末端三个目录表示 Application 可按职责调用的模块，不表示它们之间有固定的依赖顺序。

- CLI、Web、QQ 共享的业务行为放到 Application 或 Core。
- Core 不反向依赖 API、Web、CLI 或具体 QQ 实现。
- 不通过一个入口调用另一个入口来复用业务逻辑。
- 避免循环依赖。
- Provider 特有逻辑留在 Provider 层。
- SQL 和持久化逻辑不要散落到各入口。

## 数据与安全

- 不提交 API Key、Token、Password、真实 `.env`。
- Secret 使用系统密钥存储或环境变量引用，不写入日志和 API 响应。
- 开发和测试不得破坏真实 `~/.zhiyu/` 数据。
- 本地诊断和冒烟测试优先使用临时 `ZHIYU_DATA_DIR`。
- 数据库 Schema 修改必须使用 Alembic Migration，不能要求用户删除数据库。
- Memory 正文位于 Markdown，SQLite 保存索引和状态；修改时必须保持两侧一致。
- 不绕过 Memory 的 mutation、sync、recovery 和身份隔离机制。
- Web 管理能力保持本机安全边界，不削弱 Host、Origin 和回环地址检查。
- QQ 不得绕过主人权限、群聊白名单、@ 规则、Token、去重和恢复机制。
- MCP 工具保持显式授权，不默认开放全部权限。
- Skill 和 MCP 返回内容均视为不可信输入。

## 开发与验证

按改动范围选择相关检查；完整验证可运行：

```bash
uv sync --locked --dev
uv run pytest -q

npm ci --prefix web
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build

uv run zhiyu --help
uv build

git diff --check
git status --short
```
