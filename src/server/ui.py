"""
REST API endpoints for the Web UI.
Mounted into the main Starlette app by serve.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from src.core.config import DEFAULT_TOP_K, SYNTHESIS_BACKEND, USE_RERANKING
from src.core.reranker import Reranker
from src.server.synthesis import LLMSynthesizer, _sse

_STATIC_DIR = Path(__file__).parent / "static"


def _engine(request: Request):
    return request.app.state.engine


# ── Page ──────────────────────────────────────────────────────────────────


async def handle_ui(request: Request) -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "index.html"))


# ── API ───────────────────────────────────────────────────────────────────


async def handle_stats(request: Request) -> JSONResponse:
    engine = _engine(request)
    engine._ensure_initialized()
    return JSONResponse({
        "kb_text": engine._text_collection.count(),
        "kb_code": engine._code_collection.count(),
        "total": engine._text_collection.count() + engine._code_collection.count(),
    })


async def handle_documents(request: Request) -> JSONResponse:
    engine = _engine(request)
    docs = engine.list_documents()
    return JSONResponse(docs)


async def handle_search(request: Request) -> JSONResponse:
    engine = _engine(request)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    mode = body.get("mode", "all")
    top_k = min(int(body.get("top_k", DEFAULT_TOP_K)), 20)

    if mode == "code":
        results = engine.search_code(query, top_k=top_k)
    elif mode == "docs":
        results = engine.search_docs(query, top_k=top_k)
    else:
        results = engine.search(query, top_k=top_k)

    return JSONResponse(results)


async def handle_search_exact(request: Request) -> JSONResponse:
    engine = _engine(request)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    top_k = min(int(body.get("top_k", 10)), 20)

    # Symbol search (indexed content)
    symbol_hits = engine.search_symbol(query, top_k=top_k)

    # Grep search (disk files) — limit to avoid overload
    grep_result = engine.grep_code(pattern=query, max_results=20)
    grep_hits = [
        {
            "doc_name": h["file"].replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0],
            "file_type": h["file"].rsplit(".", 1)[-1] if "." in h["file"] else "",
            "source_path": h["file"],
            "chunk_index": 0,
            "total_chunks": 1,
            "score": 1.0,
            "collection": "grep",
            "content": f"Line {h['line']}: {h['text']}",
        }
        for h in grep_result.get("matches", [])
    ]

    # Merge: symbol hits first, then unique grep hits
    seen = {f"{h['doc_name']}:{h.get('chunk_index',0)}" for h in symbol_hits}
    merged = symbol_hits[:]
    for h in grep_hits:
        key = f"{h['doc_name']}:{h.get('chunk_index',0)}"
        if key not in seen:
            merged.append(h)
            seen.add(key)

    return JSONResponse(merged[:top_k])


async def handle_get_file(request: Request) -> JSONResponse:
    engine = _engine(request)
    doc_name = request.path_params["doc_name"]
    chunks = engine.get_file(doc_name)
    return JSONResponse(chunks)


async def handle_answer(request: Request):
    """POST /api/answer — retrieve + rerank + LLM streaming answer (SSE)."""
    engine = _engine(request)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    use_rerank = body.get("rerank", USE_RERANKING)
    history = body.get("history") or []
    max_tokens = body.get("max_tokens")  # 客户端可选；服务端会封顶到 LLM_MAX_TOKENS

    async def event_stream():
        reranker = Reranker() if use_rerank else None
        # CrossEncoder load + inference is CPU-bound/blocking — run in thread pool
        loop = asyncio.get_event_loop()
        docs = await loop.run_in_executor(
            None, lambda: engine.search_with_rerank(query, reranker=reranker)
        )
        yield _sse("results", data=docs)

        if not SYNTHESIS_BACKEND:
            yield _sse("error", message="SYNTHESIS_BACKEND not configured")
            return

        synthesizer = LLMSynthesizer()
        async for chunk in synthesizer.stream(query, docs, history=history, max_tokens=max_tokens):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Route list (imported by serve.py) ─────────────────────────────────────

UI_ROUTES: list[Route] = [
    Route("/ui", endpoint=handle_ui, methods=["GET"]),
    Route("/api/stats", endpoint=handle_stats, methods=["GET"]),
    Route("/api/documents", endpoint=handle_documents, methods=["GET"]),
    Route("/api/search", endpoint=handle_search, methods=["POST"]),
    Route("/api/search/exact", endpoint=handle_search_exact, methods=["POST"]),
    Route("/api/answer", endpoint=handle_answer, methods=["POST"]),
    Route("/api/file/{doc_name:path}", endpoint=handle_get_file, methods=["GET"]),
]
