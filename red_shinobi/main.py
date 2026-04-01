"""
RED SHINOBI - Multi-Agent AI Terminal

Main entry point and command router for the RED SHINOBI CLI.
Single model mode with /set-model command. Tool calling via MCP.
Dynamic model discovery via /models refresh.
"""

import os
import sys
import asyncio
from pathlib import Path
from typing import Callable, Dict, Any, Awaitable, List, Optional

from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import NestedCompleter
from prompt_toolkit.formatted_text import HTML

from red_shinobi.core import brain, config
from red_shinobi.core.mcp_client import MCPManager
from red_shinobi.core.config import reload_keys
from red_shinobi.core.nvidia_catalog import MODEL_CATALOG, get_first_working_model
from red_shinobi.commands import auth_cmds, mcp_cmds, model_cmds, file_cmds

# =============================================================================
# GLOBAL INSTANCES
# =============================================================================

console = Console()
mcp_manager = MCPManager()
session_history: List[str] = []

# Current model state - CLI uses single model at a time
# Can be a friendly name (from MODEL_REGISTRY) or a catalog model ID
current_model: str = brain.DEFAULT_MODEL

# Active model ID from catalog (None until /models refresh is run)
active_model_id: Optional[str] = None

# =============================================================================
# CONFIGURATION
# =============================================================================

THEME_COLOR = "red"
ACCENT_COLOR = "red"


# =============================================================================
# BANNER & UI
# =============================================================================

def load_ascii_banner() -> str:
    """Load the ASCII art banner from ascii-art.txt file."""
    search_paths = [
        Path.cwd() / "ascii-art.txt",
        Path(__file__).parent.parent.parent / "ascii-art.txt",
        Path(__file__).parent.parent / "ascii-art.txt",
        Path(__file__).parent / "ascii-art.txt",
    ]
    
    for path in search_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                continue
    
    return """
    ██████╗ ███████╗██████╗     ███████╗██╗  ██╗██╗███╗   ██╗ ██████╗ ██████╗ ██╗
    ██╔══██╗██╔════╝██╔══██╗    ██╔════╝██║  ██║██║████╗  ██║██╔═══██╗██╔══██╗██║
    ██████╔╝█████╗  ██║  ██║    ███████╗███████║██║██╔██╗ ██║██║   ██║██████╔╝██║
    ██╔══██╗██╔══╝  ██║  ██║    ╚════██║██╔══██║██║██║╚██╗██║██║   ██║██╔══██╗██║
    ██║  ██║███████╗██████╔╝    ███████║██║  ██║██║██║ ╚████║╚██████╔╝██████╔╝██║
    ╚═╝  ╚═╝╚══════╝╚═════╝     ╚══════╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚═════╝ ╚═╝
    """


def print_banner() -> None:
    """Display the RED SHINOBI ASCII banner."""
    banner = load_ascii_banner()
    console.print(banner, style="bold red")
    console.print("[dim]────────────────────────────────────────────────────────[/dim]")
    console.print("[bold red]RED SHINOBI[/bold red] [dim]- Multi-Agent AI Terminal[/dim]")
    console.print("[dim]Made by[/dim] [bold red]Brojen Gurung[/bold red]")
    console.print("[dim]github.com/BrozG[/dim]")
    console.print("[dim]────────────────────────────────────────────────────────[/dim]")
    console.print(f"[dim]Current Model:[/dim] [bold cyan]{current_model}[/bold cyan]")
    console.print("[dim]Use /set-model <name> or /model <name> to switch[/dim]\n")


def get_completer() -> NestedCompleter:
    """Create a dynamic NestedCompleter with available models."""
    available_models = brain.get_all_model_names()
    model_dict = {model_name: None for model_name in available_models}
    at_model_dict = {f"@{model_name}": None for model_name in available_models}
    
    return NestedCompleter.from_nested_dict({
        "/key": None,
        "/models": None,
        "/model": model_dict,
        "/set-model": model_dict,
        "/help": None,
        "/clear": None,
        "/save": None,
        "/chatbox": None,
        "/file": None,
        "/system": model_dict,
        "/mcp": None,
        "/mcp-list": None,
        "/mcp-disconnect": None,
        "/info": model_dict,
        "/read": None,
        "/exit": None,
        "/quit": None,
        **at_model_dict,
    })


