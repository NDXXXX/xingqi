# 知语整体架构整理与 NapCat 式 WebUI 重构设计方案

> 版本：v1.1  
> 日期：2026-10-06  
> 状态：实施中  
> 范围：在不推倒重写业务的前提下，整理知语前后端模块边界，并将 WebUI 从原生 HTML/CSS/JavaScript 升级为 React 组件化前端。保留单体部署、FastAPI API、数据库和用户配置。

## 1. 背景与目标

NapCat WebUI 是一个由 React 驱动的单页应用：服务端返回应用入口，浏览器挂载前端根节点；页面由组件渲染，通过路由切换，通过 HTTP API 与后端交互，并以 SSE 接收实时状态。其配置弹窗使用统一的暗色面板、模糊遮罩、分组表单、自定义开关和明确的取消/保存操作。

知语当前前端是 FastAPI 托管的静态 HTML、CSS 和原生 JavaScript。它已有 Provider、MCP、Skills 等管理能力，但交互仍混用原生 `prompt`、`confirm`、`alert` 与少量 `<dialog>`，造成风格和表单体验不一致。

后端已经按 `api / application / core / infrastructure / channels / integrations` 分目录，但实际依赖没有完全遵循这些边界：入口文件较大，部分 `core` 代码直接访问 ORM、Repository 或外部集成。新增功能时容易不知道逻辑应该放在哪里。

本方案目标是让知语采用类似 NapCat 的前端实现方式：

1. 以渐进式模块化单体整理 API、CLI、应用服务、核心逻辑与基础设施的职责边界。
2. 以 React 组件组织页面、表单、弹窗、通知和状态反馈，统一替换浏览器原生输入/确认/提示框。
3. 延续知语现有深色界面、粉色强调色与侧栏导航，并借鉴 NapCat 的紧凑设置面板交互。
4. 保持 FastAPI、数据库、密钥存储、运行时行为和现有 `/api` 合约不变。
5. 产物仍可由 `uv run zhiyu serve` 单命令托管，不要求最终用户运行 Node 服务。

## 2. 当前实现基线

- `src/zhiyu/api/app.py` 使用 FastAPI 提供 API，并从 `src/zhiyu/web/static` 托管静态文件。
- `src/zhiyu/web/static/index.html` 是当前单页骨架，包含导航、视图容器和少量 `<dialog>`。
- `src/zhiyu/web/static/app.js` 直接查询 DOM 并绑定事件，承担视图切换、API 请求、表单操作和状态渲染。
- `src/zhiyu/web/static/styles.css` 同时承载基础样式和深色管理台主题。
- 前端没有独立的 `package.json`、构建配置或 Node 锁文件。
- 当前 MCP 新增流程已经改为站内 `<dialog>`；Provider 编辑、MCP 密钥与授权、Skills 生命周期、记忆编辑和确认操作仍有原生对话框。
- `src/zhiyu/api/app.py` 同时创建服务、定义各类 API 路由并挂载静态资源；目标是让它只负责应用装配和路由注册。
- `src/zhiyu/cli/main.py` 集中定义大量命令和运行流程；目标是保留 CLI 兼容性，将命令实现按领域拆分。
- `src/zhiyu/core` 中的 Agent、Memory 和 Provider 模块包含核心算法，但部分文件直接依赖 `infrastructure.database`、Repository、全局配置或 `integrations`。
- `application` 服务也直接构造具体 Repository、使用默认全局 Session/Manager；测试可注入部分依赖，但边界尚未统一。
- 仓库整体适合继续作为单机模块化单体，不需要拆分进程或服务。

## 3. 方案决策

### 3.1 采用 React 前端，不改 FastAPI

前端使用 React、TypeScript、Vite、Tailwind CSS 和与 NapCat 相近的 NextUI/HeroUI 风格组件库。组件库在实施前确认兼容性和维护状态，并锁定准确版本。FastAPI 继续提供静态构建产物及 `/api`，不改业务 API 的 URL、请求/响应结构或应用服务边界。

