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
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML

from red_shinobi.core import brain, config
from red_shinobi.core.mcp_client import MCPManager
from red_shinobi.core.config import reload_keys
from red_shinobi.core.nvidia_catalog import MODEL_CATALOG, get_first_working_model
from red_shinobi.commands import auth_cmds, mcp_cmds, model_cmds, file_cmds, erasemodel_cmds, refresh_cmds

# =============================================================================
# GLOBAL INSTANCES
# =============================================================================

console = Console()
mcp_manager = MCPManager()
session_history: List[str] = []
chat_history: List[Dict[str, Any]] = []

# Current model state - CLI uses single model at a time
# Can be a friendly name (from MODEL_REGISTRY) or a catalog model ID
# None until user selects with /set
current_model: Optional[str] = None

# Active model ID from catalog (None until /models refresh is run)
active_model_id: Optional[str] = None

# =============================================================================
# CONFIGURATION
# =============================================================================

THEME_COLOR = "red"
ACCENT_COLOR = "red"


# =============================================================================
# CUSTOM COMPLETER
# =============================================================================

class RedShinobiCompleter(Completer):
    """Custom completer for RED SHINOBI with command and model completion."""
    
    COMMANDS = [
        "/key",
        "/models",
        "/set",
        "/refresh",
        "/erasemodel",
        "/help",
        "/clear",
        "/save",
        "/chatbox",
        "/file",
        "/system",
        "/mcp",
        "/mcp-list",
        "/mcp-disconnect",
        "/info",
        "/read",
        "/exit",
    ]
    
    def get_completions(self, document: Document, complete_event):
        """Generate completions based on current input."""
        text = document.text_before_cursor
        
        # Model completion with @
        if "@" in text:
            # Get the part after the last @
            at_index = text.rfind("@")
            prefix = text[at_index + 1:]
            
            # Complete with models from catalog
            for model_id in MODEL_CATALOG.keys():
                if model_id.lower().startswith(prefix.lower()):
                    yield Completion(
                        model_id,
                        start_position=-len(prefix),
                        display=f"@{model_id}",
                        display_meta="model"
                    )
        
        # Command completion with /
        elif text.startswith("/"):
            for cmd in self.COMMANDS:
                if cmd.startswith(text):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=cmd,
                        display_meta="command"
                    )


def get_completer() -> RedShinobiCompleter:
    """Create a dynamic completer with available commands and models."""
    return RedShinobiCompleter()


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
    console.print("[dim]Quick start: /key → /models → /set @<name>[/dim]\n")


# =============================================================================
# COMMANDS
# =============================================================================

def cmd_help() -> None:
    """Display help information."""
    model_display = f"[cyan]{current_model[:50] if current_model else '<no-model>'}[/cyan]" if current_model else "[yellow]<no-model>[/yellow]"
    
    help_text = f"""
[{THEME_COLOR}]RED SHINOBI[/{THEME_COLOR}] - Quick Reference

[bold]Setup & Model Management[/bold]
  /key              Add API keys and models
  /models           List all models in catalog
  /set <id>         Select a model (use @ to autocomplete)
  /refresh          Verify models in catalog
  /erasemodel       Remove model(s) from catalog

[bold]Chat & Files[/bold]
  /file <path>      Query a file with AI
  /read <path>      Display file contents
  /save             Save conversation to markdown

[bold]MCP Servers[/bold]
  /mcp <name> <cmd> Connect MCP server via stdio
                    e.g. /mcp github npx -y @modelcontextprotocol/server-github
                    <name> = your label, <cmd> = shell command to launch server
  /mcp-list         Show connected servers
  /mcp-disconnect   Disconnect server (no arg = interactive picker)

[bold]System[/bold]
  /chatbox          Launch graphical UI
  /system           Update model system prompt
  /info             Show model details
  /clear            Clear screen
  /help             Show this help
  /exit             Exit RED SHINOBI

[{THEME_COLOR}]Current Model:[/{THEME_COLOR}] {model_display}

[dim]Quick Start:[/dim]
  [dim]1. /key → select provider → enter API key (models added automatically)[/dim]
  [dim]2. /models → see all available models[/dim]
  [dim]3. /set <name> → start chatting (type @ to autocomplete)[/dim]
  [dim]4. /refresh → verify models work (optional)[/dim]
"""
    console.print(help_text)


