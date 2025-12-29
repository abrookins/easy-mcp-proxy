"""Client management for MCP Proxy."""

from contextlib import AsyncExitStack
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

from mcp_proxy.models import ProxyConfig, UpstreamServerConfig
from mcp_proxy.utils import expand_env_vars


class ClientManager:
    """Manages MCP client connections to upstream servers."""

    def __init__(self, config: ProxyConfig):
        self.config = config
        self.upstream_clients: dict[str, Client] = {}
        self._upstream_tools: dict[str, list[Any]] = {}  # Cached tools from upstreams
        self._active_clients: dict[str, Client] = {}  # Clients with active connections
        self._exit_stack: AsyncExitStack | None = None  # Manages client lifecycles

    def create_client_from_config(self, config: UpstreamServerConfig) -> Client:
        """Create an MCP client from server configuration."""
        if config.url:
            # HTTP-based server
            url = expand_env_vars(config.url)
            headers = {k: expand_env_vars(v) for k, v in config.headers.items()}
            transport = StreamableHttpTransport(url=url, headers=headers)
            return Client(transport=transport)
        elif config.command:
            # Stdio-based server (command execution)
            command = config.command
            args = config.args or []
            env = (
                {k: expand_env_vars(v) for k, v in config.env.items()}
                if config.env
                else None
            )
            cwd = expand_env_vars(config.cwd) if config.cwd else None
            transport = StdioTransport(command=command, args=args, env=env, cwd=cwd)
            return Client(transport=transport)
        else:
            raise ValueError("Server config must have either 'url' or 'command'")

    async def create_client(self, server_name: str) -> Client:
        """Create an MCP client for an upstream server.

        Args:
            server_name: Name of the server from config

        Returns:
            FastMCP Client instance configured for the server
        """
        if server_name not in self.config.mcp_servers:
            raise ValueError(f"Server '{server_name}' not found in config")

        server_config = self.config.mcp_servers[server_name]
        return self.create_client_from_config(server_config)

    async def fetch_upstream_tools(self, server_name: str) -> list[Any]:
        """Fetch tools from an upstream server.

        Args:
            server_name: Name of the server to fetch tools from

        Returns:
            List of tool objects from the upstream server
        """
        if server_name not in self.upstream_clients:
            raise ValueError(f"No client for server '{server_name}'")

        client = self.upstream_clients[server_name]
        async with client:
            tools = await client.list_tools()
            self._upstream_tools[server_name] = tools
            return tools

    async def refresh_upstream_tools(self) -> None:
        """Refresh tool lists from all upstream servers.

        Errors connecting to individual servers are logged but don't
        prevent other servers from being contacted. Tools from servers
        that can't be reached will have no schema information.
        """
        for server_name in self.upstream_clients:
            try:
                await self.fetch_upstream_tools(server_name)
            except Exception:
                # Log error but continue - tool will work without schema
                pass

    async def connect_clients(self) -> None:
        """Establish persistent connections to all upstream servers.

        This enters the async context for each client, keeping the connections
        (and stdio subprocesses) alive until disconnect_clients() is called.
        Should be called during server lifespan startup.
        """
        if self._exit_stack is not None:
            return  # Already connected

        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        for server_name in self.config.mcp_servers:
            try:
                # Create a fresh client for the persistent connection
                client = self.create_client_from_config(
                    self.config.mcp_servers[server_name]
                )
                # Enter the client context - this starts the connection/subprocess
                await self._exit_stack.enter_async_context(client)
                self._active_clients[server_name] = client
            except Exception:
                # Log but continue - some servers may be unavailable
                pass

    async def disconnect_clients(self) -> None:
        """Close all persistent client connections.

        This exits the async context for all clients, terminating
        stdio subprocesses. Should be called during server lifespan shutdown.
        """
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None
            self._active_clients.clear()

    def get_active_client(self, server_name: str) -> Client | None:
        """Get an active (connected) client for a server."""
        return self._active_clients.get(server_name)

    def has_active_connection(self, server_name: str) -> bool:
        """Check if there's an active connection to a server."""
        return server_name in self._active_clients

    async def call_upstream_tool(
        self, server_name: str, tool_name: str, args: dict[str, Any]
    ) -> Any:
        """Call a tool on an upstream server."""
        if server_name not in self.config.mcp_servers:
            raise ValueError(f"No client for server '{server_name}'")

        # Use active client if available (connection pooling)
        active_client = self._active_clients.get(server_name)
        if active_client:
            return await active_client.call_tool(tool_name, args)

        # Fall back to creating a fresh client for each call
        client = self.create_client_from_config(self.config.mcp_servers[server_name])
        async with client:
            return await client.call_tool(tool_name, args)
