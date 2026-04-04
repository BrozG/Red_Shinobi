"""
RED SHINOBI MCP Commands Module

Handles the /mcp command for connecting to and managing MCP servers.
"""

from typing import Any, List

from rich.console import Console
from rich.table import Table
from prompt_toolkit import PromptSession

from red_shinobi.core.mcp_client import MCPManager
from red_shinobi.commands.auth_cmds import arrow_select

console = Console()
THEME_COLOR = "red"
ACCENT_COLOR = "red"


async def execute(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Execute the /mcp command.
    Connects to an MCP server and displays available tools.
    
    Usage:
        /mcp <server_name> <command> [args...]
    
    Example:
        /mcp github npx -y @modelcontextprotocol/server-github
    
    Args:
        args: The arguments after /mcp (server name, command, and args)
        session: The PromptSession instance
        mcp_manager: The MCPManager instance
        session_history: The conversation history list
    """
    if not args:
        console.print(f"\n[{ACCENT_COLOR}][x] Usage: /mcp <name> <command> [args...][/{ACCENT_COLOR}]")
        console.print("[dim]Example: /mcp github npx -y @modelcontextprotocol/server-github[/dim]\n")
        return
    
    parts = args.split()
    if len(parts) < 2:
        console.print(f"[{ACCENT_COLOR}][x] Must provide server name and command[/{ACCENT_COLOR}]")
        return
    
    server_name = parts[0]
    command = parts[1]
    cmd_args = parts[2:] if len(parts) > 2 else []
    
    console.print(f"\n[dim]Connecting to MCP server '{server_name}'...[/dim]")
    console.print(f"[dim]Command: {command} {' '.join(cmd_args)}[/dim]\n")
    
    result = await mcp_manager.connect_server(server_name, command, cmd_args)
    
    if "[ok]" in result or "Successfully" in result:
        console.print(f"[green][ok] Connected to {server_name}[/green]\n")
        
        console.print(f"[dim]Fetching tools...[/dim]")
        tools = await mcp_manager.get_tools(server_name)
        
        if isinstance(tools, list) and tools:
            table = Table(show_header=True, header_style=f"bold {THEME_COLOR}", border_style="dim")
            table.add_column("Tool", style="bold")
            table.add_column("Description", style="dim")
            
            for tool in tools:
                tool_name = tool.get("name", "Unknown")
                description = tool.get("description", "No description")
                # Truncate description if too long
                if len(description) > 50:
                    description = description[:47] + "..."
                table.add_row(tool_name, description)
            
            console.print(table)
            servers = [s["name"] for s in mcp_manager.list_servers()]
            console.print(f"\n[dim]Servers: {', '.join(servers)}[/dim]\n")
        else:
            console.print(f"[dim]No tools found or error: {tools}[/dim]\n")
    else:
        console.print(f"[{ACCENT_COLOR}][x] {result}[/{ACCENT_COLOR}]\n")


async def list_servers_cmd(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    List all connected MCP servers with their status.
    
    Args:
        args: Command arguments (unused)
        session: The PromptSession instance
        mcp_manager: The MCPManager instance
        session_history: The conversation history list
    """
    servers = mcp_manager.list_servers()
    
    if not servers:
        console.print(f"\n[{THEME_COLOR}]No MCP servers connected[/{THEME_COLOR}]")
        console.print("[dim]Use /mcp <name> <command> to connect[/dim]\n")
        return
    
    table = Table(show_header=True, header_style=f"bold {THEME_COLOR}", border_style="dim")
    table.add_column("Name", style="bold")
    table.add_column("State", style="dim")
    table.add_column("Server", style="dim")
    table.add_column("Capabilities", style="dim")
    
    for server in servers:
        name = server.get("name", "Unknown")
        state = server.get("state", "unknown")
        server_name = server.get("server_name", "N/A")
        server_version = server.get("server_version", "")
        
        server_str = f"{server_name}"
        if server_version:
            server_str += f" v{server_version}"
        
        caps = server.get("capabilities", {})
        caps_list = []
        if caps.get("tools"):
            caps_list.append("tools")
        if caps.get("resources"):
            caps_list.append("resources")
        if caps.get("prompts"):
            caps_list.append("prompts")
        caps_str = ", ".join(caps_list) if caps_list else "none"
        
        # Color state
        if state == "ready":
            state_str = "[green]ready[/green]"
        elif state == "error":
            state_str = "[red]error[/red]"
        else:
            state_str = f"[yellow]{state}[/yellow]"
        
        table.add_row(name, state_str, server_str, caps_str)
    
    console.print("\n")
    console.print(table)
    console.print("\n")


async def disconnect_cmd(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Disconnect from an MCP server.
    
    Usage:
        /mcp-disconnect <server_name>
    
    Args:
        args: The server name to disconnect
        session: The PromptSession instance
        mcp_manager: The MCPManager instance
        session_history: The conversation history list
    """
    # If no arg given, show interactive picker
    if not args:
        servers = mcp_manager.list_servers()
        if not servers:
            console.print(f"\n[{ACCENT_COLOR}][x] No MCP servers connected.[/{ACCENT_COLOR}]\n")
            return

        server_names = [s["name"] for s in servers]
        options = ["← Back"] + server_names

        chosen = await arrow_select(
            "Select server to disconnect (↑↓ navigate, Enter confirm, Esc cancel):",
            options
        )

        if chosen is None or chosen == "← Back":
            console.print("[dim]Cancelled[/dim]")
            return

        server_name = chosen
    else:
        server_name = args.strip()

    result = await mcp_manager.disconnect_server(server_name)

    if "[ok]" in result:
        console.print(f"[green]{result}[/green]\n")
    else:
        console.print(f"[{ACCENT_COLOR}]{result}[/{ACCENT_COLOR}]\n")
