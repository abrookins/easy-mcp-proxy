"""Tests for safe output handling helpers."""

import json
import logging
from unittest.mock import MagicMock, patch

from mcp_proxy.models import OutputCacheConfig
from mcp_proxy.output_handling import (
    _truncate_line,
    build_bounded_cached_output_payload,
    build_bounded_line_window_payload,
    build_char_window_payload,
    effective_max_inline_chars,
    estimate_tokens,
    measure_text,
    protect_tool_output,
    serialize_query_result,
    serialize_visible_result,
    truncation_reasons,
)


def _assert_cached_result(result):
    assert result.structured_content is not None
    structured = result.structured_content
    assert structured["cached"] is True
    assert structured["cache_id"] == structured["token"]
    assert structured["truncated"] is True
    assert len(result.content) == 3
    assert result.content[0].type == "text"
    assert result.content[1].type == "resource_link"
    assert result.content[2].type == "resource_link"
    return structured


class TestOutputMeasurement:
    """Tests for output measurement and serialization."""

    def test_estimate_tokens_uses_configured_ratio(self):
        """Token estimation should use the configured chars/token ratio."""
        config = OutputCacheConfig(token_chars_ratio=5)

        assert estimate_tokens("x" * 11, config) == 3

    def test_estimate_tokens_returns_zero_for_empty_text(self):
        """Empty text should estimate to zero tokens."""
        assert estimate_tokens("", OutputCacheConfig()) == 0

    def test_effective_max_inline_chars_uses_preview_alias(self):
        """preview_chars should cap max_inline_chars for compatibility."""
        config = OutputCacheConfig(max_inline_chars=5000, preview_chars=100)

        assert effective_max_inline_chars(config) == 100

    def test_effective_max_inline_chars_applies_strict_ceiling(self):
        """Strict mode should cap very large configured inline limits."""
        config = OutputCacheConfig(
            max_inline_tokens=100000,
            max_inline_chars=500000,
            strict=True,
        )

        assert effective_max_inline_chars(config) == 16000

    def test_effective_max_inline_chars_can_disable_strict_ceiling(self):
        """Non-strict mode should allow configured inline limits."""
        config = OutputCacheConfig(
            max_inline_tokens=100000,
            max_inline_chars=500000,
            strict=False,
        )

        assert effective_max_inline_chars(config) == 500000

    def test_measure_text_records_sizes_and_longest_line(self):
        """Measurements should include bytes, chars, tokens, lines, and line size."""
        config = OutputCacheConfig(token_chars_ratio=4)

        result = measure_text("abc\nlonger", config)

        assert result["bytes"] == len("abc\nlonger".encode())
        assert result["chars"] == len("abc\nlonger")
        assert result["estimated_tokens"] == 3
        assert result["lines"] == 2
        assert result["longest_line_chars"] == 6

    def test_serialize_visible_result_extracts_text_content(self):
        """ToolResult-like content should serialize only visible text content."""
        text_content = MagicMock()
        text_content.text = "hello"
        image_content = MagicMock(spec=["type"])
        result = MagicMock()
        result.content = [text_content, image_content]

        assert serialize_visible_result(result) == "hello"

    def test_serialize_visible_result_falls_back_for_non_text_content(self):
        """ToolResult-like content without text should use normal serialization."""
        item = MagicMock(spec=["type"])
        result = MagicMock()
        result.content = [item]

        assert serialize_visible_result(result)

    def test_serialize_visible_result_uses_json_for_dicts(self):
        """Plain structured results should serialize as JSON."""
        assert serialize_visible_result({"a": 1}) == '{"a": 1}'


