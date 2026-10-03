# 知语

运行在本地的 Personal AI Agent。当前阶段以 CLI 为唯一产品入口，用于开发和验证聊天、Provider、Agent、Memory、Skills、MCP 与 QQ 渠道。

## 目录

```text
src/zhiyu/
  cli/             命令行入口
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
uv run zhiyu qq configure --endpoint ws://127.0.0.1:6199/ws
uv run zhiyu qq listen
```

在 NapCat 新增 WebSocket 客户端，填写相同地址和 Token，消息格式选择 Array。当前只支持一个连接和私聊文本。

## 测试与安装

```bash
uv run pytest -q
uv build
uv tool install .
```

安装后可以直接运行 `zhiyu doctor` 和 `zhiyu chat`。

开发路线见 [CLI 优先开发设计方案](docs/CLI优先开发设计方案.md)，QQ 后续范围见 [QQ 接入设计方案](docs/QQ接入设计方案.md)。
