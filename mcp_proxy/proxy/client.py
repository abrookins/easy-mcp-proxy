"""Client management for MCP Proxy."""

import logging
from contextlib import AsyncExitStack
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport, StreamableHttpTransport

from mcp_proxy.models import ProxyConfig, UpstreamServerConfig
from mcp_proxy.utils import expand_env_vars

logger = logging.getLogger(__name__)


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

        This opens a temporary connection to fetch tool metadata.
        For fetching from an already-connected client, use
        fetch_tools_from_active_client.

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

    async def fetch_tools_from_active_client(self, server_name: str) -> list[Any]:
        """Fetch tools from an already-connected client.

        Unlike fetch_upstream_tools, this does not open a new connection.
        The client must already be connected via connect_clients().

        Args:
            server_name: Name of the server to fetch tools from

        Returns:
            List of tool objects from the upstream server
        """
        client = self._active_clients.get(server_name)
        if client is None:
            raise ValueError(f"No active client for server '{server_name}'")

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
            except Exception as e:
                # Log error but continue - tool will work without schema
                logger.debug("Failed to fetch tools from %s: %s", server_name, e)

    async def refresh_tools_from_active_clients(
        self, instruction_callback: Any | None = None
    ) -> None:
        """Refresh tool lists from all active (connected) clients.

        This is more efficient than refresh_upstream_tools as it uses
        existing connections rather than opening new ones.

        Args:
            instruction_callback: Optional async callback(server_name, client) to
                                 fetch instructions from each client.
        """
        for server_name in self._active_clients:
            try:
                await self.fetch_tools_from_active_client(server_name)
                if instruction_callback:
                    await instruction_callback(
                        server_name, self._active_clients[server_name]
                    )
            except Exception as e:
                # Log error but continue - tool will work without schema
                logger.debug("Failed to refresh tools from %s: %s", server_name, e)

    async def connect_clients(self, fetch_tools: bool = False) -> None:
        """Establish persistent connections to all upstream servers.

        This enters the async context for each client, keeping the connections
        (and stdio subprocesses) alive until disconnect_clients() is called.
        Should be called during server lifespan startup.

        Args:
            fetch_tools: If True, also fetch tool metadata from connected clients.
                        This is useful for HTTP transport where tools are fetched
                        lazily after connections are established.
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
                # Also populate upstream_clients for fallback/compatibility
                self.upstream_clients[server_name] = client
            except Exception as e:
                # Log but continue - some servers may be unavailable
                logger.warning("Failed to connect to server %s: %s", server_name, e)

        if fetch_tools:
            await self.refresh_tools_from_active_clients()

    async def disconnect_clients(self) -> None:
        """Close all persistent client connections.

        This exits the async context for all clients, terminating
        stdio subprocesses. Should be called during server lifespan shutdown.
        """
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(None, None, None)
            self._exit_stack = None
            self._active_clients.clear()
            self.upstream_clients.clear()

    def get_active_client(self, server_name: str) -> Client | None:
        """Get an active (connected) client for a server."""
        return self._active_clients.get(server_name)

    def has_active_connection(self, server_name: str) -> bool:
        """Check if there's an active connection to a server."""
        return server_name in self._active_clients

    async def call_upstream_tool(
        self, server_name: str, tool_name: str, args: dict[str, Any]
    ) -> Any:
        """Call a tool on an upstream server.

        If the active client connection has failed, attempts to reconnect
        once before falling back to a fresh client for each call.
        """
        if server_name not in self.config.mcp_servers:
            raise ValueError(f"No client for server '{server_name}'")

        # Use active client if available (connection pooling)
        active_client = self._active_clients.get(server_name)
        if active_client:
            try:
                return await active_client.call_tool(tool_name, args)
            except Exception as e:
                # Connection may have died - try to reconnect
                logger.warning(
                    "Active client for %s failed, attempting reconnect: %s",
                    server_name,
                    e,
                )
                try:
                    await self._reconnect_client(server_name)
                    active_client = self._active_clients.get(server_name)
                    if active_client:
                        return await active_client.call_tool(tool_name, args)
                except Exception as reconnect_error:
                    logger.warning(
                        "Reconnect to %s failed: %s", server_name, reconnect_error
                    )
                # Fall through to fresh client

        # Fall back to creating a fresh client for each call
        client = self.create_client_from_config(self.config.mcp_servers[server_name])
        async with client:
            return await client.call_tool(tool_name, args)

    async def _reconnect_client(self, server_name: str) -> None:
        """Attempt to reconnect a single upstream client.

        This removes the old client from _active_clients and creates
        a new connection.
        """
        if self._exit_stack is None:
            # No exit stack means connect_clients was never called
            return

        # Remove old client reference
        self._active_clients.pop(server_name, None)

        try:
            # Create and connect a new client
            client = self.create_client_from_config(
                self.config.mcp_servers[server_name]
            )
            await self._exit_stack.enter_async_context(client)
            self._active_clients[server_name] = client
            logger.info("Successfully reconnected to %s", server_name)
        except Exception as e:
            logger.warning("Failed to reconnect to %s: %s", server_name, e)
