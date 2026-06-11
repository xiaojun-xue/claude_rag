"""
Multi-provider LLM synthesis with streaming SSE output.

Supported backends (set SYNTHESIS_BACKEND env var):
  deepseek  — api.deepseek.com          (OpenAI-compat)
  qianwen   — dashscope.aliyuncs.com    (OpenAI-compat)
  ollama    — localhost:11434/v1         (OpenAI-compat)
  openai    — api.openai.com             (OpenAI)
  claude    — api.anthropic.com          (Anthropic SDK)
  custom    — LLM_BASE_URL               (OpenAI-compat)
"""

from __future__ import annotations

import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    SYNTHESIS_BACKEND,
)

logger = logging.getLogger(__name__)

# ── Provider registry ──────────────────────────────────────────────────────

PROVIDER_DEFAULTS: dict[str, dict] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "qianwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5:7b",
    },
    "openai": {
        "base_url": None,
        "model": "gpt-4o-mini",
    },
    "claude": {
        "base_url": None,
        "model": "claude-haiku-4-5-20251001",
    },
}

RAG_SYSTEM_PROMPT = (
    "你是专业的技术知识库助手。基于提供的上下文回答问题。\n"
    "规则：\n"
    "1. 只使用上下文中的信息，不编造\n"
    "2. 引用来源时使用 [文件名] 格式（禁止使用数字编号，如 [1]、[2]）\n"
    "3. 代码片段保留原始格式\n"
    "4. 信息不足时明确说明"
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _sse(type: str, **kwargs) -> str:  # noqa: A002
    return f"data: {json.dumps({'type': type, **kwargs}, ensure_ascii=False)}\n\n"


def _effective_max_tokens(max_tokens: int | None) -> int:
    """把客户端传入的 max_tokens 限制在 [1, LLM_MAX_TOKENS] 范围内。

    客户端不传（None）或非法值时回退到服务端默认上限 LLM_MAX_TOKENS。
    服务端上限始终是硬封顶：客户端无法借此申请超过配额的 token。
    """
    if max_tokens is None:
        return LLM_MAX_TOKENS
    try:
        requested = int(max_tokens)
    except (TypeError, ValueError):
        return LLM_MAX_TOKENS
    return max(1, min(requested, LLM_MAX_TOKENS))


def _build_context(docs: list[dict]) -> str:
    parts = []
    for d in docs:
        name = d.get("doc_name", "unknown")
        content = d.get("content", "").strip()
        parts.append(f"{content}\n\n[{name}]")
    return "\n\n".join(parts)


def _build_messages(history: list[dict] | None, user_content: str) -> list[dict]:
    """Merge prior conversation turns with the current user message.

    Enforces user/assistant alternation (required by Anthropic).
    Caps history at 6 messages (3 turns) to limit token usage.
    """
    msgs: list[dict] = []
    for m in (history or []):
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if msgs and msgs[-1]["role"] == role:
            continue  # skip consecutive same-role messages
        msgs.append({"role": role, "content": content})
    # Anthropic requires first message to be from user
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    msgs = msgs[-6:]  # keep at most 3 prior turns
    msgs.append({"role": "user", "content": user_content})
    return msgs


# ── Synthesizer ────────────────────────────────────────────────────────────

class LLMSynthesizer:
    """Unified multi-provider streaming synthesizer.

    OpenAI-compatible backends (deepseek/qianwen/ollama/openai/custom) use the
    openai SDK. Anthropic Claude uses the anthropic SDK.
    """

    def __init__(self, backend: str = "") -> None:
        self._backend = (backend or SYNTHESIS_BACKEND).lower()
        self._client = None

    def _ensure_client(self) -> None:
        if self._client is not None:
            return

        defaults = PROVIDER_DEFAULTS.get(self._backend, {})
        base_url = LLM_BASE_URL or defaults.get("base_url")
        api_key = LLM_API_KEY or "ollama"  # ollama doesn't require a real key

        if self._backend == "claude":
            try:
                import anthropic
            except ImportError as exc:
                raise RuntimeError(
                    "anthropic package not installed. Run: pip install anthropic"
                ) from exc
            kwargs: dict = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = anthropic.AsyncAnthropic(**kwargs)
        else:
            try:
                import openai
            except ImportError as exc:
                raise RuntimeError(
                    "openai package not installed. Run: pip install openai"
                ) from exc
            kwargs: dict = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            self._client = openai.AsyncOpenAI(**kwargs)

    def _resolve_model(self) -> str:
        if LLM_MODEL:
            return LLM_MODEL
        return PROVIDER_DEFAULTS.get(self._backend, {}).get("model", "")

    async def stream(
        self,
        query: str,
        docs: list[dict],
        history: list[dict] | None = None,
        max_tokens: int | None = None,
    ):
        """Async generator yielding SSE lines.

        Args:
            max_tokens: 客户端期望的输出 token 上限；服务端会封顶到 LLM_MAX_TOKENS。
                        None 时使用服务端默认值。

        Yields:
            str: SSE-formatted lines ("data: {...}\\n\\n")
        """
        if not self._backend:
            yield _sse("error", message="SYNTHESIS_BACKEND is not configured.")
            return

        try:
            self._ensure_client()
            model = self._resolve_model()
            effective_max_tokens = _effective_max_tokens(max_tokens)
            context = _build_context(docs)
            user_content = f"问题：{query}\n\n上下文：\n{context}"

            # Build message list: prior turns + current query
            messages = _build_messages(history, user_content)

            logger.info("LLM synthesis — backend=%s model=%s docs=%d history=%d max_tokens=%d",
                        self._backend, model, len(docs), len(messages) - 1, effective_max_tokens)

            if self._backend == "claude":
                async with self._client.messages.stream(
                    model=model,
                    max_tokens=effective_max_tokens,
                    system=RAG_SYSTEM_PROMPT,
                    messages=messages,
                ) as stream:
                    async for event in stream:
                        if (
                            hasattr(event, "type")
                            and event.type == "content_block_delta"
                            and hasattr(event, "delta")
                            and hasattr(event.delta, "text")
                        ):
                            yield _sse("delta", text=event.delta.text)
            else:
                # OpenAI-compatible: deepseek / qianwen / ollama / openai / custom
                response = await self._client.chat.completions.create(
                    model=model,
                    messages=[{"role": "system", "content": RAG_SYSTEM_PROMPT}] + messages,
                    max_tokens=effective_max_tokens,
                    stream=True,
                )
                async for chunk in response:
                    text = chunk.choices[0].delta.content or ""
                    if text:
                        yield _sse("delta", text=text)

            yield _sse("done", provider=self._backend, model=model)

        except Exception as exc:
            logger.exception("LLM synthesis error")
            yield _sse("error", message=str(exc))
