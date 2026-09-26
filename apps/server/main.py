"""Agent Runtime 服务入口。"""

import os

import uvicorn

HOST = os.getenv("SERVER_HOST", "127.0.0.1")
PORT = int(os.getenv("SERVER_PORT", "8001"))


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        log_level=os.getenv("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