# =============================================================================
# COMMANDS
# =============================================================================

def cmd_help() -> None:
    """Display help information."""
    models_list = ", ".join(brain.get_all_model_names()[:5]) + "..."
    
    help_text = f"""
[{THEME_COLOR}]RED SHINOBI Commands[/{THEME_COLOR}]

  [bold]/model[/bold] <name>  Switch to a different model (alias: /set-model)
  [bold]/models[/bold]       List all available models
  [bold]/key[/bold]          Set API keys
  [bold]/system[/bold]       Update model system prompt
  [bold]/info[/bold]         Show model info
  [bold]/chatbox[/bold]      Launch graphical UI (multi-model)
  [bold]/file[/bold]         Query a file with AI
  [bold]/read[/bold]         Display file contents
  [bold]/save[/bold]         Save conversation
  [bold]/mcp[/bold]          Connect to MCP server
  [bold]/mcp-list[/bold]     List MCP servers
  [bold]/mcp-disconnect[/bold] Disconnect MCP server
  [bold]/clear[/bold]        Clear screen
  [bold]/exit[/bold]         Exit

[{THEME_COLOR}]Current Model:[/{THEME_COLOR}] [cyan]{current_model}[/cyan]

[dim]Use @ModelName in message to route to specific model[/dim]
[dim]Available: {models_list}[/dim]
"""
    console.print(help_text)


def cmd_set_model(args: str) -> None:
    """
    Set the current model. Usage: /set-model <ModelName> or /model <ModelName>
    
    Supports both:
    - Friendly names from MODEL_REGISTRY (e.g., Nemotron-4-340B)
    - Catalog model IDs from /models refresh (e.g., meta/llama-3.1-70b-instruct)
    """
    global current_model, active_model_id
    
    model_name = args.strip()
    
    if not model_name:
        console.print(f"[cyan]Current model: {current_model}[/cyan]")
        if active_model_id:
            console.print(f"[dim]Active catalog ID: {active_model_id}[/dim]")
        console.print("[dim]Usage: /model <ModelName or catalog ID>[/dim]")
        console.print(f"[dim]Registry: {', '.join(brain.get_all_model_names()[:5])}...[/dim]")
        if MODEL_CATALOG:
            console.print(f"[dim]Catalog: {len(MODEL_CATALOG)} models (run /models to see)[/dim]")
        return
    
    # First try MODEL_REGISTRY (friendly names)
    normalized = brain.normalize_model_name(model_name)
    if normalized:
        current_model = normalized
        active_model_id = None
        console.print(f"[green]✓ Model set to: {current_model}[/green]")
        return
    
    # Then try MODEL_CATALOG (direct model IDs)
    if model_name in MODEL_CATALOG:
        entry = MODEL_CATALOG[model_name]
        api_key = config.get_env_key(entry["api_key_env"])
        
        if entry["endpoint_type"] != "local" and not api_key:
            console.print(f"[{ACCENT_COLOR}][x] Missing key: {entry['api_key_env']}[/{ACCENT_COLOR}]")
            console.print(f"[dim]Set env var or use: /key {entry['api_key_env']} <value>[/dim]")
            return
        
        active_model_id = model_name
        current_model = model_name
        console.print(f"[green]✓ Model set to catalog ID: {model_name}[/green]")
        return
    
    # Not found anywhere
    console.print(f"[{ACCENT_COLOR}][x] Model not found: {model_name}[/{ACCENT_COLOR}]")
    if MODEL_CATALOG:
        console.print("[dim]Run /models to see available models[/dim]")
    else:
        console.print("[dim]Run /models refresh to discover NVIDIA models[/dim]")


def cmd_chatbox() -> None:
    """Launch the Textual UI with shared MCP manager."""
    console.print("\n[dim]Launching RED SHINOBI UI...[/dim]\n")
    try:
        from red_shinobi.interface.ui import run_ui
        run_ui(mcp_manager=mcp_manager)
        console.print("\n[dim]Back to CLI[/dim]\n")
    except ImportError as e:
        console.print(f"[{ACCENT_COLOR}][x] Textual not installed: {e}[/{ACCENT_COLOR}]")
        console.print("[dim]Install with: pip install textual[/dim]")
    except Exception as e:
        console.print(f"[{ACCENT_COLOR}][x] Error launching UI: {e}[/{ACCENT_COLOR}]")