开发时可由 Vite 提供热更新，并将 `/api` 代理到 FastAPI；交付构建时把 Vite 产物输出到 Python 包内的静态目录。用户运行知语仍只需启动 FastAPI。

### 3.2 备选方案

| 方案 | 优点 | 代价 | 结论 |
|---|---|---|---|
| 继续原生 JS，只添加弹窗和表单组件 | 改动最少，无 Node 构建 | 页面状态仍靠手动 DOM 操作；后续管理页越多越难保持一致 | 可作为短期修补，不满足“采用他那种实现”的完整目标 |
| React 化整个 WebUI，保留 FastAPI | 页面和交互可复用组件；支持一致的路由和状态管理；贴近 NapCat 结构 | 增加前端依赖及构建流程 | **推荐** |
| 将后端也迁移到 Node | 与 NapCat 技术栈更接近 | 重写 API/运行时边界，影响范围大且无必要 | 不采用 |

本方案按第二种方式实施。React 只替代浏览器前端，不迁移 FastAPI，不复制 NapCat 的账号认证模型或服务端实现细节。

### 3.3 后端采用渐进式模块化单体

- 保留一个 Python 包、一个 FastAPI 进程、一个 CLI 入口和现有 SQLite 数据库。
- 不按技术潮流改为微服务，不重命名所有模块，不一次性重写 Agent、Memory、渠道或配置系统。
- 依赖方向统一为：入口层 → application 用例 → core 领域/算法；application 通过明确注入使用持久化及外部能力；`infrastructure`、`channels`、`integrations` 位于外层，不能反向成为 `core` 的依赖。
- 仅在确实需要隔离且有多个调用方时引入 Protocol/Port，不为单一 Repository 或简单函数机械增加抽象层。
- 重构期间先移动入口编排和依赖获取，再逐模块切断 `core` 对 SQLAlchemy、Repository、全局单例和集成实现的直接依赖；外部行为与 API 合约保持不变。

## 4. 目标架构

```text
浏览器 React SPA
  ├─ 页面与共享 UI 组件
  ├─ API Client / SSE Client
  └─ Vite 构建静态资源
          │ 同源 HTTP / SSE：/api
          ▼
FastAPI 入口 / routers
          ▼
Application 用例（事务、业务编排、运行时协调）
       ├─ Core（领域规则与 Agent/Memory 算法）
       └─ 注入的持久化/外部能力
             ▲
Infrastructure / Channels / Integrations（DB、KeyStore、OneBot、MCP、Skills）
```

生产运行：FastAPI 托管 React 编译生成的 HTML、JS、CSS 和静态资源。前端不得直接访问数据库、密钥存储或 Runtime 私有对象，只调用现有 API。

推荐目录（只新增/拆分明确边界，不要求一次性搬迁所有文件）：

```text
web/
  package.json
  vite.config.ts
  tsconfig.json
  src/
    app/          # App、路由、布局
    components/   # Modal、FormField、Switch、Toast、确认框
    features/     # providers、mcp、skills、channels、memory 等页面模块
    lib/          # API Client、SSE、格式化与校验
    styles/       # Tailwind 入口和主题 token
  dist/           # 构建结果，复制/输出至知语静态资源目录
```

后端目标边界：

```text
src/zhiyu/
  api/
    app.py             # lifespan、中间件、router 注册、静态资源挂载
    routes/            # 按 providers、mcp、skills、channels、memory、chat 拆路由
    schemas/            # 请求/响应模型；共享 DTO 避免各路由重复定义
  cli/
    main.py             # 参数解析与命令注册
    commands/           # 按 chat、provider、channel、mcp、skills、memory 拆命令实现
  application/          # 用例与事务编排；入口共享同一组服务
  core/                 # Agent、Memory、Provider 等核心规则/算法，不访问具体 DB/API
  infrastructure/
    database/           # SQLAlchemy models、repositories、migrations
    config/             # Settings、KeyStore、日志等系统适配
  channels/             # OneBot/QQ 等渠道适配、消息协议与媒体处理
  integrations/         # MCP、Skills 等外部协议/扩展适配
  web/static/           # React 生产构建产物（开发源码独立放在 web/src）
```

