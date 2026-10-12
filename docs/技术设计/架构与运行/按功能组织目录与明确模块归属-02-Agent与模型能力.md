# 按功能组织目录与明确模块归属：02 Agent 与模型能力迁移

## 文档状态与边界

- 状态：迁移已实施；依赖[总设计](按功能组织目录与明确模块归属设计方案.md)及 01 批。
- 范围：Agent 运行内核、角色、Provider、通用工具，以及 Skills Agent 工具的归属调整。
- 不改变 Agent 运行步骤、提示词、模型选择、工具权限、公开 API 或用户配置。

## 1. 文件迁移清单

| 当前路径 | 目标路径 | 说明 |
| --- | --- | --- |
| `src/zhiyu/core/agent/__init__.py` | `src/zhiyu/agents/__init__.py` | Agent 包入口；只导出必要符号 |
| `src/zhiyu/core/agent/context.py` | `src/zhiyu/agents/context.py` | Agent 上下文构造 |
| `src/zhiyu/core/agent/graph.py` | `src/zhiyu/agents/graph.py` | Agent 图与执行步骤 |
| `src/zhiyu/core/agent/run_manager.py` | `src/zhiyu/agents/run_manager.py` | Agent 执行生命周期管理 |
| `src/zhiyu/core/agent/runtime.py` | `src/zhiyu/agents/runtime.py` | Agent runtime |
| `src/zhiyu/core/agent/state.py` | `src/zhiyu/agents/state.py` | Agent 状态 |
| `src/zhiyu/core/characters/__init__.py` | `src/zhiyu/characters/__init__.py` | 角色包入口 |
| `src/zhiyu/core/characters/prompts.py` | `src/zhiyu/characters/prompts.py` | 角色提示词组装 |
| `src/zhiyu/application/characters.py` | `src/zhiyu/characters/service.py` | 角色应用服务 |
| `src/zhiyu/core/providers/__init__.py` | `src/zhiyu/providers/__init__.py` | Provider 包入口 |
| — | `src/zhiyu/providers/catalog.py` | 新增纯 Provider 类型目录，只保存 provider_type、默认 Base URL、默认模型等标量元数据 |
| `src/zhiyu/core/providers/anthropic.py` | `src/zhiyu/providers/anthropic.py` | Anthropic 协议实现 |
| `src/zhiyu/core/providers/base.py` | `src/zhiyu/providers/base.py` | Provider 协议和共享类型 |
| `src/zhiyu/core/providers/embedding.py` | `src/zhiyu/providers/embedding.py` | Embedding Provider |
| `src/zhiyu/core/providers/openai_compatible.py` | `src/zhiyu/providers/openai_compatible.py` | OpenAI compatible 协议实现 |
| `src/zhiyu/core/providers/router.py` | `src/zhiyu/providers/router.py` | Provider 路由；组合纯目录元数据与具体 Provider 实现 |
| `src/zhiyu/core/providers/selection.py` | `src/zhiyu/providers/selection.py` | Provider 选择规则 |
| `src/zhiyu/application/providers.py` | `src/zhiyu/providers/service.py` | Provider 管理用例 |
| `src/zhiyu/core/tools/__init__.py` | `src/zhiyu/agents/tools/__init__.py` | Agent 通用工具包入口 |
| `src/zhiyu/core/tools/base.py` | `src/zhiyu/agents/tools/base.py` | 通用工具协议 |
| `src/zhiyu/core/tools/calculator.py` | `src/zhiyu/agents/tools/calculator.py` | 通用计算器工具 |
| `src/zhiyu/core/tools/datetime.py` | `src/zhiyu/agents/tools/datetime.py` | 通用时间工具 |
| `src/zhiyu/core/tools/registry.py` | `src/zhiyu/agents/tools/registry.py` | 通用工具注册和装配 |
| `src/zhiyu/core/tools/skills.py` | `src/zhiyu/skills/tool.py` | Skills 专属 Agent 工具；与 Agent 通用工具分开归属 |

新增 `src/zhiyu/agents/tools/__init__.py`。`core/tools/skills.py` 移入独立 `skills/` 功能包，不放进通用 Agent 工具目录。

