# 知语 Web 前端

前端源码位于 `web/src`，使用 Vite 构建到 Python 包内的 `src/zhiyu/web/static/react`。FastAPI 继续托管现有页面与 `/api`；React overlay 为原生浏览器提示框提供统一的站内弹窗和 Toast。

```sh
npm --prefix web install
npm --prefix web run typecheck
npm --prefix web run build
```

构建后的静态文件随 Python wheel 一起发布；用户运行 `uv run zhiyu serve` 不需要安装 Node.js。