def cmd_set_model(args: str) -> None:
    """
    Set the current model. Usage: /set <model_id>
    
    Only accepts models from MODEL_CATALOG (discovered via /models refresh or /models add).
    """
    global current_model, active_model_id
    
    model_id = args.strip()
    # Strip @ prefix if present (from autocomplete)
    if model_id.startswith("@"):
        model_id = model_id[1:]
    
    if not model_id:
        if current_model:
            console.print(f"[cyan]Current model: {current_model}[/cyan]")
        else:
            console.print("[yellow]No model selected.[/yellow]")
        console.print("[dim]Usage: /set <model_id>[/dim]")
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
    
    # Check for known incompatible model patterns
    incompatible_patterns = ["guard", "moderation", "classifier", "safety"]
    is_likely_incompatible = any(pattern in model_id.lower() for pattern in incompatible_patterns)
    
    # Show verification status if available
    if entry.get("ok") is True:
        console.print(f"[dim]Status: Verified ({entry.get('latency_ms')}ms)[/dim]")
    elif entry.get("ok") is False:
        error = entry.get("error", "")
        if "400" in str(error) or "BadRequest" in str(error) or is_likely_incompatible:
            console.print(f"[yellow]⚠ WARNING: This model appears incompatible with standard chat API[/yellow]")
            console.print(f"[dim]It may be a classifier/safety model, not a chat model. Use /erasemodel to remove.[/dim]")
        else:
            console.print(f"[yellow]⚠ Model failed verification, but you can try it anyway[/yellow]")
    else:
        if is_likely_incompatible:
            console.print(f"[yellow]⚠ Note: Model name suggests it may not be a standard chat model[/yellow]")
        console.print(f"[dim]Run /refresh to test this model[/dim]")



async def cmd_chatbox(
    args: str,
    session: PromptSession,
    mcp_manager_param: MCPManager,
    session_history: list
) -> None:
    """Launch the Textual UI with shared MCP manager."""
    console.print("\n[dim]Launching RED SHINOBI UI...[/dim]\n")
    try:
        from red_shinobi.interface.ui import RedShinobiApp
        app = RedShinobiApp(mcp_manager=mcp_manager)
        await app.run_async()
        console.print("\n[dim]Back to CLI[/dim]\n")
    except ImportError as e:
        console.print(f"[{ACCENT_COLOR}][x] Textual not installed: {e}[/{ACCENT_COLOR}]")
        console.print("[dim]Install with: pip install textual[/dim]")
    except Exception as e:
        console.print(f"[{ACCENT_COLOR}][x] Error launching UI: {e}[/{ACCENT_COLOR}]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


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
        console.print("[dim]Quick start:[/dim]")
        console.print("[dim]  1. /key         - Add API key (models added automatically)[/dim]")
        console.print("[dim]  2. /models      - List available models[/dim]")
        console.print("[dim]  3. /set @...    - Select a model (@ to autocomplete)[/dim]\n")
        return
    
    console.print(f"\n[dim]You:[/dim] {user_input}\n")
    session_history.append(f"**You:** {user_input}")
    chat_history.append({"role": "user", "content": user_input})
    
    try:
        conversation = await brain.run_agent_conversation(
            task=user_input,
            active_models=[current_model],
            mode="offline",
            max_turns=2,
            mcp_manager=mcp_manager,
            chat_history=chat_history
        )
        
        for message in conversation:
            model = message.get("model", "Unknown")
            content = message.get("content", "")
            
            console.print(f"[{THEME_COLOR}]{model}:[/{THEME_COLOR}] {content}\n")
            session_history.append(f"**{model}:** {content}")
            chat_history.append({"role": "assistant", "content": content})
            
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
    "/refresh": refresh_cmds.execute,
    "/system": model_cmds.system_execute,
    "/info": model_cmds.info_execute,
    "/file": file_cmds.execute,
    "/save": file_cmds.save_execute,
    "/read": file_cmds.read_execute,
    "/mcp": mcp_cmds.execute,
    "/mcp-list": mcp_cmds.list_servers_cmd,
    "/mcp-disconnect": mcp_cmds.disconnect_cmd,
    "/erasemodel": erasemodel_cmds.execute,
    "/chatbox": cmd_chatbox,
}

SYNC_COMMANDS: Dict[str, Callable[..., None]] = {
    "/help": lambda: cmd_help(),
}


async def handle_command(user_input: str, session: PromptSession) -> bool:
    """Route commands. Returns False to exit."""
    parts = user_input.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    
    if cmd == "/exit":
        console.print(f"[{THEME_COLOR}]Goodbye from RED SHINOBI[/{THEME_COLOR}]")
        await mcp_manager.cleanup()
        return False
    
    if cmd == "/clear":
        global chat_history
        chat_history = []
        os.system("cls" if os.name == "nt" else "clear")
        print_banner()
        return True
    
    if cmd == "/set":
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
                HTML("<b><ansired>Red Shinobi</ansired></b> <ansibrightblack>›</ansibrightblack> ")
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