`providers/catalog.py` 是本批唯一新增的 Provider 边界文件。它只保存类型名、默认 Base URL、默认模型及必要的协议标识，不导入 SDK、密钥、数据库模型或 Provider 实现。`router.py` 根据该目录和本地实现映射创建运行时 Provider；如现有调用需要 `PROVIDER_SPECS`，由 Router 继续导出兼容映射。`ProviderRepository` 的默认模型播种与 `providers/service.py` 的类型校验改为读取纯目录，保留当前创建结果和校验行为，不把 Repository 的事务/播种职责转交给应用服务。

## 2. 留在原位置的相关文件

- 第 01 批的 `memory/tools.py` 已接管记忆专属工具；本批只移动通用工具及 Skills 工具。
- `application/runtime.py` 留作运行时装配，更新其 Agent/Provider/角色/工具导入。`chat.py` 和 `conversations.py` 在第 03 批分别迁入 `chat/`、`sessions/`。
- `api/routes/agent.py`、`api/routes/providers.py`、`api/schemas/**` 和 CLI 命令保持入口职责，仅更新调用路径。
- `infrastructure/database/repositories/agent_run_repository.py`、`provider_repository.py`、`character_repository.py` 留在 Repository 层。
- `skills/loader.py`、`registry.py` 在第 03 批一起迁入 `skills/`；这是 Skill 加载机制，非 Agent 通用工具。
- `src/zhiyu/core/__init__.py` 和 `core/memory/indexer.py` 是第 01 批明确保留的兼容入口；它们不再代表业务实现目录，本批不删除。

## 3. 调用方和测试

同步检查全仓 Python 导入、测试 mock/patch 路径、动态加载、注释和文档示例。重点测试：

- Agent：`tests/test_agent.py`、`test_agent_context.py`、`test_multi_agent.py`、`test_runtime_host.py`。
- Provider：`tests/test_providers.py`、`test_provider_service.py`、`test_embedding.py`。
- 角色：`tests/test_characters.py`、`test_character_service.py`。
- 工具与 Skills：`tests/test_tools.py`、`test_memory_tools.py`、`test_skills.py`、`test_skills_lifecycle.py`、`test_mcp.py`。
- 集成调用面：`tests/test_chat_service.py`、`test_web_api.py`、`test_cli.py`。

## 4. 执行与风险控制

1. 完成 01 批后复核 Agent/Provider 与 Memory 的真实引用，避免使用旧 `core` 路径的测试 patch 造成假阳性。
2. 逐包移动并同步导入。Provider 特有协议逻辑留在 `providers/`，Agent 通用工具协议和注册位于 `agents/tools/`，Skills 相关加载/权限留在独立 `skills/`。
3. 搜索旧前缀 `zhiyu.core.agent`、`zhiyu.core.characters`、`zhiyu.core.providers`、`zhiyu.core.tools`、`zhiyu.application.characters`、`zhiyu.application.providers`。
4. 运行本批重点测试、完整 Python 测试、CLI help 和构建检查；确认真实可用的模型和工具装配顺序未改变。
5. 检查没有从 `agents/` 或 `providers/` 反向导入 API、CLI、`application/` 或具体 QQ 实现；确需应用级装配的引用放在 `application/`。

## 5. 批次验收

- 表中所有迁移项均归入新目标，通用工具、Memory 工具、Skills 工具各自归属明确。
- 生产代码与测试不再使用表列的旧模块路径。
- Agent、Provider、角色和工具相关测试通过，入口和产品行为保持一致。
- 不改变模型配置数据、角色数据、工具授权、数据库结构及打包入口。

## 6. 实施记录

- Agent、角色、Provider 和通用工具已迁入目标功能包；Skills 工具归入 `skills/tool.py`。Provider 默认元数据抽到纯 `providers/catalog.py`，Repository 不再导入 Router；Router 继续导出 `PROVIDER_SPECS`。
- 本批重点测试：128 passed、3 failed；失败为基线已有的 3 项 `test_agent_context.py` 摘要压缩用例。完整测试见第 03 批实施记录。
- Provider 与相关生产、测试导入已更新；未改变数据库 Schema、Provider 配置或工具授权。
