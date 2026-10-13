"""Trusted test tools that exercise context through hooks and custom dispatch."""

from mcp_proxy.custom_tools import custom_tool
from mcp_proxy.hooks import HookResult
from mcp_proxy.identity import current_principal


@custom_tool("owned_custom", "Test caller-bound custom tool")
async def owned_custom(ctx):
    return await ctx.call_tool("same.echo", value=current_principal().identity.subject)


async def owned_hook(args, context):
    return HookResult(args={"value": current_principal().identity.subject})
