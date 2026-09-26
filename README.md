# Desktop AI Companion

运行在电脑上的 Personal AI Agent，通过桌面端与 QQ 等聊天渠道与用户交互。

## 结构

```text
apps/
  desktop/   Electron + React + TypeScript + Vite + Tailwind + Zustand
  server/    Python FastAPI + LangGraph (Agent Runtime)
packages/    shared-types / ui（后续）
skills/      Skill 定义（SKILL.md）
data/        本地数据（SQLite）
docs/        文档
scripts/     脚本
```

## 运行

### 后端

```bash
cd apps/server
uv sync          # 创建 .venv 并安装依赖（Python 3.12）
uv run main.py   # 启动，默认 http://127.0.0.1:8001
```

### 桌面端

```bash
cd apps/desktop
npm install
npm run dev      # 启动 Electron，并自动拉起 Python 后端
```

## 开发阶段

当前进度：Phase 1-5 已完成；Phase 7 Agent 骨架（LangGraph 图 + Tool Calling + Agent Run 面板）与 Phase 6 Character 系统（角色 CRUD + 会话选角色 + system 提示词注入）已完成。

详见 `设计文档v1.md`。
