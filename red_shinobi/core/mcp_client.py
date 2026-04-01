"""
RED SHINOBI MCP Client Module

Production-grade implementation of the Model Context Protocol (MCP).
Implements JSON-RPC 2.0 over stdio for communicating with MCP servers.
Handles the full lifecycle: initialize handshake, message framing,
request/response matching, and background notification listening.
"""

import asyncio
import json
import platform
import shlex
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, List, Dict


class MCPError(Exception):
    """Base exception for MCP-related errors."""
    pass


class MCPConnectionError(MCPError):
    """Raised when connection to MCP server fails."""
    pass


class MCPProtocolError(MCPError):
    """Raised when MCP protocol violation occurs."""
    pass


class MCPTimeoutError(MCPError):
    """Raised when an MCP operation times out."""
    pass


class ServerState(Enum):
    """Lifecycle states for an MCP server connection."""
    DISCONNECTED = "disconnected"
    STARTING = "starting"
    INITIALIZING = "initializing"
    READY = "ready"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"


@dataclass
class ServerCapabilities:
    """Parsed capabilities from the MCP server's initialize response."""
    tools: bool = False
    resources: bool = False
    prompts: bool = False
    logging: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPServerConnection:
    """
    Represents an active connection to an MCP server subprocess.
    
    Attributes:
        name: Friendly identifier for this server
        command: Full command used to launch the server
        process: The asyncio subprocess handle
        state: Current lifecycle state
        capabilities: Server capabilities after handshake
        server_info: Server metadata from initialize response
        request_id: Auto-incrementing ID for JSON-RPC requests
        pending_requests: Map of request_id -> Future for response matching
        stderr_buffer: Accumulated stderr output for diagnostics
    """
    name: str
    command: List[str]
    process: asyncio.subprocess.Process
    state: ServerState = ServerState.STARTING
    capabilities: Optional[ServerCapabilities] = None
    server_info: Dict[str, Any] = field(default_factory=dict)
    request_id: int = 0
    pending_requests: Dict[int, asyncio.Future] = field(default_factory=dict)
    stderr_buffer: List[str] = field(default_factory=list)
    _reader_task: Optional[asyncio.Task] = None
    _stderr_task: Optional[asyncio.Task] = None
    _notification_handler: Optional[Callable] = None