class TestProtectionDecision:
    """Tests for deciding when output must be protected."""

    def test_truncation_reasons_detects_all_limits(self):
        """Oversized outputs should report each triggered truncation reason."""
        config = OutputCacheConfig(
            max_inline_tokens=1,
            max_inline_chars=3,
            max_line_chars=2,
            min_size=1,
        )
        measurement = measure_text("abcde", config)

        assert truncation_reasons(measurement, config) == [
            "estimated_tokens",
            "max_inline_chars",
            "max_line_chars",
            "min_size",
        ]

    def test_protect_tool_output_passes_through_small_result(self, caplog):
        """Small outputs should remain unchanged while measurements are logged."""
        config = OutputCacheConfig()
        result = {"status": "ok"}

        with caplog.at_level(logging.INFO, logger="mcp_proxy.output_handling"):
            protected = protect_tool_output(
                result,
                view_name="view",
                server_name="server",
                tool_name="tool",
                config=config,
                cache_secret="secret",
                cache_base_url="http://localhost:8000",
            )

        assert protected is result
        event = caplog.records[0].output_handling
        assert event["tool_name"] == "tool"
        assert event["truncated"] is False
        assert event["cache_id"] is None

    def test_protect_tool_output_caches_large_result(self, tmp_path):
        """Oversized outputs should return a cached ToolResult envelope."""
        config = OutputCacheConfig(max_inline_chars=20, max_inline_tokens=100)

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            result = protect_tool_output(
                "x" * 100,
                view_name="view",
                server_name="server",
                tool_name="tool",
                config=config,
                cache_secret="secret",
                cache_base_url="http://localhost:8000",
            )

        structured = _assert_cached_result(result)
        assert structured["original"]["chars"] == 100
        assert structured["returned"]["chars"] <= 20
        assert "max_inline_chars" in structured["truncation_reasons"]
        assert (tmp_path / f"{structured['token']}.txt").read_text() == "x" * 100

    def test_protect_tool_output_caches_giant_single_line(self, tmp_path):
        """A giant line should be cached even when total token budget is high."""
        config = OutputCacheConfig(
            max_inline_chars=1000,
            max_inline_tokens=1000,
            max_line_chars=40,
        )

        with patch("mcp_proxy.cache.CACHE_DIR", tmp_path):
            from mcp_proxy import cache

            cache.CACHE_DIR = tmp_path
            result = protect_tool_output(
                "a" * 200,
                view_name="view",
                server_name="server",
                tool_name="tool",
                config=config,
                cache_secret="secret",
                cache_base_url="http://localhost:8000",
            )

        structured = _assert_cached_result(result)
        assert "max_line_chars" in structured["truncation_reasons"]
        assert structured["returned"]["longest_line_chars"] <= 40
        assert structured["navigation"]["next_char_offset"] == 40

    def test_protect_tool_output_respects_disabled_config(self):
        """Disabled configs should return the result unchanged."""
        result = "x" * 100

        protected = protect_tool_output(
            result,
            view_name=None,
            server_name="server",
            tool_name="tool",
            config=OutputCacheConfig(enabled=False, max_inline_chars=1),
            cache_secret="secret",
            cache_base_url="http://localhost:8000",
        )

        assert protected is result


