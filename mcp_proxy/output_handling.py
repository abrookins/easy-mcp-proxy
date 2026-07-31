"""Safe output handling for proxied tool calls."""

from __future__ import annotations

import json
import logging
from math import ceil
from typing import Any

import jmespath
from fastmcp.tools.tool import ToolResult

from mcp_proxy.models import OutputCacheConfig

logger = logging.getLogger(__name__)

HARD_MAX_INLINE_CHARS = 16000


def estimate_tokens(text: str, config: OutputCacheConfig) -> int:
    """Estimate token count without adding a tokenizer dependency."""
    if not text:
        return 0
    ratio = max(config.token_chars_ratio, 1)
    return ceil(len(text) / ratio)


def effective_max_inline_chars(config: OutputCacheConfig) -> int:
    """Return the effective inline character budget for a cache config."""
    derived = config.max_inline_tokens * max(config.token_chars_ratio, 1)
    max_chars = config.max_inline_chars or derived
    if config.preview_chars is not None:
        max_chars = min(max_chars, config.preview_chars)
    if config.strict:
        max_chars = min(max_chars, HARD_MAX_INLINE_CHARS)
    return max(max_chars, 0)


def output_limits(config: OutputCacheConfig) -> dict[str, int]:
    """Return the concrete output limits used for decisions and metadata."""
    return {
        "max_inline_tokens": config.max_inline_tokens,
        "max_inline_chars": effective_max_inline_chars(config),
        "max_line_chars": config.max_line_chars,
        "retrieval_default_line_count": config.retrieval_default_line_count,
        "retrieval_max_line_count": config.retrieval_max_line_count,
        "retrieval_max_chars": config.retrieval_max_chars,
    }


def measure_text(text: str, config: OutputCacheConfig) -> dict[str, int]:
    """Measure text dimensions relevant to context usage."""
    lines = text.splitlines()
    return {
        "bytes": len(text.encode("utf-8")),
        "chars": len(text),
        "estimated_tokens": estimate_tokens(text, config),
        "lines": len(lines),
        "longest_line_chars": max((len(line) for line in lines), default=0),
    }


def serialize_visible_result(result: Any) -> str:
    """Serialize the model-visible portion of a tool result."""
    if hasattr(result, "content") and isinstance(result.content, list):
        texts = []
        for item in result.content:
            if hasattr(item, "text"):
                texts.append(item.text)
        if texts:
            return "\n".join(texts)

    if isinstance(result, str):
        return result

    try:
        return json.dumps(result, default=str)
    except (TypeError, ValueError):
        return str(result)


def truncation_reasons(
    measurement: dict[str, int], config: OutputCacheConfig
) -> list[str]:
    """Return reasons why a result must be cached and previewed."""
    reasons = []
    if measurement["estimated_tokens"] > config.max_inline_tokens:
        reasons.append("estimated_tokens")
    if measurement["chars"] > effective_max_inline_chars(config):
        reasons.append("max_inline_chars")
    if measurement["longest_line_chars"] > config.max_line_chars:
        reasons.append("max_line_chars")
    if config.min_size is not None and measurement["bytes"] >= config.min_size:
        reasons.append("min_size")
    return reasons


def _line_truncation_marker(original_chars: int, next_char_offset: int) -> str:
    return (
        "..."
        f" [line truncated; original_chars={original_chars}; "
        f"next_char_offset={next_char_offset}]"
    )


def _truncate_line(
    line: str,
    *,
    line_index: int,
    max_line_chars: int,
    char_offset: int = 0,
) -> tuple[str, dict[str, int] | None]:
    """Return a line segment capped to max_line_chars."""
    if char_offset < 0:
        raise ValueError("char_offset must be >= 0")
    if max_line_chars <= 0:
        return "", {
            "line_index": line_index,
            "original_chars": len(line),
            "returned_chars": 0,
            "char_offset": char_offset,
            "next_char_offset": char_offset,
        }

    segment = line[char_offset:]
    if len(segment) <= max_line_chars:
        return segment, None

    next_char_offset = char_offset + max_line_chars
    marker = _line_truncation_marker(len(line), next_char_offset)
    if len(marker) < max_line_chars:
        text_chars = max_line_chars - len(marker)
        next_char_offset = char_offset + text_chars
        marker = _line_truncation_marker(len(line), next_char_offset)
        clipped = f"{segment[:text_chars]}{marker}"
    else:
        clipped = segment[:max_line_chars]

    return clipped, {
        "line_index": line_index,
        "original_chars": len(line),
        "returned_chars": len(clipped),
        "char_offset": char_offset,
        "next_char_offset": next_char_offset,
    }


