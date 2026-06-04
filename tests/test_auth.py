"""
Unit tests for src/server/auth.py — the multi-key / role-based ASGI auth
middleware.

Pure ASGI tests: the middleware is driven directly with hand-built scope /
receive / send, so no HTTP client (httpx) or pytest-asyncio is required —
each async path is run with asyncio.run().
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.server.auth import (
    ROLE_ADMIN,
    ROLE_READONLY,
    AuthMiddleware,
    extract_api_key,
    is_protected,
    is_tool_allowed,
    requires_admin,
    resolve_role,
)

ADMIN_KEY = "admin-key-AAA"
ADMIN_KEY2 = "admin-key-AAA2"
READONLY_KEY = "readonly-key-BBB"
READONLY_KEY2 = "readonly-key-BBB2"


# ── Test doubles ────────────────────────────────────────────────────────────

class DummyApp:
    """Downstream ASGI app: records reach + the role left in scope, replies 200."""

    def __init__(self):
        self.called = False
        self.seen_role = "<unset>"

    async def __call__(self, scope, receive, send):
        self.called = True
        self.seen_role = scope.get("auth_role", "<unset>")
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def http_scope(path, headers=None, query_string=b""):
    return {
        "type": "http",
        "path": path,
        "headers": headers or [],
        "query_string": query_string,
    }


def key_header(key):
    return [(b"x-api-key", key.encode())]


def drive(middleware, scope):
    """Run one request through the middleware; return (status, downstream_app)."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))

    status = next(
        (m["status"] for m in sent if m["type"] == "http.response.start"), None
    )
    return status, sent


def mw(admin_keys=(ADMIN_KEY,), readonly_keys=(READONLY_KEY,)):
    return AuthMiddleware(DummyApp(), admin_keys=admin_keys, readonly_keys=readonly_keys)


# ── is_protected / requires_admin ─────────────────────────────────────────────

class TestPathClassification:
    @pytest.mark.parametrize("path", [
        "/sse", "/messages/", "/messages/abc", "/api/stats", "/api/answer",
        "/api/file/foo.c", "/shutdown",
    ])
    def test_protected_paths(self, path):
        assert is_protected(path) is True

    @pytest.mark.parametrize("path", [
        "/health", "/ui", "/assets/index.js", "/static/favicon.ico",
    ])
    def test_public_paths(self, path):
        assert is_protected(path) is False

    def test_unknown_path_is_not_protected(self):
        assert is_protected("/") is False
        assert is_protected("/favicon.ico") is False

    def test_requires_admin(self):
        assert requires_admin("/shutdown") is True
        assert requires_admin("/api/stats") is False
        assert requires_admin("/sse") is False


# ── extract_api_key ───────────────────────────────────────────────────────────

class TestExtractApiKey:
    def test_from_header(self):
        scope = http_scope("/api/stats", headers=[(b"x-api-key", b"hello")])
        assert extract_api_key(scope) == "hello"

    def test_from_query_param(self):
        scope = http_scope("/sse", query_string=b"api_key=fromquery&foo=bar")
        assert extract_api_key(scope) == "fromquery"

    def test_header_takes_precedence_over_query(self):
        scope = http_scope(
            "/api/stats",
            headers=[(b"x-api-key", b"fromheader")],
            query_string=b"api_key=fromquery",
        )
        assert extract_api_key(scope) == "fromheader"

    def test_missing_returns_none(self):
        assert extract_api_key(http_scope("/api/stats")) is None


# ── resolve_role ───────────────────────────────────────────────────────────────

class TestResolveRole:
    def test_admin_key(self):
        assert resolve_role(ADMIN_KEY, [ADMIN_KEY], [READONLY_KEY]) == ROLE_ADMIN

    def test_readonly_key(self):
        assert resolve_role(READONLY_KEY, [ADMIN_KEY], [READONLY_KEY]) == ROLE_READONLY

    def test_unknown_key(self):
        assert resolve_role("nope", [ADMIN_KEY], [READONLY_KEY]) is None

    def test_none_provided(self):
        assert resolve_role(None, [ADMIN_KEY], [READONLY_KEY]) is None

    def test_admin_takes_precedence_when_keys_equal(self):
        assert resolve_role("same", ["same"], ["same"]) == ROLE_ADMIN

    def test_empty_server_keys_never_match(self):
        # fail closed：服务端未配置密钥时，任何输入（含空串）都不匹配
        assert resolve_role("", [], []) is None
        assert resolve_role("anything", [], []) is None
        assert resolve_role("anything", [""], [""]) is None  # 空 key 被跳过

    # ── 每个角色支持多把 key ───────────────────────────────────────────────
    def test_any_admin_key_matches(self):
        keys = [ADMIN_KEY, ADMIN_KEY2]
        assert resolve_role(ADMIN_KEY, keys, []) == ROLE_ADMIN
        assert resolve_role(ADMIN_KEY2, keys, []) == ROLE_ADMIN

    def test_any_readonly_key_matches(self):
        ro = [READONLY_KEY, READONLY_KEY2]
        assert resolve_role(READONLY_KEY, [], ro) == ROLE_READONLY
        assert resolve_role(READONLY_KEY2, [], ro) == ROLE_READONLY

    def test_unknown_key_with_multiple_configured(self):
        assert resolve_role("nope", [ADMIN_KEY, ADMIN_KEY2],
                            [READONLY_KEY, READONLY_KEY2]) is None