class MCPManager:
    """
    Production-grade manager for MCP server connections.
    
    Implements the full MCP lifecycle:
    1. Spawn server subprocess
    2. Perform initialize/initialized handshake
    3. Background listener for responses and notifications
    4. Request/response matching via incremental IDs
    5. Proper shutdown with cleanup
    
    Example:
        manager = MCPManager()
        result = await manager.connect_server(
            "github",
            "npx", ["-y", "@modelcontextprotocol/server-github"]
        )
        tools = await manager.get_tools("github")
        result = await manager.call_tool("github", "list_repos", {"org": "octocat"})
        await manager.disconnect_server("github")
    """
    
    # MCP Protocol version we support
    PROTOCOL_VERSION = "2024-11-05"
    
    # Client info sent during initialize
    CLIENT_INFO = {
        "name": "red_shinobi",
        "version": "1.0.0"
    }
    
    # Default timeouts in seconds
    INIT_TIMEOUT = 30.0
    REQUEST_TIMEOUT = 60.0
    SHUTDOWN_TIMEOUT = 5.0
    
    def __init__(
        self,
        notification_handler: Optional[Callable[[str, str, Dict[str, Any]], None]] = None
    ):
        """
        Initialize the MCP manager.
        
        Args:
            notification_handler: Optional callback for server notifications.
                Signature: (server_name, method, params) -> None
        """
        self._servers: Dict[str, MCPServerConnection] = {}
        self._notification_handler = notification_handler
    
    @staticmethod
    def parse_mcp_command(raw_input: str) -> tuple:
        """
        Parse a raw /mcp command string into components.
        
        Handles the format: /mcp <name> <command> [args...]
        Supports quoted arguments and shell-like parsing.
        
        Args:
            raw_input: The full command string (e.g., "/mcp github npx -y @modelcontextprotocol/server-github")
        
        Returns:
            Tuple of (server_name, command, args_list)
        
        Raises:
            ValueError: If the command format is invalid
        """
        # Remove leading /mcp if present
        cleaned = raw_input.strip()
        if cleaned.lower().startswith("/mcp"):
            cleaned = cleaned[4:].strip()
        
        if not cleaned:
            raise ValueError("Usage: /mcp <name> <command> [args...]")
        
        # Use shlex for proper shell-like parsing (handles quotes)
        try:
            parts = shlex.split(cleaned, posix=(sys.platform != "win32"))
        except ValueError as e:
            raise ValueError(f"Invalid command syntax: {e}")
        
        if len(parts) < 2:
            raise ValueError("Usage: /mcp <name> <command> [args...]")
        
        server_name = parts[0]
        command = parts[1]
        args = parts[2:] if len(parts) > 2 else []
        
        return server_name, command, args
    
    async def connect_server(
        self,
        server_name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> str:
        """
        Connect to an MCP server and perform the initialization handshake.
        
        This method:
        1. Spawns the server as a subprocess
        2. Starts background readers for stdout/stderr
        3. Sends the 'initialize' request
        4. Waits for the capabilities response
        5. Sends the 'initialized' notification
        6. Marks the server as READY for tool calls
        
        Args:
            server_name: Friendly name for this server connection
            command: The executable to run (e.g., "npx", "python")
            args: Command arguments (e.g., ["-y", "@modelcontextprotocol/server-github"])
            env: Optional environment variables to pass to the subprocess
            timeout: Initialization timeout in seconds (default: INIT_TIMEOUT)
        
        Returns:
            Success message with server info, or error description
        """
        if args is None:
            args = []
        if timeout is None:
            timeout = self.INIT_TIMEOUT
        
        # Check if already connected
        if server_name in self._servers:
            existing = self._servers[server_name]
            if existing.state == ServerState.READY:
                return f"[ok] Already connected to '{server_name}'"
            # Clean up failed/stale connection
            await self._cleanup_server(server_name)
        
        # Windows-specific handling: npx requires .cmd extension
        if platform.system() == "Windows" and command == "npx":
            command = "npx.cmd"
        
        full_cmd = [command] + args
        
        try:
            # Spawn the subprocess
            process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            
            # Create the connection object
            conn = MCPServerConnection(
                name=server_name,
                command=full_cmd,
                process=process,
                state=ServerState.STARTING,
                _notification_handler=self._notification_handler
            )
            self._servers[server_name] = conn
            
            # Check immediate process failure
            await asyncio.sleep(0.1)
            if process.returncode is not None:
                stderr = await self._drain_stderr(process)
                conn.state = ServerState.ERROR
                return f"[x] Server exited immediately: {stderr[:200]}"
            
            # Start background readers
            conn._reader_task = asyncio.create_task(
                self._stdout_reader(conn),
                name=f"mcp-reader-{server_name}"
            )
            conn._stderr_task = asyncio.create_task(
                self._stderr_reader(conn),
                name=f"mcp-stderr-{server_name}"
            )
            
            # Perform the initialization handshake
            conn.state = ServerState.INITIALIZING
            
            try:
                init_result = await asyncio.wait_for(
                    self._perform_handshake(conn),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                stderr_output = "\n".join(conn.stderr_buffer[-5:])
                await self._cleanup_server(server_name)
                return f"[x] Initialization timeout after {timeout}s. Stderr: {stderr_output}"
            
            if not init_result:
                stderr_output = "\n".join(conn.stderr_buffer[-5:])
                await self._cleanup_server(server_name)
                return f"[x] Handshake failed. Stderr: {stderr_output}"
            
            conn.state = ServerState.READY
            
            # Build success message
            server_info_name = conn.server_info.get("name", "Unknown")
            server_version = conn.server_info.get("version", "?")
            caps = []
            if conn.capabilities and conn.capabilities.tools:
                caps.append("tools")
            if conn.capabilities and conn.capabilities.resources:
                caps.append("resources")
            if conn.capabilities and conn.capabilities.prompts:
                caps.append("prompts")
            
            caps_str = ", ".join(caps) if caps else "none"
            return f"[ok] Connected to '{server_name}' ({server_info_name} v{server_version}) - capabilities: {caps_str}"
        
        except FileNotFoundError:
            return f"[x] Command not found: {command}"
        except PermissionError:
            return f"[x] Permission denied: {command}"
        except Exception as e:
            await self._cleanup_server(server_name)
            return f"[x] Connection failed: {type(e).__name__}: {e}"
    
    async def _perform_handshake(self, conn: MCPServerConnection) -> bool:
        """
        Execute the MCP initialize/initialized handshake.
        
        Args:
            conn: The server connection to initialize
        
        Returns:
            True if handshake succeeded, False otherwise
        """
        # Send initialize request
        init_request = {
            "protocolVersion": self.PROTOCOL_VERSION,
            "capabilities": {
                "roots": {"listChanged": True},
                "sampling": {}
            },
            "clientInfo": self.CLIENT_INFO
        }
        
        try:
            response = await self._send_request(conn, "initialize", init_request)
        except Exception as e:
            conn.stderr_buffer.append(f"Initialize request failed: {e}")
            return False
        
        if "error" in response:
            conn.stderr_buffer.append(f"Initialize error: {response['error']}")
            return False
        
        result = response.get("result", {})
        
        # Parse server capabilities
        caps_raw = result.get("capabilities", {})
        conn.capabilities = ServerCapabilities(
            tools="tools" in caps_raw,
            resources="resources" in caps_raw,
            prompts="prompts" in caps_raw,
            logging="logging" in caps_raw,
            raw=caps_raw
        )
        
        # Store server info
        conn.server_info = result.get("serverInfo", {})
        
        # Send initialized notification (no response expected)
        await self._send_notification(conn, "notifications/initialized", {})
        
        return True
    
    async def _send_request(
        self,
        conn: MCPServerConnection,
        method: str,
        params: Dict[str, Any],
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Send a JSON-RPC 2.0 request and wait for the response.
        
        Args:
            conn: Server connection
            method: The RPC method name
            params: Method parameters
            timeout: Response timeout (default: REQUEST_TIMEOUT)
        
        Returns:
            The JSON-RPC response dict
        
        Raises:
            MCPTimeoutError: If response not received within timeout
            MCPProtocolError: If protocol error occurs
        """
        if timeout is None:
            timeout = self.REQUEST_TIMEOUT
        
        # Generate unique request ID
        conn.request_id += 1
        request_id = conn.request_id
        
        # Create future for response
        loop = asyncio.get_event_loop()
        response_future: asyncio.Future = loop.create_future()
        conn.pending_requests[request_id] = response_future
        
        # Build and send the request
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }
        
        try:
            await self._write_message(conn, message)
            
            # Wait for response
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            conn.pending_requests.pop(request_id, None)
            raise MCPTimeoutError(f"Request '{method}' timed out after {timeout}s")
        except Exception as e:
            conn.pending_requests.pop(request_id, None)
            raise MCPProtocolError(f"Request failed: {e}")
    
    async def _send_notification(
        self,
        conn: MCPServerConnection,
        method: str,
        params: Dict[str, Any]
    ) -> None:
        """
        Send a JSON-RPC 2.0 notification (no response expected).
        
        Args:
            conn: Server connection
            method: The notification method name
            params: Notification parameters
        """
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        await self._write_message(conn, message)
    
    async def _write_message(self, conn: MCPServerConnection, message: Dict[str, Any]) -> None:
        """
        Write a JSON-RPC message to the server's stdin.
        
        Uses newline-delimited JSON framing as per MCP spec.
        
        Args:
            conn: Server connection
            message: The message dict to send
        """
        if conn.process.stdin is None:
            raise MCPProtocolError("Server stdin not available")
        
        line = json.dumps(message) + "\n"
        conn.process.stdin.write(line.encode("utf-8"))
        await conn.process.stdin.drain()
    
    async def _stdout_reader(self, conn: MCPServerConnection) -> None:
        """
        Background task: continuously read stdout and dispatch messages.
        
        Handles:
        - Responses (matched to pending requests via ID)
        - Notifications (dispatched to notification handler)
        - Protocol errors (logged to stderr buffer)
        """
        if conn.process.stdout is None:
            return
        
        try:
            while conn.state not in (ServerState.DISCONNECTED, ServerState.ERROR):
                line = await conn.process.stdout.readline()
                
                if not line:
                    # EOF - server closed stdout
                    if conn.state == ServerState.READY:
                        conn.stderr_buffer.append("Server closed stdout unexpectedly")
                        conn.state = ServerState.ERROR
                    break
                
                try:
                    message = json.loads(line.decode("utf-8").strip())
                except json.JSONDecodeError as e:
                    conn.stderr_buffer.append(f"Invalid JSON from server: {e}")
                    continue
                
                # Dispatch based on message type
                if "id" in message:
                    # Response to a request
                    request_id = message.get("id")
                    if request_id in conn.pending_requests:
                        future = conn.pending_requests.pop(request_id)
                        if not future.done():
                            future.set_result(message)
                    else:
                        conn.stderr_buffer.append(f"Unexpected response ID: {request_id}")
                
                elif "method" in message:
                    # Server notification
                    method = message.get("method", "")
                    params = message.get("params", {})
                    
                    if conn._notification_handler:
                        try:
                            conn._notification_handler(conn.name, method, params)
                        except Exception as e:
                            conn.stderr_buffer.append(f"Notification handler error: {e}")
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            conn.stderr_buffer.append(f"Reader error: {e}")
    
    async def _stderr_reader(self, conn: MCPServerConnection) -> None:
        """
        Background task: capture stderr output for diagnostics.
        
        Stores recent lines in the connection's stderr_buffer
        for error reporting and debugging.
        """
        if conn.process.stderr is None:
            return
        
        try:
            while conn.state not in (ServerState.DISCONNECTED, ServerState.ERROR):
                line = await conn.process.stderr.readline()
                
                if not line:
                    break
                
                decoded = line.decode("utf-8", errors="replace").rstrip()
                conn.stderr_buffer.append(decoded)
                
                # Keep buffer bounded
                if len(conn.stderr_buffer) > 100:
                    conn.stderr_buffer = conn.stderr_buffer[-50:]
                    
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
    
    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> str:
        """Read all available stderr from a process."""
        if process.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(process.stderr.read(), timeout=1.0)
            return data.decode("utf-8", errors="replace").strip()
        except asyncio.TimeoutError:
            return ""
    
    async def get_tools(self, server_name: str) -> Any:
        """
        Retrieve the list of available tools from a connected MCP server.
        
        Args:
            server_name: Name of the connected server
        
        Returns:
            List of tool definitions, or error string
        """
        conn = self._servers.get(server_name)
        if not conn:
            return f"[x] Server '{server_name}' not connected"
        
        if conn.state != ServerState.READY:
            return f"[x] Server '{server_name}' not ready (state: {conn.state.value})"
        
        if not conn.capabilities or not conn.capabilities.tools:
            return f"[x] Server '{server_name}' does not support tools"
        
        try:
            response = await self._send_request(conn, "tools/list", {})
            
            if "error" in response:
                error = response["error"]
                return f"[x] tools/list error: {error.get('message', error)}"
            
            tools = response.get("result", {}).get("tools", [])
            return tools
            
        except MCPTimeoutError:
            return f"[x] tools/list timed out"
        except MCPProtocolError as e:
            return f"[x] Protocol error: {e}"
    
    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None
    ) -> Any:
        """
        Execute a tool on a connected MCP server.
        
        Args:
            server_name: Name of the connected server
            tool_name: Name of the tool to call
            arguments: Tool arguments as a dict
            timeout: Optional timeout override
        
        Returns:
            Tool result dict, or error string
        """
        if arguments is None:
            arguments = {}
        
        conn = self._servers.get(server_name)
        if not conn:
            return f"[x] Server '{server_name}' not connected"
        
        if conn.state != ServerState.READY:
            return f"[x] Server '{server_name}' not ready (state: {conn.state.value})"
        
        try:
            response = await self._send_request(
                conn,
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                timeout=timeout
            )
            
            if "error" in response:
                error = response["error"]
                return f"[x] Tool error: {error.get('message', error)}"
            
            return response.get("result", {})
            
        except MCPTimeoutError:
            return f"[x] Tool call '{tool_name}' timed out"
        except MCPProtocolError as e:
            return f"[x] Protocol error: {e}"
    
    async def get_resources(self, server_name: str) -> Any:
        """
        Retrieve the list of available resources from a connected MCP server.
        
        Args:
            server_name: Name of the connected server
        
        Returns:
            List of resource definitions, or error string
        """
        conn = self._servers.get(server_name)
        if not conn:
            return f"[x] Server '{server_name}' not connected"
        
        if conn.state != ServerState.READY:
            return f"[x] Server '{server_name}' not ready"
        
        if not conn.capabilities or not conn.capabilities.resources:
            return f"[x] Server '{server_name}' does not support resources"
        
        try:
            response = await self._send_request(conn, "resources/list", {})
            
            if "error" in response:
                error = response["error"]
                return f"[x] resources/list error: {error.get('message', error)}"
            
            return response.get("result", {}).get("resources", [])
            
        except (MCPTimeoutError, MCPProtocolError) as e:
            return f"[x] Error: {e}"
    
    async def read_resource(
        self,
        server_name: str,
        uri: str
    ) -> Any:
        """
        Read a specific resource from a connected MCP server.
        
        Args:
            server_name: Name of the connected server
            uri: Resource URI to read
        
        Returns:
            Resource content dict, or error string
        """
        conn = self._servers.get(server_name)
        if not conn:
            return f"[x] Server '{server_name}' not connected"
        
        if conn.state != ServerState.READY:
            return f"[x] Server '{server_name}' not ready"
        
        try:
            response = await self._send_request(
                conn,
                "resources/read",
                {"uri": uri}
            )
            
            if "error" in response:
                error = response["error"]
                return f"[x] resources/read error: {error.get('message', error)}"
            
            return response.get("result", {})
            
        except (MCPTimeoutError, MCPProtocolError) as e:
            return f"[x] Error: {e}"
    
    async def get_prompts(self, server_name: str) -> Any:
        """
        Retrieve the list of available prompts from a connected MCP server.
        
        Args:
            server_name: Name of the connected server
        
        Returns:
            List of prompt definitions, or error string
        """
        conn = self._servers.get(server_name)
        if not conn:
            return f"[x] Server '{server_name}' not connected"
        
        if conn.state != ServerState.READY:
            return f"[x] Server '{server_name}' not ready"
        
        if not conn.capabilities or not conn.capabilities.prompts:
            return f"[x] Server '{server_name}' does not support prompts"
        
        try:
            response = await self._send_request(conn, "prompts/list", {})
            
            if "error" in response:
                error = response["error"]
                return f"[x] prompts/list error: {error.get('message', error)}"
            
            return response.get("result", {}).get("prompts", [])
            
        except (MCPTimeoutError, MCPProtocolError) as e:
            return f"[x] Error: {e}"
    
    def list_servers(self) -> List[Dict[str, Any]]:
        """
        List all MCP server connections with their status.
        
        Returns:
            List of dicts with server info
        """
        result = []
        for name, conn in self._servers.items():
            info: Dict[str, Any] = {
                "name": name,
                "state": conn.state.value,
                "command": " ".join(conn.command),
            }
            if conn.server_info:
                info["server_name"] = conn.server_info.get("name")
                info["server_version"] = conn.server_info.get("version")
            if conn.capabilities:
                info["capabilities"] = {
                    "tools": conn.capabilities.tools,
                    "resources": conn.capabilities.resources,
                    "prompts": conn.capabilities.prompts
                }
            result.append(info)
        return result
    
    def get_server_status(self, server_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed status for a specific server.
        
        Args:
            server_name: Name of the server
        
        Returns:
            Status dict or None if not found
        """
        conn = self._servers.get(server_name)
        if not conn:
            return None
        
        return {
            "name": conn.name,
            "state": conn.state.value,
            "command": conn.command,
            "server_info": conn.server_info,
            "capabilities": conn.capabilities.raw if conn.capabilities else {},
            "pending_requests": len(conn.pending_requests),
            "recent_stderr": conn.stderr_buffer[-10:] if conn.stderr_buffer else []
        }
    
    async def disconnect_server(self, server_name: str) -> str:
        """
        Gracefully disconnect from an MCP server.
        
        Sends shutdown notification if possible, then terminates the process.
        
        Args:
            server_name: Name of the server to disconnect
        
        Returns:
            Status message
        """
        conn = self._servers.get(server_name)
        if not conn:
            return f"[x] Server '{server_name}' not connected"
        
        return await self._cleanup_server(server_name, graceful=True)
    
    async def _cleanup_server(self, server_name: str, graceful: bool = False) -> str:
        """
        Clean up a server connection.
        
        Args:
            server_name: Name of the server
            graceful: If True, attempt graceful shutdown first
        
        Returns:
            Status message
        """
        conn = self._servers.get(server_name)
        if not conn:
            return f"[ok] Server '{server_name}' already disconnected"
        
        conn.state = ServerState.SHUTTING_DOWN
        
        # Attempt graceful shutdown if ready
        if graceful and conn.process.returncode is None:
            try:
                # Cancel pending requests
                for future in conn.pending_requests.values():
                    if not future.done():
                        future.cancel()
                conn.pending_requests.clear()
                
                # Close stdin to signal shutdown
                if conn.process.stdin:
                    conn.process.stdin.close()
                    await conn.process.stdin.wait_closed()
                
                # Wait briefly for graceful exit
                await asyncio.wait_for(
                    conn.process.wait(),
                    timeout=self.SHUTDOWN_TIMEOUT
                )
            except asyncio.TimeoutError:
                pass  # Will force kill below
            except Exception:
                pass
        
        # Force terminate if still running
        if conn.process.returncode is None:
            try:
                conn.process.terminate()
                await asyncio.wait_for(conn.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                conn.process.kill()
                await conn.process.wait()
            except Exception:
                pass
        
        # Cancel background tasks
        for task in [conn._reader_task, conn._stderr_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        conn.state = ServerState.DISCONNECTED
        del self._servers[server_name]
        
        return f"[ok] Disconnected from '{server_name}'"
    
    async def cleanup(self) -> None:
        """
        Disconnect all servers and clean up resources.
        
        Call this before exiting the application.
        """
        server_names = list(self._servers.keys())
        
        # Disconnect all servers concurrently
        if server_names:
            await asyncio.gather(
                *[self._cleanup_server(name, graceful=True) for name in server_names],
                return_exceptions=True
            )
        
        self._servers.clear()