# =============================================================================
# CONVERSATION HANDLER
# =============================================================================

async def run_conversation(user_input: str) -> None:
    """
    Run 1-on-1 conversation using current_model.
    Passes [current_model] as single-element list to brain.
    """
    global current_model
    
    if not brain.get_all_model_names():
        console.print(f"[{ACCENT_COLOR}][x] No models available. Configure API key with /key[/{ACCENT_COLOR}]")
        return
    
    console.print(f"\n[dim]You:[/dim] {user_input}\n")
    session_history.append(f"**You:** {user_input}")
    
    try:
        conversation = await brain.run_agent_conversation(
            task=user_input,
            active_models=[current_model],
            mode="offline",
            max_turns=2,
            mcp_manager=mcp_manager
        )
        
        for message in conversation:
            model = message.get("model", "Unknown")
            content = message.get("content", "")
            
            console.print(f"[{THEME_COLOR}]{model}:[/{THEME_COLOR}] {content}\n")
            session_history.append(f"**{model}:** {content}")
            
    except Exception as e:
        console.print(f"[{ACCENT_COLOR}][x] Error: {e}[/{ACCENT_COLOR}]\n")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


# =============================================================================
# COMMAND REGISTRY
# =============================================================================

COMMAND_REGISTRY: Dict[str, Callable[..., Awaitable[None]]] = {
    "/key": auth_cmds.execute,
    "/models": model_cmds.execute,
    "/system": model_cmds.system_execute,
    "/info": model_cmds.info_execute,
    "/file": file_cmds.execute,
    "/save": file_cmds.save_execute,
    "/read": file_cmds.read_execute,
    "/mcp": mcp_cmds.execute,
    "/mcp-list": mcp_cmds.list_servers_cmd,
    "/mcp-disconnect": mcp_cmds.disconnect_cmd,
}

SYNC_COMMANDS: Dict[str, Callable[..., None]] = {
    "/help": lambda: cmd_help(),
    "/chatbox": lambda: cmd_chatbox(),
}


async def handle_command(user_input: str, session: PromptSession) -> bool:
    """Route commands. Returns False to exit."""
    parts = user_input.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    
    if cmd in ["/exit", "/quit"]:
        console.print(f"[{THEME_COLOR}]Goodbye from RED SHINOBI[/{THEME_COLOR}]")
        await mcp_manager.cleanup()
        return False
    
    if cmd == "/clear":
        os.system("cls" if os.name == "nt" else "clear")
        print_banner()
        return True
    
    if cmd in ["/model", "/set-model"]:
        cmd_set_model(args)
        return True
    
    if cmd in SYNC_COMMANDS:
        SYNC_COMMANDS[cmd]()
        return True
    
    if cmd in COMMAND_REGISTRY:
        handler = COMMAND_REGISTRY[cmd]
        await handler(args, session, mcp_manager, session_history)
        return True
    
    console.print(f"[{ACCENT_COLOR}][x] Unknown command: {cmd}[/{ACCENT_COLOR}]")
    console.print("[dim]Type /help for commands[/dim]")
    return True


# =============================================================================
# MAIN LOOP
# =============================================================================

async def main_loop() -> None:
    """Main CLI loop."""
    print_banner()
    auth_cmds.check_api_keys()
    
    session: PromptSession = PromptSession(completer=get_completer())
    
    while True:
        try:
            user_input = await session.prompt_async(
                HTML(f"<b><ansired>{current_model[:15]}></ansired></b> ")
            )
            user_input = user_input.strip()
            
            if not user_input:
                continue
            
            if user_input.startswith("/"):
                should_continue = await handle_command(user_input, session)
                if not should_continue:
                    sys.exit(0)
            else:
                await run_conversation(user_input)
                
        except KeyboardInterrupt:
            console.print(f"\n[dim]Use /exit to quit[/dim]")
        except EOFError:
            console.print(f"\n[{THEME_COLOR}]Goodbye[/{THEME_COLOR}]")
            await mcp_manager.cleanup()
            sys.exit(0)
        except Exception as e:
            console.print(f"[{ACCENT_COLOR}][x] Error: {e}[/{ACCENT_COLOR}]")


def main() -> None:
    """Entry point for the 'red' command."""
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