def _append_with_char_budget(
    output_lines: list[str],
    next_line: str,
    max_chars: int,
) -> tuple[bool, int]:
    """Append a line if possible and return whether the budget was exhausted."""
    current = sum(len(line) for line in output_lines)
    current += max(len(output_lines) - 1, 0)
    separator_chars = 1 if output_lines else 0
    remaining = max_chars - current - separator_chars
    if remaining <= 0:
        return True, 0
    if len(next_line) <= remaining:
        output_lines.append(next_line)
        return False, len(next_line)
    output_lines.append(next_line[:remaining])
    return True, remaining


def build_bounded_line_window_payload(
    content: str,
    config: OutputCacheConfig | None = None,
    *,
    line_offset: int = 0,
    line_count: int | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Build a bounded line-window payload with per-line caps."""
    config = config or OutputCacheConfig()
    if line_offset < 0:
        raise ValueError("line_offset must be >= 0")
    if line_count is not None and line_count < 0:
        raise ValueError("line_count must be >= 0")

    lines = content.splitlines()
    total_lines = len(lines)
    requested_line_count = (
        config.retrieval_default_line_count if line_count is None else line_count
    )
    selected_line_count = min(
        requested_line_count,
        max(config.retrieval_max_line_count, 0),
    )
    max_chars = config.retrieval_max_chars if max_chars is None else max_chars
    max_chars = max(max_chars, 0)

    output_lines: list[str] = []
    truncated_lines: list[dict[str, int]] = []
    next_line_offset: int | None = None
    char_budget_exhausted = False
    end_offset = min(line_offset + selected_line_count, total_lines)

    for index in range(line_offset, end_offset):
        line, line_truncation = _truncate_line(
            lines[index],
            line_index=index,
            max_line_chars=config.max_line_chars,
        )
        if line_truncation:
            truncated_lines.append(line_truncation)

        char_budget_exhausted, _returned_chars = _append_with_char_budget(
            output_lines, line, max_chars
        )
        if char_budget_exhausted:
            next_line_offset = index
            break

    if next_line_offset is None and end_offset < total_lines:
        next_line_offset = end_offset

    returned_content = "\n".join(output_lines)
    returned = measure_text(returned_content, config)
    line_count_capped = requested_line_count > selected_line_count
    truncated = bool(
        next_line_offset is not None
        or truncated_lines
        or char_budget_exhausted
        or line_count_capped
    )

    return {
        "content": returned_content,
        "line_offset": line_offset,
        "line_count": selected_line_count,
        "returned_lines": len(output_lines),
        "total_lines": total_lines,
        "next_line_offset": next_line_offset,
        "truncated": truncated,
        "truncated_lines": truncated_lines,
        "line_count_capped": line_count_capped,
        "returned": returned,
    }


def build_char_window_payload(
    content: str,
    config: OutputCacheConfig | None = None,
    *,
    char_offset: int = 0,
    char_count: int | None = None,
) -> dict[str, Any]:
    """Build a bounded character window from cached content."""
    config = config or OutputCacheConfig()
    if char_offset < 0:
        raise ValueError("char_offset must be >= 0")
    if char_count is not None and char_count < 0:
        raise ValueError("char_count must be >= 0")

    requested_count = config.retrieval_max_chars if char_count is None else char_count
    selected_count = min(requested_count, config.retrieval_max_chars)
    end = char_offset + selected_count
    output = content[char_offset:end]
    next_char_offset = end if end < len(content) else None
    returned = measure_text(output, config)

    return {
        "content": output,
        "char_offset": char_offset,
        "char_count": selected_count,
        "returned_chars": len(output),
        "total_chars": len(content),
        "next_char_offset": next_char_offset,
        "truncated": next_char_offset is not None,
        "char_count_capped": requested_count > selected_count,
        "returned": returned,
    }


def serialize_query_result(result: Any) -> str:
    """Serialize a JMESPath result for bounded retrieval."""
    try:
        return json.dumps(result, indent=2, default=str)
    except (TypeError, ValueError):
        return str(result)


def build_bounded_cached_output_payload(
    content: str,
    config: OutputCacheConfig | None = None,
    *,
    line_offset: int = 0,
    line_count: int | None = None,
    jmespath_expression: str | None = None,
    char_offset: int | None = None,
    char_count: int | None = None,
    allow_full: bool = False,
) -> dict[str, Any]:
    """Build a bounded retrieval payload for cached content."""
    config = config or OutputCacheConfig()
    output = content
    payload: dict[str, Any] = {
        "original": measure_text(content, config),
        "limits": output_limits(config),
    }

    if jmespath_expression is not None:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return {"error": "Cached output is not valid JSON"}

        try:
            output = serialize_query_result(
                jmespath.search(jmespath_expression, parsed)
            )
        except jmespath.exceptions.JMESPathError as exc:
            return {"error": f"Invalid JMESPath expression: {exc}"}
        payload["jmespath_expression"] = jmespath_expression

    if allow_full:
        payload["content"] = output
        payload["returned"] = measure_text(output, config)
        payload["truncated"] = False
        return payload

    if char_offset is not None or char_count is not None:
        try:
            window_payload = build_char_window_payload(
                output,
                config,
                char_offset=char_offset or 0,
                char_count=char_count,
            )
        except ValueError as exc:
            return {"error": str(exc)}
    else:
        try:
            window_payload = build_bounded_line_window_payload(
                output,
                config,
                line_offset=line_offset,
                line_count=line_count,
            )
        except ValueError as exc:
            return {"error": str(exc)}

    return {**payload, **window_payload}


def _navigation_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    navigation = {
        "preview_tool": "preview_cached_output",
        "range_tool": "range_cached_output",
        "query_tool": "query_cached_output",
        "next_line_offset": payload.get("next_line_offset"),
        "next_char_offset": payload.get("next_char_offset"),
    }
    truncated_lines = payload.get("truncated_lines") or []
    if truncated_lines and navigation["next_char_offset"] is None:
        navigation["next_char_offset"] = truncated_lines[0]["next_char_offset"]
    return navigation


def _build_cached_tool_result(
    *,
    content: str,
    preview_payload: dict[str, Any],
    original: dict[str, int],
    reasons: list[str],
    config: OutputCacheConfig,
    cache_secret: str,
    cache_base_url: str,
) -> ToolResult:
    from mcp_proxy.cache import (
        build_cached_output_tool_result,
        create_cached_output_with_meta,
        infer_cached_content_mime_type,
    )

    preview = preview_payload["content"]
    navigation = _navigation_from_payload(preview_payload)
    cached_response = create_cached_output_with_meta(
        content=content,
        secret=cache_secret,
        base_url=cache_base_url,
        ttl_seconds=config.ttl_seconds,
        preview_chars=len(preview),
        preview=preview,
        metadata={
            "truncated": True,
            "truncation_reasons": reasons,
            "original": original,
            "returned": preview_payload["returned"],
            "limits": output_limits(config),
            "navigation": navigation,
        },
    )

    return build_cached_output_tool_result(
        cached_response,
        infer_cached_content_mime_type(content),
    )


def record_output_event(
    *,
    view_name: str | None,
    server_name: str | None,
    tool_name: str,
    cache_id: str | None,
    original: dict[str, int],
    returned: dict[str, int],
    truncated: bool,
    reasons: list[str],
) -> None:
    """Record output handling metadata without logging full content."""
    logger.info(
        "tool output handling",
        extra={
            "output_handling": {
                "view_name": view_name,
                "server_name": server_name,
                "tool_name": tool_name,
                "cache_id": cache_id,
                "original": original,
                "returned": returned,
                "truncated": truncated,
                "truncation_reasons": reasons,
            }
        },
    )


def protect_tool_output(
    result: Any,
    *,
    view_name: str | None,
    server_name: str | None,
    tool_name: str,
    config: OutputCacheConfig,
    cache_secret: str,
    cache_base_url: str,
) -> Any:
    """Return result unchanged when safe, or a bounded cached ToolResult."""
    if not config.enabled:
        return result

    content = serialize_visible_result(result)
    original = measure_text(content, config)
    reasons = truncation_reasons(original, config)
    if not reasons:
        record_output_event(
            view_name=view_name,
            server_name=server_name,
            tool_name=tool_name,
            cache_id=None,
            original=original,
            returned=original,
            truncated=False,
            reasons=[],
        )
        return result

    preview_payload = build_bounded_line_window_payload(
        content,
        config,
        line_count=config.retrieval_default_line_count,
        max_chars=effective_max_inline_chars(config),
    )
    protected = _build_cached_tool_result(
        content=content,
        preview_payload=preview_payload,
        original=original,
        reasons=reasons,
        config=config,
        cache_secret=cache_secret,
        cache_base_url=cache_base_url,
    )
    structured = protected.structured_content or {}
    record_output_event(
        view_name=view_name,
        server_name=server_name,
        tool_name=tool_name,
        cache_id=structured.get("cache_id") or structured.get("token"),
        original=original,
        returned=preview_payload["returned"],
        truncated=True,
        reasons=reasons,
    )
    return protected