按当前规模继续使用 `application/*.py` 等现有文件布局也可；只有在文件职责自然成组时才形成子包。目录名称不能替代依赖规则，边界以 import 方向和公开接口为准。

实际文件位置应按 Python 包构建规则确认，避免源码包漏掉构建后的静态资源。Node 依赖、lockfile 和构建命令放在独立 `web/` 目录，不让 Python 运行时安装 Node 依赖。

## 5. 视觉与交互规范

### 5.1 统一外观

- 延续知语现有深色背景、粉色主操作色、圆角面板和左侧导航，不整体照搬 NapCat 的信息架构或品牌素材。
- 管理弹窗居中显示，背景使用半透明暗色遮罩和适度模糊；面板宽度按任务调整，内容过长时面板内部滚动。
- 标题、简短说明、关闭按钮、分区表单、底部取消/主操作按钮采用统一布局。
- 错误放在字段旁或表单顶部；成功使用轻量 Toast；破坏性确认使用自定义 ConfirmDialog。
- ESC 可关闭未提交的弹窗；有未保存改动时先显示站内确认框。

### 5.2 共享组件

| 组件 | 用途 | 必要状态 |
|---|---|---|
| `AppDialog` | 统一弹窗外壳、标题、说明和操作区 | 打开、关闭、提交中、未保存 |
| `FormField` | 标签、必填、提示、字段错误 | 正常、聚焦、错误、禁用 |
| `SecretField` | API Key、MCP Secret、QQ Token 输入 | 空白占位、当前已保存提示、替换/清除；绝不回填明文 |
| `SwitchCard` | 启用、Debug、权限等布尔选项 | 开启、关闭、禁用、保存中 |
| `ConfirmDialog` | 删除、覆盖更新、重试未知投递等 | 风险说明、取消、确认中 |
| `ToastHost` | 操作成功/失败的短时反馈 | 成功、警告、失败 |
| `LoadingButton` | 避免重复提交 | 空闲、处理中、成功/失败反馈 |

组件优先使用原生可访问性语义及组件库已有实现，不额外引入第二套重型组件系统。

### 5.3 交互规则

- 所有用户输入都在站内表单中完成，前端禁止使用 `window.prompt/confirm/alert`。
- 校验在客户端即时提示，并由后端再次校验；错误信息保留在弹窗内，不清空用户已经填写的非敏感字段。
- API Key、Token、Secret 读取时显示“已保存”状态，不回显内容；关闭或成功提交后清除输入框中的密钥值。
- 提交过程中显示加载状态并禁用重复提交；失败后保留可安全重试的表单状态。
- 关闭或切换视图遇未保存数据时，先通过 `ConfirmDialog` 询问，不静默丢弃。
- 空列表提供直接进入新增表单的按钮；空状态、无结果、加载失败和接口不可用分开呈现。

## 6. 页面与弹窗清单

### 6.1 Provider 与模型

- Provider 新增/编辑：名称、协议、Base URL、启用状态、API Key 或环境变量来源。
- 密钥处理：输入框默认为空，允许明确替换或清除；不在前端 localStorage 保存凭据。
- 模型新增/编辑：标识、显示名、启用、工具/流式/视觉能力、上下文窗口和最大输出 Token。布尔能力用 `SwitchCard`，不要求用户编辑 JSON。
- 默认模型：通过模型列表选择，不要求手工输入模型字符串。
- Fallback：按可用 Provider 列表选择，并以清晰顺序展示/调整；阻止自引用和重复选择。
- 删除：使用 `ConfirmDialog` 展示会删除的 Provider/模型及默认/Fallback 清理影响。
- 测试连接：返回结果显示在结果对话框或卡片内，不用系统 alert 展示原始 JSON。

### 6.2 MCP

- 新增/编辑使用同一表单弹窗：名称、stdio/Streamable HTTP/SSE、条件化命令/参数或 URL、启用状态。
- Secret 与环境变量使用专门设置对话框；已有密钥只显示名称和已保存状态，支持显式替换/删除。
- 能力发现后以可勾选列表授权 Tools、Resources 和 Prompts；旧 `legacy_all_tools` 配置展示迁移警告。
- Resource 读取和 Prompt 渲染使用站内结果面板，以纯文本呈现外部内容，并标记其不可信。
- 重连、启停、删除使用统一按钮状态和确认流程；连接状态、最后错误和能力摘要仍在 MCP 卡片中可见。