# ── is_tool_allowed ─────────────────────────────────────────────────────────────

class TestIsToolAllowed:
    @pytest.mark.parametrize("tool", [
        "search_knowledge_base", "ingest_document", "delete_document",
        "grep_code", "list_documents", "list_code_files",
    ])
    def test_admin_allowed_everything(self, tool):
        assert is_tool_allowed(ROLE_ADMIN, tool) is True

    @pytest.mark.parametrize("tool", [
        # 语义搜索（3）
        "search_knowledge_base", "search_code", "search_docs",
        # 精确检索 / 读取（6）
        "search_symbol", "grep_code", "get_file", "get_chunk_context",
        "list_documents", "list_code_files",
    ])
    def test_readonly_allowed_read_tools(self, tool):
        assert is_tool_allowed(ROLE_READONLY, tool) is True

    @pytest.mark.parametrize("tool", [
        "ingest_document", "ingest_directory", "delete_document",
    ])
    def test_readonly_denied_write_tools(self, tool):
        assert is_tool_allowed(ROLE_READONLY, tool) is False

    def test_readonly_denied_unknown_tool(self):
        # deny-by-default：未知/未来新增工具对 readonly 一律拒绝
        assert is_tool_allowed(ROLE_READONLY, "some_new_dangerous_tool") is False

    def test_none_role_denied(self):
        assert is_tool_allowed(None, "list_documents") is False

    def test_read_and_write_sets_are_disjoint(self):
        from src.server.auth import ADMIN_ONLY_TOOLS, READONLY_TOOLS
        assert READONLY_TOOLS.isdisjoint(ADMIN_ONLY_TOOLS)
        assert len(READONLY_TOOLS) == 9  # 3 语义搜索 + 6 精确检索/读取


# ── AuthMiddleware ─────────────────────────────────────────────────────────────

class TestAuthMiddleware:
    def test_protected_without_key_returns_401(self):
        m = mw()
        status, _ = drive(m, http_scope("/api/stats"))
        assert status == 401
        assert m.app.called is False

    def test_protected_with_wrong_key_returns_401(self):
        m = mw()
        status, _ = drive(m, http_scope("/api/stats", headers=key_header("wrong")))
        assert status == 401
        assert m.app.called is False

    def test_admin_key_on_rest_passes_with_role(self):
        m = mw()
        status, _ = drive(m, http_scope("/api/stats", headers=key_header(ADMIN_KEY)))
        assert status == 200
        assert m.app.called is True
        assert m.app.seen_role == ROLE_ADMIN

    def test_readonly_key_on_rest_passes_with_role(self):
        m = mw()
        status, _ = drive(m, http_scope("/api/stats", headers=key_header(READONLY_KEY)))
        assert status == 200
        assert m.app.seen_role == ROLE_READONLY

    def test_readonly_key_on_sse_passes(self):
        # readonly 可建立 SSE 连接（工具级门禁在 serve.py 完成）
        m = mw()
        status, _ = drive(m, http_scope("/sse", query_string=f"api_key={READONLY_KEY}".encode()))
        assert status == 200
        assert m.app.seen_role == ROLE_READONLY

    def test_shutdown_requires_admin_readonly_gets_403(self):
        m = mw()
        status, _ = drive(m, http_scope("/shutdown", headers=key_header(READONLY_KEY)))
        assert status == 403
        assert m.app.called is False

    def test_shutdown_allows_admin(self):
        m = mw()
        status, _ = drive(m, http_scope("/shutdown", headers=key_header(ADMIN_KEY)))
        assert status == 200
        assert m.app.called is True

    def test_public_path_passes_without_key(self):
        m = mw()
        status, _ = drive(m, http_scope("/health"))
        assert status == 200
        assert m.app.called is True

    def test_non_http_scope_passes_through(self):
        m = mw()
        _status, _ = drive(m, {"type": "lifespan"})
        assert m.app.called is True

    def test_no_keys_configured_fails_closed(self):
        m = AuthMiddleware(DummyApp(), admin_keys=(), readonly_keys=())
        status, _ = drive(m, http_scope("/api/stats", headers=key_header("")))
        assert status == 401
        assert m.app.called is False

    def test_second_admin_key_works(self):
        m = mw(admin_keys=(ADMIN_KEY, ADMIN_KEY2), readonly_keys=(READONLY_KEY,))
        status, _ = drive(m, http_scope("/api/stats", headers=key_header(ADMIN_KEY2)))
        assert status == 200
        assert m.app.seen_role == ROLE_ADMIN

    def test_second_readonly_key_works_and_is_gated_on_shutdown(self):
        m = mw(admin_keys=(ADMIN_KEY,), readonly_keys=(READONLY_KEY, READONLY_KEY2))
        status, _ = drive(m, http_scope("/shutdown", headers=key_header(READONLY_KEY2)))
        assert status == 403
        assert m.app.called is False
