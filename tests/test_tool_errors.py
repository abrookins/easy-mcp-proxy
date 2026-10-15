"""Safe, actionable failures survive the managed MCP wire boundary."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastmcp.exceptions import ToolError, ValidationError
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from mcp_proxy.identity import principal_context
from mcp_proxy.proxy.search_tools import UnknownToolError
from mcp_proxy.proxy.validation import ToolArgumentValidationError
from mcp_proxy.tool_errors import MAX_ERROR_LENGTH, public_tool_error
from mcp_proxy.user_gateway import UserProvider
from tests.test_user_gateway import gateway, rpc  # noqa: F401


def status_error(status):
    request = httpx.Request("GET", "https://private-token.test")
    return httpx.HTTPStatusError(
        "private-token",
        request=request,
        response=httpx.Response(status, request=request),
    )


@pytest.mark.parametrize(
    "error,code",
    [
        (ToolError("private-token"), "upstream_tool_error"),
        (ValidationError("private-token"), "invalid_tool_arguments"),
        (
            McpError(ErrorData(code=-32602, message="private-token")),
            "upstream_protocol_error",
        ),
        (TimeoutError("private-token"), "upstream_timeout"),
        (httpx.ReadTimeout("private-token"), "upstream_timeout"),
        (ConnectionError("private-token"), "upstream_connection_error"),
        (httpx.ConnectError("private-token"), "upstream_connection_error"),
        (RuntimeError("private-token"), "tool_execution_error"),
        (status_error(401), "upstream_auth_error"),
        (status_error(403), "upstream_auth_error"),
        (status_error(500), "upstream_http_error"),
    ],
)
async def test_error_categories_are_safe_on_managed_wire(request, error, code):
    app, alice, _ = request.getfixturevalue("gateway")
    with principal_context(alice):
        tool = (await UserProvider(app.runtime).list_tools())[0]
    tool.inner = SimpleNamespace(run=AsyncMock(side_effect=error))
    app.mcp.add_tool(tool)
    async with app.app.router.lifespan_context(app.app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app.app),
            base_url="https://proxy.test",
            headers={"Authorization": "Bearer alice"},
        ) as client:
            response = await rpc(
                client, "/mcp", "tools/call", {"name": tool.name, "arguments": {}}
            )
    result = response["result"]
    assert result["isError"] is True
    payload = json.loads(result["content"][0]["text"])
    assert payload["error"] == code
    assert "private-token" not in json.dumps(result)
    tool.inner.run.assert_awaited_once()


@pytest.mark.parametrize("error_type", [ToolArgumentValidationError, UnknownToolError])
def test_trusted_validation_metadata_is_bounded(error_type):
    payload = {
        "schema_version": 1,
        "error": "invalid_tool_arguments",
        "message": "wrong type",
        "validation_path": ["operation"],
    }
    assert json.loads(public_tool_error(error_type(payload))) == payload
    payload["inputSchema"] = {"description": "x" * MAX_ERROR_LENGTH}
    bounded = public_tool_error(error_type(payload))
    assert len(bounded) < MAX_ERROR_LENGTH
    assert json.loads(bounded)["details_omitted"] is True