class TestBoundedRetrievalPayloads:
    """Tests for bounded cache retrieval payloads."""

    def test_line_window_caps_line_count_and_line_length(self):
        """Line windows should enforce max line count and max line chars."""
        config = OutputCacheConfig(
            max_line_chars=10,
            retrieval_max_line_count=1,
            retrieval_max_chars=100,
        )

        payload = build_bounded_line_window_payload(
            "a" * 50 + "\nsecond",
            config,
            line_count=5,
        )

        assert payload["line_count"] == 1
        assert payload["line_count_capped"] is True
        assert payload["returned_lines"] == 1
        assert payload["returned"]["longest_line_chars"] == 10
        assert payload["truncated_lines"][0]["next_char_offset"] == 10

    def test_line_window_rejects_negative_offsets(self):
        """Negative line offsets should be rejected."""
        payload = build_bounded_cached_output_payload("a\nb", line_offset=-1)

        assert payload == {"error": "line_offset must be >= 0"}

    def test_line_window_rejects_negative_line_count_directly(self):
        """Direct line-window calls should reject negative line counts."""
        try:
            build_bounded_line_window_payload("a\nb", line_count=-1)
        except ValueError as exc:
            assert str(exc) == "line_count must be >= 0"
        else:  # pragma: no cover
            raise AssertionError("expected ValueError")

    def test_line_window_handles_zero_line_length_limit(self):
        """Zero max_line_chars should return an empty truncated line."""
        config = OutputCacheConfig(max_line_chars=0)

        payload = build_bounded_line_window_payload("abcdef", config)

        assert payload["content"] == ""
        assert payload["truncated_lines"][0]["next_char_offset"] == 0

    def test_line_window_handles_exhausted_char_budget(self):
        """A zero total char budget should truncate before appending content."""
        payload = build_bounded_line_window_payload("a\nb", max_chars=0)

        assert payload["content"] == ""
        assert payload["truncated"] is True
        assert payload["next_line_offset"] == 0

    def test_char_window_returns_bounded_range(self):
        """Character windows should return bounded slices with next offsets."""
        config = OutputCacheConfig(retrieval_max_chars=4)

        payload = build_char_window_payload(
            "abcdef",
            config,
            char_offset=1,
            char_count=10,
        )

        assert payload["content"] == "bcde"
        assert payload["char_count"] == 4
        assert payload["char_count_capped"] is True
        assert payload["next_char_offset"] == 5

    def test_char_window_rejects_negative_count(self):
        """Negative character counts should be rejected."""
        payload = build_bounded_cached_output_payload("abc", char_count=-1)

        assert payload == {"error": "char_count must be >= 0"}

    def test_char_window_rejects_negative_offset_directly(self):
        """Direct char-window calls should reject negative offsets."""
        try:
            build_char_window_payload("abc", char_offset=-1)
        except ValueError as exc:
            assert str(exc) == "char_offset must be >= 0"
        else:  # pragma: no cover
            raise AssertionError("expected ValueError")

    def test_cached_payload_defaults_to_bounded_preview(self):
        """Cached payload retrieval should no longer return all content by default."""
        config = OutputCacheConfig(retrieval_default_line_count=1)

        payload = build_bounded_cached_output_payload("a\nb\nc", config)

        assert payload["content"] == "a"
        assert payload["next_line_offset"] == 1
        assert payload["truncated"] is True

    def test_cached_payload_allows_explicit_full_retrieval(self):
        """Explicit full retrieval should still be available for download paths."""
        payload = build_bounded_cached_output_payload("a\nb", allow_full=True)

        assert payload["content"] == "a\nb"
        assert payload["truncated"] is False

    def test_cached_payload_applies_jmespath_before_windowing(self):
        """JMESPath results should still be bounded by retrieval limits."""
        config = OutputCacheConfig(retrieval_default_line_count=2)
        content = json.dumps({"items": [{"title": "A"}, {"title": "B"}]})

        payload = build_bounded_cached_output_payload(
            content,
            config,
            jmespath_expression="items",
        )

        assert payload["jmespath_expression"] == "items"
        assert payload["content"] == "[\n  {"
        assert payload["truncated"] is True

    def test_cached_payload_reports_jmespath_errors(self):
        """Invalid JMESPath expressions should return structured errors."""
        payload = build_bounded_cached_output_payload(
            '{"items": []}',
            jmespath_expression="items[",
        )

        assert payload["error"].startswith("Invalid JMESPath expression:")

    def test_serialize_query_result_falls_back_to_string(self):
        """Query result serialization should handle unserializable cycles."""
        cyclic = []
        cyclic.append(cyclic)

        assert serialize_query_result(cyclic).startswith("[[")

    def test_truncate_line_rejects_negative_char_offset(self):
        """Internal line truncation should validate character offsets."""
        try:
            _truncate_line("abc", line_index=0, max_line_chars=1, char_offset=-1)
        except ValueError as exc:
            assert str(exc) == "char_offset must be >= 0"
        else:  # pragma: no cover
            raise AssertionError("expected ValueError")
