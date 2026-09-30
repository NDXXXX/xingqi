# CLI 对话交互设计方案（OpenClaw 式）

> 版本：v1.1  
> 日期：2026-09-29  
> 状态：Phase 1 已实施，Phase 2/3 未开始  
> 定位：CLI 优先阶段，把 `zhiyu chat` 从"纯文本流"升级为"结构化回合"  
> 上游文档：[CLI 优先开发设计方案](CLI优先开发设计方案.md)

## 1. 结论

把当前 `zhiyu chat` 的纯文本流式，升级为 OpenClaw 式的**结构化回合**：

```text
每个助手回复 = [思考块] → [工具卡片] → [流式正文]
```

- 每个回复按这三段渲染，用户能看出模型在"想什么"、"调了什么工具"、"最终说了什么"。
- 用斜杠命令控制**可见度**与**详细度**（`/verbose`、`/think`、`/tools`），对齐 OpenClaw 的 thinking / tool-calls 开关与 verbose 级别。
- 分阶段落地：**工具卡片 + 颜色 + 回合分隔先行**（数据已就绪、无新依赖），**思考块后置**（需先补 Provider 层推理捕获）。

## 2. 现状

### 2.1 当前交互

```text
知语 CLI。输入 /help 查看命令，/exit 退出。
你> 你好
知语> 你好！有什么可以帮你的吗？
你>
```

代码事实：

