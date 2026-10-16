"""Public tool failures without upstream exception text or argument values."""

import json

import httpx
from anyio import BrokenResourceError, ClosedResourceError, EndOfStream
from fastmcp.exceptions import ToolError, ValidationError
from mcp.shared.exceptions import McpError
from pydantic import ValidationError as PydanticValidationError

from mcp_proxy.proxy.search_tools import UnknownToolError
from mcp_proxy.proxy.validation import ToolArgumentValidationError

MAX_ERROR_LENGTH = 16384


def public_tool_error(exc: Exception) -> str:
    """Keep trusted local validation metadata; never forward upstream messages.

    An upstream ToolError can contain arbitrary exception text, including secrets
    resolved by hooks. Its type establishes rejection, not safe disclosure.
    """
    if isinstance(exc, (ToolArgumentValidationError, UnknownToolError)):
        encoded = json.dumps(exc.payload, sort_keys=True)
        if len(encoded) <= MAX_ERROR_LENGTH:
            return encoded
        payload = {
            "error": exc.payload["error"],
            "message": "Invalid request; use search/describe to inspect the schema.",
            "details_omitted": True,
        }
    elif isinstance(exc, ValidationError):
        payload = {
            "error": "invalid_tool_arguments",
            "message": "Invalid tool arguments; inspect the tool's input schema.",
        }
    elif isinstance(exc, PydanticValidationError):
        payload = {
            "error": "upstream_response_validation_error",
            "message": (
                "The upstream tool returned an invalid MCP response; check its "
                "result schema. Private error details omitted."
            ),
        }
    elif isinstance(exc, ToolError):
        payload = {
            "error": "upstream_tool_error",
            "message": (
                "The upstream tool rejected the request. Check its arguments, "
                "selected source/resource, and permissions. Use search/describe "
                "to inspect the tool's input schema. Private error details omitted."
            ),
        }
    elif isinstance(exc, McpError):
        payload = {
            "error": "upstream_protocol_error",
            "message": "The upstream rejected the MCP request; check the tool schema.",
        }
    elif isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in (401, 403):
            payload = {
                "error": "upstream_auth_error",
                "message": "The upstream denied access; check its credentials/grants.",
            }
        else:
            payload = {
                "error": "upstream_http_error",
                "message": "The upstream returned an HTTP error; check its status.",
            }
    elif isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        payload = {
            "error": "upstream_timeout",
            "message": "The upstream request timed out; check connection health.",
        }
    elif isinstance(
        exc,
        (
            ConnectionError,
            httpx.TransportError,
            BrokenResourceError,
            ClosedResourceError,
            EndOfStream,
        ),
    ):
        payload = {
            "error": "upstream_connection_error",
            "message": "The upstream connection failed; check connection health.",
        }
    else:
        payload = {
            "error": "tool_execution_error",
            "message": "Tool execution failed; private error details omitted.",
        }
    return json.dumps({"schema_version": 1, **payload}, sort_keys=True)
