"""
Unit tests for client-controllable LLM max_tokens clamping.

Covers src/server/synthesis.py::_effective_max_tokens, which enforces the
server-side cap LLM_MAX_TOKENS. Importing synthesis only pulls in config
(no openai/anthropic/torch), so these tests need no model weights.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.core.config import LLM_MAX_TOKENS
from src.server.synthesis import _effective_max_tokens


class TestEffectiveMaxTokens:
    def test_none_uses_server_default(self):
        assert _effective_max_tokens(None) == LLM_MAX_TOKENS

    def test_in_range_value_passes_through(self):
        # 100 应在 [1, LLM_MAX_TOKENS] 内（默认上限 1024）
        assert _effective_max_tokens(100) == min(100, LLM_MAX_TOKENS)

    def test_oversized_value_is_capped(self):
        assert _effective_max_tokens(99999) == LLM_MAX_TOKENS

    def test_value_equal_to_cap(self):
        assert _effective_max_tokens(LLM_MAX_TOKENS) == LLM_MAX_TOKENS

    def test_zero_is_clamped_to_one(self):
        assert _effective_max_tokens(0) == 1

    def test_negative_is_clamped_to_one(self):
        assert _effective_max_tokens(-50) == 1

    def test_numeric_string_is_coerced(self):
        assert _effective_max_tokens("100") == min(100, LLM_MAX_TOKENS)

    def test_invalid_string_falls_back_to_default(self):
        assert _effective_max_tokens("not-a-number") == LLM_MAX_TOKENS

    def test_cap_is_positive(self):
        # 服务端默认上限本身必须是正数，否则封顶逻辑无意义
        assert LLM_MAX_TOKENS >= 1
