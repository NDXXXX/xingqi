# 星栖 Web 前端

前端源码位于 `web/src`，使用 React、TypeScript、Vite 与 HeroUI 构建到 Python 包内的 `src/zhiyu/web/static/react`。FastAPI 继续托管页面和 `/api`；React 应用负责全站 Shell、八个页面、状态展示和交互，React overlay 提供统一的站内弹窗和 Toast。用户运行 WebUI 不需要安装 Node.js。

```sh
npm --prefix web install
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
```

构建后的静态文件随 Python wheel 一起发布。CI 会执行前端依赖安装、类型检查、状态选择器测试和生产构建，并验证 FastAPI 能提供 React 入口资源。用户运行 `uv run zhiyu serve` 不需要安装 Node.js。