### 6.3 Skills

- 安装：站内表单输入本地路径或 HTTPS Git 来源，先预览名称、来源、文件清单、依赖和警告，再确认安装。
- 更新：展示版本变化、文件差异和本地修改提醒；用户确认后应用，不以浏览器 confirm 代替详情预览。
- 移入回收站与恢复：使用站内确认/结果反馈；同名冲突显示可操作错误。
- 回收站内容为空时明确展示空态，不将内置 Skill 暴露为可删除操作。

### 6.4 其他页面

- QQ 配置、群聊策略、记忆编辑、渠道事件重放和未知状态投递重试逐步迁移到统一表单/确认/结果组件。
- 本方案完成后，`app.js` 中的功能按页面拆为 React feature modules；不要求改变页面当前业务范围。

## 7. 状态与 API 约定

- 建立单一 API Client，统一 JSON 解码、HTTP 错误映射、请求超时和 AbortSignal；错误文案不携带密钥或认证头。
- 初期直接使用轻量 React state 和页面级请求，不因为改 React 就引入全局状态框架或请求缓存库。
- SSE 仅用于已有或确需的实时状态/日志，页面卸载时关闭连接；不得以高频轮询替代。
- 继续使用现有 API 路径与 Pydantic 校验；只有实际缺少业务能力时才单独提出后端接口改动。
- Provider/MCP/Skills 变更后沿用现有 Runtime revision/reload 机制；UI 明确区分“已保存”和“运行时已生效”。
- 将 `api/app.py` 收敛为 FastAPI factory、lifespan、中间件、依赖装配和 router 注册；每类资源由 `api/routes/<feature>.py` 处理，输入/输出模型放在对应 `schemas` 文件。路由只做协议层校验、调用用例、转换 HTTP 错误，不直接操作 ORM、Repository 或 Manager 私有字段。
- 将 `cli/main.py` 收敛为命令解析、命令注册与进程启动；命令实现迁到 `cli/commands/<feature>.py`。CLI 和 Web/API 共享 `application` 服务，不能分别复制业务规则。
- `RuntimeHost` 是常驻进程的 composition root：集中创建和注入 Chat、Channel、MCP、Skills、Provider 等对象并管理生命周期。业务模块不反向导入 `RuntimeHost` 或读取其全局实例。
- `core` 不直接依赖 SQLAlchemy、具体 Repository、KeyStore、FastAPI、CLI、`channels` 或 `integrations`。持久化和外部能力需要由 application 通过构造参数/小型 Protocol 注入；不需要外部能力的核心算法保持纯函数或纯对象。
- `application` 负责事务边界和用例编排，可依赖 core 与稳定的 Repository/能力接口；具体 SQLAlchemy Repository、HTTP/MCP/OneBot 实现由外层装配提供。逐步移除服务中隐式创建全局 Session、默认 Manager 和全局 Registry 的路径。
- 不以文件行数机械拆分。只有当一组路由/命令/用例具有独立职责、生命周期或测试边界时才拆模块；拆分前后保持对外 API、CLI 参数和数据格式兼容。

## 8. 安全、兼容与部署

1. FastAPI 的本机回环访问限制、Host/Origin 校验和不开放远程管理要求保持不变。
2. 不把 Secret 写入 React 状态持久化、URL、日志、错误追踪或浏览器存储；短暂 React state 在提交后清空。
3. React 对外部 MCP 描述、Resource、Prompt 和 Skill 文本默认按文本渲染，不使用不安全 HTML 注入。
4. 不改数据库 Schema、不改 Provider/MCP/Skills 配置文件格式、不改变 CLI 使用方式；模块迁移保持旧命令和 API 路径可用。
5. `uv run zhiyu serve` 仍能直接启动生产 UI；打包发布时只需包含已构建的静态文件，不要求用户安装 Node。
6. 开发命令可运行 Vite 与 FastAPI 两个本地进程；文档需写明 API proxy、构建、测试及静态资源打包步骤。

