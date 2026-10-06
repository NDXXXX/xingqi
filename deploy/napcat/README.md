# NapCat Docker

此配置用于知语当前支持的 macOS + Docker Desktop 测试环境。镜像固定为已经完成真实收发验证的 digest，不会自动升级。

1. 复制 `.env.example` 为 `.env`，把 `ZHIYU_NAPCAT_DATA_DIR` 改成自己的绝对路径；不要使用 `~`。
2. 载入配置并创建数据目录：`set -a; source .env; set +a; mkdir -p "$ZHIYU_NAPCAT_DATA_DIR/config" "$ZHIYU_NAPCAT_DATA_DIR/qq"`。
3. 启动：`docker compose --env-file .env up -d`。
4. 打开 <http://127.0.0.1:6099>，扫码登录 QQ。
5. 在 NapCat 中启用 OneBot 11 WebSocket 客户端，URL 填 `ws://host.docker.internal:6199/ws`，Access Token 与知语配置保持一致。
6. 配置知语监听：`zhiyu qq configure --endpoint ws://0.0.0.0:6199/ws --owner-user-id <主人QQ号>`，交互输入同一 Token。
7. 运行 `zhiyu serve`；不需要另开 `zhiyu qq listen`。
8. 检查：`zhiyu qq doctor`。

`0.0.0.0:6199` 仅用于让 Docker Desktop 访问宿主机。必须配置高强度 Token，并通过 macOS 防火墙限制外部设备访问。WebUI 端口只映射到 `127.0.0.1`。

升级镜像时先在测试账号验证登录、私聊、群策略、图片和发送回执，再替换 digest。不要直接改回 `latest`。
