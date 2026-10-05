# 知语

运行在本地的 Personal AI Agent。当前提供 CLI、TUI、本地 WebUI 与 QQ OneBot 入口，共用同一套 Agent、会话和长期记忆。

## 目录

```text
src/zhiyu/
  cli/             命令行入口
  api/             本地 Web API
  web/             无构建静态 WebUI
  application/     可复用用例编排
  core/            Agent、Provider、Memory、Tools、Characters
  channels/        QQ 等消息入口
  integrations/    MCP、Skills
  infrastructure/  配置、数据库、Keyring
tests/
docs/
```

运行数据默认保存在 `~/.zhiyu`，API Key 和 Access Token 通过系统 Keyring 保存。可以使用 `ZHIYU_DATA_DIR` 覆盖数据目录。

## 开发

需要 Python 3.12 和 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync
uv run zhiyu db upgrade
uv run zhiyu doctor
```

配置模型并聊天：

```bash
uv run zhiyu provider add work --type openai
uv run zhiyu provider list
uv run zhiyu provider default work gpt-4o-mini
uv run zhiyu chat
```

启动仅监听本机的 WebUI：

```bash
uv run zhiyu serve
# 打开 http://127.0.0.1:8765
```

配置主 Provider 的故障切换顺序：

```bash
uv run zhiyu provider fallback work backup-a backup-b
```

查看和纠正长期记忆：

```bash
uv run zhiyu memory list
uv run zhiyu memory search "咖啡"
uv run zhiyu memory add --type preference --content "用户喜欢简洁回答"
uv run zhiyu memory edit <id> --content "用户喜欢详细解释"
uv run zhiyu memory complete <id>
uv run zhiyu memory forget <id>             # 预览
uv run zhiyu memory forget <id> --apply     # 执行
uv run zhiyu memory status
uv run zhiyu memory sync
uv run zhiyu memory retry
uv run zhiyu memory index
uv run zhiyu memory recall-explain "接着做那个桌面助手"
```

聊天结束后，长期记忆由持久化后台任务提取；单次 CLI 退出也不会丢失任务。常驻 TUI/QQ 会自动处理，`memory sync` 可手动恢复和执行待处理任务。

长会话超过模型上下文预算时，知语保留最近完整轮次，并把较早消息压缩成可重新生成的派生摘要；原始消息不会被摘要替换。

配置常驻 MCP stdio服务器及工具白名单：

```bash
uv run zhiyu mcp add filesystem npx --arg=-y --arg @modelcontextprotocol/server-filesystem --arg /path/to/workspace --allow-tool read_file
uv run zhiyu mcp list
```

`zhiyu serve` 启动时自动连接已启用的 MCP服务器。Skill正文不会预先全部注入上下文，Agent只在需要时通过 `read_skill`读取匹配 Skill。

使用已配置的 Provider 运行固定记忆语义评估集：

```bash
PYTHONPATH=src uv run python scripts/evaluate_memory.py --provider deepseek --model deepseek-chat
PYTHONPATH=src uv run python scripts/evaluate_memory_retrieval.py
```

非交互环境通过环境变量提供密钥：

```bash
export OPENAI_API_KEY='...'
uv run zhiyu provider add work --type openai --api-key-env OPENAI_API_KEY
```

也可以把密钥写进 `.env`（`cp .env.example .env` 后填入），`zhiyu` 启动时会自动加载：

```bash
# .env
DEEPSEEK_API_KEY='sk-xxx'
```

```bash
uv run zhiyu provider add deepseek --type deepseek --api-key-env DEEPSEEK_API_KEY
```

## QQ

知语监听 OneBot v11 反向 WebSocket，由 NapCat 主动连接：

```bash
uv run zhiyu qq configure --endpoint ws://127.0.0.1:6199/ws --owner-user-id <你的QQ号>
uv run zhiyu qq listen
```

在 NapCat 新增 WebSocket 客户端，填写相同地址和 Token，消息格式选择 Array。当前支持一个 OneBot连接、主人私聊文本以及可选的主人群聊文本。入站消息按消息 ID持久化去重，发送等待 OneBot `echo`回执；同一会话串行处理，不同会话可并行。发送 `/new` 可开始一条独立私聊会话，所有获准 QQ会话与本机共享记忆。

群聊默认关闭；开启后默认仍然必须 @ Agent：

```bash
uv run zhiyu qq configure --group-messages --group-require-mention
```

图片、语音和文件已有统一消息结构，但尚未接通 QQ真实收发和模型多模态。

监听地址不是 `localhost`、`127.0.0.0/8` 或 `::1` 时必须配置 Access Token；可通过 `--token-env <环境变量名>` 提供。

## 测试与安装

```bash
uv run pytest -q
uv build
uv tool install .
```

安装后可以直接运行 `zhiyu doctor`、`zhiyu chat` 和 `zhiyu serve`。

本轮消息平台实现见 [AstrBot 式消息平台重构设计方案](docs/AstrBot式消息平台重构设计方案.md)，QQ 后续范围见 [QQ 接入设计方案](docs/QQ接入设计方案.md)。