## 9. 分阶段实施

### 阶段 A：稳定架构边界与保护现状

- 固化当前行为基线：Python 全量测试、关键 Web API 合约、CLI `--help`/命令测试、数据库迁移启动测试。
- 将 FastAPI 路由按 Provider、MCP、Skills、渠道、记忆、对话等资源拆出，`api/app.py` 保留装配和生命周期逻辑。
- 将 CLI 命令实现按领域拆分，`cli/main.py` 保留解析和注册；所有业务逻辑仍调用现有 application 服务。
- 增加轻量依赖边界检查，逐步禁止 `core` 新增对 ORM、Repository 和 adapter 的反向依赖；本阶段不要求一次性清除所有既有反向依赖。

### 阶段 B：应用层依赖收敛

- 确认 `RuntimeHost` 是唯一运行时装配入口，统一创建同一组 services/managers/registries。
- 优先选一条垂直链路（建议 Provider 配置或 Memory 读取/写入）演练“核心规则—application 用例—Repository 接口—infrastructure 实现”的边界。
- 对核心模块逐块迁出直接数据库查询、全局配置和集成实例；保留现有数据库模型及数据，仅调整依赖传递方式。
- 每次只迁一块并保留行为测试；未证明能降低耦合的抽象不扩散到其他模块。

### 阶段 C：React 工程骨架与共享交互

- 增加 Vite、React、TypeScript、Tailwind 和与 NapCat 对照的 UI 组件库依赖及锁文件。
- 配置开发代理至 FastAPI `/api`，配置生产输出目录和 Python 包静态资源路径。
- 建立 React 根组件、路由、侧栏布局、主题 token、API Client、SSE 生命周期和全局 Toast。
- 实现 `AppDialog`、FormField、SecretField、SwitchCard、ConfirmDialog 和 LoadingButton。
- 验证 `uv run zhiyu serve` 能正确提供构建产物，且现有 API/CLI 行为不受影响。

### 阶段 D：逐页迁移 WebUI

- 优先迁移 Provider/模型与 MCP，再迁移 Skills、QQ 渠道、运行诊断、记忆编辑、聊天和总览。
- 页面源码按 `features/<feature>` 拆分，共享状态与 API 放在 `app`/`lib`，不继续产生新的巨型入口文件。
- 各页面接入成功/失败反馈、空态、加载态、未保存确认、键盘与焦点行为。
- 对照 API 清单完成交互冒烟和安全检查。
- 确认无页面依赖旧 `app.js` 后删除旧事件处理代码和不再使用的 CSS。
- 整理 `docs/README.md` 作为唯一设计文档索引，标记方案状态、实施记录和当前有效基线；修正失效链接，不自动删除旧文档。
- 更新开发与打包文档；执行 Python 测试、前端类型检查、构建、wheel 静态资源检查和主要路径冒烟。

每阶段均可运行和回滚；只有阶段 D 验收通过后才移除旧前端文件。React 构建失败时保留上一份可运行静态产物。后端结构迁移不执行数据库操作，因此回滚不涉及数据恢复。

## 10. 验收标准

### 视觉与交互

- 页面使用 React 组件渲染，路由切换不依赖手工隐藏/显示所有视图节点。
- 弹窗视觉符合知语主题并借鉴 NapCat：统一遮罩、面板、表单分组、关闭、取消、主操作和提交状态。
- 全前端不再调用 `window.prompt`、`window.confirm` 或 `window.alert`。
- Provider、MCP、Skills 的核心管理操作不要求用户手写 JSON；权限通过可读列表勾选。
- 表单具备标签、必填状态、校验错误、提交状态、键盘操作和未保存离开保护。

### 业务与安全

- Provider、模型、MCP、Skills 原有能力保持，React 化不导致 API 或持久化行为回归。
- API Key、MCP Secret、QQ Token 从不回显，浏览器存储及日志不包含密钥。
- MCP/Skill 外部文本安全显示；删除、覆盖更新、未知状态重试均显示明确风险和确认。
- 空列表和加载失败可区分，管理入口在滚动页面的空状态中仍然可见。

