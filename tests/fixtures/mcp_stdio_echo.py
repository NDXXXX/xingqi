import asyncio
import sys

from mcp.server.mcpserver import MCPServer


server = MCPServer("zhiyu-test-echo", version="1")


@server.tool()
def echo(text: str) -> str:
    return text


@server.resource("test://data", name="test-data")
def data() -> str:
    return "resource smoke"


@server.prompt()
def greet(name: str) -> str:
    return f"Hello, {name}!"


if len(sys.argv) > 1 and sys.argv[1] == "http":
    asyncio.run(server.run_streamable_http_async(
        host="127.0.0.1", port=int(sys.argv[2]), json_response=True, stateless_http=True
    ))
elif len(sys.argv) > 1 and sys.argv[1] == "sse":
    asyncio.run(server.run_sse_async(host="127.0.0.1", port=int(sys.argv[2])))
else:
    asyncio.run(server.run_stdio_async())
