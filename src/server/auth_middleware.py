"""
可复用的 Bearer Token 鉴权中间件（方案一）。

把这个文件拷到你已有的 MCP 服务器项目里，按 INTEGRATE_SCHEME_A.md 的说明，
用一行代码把它套在你的 ASGI app 外层即可。适用于任何基于 ASGI 的 MCP 服务器
（mcp SDK 的 FastMCP、fastmcp、或自建 Starlette/uvicorn）。

token 从环境变量 MCP_TOKEN 读取，绝不写死在代码里。
"""

import os
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BearerTokenMiddleware:
    """对所有 HTTP 请求校验 `Authorization: Bearer <token>`，不匹配返回 401。"""

    def __init__(self, app: ASGIApp, token: str | None = None) -> None:
        self.app = app
        self.token = token or os.environ.get("MCP_TOKEN")
        if not self.token:
            raise RuntimeError(
                "未提供 token：请设置环境变量 MCP_TOKEN，或在构造时传入 token=..."
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # 非 HTTP 流量（如 lifespan、websocket 握手前）直接放行
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        auth = Request(scope).headers.get("authorization", "")
        expected = f"Bearer {self.token}"

        # 常量时间比较，避免通过响应时间侧信道猜测 token
        if not (auth and secrets.compare_digest(auth, expected)):
            response = JSONResponse(
                {"error": "unauthorized", "detail": "missing or invalid bearer token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
