"""
RED SHINOBI Erase Model Commands Module

Handles the /erasemodel command for removing models from the catalog.
"""

from rich.console import Console
from prompt_toolkit import PromptSession

from red_shinobi.core.nvidia_catalog import MODEL_CATALOG, clear_catalog
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
    Execute the /erasemodel command.
    Removes one or all models from the catalog.
    
    Usage:
        /erasemodel <model_name>  - Remove specific model
        /erasemodel all           - Remove all models
        /erasemodel failed        - Remove all models that failed verification
    
    Args:
        args: The model name, "all", or "failed"
        session: The PromptSession instance
        mcp_manager: The MCPManager instance
        session_history: The conversation history list
    """
    # If no args, show interactive picker
    if not args:
        model_ids = list(MODEL_CATALOG.keys())
        if not model_ids:
            console.print(f"[{ACCENT_COLOR}][x] Catalog is empty.[/{ACCENT_COLOR}]\n")
            return

        options = ["← Back", "all", "failed"] + model_ids
        chosen = await arrow_select(
            "Select model to erase (↑↓ navigate, Enter confirm, Esc cancel):",
            options
        )

        if chosen is None or chosen == "← Back":
            console.print("[dim]Cancelled[/dim]")
            return

        model_name = chosen
    else:
        model_name = args.strip()
    
    if model_name.lower() == "all":
        # Clear entire catalog
        clear_catalog()
        console.print(f"[green][ok] Catalog cleared.[/green]\n")
    
    elif model_name.lower() == "failed":
        # Remove models that failed verification (ok == False)
        to_remove = [
            model_id for model_id, entry in MODEL_CATALOG.items()
            if entry.get("ok") is False
        ]
        
        if not to_remove:
            console.print(f"[yellow]No failed models to remove.[/yellow]\n")
            return
        
        for model_id in to_remove:
            del MODEL_CATALOG[model_id]
        
        console.print(f"[green][ok] Removed {len(to_remove)} failed models:[/green]")
        for model_id in to_remove[:10]:
            console.print(f"[dim]  - {model_id}[/dim]")
        if len(to_remove) > 10:
            console.print(f"[dim]  ... and {len(to_remove) - 10} more[/dim]")
        
        remaining = len(MODEL_CATALOG)
        console.print(f"[dim]{remaining} models remaining in catalog[/dim]\n")
    
    else:
        # Remove specific model
        if model_name in MODEL_CATALOG:
            del MODEL_CATALOG[model_name]
            console.print(f"[green][ok] Removed: {model_name}[/green]")
            remaining = len(MODEL_CATALOG)
            console.print(f"[dim]{remaining} models remaining in catalog[/dim]\n")
        else:
            console.print(f"[red][x] Model not found: {model_name}[/red]")
            if MODEL_CATALOG:
                console.print(f"[dim]Catalog contains {len(MODEL_CATALOG)} models (run /models to see)[/dim]\n")
            else:
                console.print(f"[dim]Catalog is empty[/dim]\n")