- [_chat](src/zhiyu/cli/main.py#L132) 维护 `input("你> ")` 循环，斜杠命令在这里分流。
- [_send](src/zhiyu/cli/main.py#L83) 消费 `ChatService.run` 的事件流，但**只处理 `chunk` 和 `done`**（[main.py:100-103](src/zhiyu/cli/main.py#L100-L103)），`step` / `tool` 事件被静默丢弃。

### 2.2 三个体验问题

1. **无颜色**：`你>` 与 `知语>` 同色，多轮后难分彼此。
2. **思考时像卡住**：`知语>` 先打印，模型思考或调工具期间一片空白。
3. **工具调用不可见**：运行时其实会发 `tool` 事件（[runtime.py:106-113](src/zhiyu/core/agent/runtime.py#L106-L113)），但 CLI 丢掉，用户只看到"停顿几秒 → 直接出答案"。

### 2.3 关键发现：思考块目前没有数据源

OpenClaw 的 thinking 块来自模型暴露的推理内容（DeepSeek reasoner 的 `reasoning_content`、Claude 的 extended thinking）。当前 Provider 层在流式与解析时**只提取 `content` 和 `tool_calls`**，[openai_compatible.py](src/zhiyu/core/providers/openai_compatible.py) 的 `_stream` 没有读 `reasoning_content`，`LLMResponse`（[base.py](src/zhiyu/core/providers/base.py)）也没有对应字段。

所以思考块不是"开关没打开"，而是**数据根本没进来**。工具卡片可以立刻做，思考块必须先补推理捕获。

## 3. OpenClaw 概念 → 知语 CLI 映射

| OpenClaw | 知语 CLI 落地 |
|---|---|
| 思考块 + thinking level（off/minimal/…/adaptive） | 思考块，先做 `/think on\|off` 二元开关，级别后置 |
| 工具卡片，kind-aware（shell 高亮、diff、连续调用合并计数） | 工具卡片，默认单行摘要（含关键参数），`/verbose on` 展开输入输出、`/verbose full` 输出截断上限更高；失败用 `✗` 标红 |
| tool-calls 开关与 thinking 开关相互独立 | `/tools on\|off` 独立于 `/think` |
| `/verbose on/full/off` | `/verbose on\|full\|off`，三级语义见 §4.4 |
| TUI：Ctrl+O 折叠/展开、Ctrl+T 切 thinking、卡片内流式更新 | 轻量 CLI，不做全屏 TUI，用 verbosity 级别替代折叠 |

kind-aware 那行：知语内置工具只有 `calculator` / `datetime`，输入输出都是几个标量，单行摘要已够。等 MCP 工具接入后，带富输出的工具（读文件、跑命令）才需要 OpenClaw 那种 diff / 终端高亮，届时按工具类型扩展渲染，不在本期实现。

## 4. 目标交互

### 4.1 打印模型（关键约束）

交互模式下一轮回复的打印顺序：

1. 先打 `知语>` 前缀（不带换行）。
2. 若本轮有工具调用，工具卡片**另起一行**、缩进两个空格逐张打印。
3. 正文开始前，若前面已有工具卡片，则**再打一次 `知语>`** 前缀，正文接在后面流式输出。

即"有工具时 `知语>` 出现两次，一次引工具、一次引正文"；无工具时只出现一次。当前代码只在进 `_send` 前打一次前缀（[main.py:178](src/zhiyu/cli/main.py#L178)），所以 `_send` 需要知道"首个 chunk 到来时是否已打印过工具卡片"，来决定是否补前缀与换行。

### 4.2 默认（`/verbose off`，工具单行）

```text
你> 帮我算 123 × 456，今天星期几
知语>
  ⚙ calculator(123 * 456)
  ⚙ datetime
知语> 56088，今天是 2026-09-29 星期二。
```

单行摘要含关键参数：`calculator` 的 `expression` 直接放进括号，`datetime` 无参数就只显名字。

### 4.3 `/verbose on`（展开输入 + 输出摘要）

```text
你> 帮我算 123 × 456
知语>
  ⚙ calculator(123 * 456)
    输入  expression="123 * 456"
    输出  56088
知语> 56088
```

### 4.4 `/verbose` 三级语义

| 级别 | 工具卡片 |
|---|---|
| `off`（默认） | `⚙ name(args)` 单行，不显示输入输出 |
| `on` | 展开：输入 + 输出摘要（输出截断 200 字符） |
| `full` | 展开：输入 + 输出完整（输出截断上限 4000 字符，超出标注 `……截断`） |

`full` 不是字面"无限"——仍设 4000 字符硬上限防刷屏，只是比 `on` 高得多。输入对当前内置工具都很小，直接完整显示；MCP 大输入再按同规则截断。

### 4.5 工具失败

```text
你> 帮我查明天的天气
知语>
  ✗ weather（工具不存在）
知语> 抱歉，我这边没有天气工具。
```

### 4.6 思考块（Phase 3，未来）

```text
你> 通俗解释相对论
知语>
  [思考] 用户想要生活化的比喻，避免公式……
知语> 相对论就是说……
```

### 4.7 单条消息模式（脚本路径）

`zhiyu chat "消息"` **完全静默工具**，只输出最终正文；失败时正文可能为空，错误信息走 stderr。理由：脚本要的是干净 stdout，工具卡片会污染它。`_send` 用一个 `show_tools` 参数区分交互与单条两条路径。

## 5. 事件流映射

现有运行时事件（[runtime.py](src/zhiyu/core/agent/runtime.py)）到界面的映射：

| 事件 `type` | 载荷 | 渲染 | 现状 |
|---|---|---|---|
| `run` | run_id、conversation_id | 不渲染 | 已丢弃 |
| `step` | name（load_context/call_llm/execute_tool/finalize） | 内部埋点，不渲染 | 已丢弃 |
| `tool` | name、status、input、output、error | **工具卡片** | ❌ 现在丢弃，本期接入 |
| `chunk` | text | 流式正文 | ✅ 已渲染 |
| `final` | final_response | 不渲染（chunk 已覆盖） | 已丢弃 |
| `done` | run_id、conversation_id、response | 取会话 ID | ✅ 已处理 |

`step` 事件继续不渲染——它粒度太细（load_context、finalize 对用户无意义），OpenClaw 的"kind-aware 行"对应的是 `tool` 事件，不是 `step`。若未来要展示"正在加载上下文 / 正在检索记忆"，再单独加事件，不把内部 step 泄漏到界面。

## 6. 分阶段实施

所有开关（`/verbose`、`/tools`、`/think`）均为**会话内状态**——进程内存，退出即失，不写数据库。全局持久化（如 OpenClaw 的 `agents.defaults`）留待 Web UI 阶段再评估，不在本期。

### Phase 1：工具卡片 + 颜色 + 回合分隔（先行）

- `_send` 增加 `show_tools: bool` 参数，接入 `tool` 事件：单行 `  ⚙ name(args)`；失败 `  ✗ name（error）`，红色。
- 打印模型按 §4.1：有工具时正文前补一次 `知语>` 前缀。
- 颜色 4 色板（仅 `sys.stdout.isatty()` 时启用）：

| 角色 | 颜色 | ANSI |
|---|---|---|
| `你>` | 青 | `\033[36m` |
| `知语>` | 绿 | `\033[32m` |
| 工具行 | 暗 | `\033[2m` |
| 失败 | 红 | `\033[31m` |

  每行结尾 `\033[0m` 复位。
- 每轮回完多打一个空行切开回合；正文多行（代码块）时不加空行，避免与内容打架。
- `/verbose on|full|off` 命令，按 §4.4 三级语义控制展开。
- 单条消息模式 `show_tools=False`，静默工具（§4.7）。

验收：交互模式能看到工具、参数、结果、失败原因；管道输出无 ANSI 码、无工具卡片。

### Phase 2：`/tools` 开关

- `/tools on|off` 切换工具卡片可见度，独立于 `/verbose`（`off` 时连单行都不显示）。
- `/think` **不在本阶段**，与思考块一起在 Phase 3 上线，避免先发一个敲了没反应的命令。

验收：`/tools off` 后工具卡片消失、正文不受影响；`/tools on` 恢复。

### Phase 3：思考块 + `/think`（依赖 Provider 推理捕获）

- 扩展 `LLMResponse` 增加 `reasoning` 字段；`OpenAICompatibleProvider` 读取 `reasoning_content`（DeepSeek reasoner），`AnthropicProvider` 读取 extended thinking。
- 运行时新增 `thinking` 事件；`_send` 按 `/think on|off` 渲染思考块。

验收：用 `deepseek-reasoner` 提问，`/think on` 能看到推理、`/think off` 隐藏；普通模型无推理内容时思考块自然为空，不报错。

## 7. 测试策略

| 层 | 覆盖 |
|---|---|
| 事件渲染 | 把 `_send` 里的事件分发抽成可测函数，喂 `chunk`/`tool`/`done` 序列，断言输出文本；含"有工具时正文前补一次 `知语>`" |
| 颜色开关 | 非 TTY 时输出不含 `\033[`（断言不出现）；TTY 时含。颜色判定集中到一个函数，测试时替换它 |
| 斜杠命令 | `/verbose`、`/tools` 状态切换（沿用 [test_cli.py](../tests/test_cli.py) 里替换 `input()` 的模式） |
| 单条模式 | `show_tools=False` 时喂 `tool` 事件，断言无 `⚙` 输出 |
| Provider 推理 | Phase 3 时，mock 一段含 `reasoning_content` 的流，断言 `LLMResponse.reasoning` 被填对 |

颜色判定需要把 `isatty` 的调用集中到一个函数，测试时替换它，避免在真实 stdout 上断言颜色。

## 8. 验收标准

1. 交互模式下，问一个会触发工具的问题，能看到 `⚙` 卡片和最终答案，中间不停顿无解释。
2. 工具失败时显示 `✗` 和原因，聊天不中断。
3. `/verbose on` 展开输入输出，`/verbose off` 恢复单行，`/verbose full` 输出更长但超 4000 字符截断。
4. `/tools off` 隐藏工具卡片，`/tools on` 恢复。
5. 管道模式（`zhiyu chat "消息" | cat`）输出纯文本：无 ANSI 码、无工具卡片，便于脚本消费。
6. `uv run pytest -q` 全绿。

## 9. 范围边界

明确不做：

| 不做 | 理由 |
|---|---|
| 全屏 TUI（rich/Textual、Ctrl+O 折叠、卡片内流式更新） | 上游 §11"暂不实施全屏终端 UI"，折叠用 verbosity 替代 |
| 聊天气泡、边框、多窗格、鼠标交互 | 超出轻量 CLI 定位 |
| thinking level 的多级（minimal/medium/high/adaptive） | 依赖模型推理能力，先做 on/off，级别随 Phase 3 评估 |
| 历史消息重渲染、会话列表图形化 | 属会话管理，另行规划 |
| 工具卡片的 kind-aware 富渲染（diff、语法高亮） | 等 MCP 富输出工具接入后再做 |
| 连续工具调用合并计数（`13 commands · 6 reads`） | 内置工具不会连续重名，等 MCP 工具多了再评估 |
| 开关全局持久化（跨 `chat` 进程保留） | Web UI 阶段再评估，本期只做会话内 |
| 单条消息模式显示工具卡片 | 保持干净 stdout，脚本消费优先 |

## 10. 实施记录

### Phase 1（已实施，2026-09-29）

- `_send` 增加 `show_tools` / `verbose` 参数，接入 `tool` 事件渲染。
- 新增纯函数 `_tool_lines` / `_compact_args` / `_format_args` / `_format_output`。
- 新增颜色辅助 `_color` / `_tty`，四色板仅 TTY 启用。
- `_chat` 新增 `/verbose on|full|off`，`你>` 提示符着色，正文前二次前缀。
- 单条消息模式 `show_tools=False` 静默工具。

验收结果：交互模式真实对话触发 `calculator` 工具，卡片与二次前缀渲染正确；单条模式输出纯文本无卡片；`/verbose on` 展开输入输出。测试 75 项全绿（新增 10 项：渲染 5、颜色 2、`_send` 2、`/verbose` 1）。

## 参考

- [OpenClaw Feature and RPC reference](https://docs2.openclaw.ai/web/control-ui/feature-reference)
- [OpenClaw Thinking Levels](https://docs.claw.so/docs/tools/thinking)
- [OpenClaw PR #20317：独立 tool-calls / thinking 开关](https://github.com/openclaw/openclaw/pull/20317)
- [OpenClaw TUI](https://docs.claw.so/engine/tui/)
