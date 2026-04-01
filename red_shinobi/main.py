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
# None until user selects with /model
current_model: Optional[str] = None

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
    model_display = current_model if current_model else "[yellow]<no-model>[/yellow]"
    console.print(f"[dim]Current Model:[/dim] {model_display}")
    console.print("[dim]Get started: /key → /models refresh → /model <id>[/dim]\n")


def get_completer() -> NestedCompleter:
    """Create a dynamic NestedCompleter with available commands."""
    return NestedCompleter.from_nested_dict({
        "/key": None,
        "/models": None,
        "/model": None,
        "/set-model": None,
        "/help": None,
        "/clear": None,
        "/save": None,
        "/chatbox": None,
        "/file": None,
        "/system": None,
        "/mcp": None,
        "/mcp-list": None,
        "/mcp-disconnect": None,
        "/info": None,
        "/read": None,
        "/exit": None,
        "/quit": None,
    })


# =============================================================================
# COMMANDS
# =============================================================================

def cmd_help() -> None:
    """Display help information."""
    model_display = f"[cyan]{current_model[:50] if current_model else '<no-model>'}[/cyan]" if current_model else "[yellow]<no-model>[/yellow]"
    
    help_text = f"""
[{THEME_COLOR}]RED SHINOBI Commands[/{THEME_COLOR}]

  [bold]/key[/bold] <provider>  Set API keys (NVIDIA, OpenAI, etc.)
  [bold]/models refresh[/bold]  Discover models from NVIDIA endpoints
  [bold]/models add[/bold]      Add custom OpenAI-compatible endpoint
  [bold]/models verify[/bold]   Verify models are working
  [bold]/models[/bold]       Show catalog entries
  [bold]/model[/bold] <id>   Select a model from catalog
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

[{THEME_COLOR}]Current Model:[/{THEME_COLOR}] {model_display}

[dim]Getting started:[/dim]
  [dim]1. /key NVIDIA <your_key>     - Set your NVIDIA_API_KEY[/dim]
  [dim]2. /models refresh            - Discover available models[/dim]
  [dim]3. /models verify --limit 10  - Test models (optional)[/dim]
  [dim]4. /model <id>                - Select a model[/dim]
"""
    console.print(help_text)


def cmd_set_model(args: str) -> None:
    """
    Set the current model. Usage: /set-model <model_id> or /model <model_id>
    
    Only accepts models from MODEL_CATALOG (discovered via /models refresh or /models add).
    """
    global current_model, active_model_id
    
    model_id = args.strip()
    
    if not model_id:
        if current_model:
            console.print(f"[cyan]Current model: {current_model}[/cyan]")
        else:
            console.print("[yellow]No model selected.[/yellow]")
        console.print("[dim]Usage: /model <model_id>[/dim]")
        if MODEL_CATALOG:
            console.print(f"[dim]Catalog: {len(MODEL_CATALOG)} models (run /models to see)[/dim]")
        else:
            console.print("[dim]Run /models refresh to discover models[/dim]")
        return
    
    # Check MODEL_CATALOG only
    if model_id not in MODEL_CATALOG:
        console.print(f"[{ACCENT_COLOR}][x] Model '{model_id}' not in catalog.[/{ACCENT_COLOR}]")
        if MODEL_CATALOG:
            console.print(f"[dim]Run /models to see {len(MODEL_CATALOG)} available models[/dim]")
        else:
            console.print("[dim]Run /models refresh to discover models[/dim]")
        return
    
    # Check key requirement
    entry = MODEL_CATALOG[model_id]
    api_key_env = entry["api_key_env"]
    endpoint_type = entry["endpoint_type"]
    
    api_key = config.get_env_key(api_key_env) if api_key_env else None
    
    if endpoint_type != "local" and not api_key:
        console.print(f"[{ACCENT_COLOR}][x] Missing API key: {api_key_env}[/{ACCENT_COLOR}]")
        console.print(f"[dim]Set with: export {api_key_env}=<your_key> or use /key[/dim]")
        return
    
    # Set the model
    current_model = model_id
    active_model_id = model_id
    console.print(f"[green]✓ Model set to: {model_id}[/green]")
    
    # Show verification status if available
    if entry.get("ok") is True:
        console.print(f"[dim]Status: Verified ({entry.get('latency_ms')}ms)[/dim]")
    elif entry.get("ok") is False:
        console.print(f"[yellow]⚠ Model failed verification, but you can try it anyway[/yellow]")
    else:
        console.print(f"[dim]Run /models verify to test this model[/dim]")



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
    
    # Check if model is selected
    if current_model is None:
        console.print(f"\n[{ACCENT_COLOR}][x] No model selected.[/{ACCENT_COLOR}]")
        console.print("[dim]Get started:[/dim]")
        console.print("[dim]  1. /key              - Set your NVIDIA_API_KEY[/dim]")
        console.print("[dim]  2. /models refresh   - Discover available models[/dim]")
        console.print("[dim]  3. /models verify    - Test models (optional)[/dim]")
        console.print("[dim]  4. /model <id>       - Select a model to use[/dim]\n")
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
            prompt_display = current_model[:15] if current_model else "&lt;no-model&gt;"
            user_input = await session.prompt_async(
                HTML(f"<b><ansired>RedShinobi{prompt_display}></ansired></b> ")
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