### 后端架构

- `api/app.py` 和 `cli/main.py` 主要承担启动、装配和注册，不再集中承载各领域操作实现。
- Provider/MCP/Skills/Channels/Memory API 依资源拆分；各 API 的请求/响应合约与当前客户端兼容。
- Web 与 CLI 复用同一 application 用例，不存在两套业务规则。
- `RuntimeHost` 负责运行时依赖装配；Application 服务的依赖显式可注入，核心代码不构造全局数据库 Session 或 Manager。
- `core` 不新增对 `infrastructure`、数据库 Repository、CLI/API 或 `integrations/channels` 实现的反向依赖；已有反向依赖按垂直切片逐步清除。
- 无 schema 迁移、无数据搬迁，旧用户数据库、配置、CLI 命令和 `/api` 请求保持兼容。

### 工程与发布

- 前端 lint/typecheck/build 全通过，构建目录包含于 Python wheel/应用发行包。
- `uv run zhiyu serve` 单命令可从打包静态目录启动完整 UI。
- Python 全量测试、前端组件/页面测试、主要用户路径冒烟均通过。
- 旧版运行实例和已存在配置无需迁移即可启动新版。
- 架构依赖检查覆盖 `core` import 方向；API 路由和 CLI 命令拆分有对应的合约/回归测试。

## 11. 非目标与风险

- 不把 NapCat 页面直接复制到知语，不复用其 Logo、角色图片或未授权静态资源。
- 不因采用 React 而迁移 FastAPI 或重写运行时、应用服务和数据库。
- 不把项目拆为微服务，不为每个文件创建接口/Protocol，不以统一目录改名代替真实依赖解耦。
- 不做完整插件市场、移动端重构、多用户权限、OAuth 或 Web 远程管理。
- 前端构建增加维护步骤；若构建产物未打包，Python 服务会出现 UI 缺失。因此静态资源的 wheel 安装测试属于发布阻断项。

## 12. 交付范围

实施完成后，知语仍是一个易于本地安装和运行的模块化单体：FastAPI/CLI 作为薄入口共享 Application 用例，Core 与具体数据库/渠道/集成实现隔离；WebUI 使用 React 组件化界面并由 FastAPI 托管。前端工程栈会变化，后端 API、CLI 使用方式和用户数据不迁移。

## 实施记录

- 2026-10-06：将 Provider、MCP、Skills、QQ/渠道事件、对话/运行记录、记忆 API 拆入 `api/routes/`，对应请求模型拆入 `api/schemas/`；`create_app` 负责服务装配和路由注册。URL、请求/响应结构及管理端安全中间件保持不变。
- 当前 `api/app.py` 从 685 行收敛至 86 行，保留 FastAPI 生命周期、本机管理安全策略、路由注册、健康检查和静态资源托管。
- 将 Provider CLI 命令首个切片迁入 `cli/commands/providers.py`，CLI 参数及命令行为保持不变；纯提示词组装模块 `core/characters/prompts.py` 不再导入 ORM 模型。
- 建立 `web/` 的 React 19、Vite、TypeScript、Tailwind CSS v4 与 HeroUI v3 构建；统一站内 Modal/Toast Host 已接管管理交互，Provider 与 MCP 新增使用分组 React 表单，其他输入、确认和提示使用同一套站内弹窗。Provider/MCP 的旧 HTML `<dialog>` 已移除，避免双实现。现有业务页面主体仍保留在旧静态入口，按渐进迁移继续推进。
- Vite 产物位于 `src/zhiyu/web/static/react/`，经 Python wheel 检查确认会随应用包携带；用户启动 WebUI 不需要 Node。
- 本轮验证：`uv run pytest -q`（218 passed）、`uv run zhiyu --help`、`git diff --check`。
- 尚未完成：其余 CLI 命令拆分、聊天/运行记录路由仍直接访问 Repository 的依赖治理、Application/Core 依赖收敛及 React 业务页面迁移。旧页面主体仍由 FastAPI 静态托管。
