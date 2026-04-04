"""
RED SHINOBI Authentication Commands Module

Handles the /key command for API key configuration and verification.
"""

import os
from typing import Optional

import httpx
from dotenv import set_key, load_dotenv, dotenv_values
from openai import OpenAI, AuthenticationError
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.formatted_text import FormattedText

from red_shinobi.core import config
from red_shinobi.core.mcp_client import MCPManager
from red_shinobi.core.nvidia_catalog import add_to_catalog

console = Console()
THEME_COLOR = "red"
ACCENT_COLOR = "red"


def check_api_keys() -> None:
    """
    Check which API keys are loaded from os.getenv without crashing.
    Displays status for NVIDIA, OPENAI, and ANTHROPIC providers.
    """
    console.print(f"\n[{THEME_COLOR}]API Key Status:[/{THEME_COLOR}]")
    providers = ["NVIDIA", "OPENAI", "ANTHROPIC"]
    status_symbols = []
    
    # Read fresh values from .env file
    env_values = dotenv_values(".env") if os.path.exists(".env") else {}
    
    for provider in providers:
        key = env_values.get(f"{provider}_API_KEY")
        if key:
            status_symbols.append(f"[green]{provider} [/green][dim]|[/dim]")
        else:
            status_symbols.append(f"[dim]{provider}[/dim] [dim]|[/dim]")
    console.print(" ".join(status_symbols).rstrip(" [dim]|[/dim]"))
    console.print()


async def arrow_select(prompt_text: str, options: list[str]) -> Optional[str]:
    """
    Pure terminal inline arrow-key selector using prompt_toolkit.
    
    Args:
        prompt_text: Text to display above the options
        options: List of option strings
    
    Returns:
        Selected option string, or None if cancelled
    """
    selected_index = [0]
    result = [None]
    
    def get_formatted_text():
        lines = [(("", prompt_text + "\n"))]
        for i, option in enumerate(options):
            if i == selected_index[0]:
                lines.append(("bold red", f"> {option}\n"))
            else:
                lines.append(("fg:gray", f"  {option}\n"))
        return FormattedText(lines)
    
    kb = KeyBindings()
    
    @kb.add("up")
    def move_up(event):
        selected_index[0] = (selected_index[0] - 1) % len(options)
    
    @kb.add("down")
    def move_down(event):
        selected_index[0] = (selected_index[0] + 1) % len(options)
    
    @kb.add("enter")
    def select(event):
        result[0] = options[selected_index[0]]
        event.app.exit()
    
    @kb.add("escape")
    @kb.add("c-c")
    def cancel(event):
        result[0] = None
        event.app.exit()
    
    control = FormattedTextControl(get_formatted_text, focusable=True)
    window = Window(control, always_hide_cursor=True)
    layout = Layout(window)
    
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=False,
        mouse_support=False
    )
    
    await app.run_async()
    
    # Clear selector UI by moving cursor up and clearing lines
    lines_to_clear = len(options) + 1
    for _ in range(lines_to_clear):
        print("\033[F\033[K", end="")
    
    if result[0]:
        console.print(f"[dim]  provider › {result[0]}[/dim]")
    
    return result[0]


async def execute(
    args: str,
    session: PromptSession,
    mcp_manager: MCPManager,
    session_history: list
) -> None:
    """
    Execute the /key command.
    Prompts user to select a provider and enter their API key.
    Saves to .env file.
    """
    console.print(f"\n[{THEME_COLOR}]API Key Management:[/{THEME_COLOR}]")
    
    # Build menu options
    options = ["NVIDIA", "OPENAI", "ANTHROPIC", "Custom", "Update Existing Key"]
    
    provider_name = await arrow_select(
        "Select an option:",
        options
    )
    
    if provider_name is None:
        console.print("[dim]Cancelled[/dim]")
        return
    
    env_path = ".env"
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            f.write("# RED SHINOBI Environment Configuration\n")
    
    # Update existing key flow
    if provider_name == "Update Existing Key":
        await _update_existing_key(env_path)
        return
    
    # Read fresh values from .env file
    env_values = dotenv_values(env_path)
    
    # NVIDIA flow
    if provider_name == "NVIDIA":
        env_key = "NVIDIA_API_KEY"
        existing_key = env_values.get(env_key)
        
        if existing_key:
            console.print(f"[dim]NVIDIA API key already configured[/dim]")
            api_key = existing_key
        else:
            api_key = console.input(f"[{THEME_COLOR}]Enter NVIDIA API key:[/{THEME_COLOR}] ").strip()
            if not api_key:
                console.print(f"[{ACCENT_COLOR}][x] API key cannot be empty[/{ACCENT_COLOR}]")
                return
            
            set_key(env_path, env_key, api_key)
            load_dotenv(override=True)
            config.API_KEYS["nvidia"] = api_key
            config.reload_keys()
            console.print(f"[green][ok] NVIDIA API key saved[/green]")
        
        # Model adding loop
        console.print(f"\n[dim]Add models (type model name or leave blank to finish):[/dim]")
        
        while True:
            model_name = await session.prompt_async("model name > ")
            model_name = model_name.strip()
            
            if not model_name:
                console.print(f"[green][ok] Done[/green]\n")
                break
            
            # Test model
            console.print(f"[dim]Testing model '{model_name}'...[/dim]")
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://integrate.api.nvidia.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": model_name,
                            "messages": [{"role": "user", "content": "hi"}],
                            "max_tokens": 1
                        },
                        timeout=15.0
                    )
                    
                    if response.status_code == 200:
                        add_to_catalog(
                            model_id=model_name,
                            base_url="https://integrate.api.nvidia.com/v1",
                            endpoint_type="nvidia_free",
                            api_key_env="NVIDIA_API_KEY",
                            source="user"
                        )
                        console.print(f"[green][ok] Model added: {model_name}[/green]")
                    elif response.status_code == 401:
                        console.print(f"[{ACCENT_COLOR}][x] Invalid API key - use 'Update Existing Key' to fix[/{ACCENT_COLOR}]")
                    elif response.status_code == 403:
                        console.print(f"[{ACCENT_COLOR}][x] API key expired/forbidden - use 'Update Existing Key' to fix[/{ACCENT_COLOR}]")
                    elif response.status_code == 404:
                        # Try image endpoint
                        console.print(f"[dim]Not a chat model, trying image endpoint...[/dim]")
                        image_response = await client.post(
                            "https://integrate.api.nvidia.com/v1/images/generations",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json"
                            },
                            json={
                                "model": model_name,
                                "prompt": "a red circle",
                                "n": 1
                            },
                            timeout=15.0
                        )
                        
                        if image_response.status_code == 200:
                            add_to_catalog(
                                model_id=model_name,
                                base_url="https://integrate.api.nvidia.com/v1",
                                endpoint_type="nvidia_free_image",
                                api_key_env="NVIDIA_API_KEY",
                                source="user"
                            )
                            console.print(f"[green][ok] Image model added: {model_name}[/green]")
                        else:
                            console.print(f"[{ACCENT_COLOR}][x] Model not found: {model_name}[/{ACCENT_COLOR}]")
                    else:
                        console.print(f"[{ACCENT_COLOR}][x] Error {response.status_code}[/{ACCENT_COLOR}]")
            except Exception as e:
                console.print(f"[{ACCENT_COLOR}][x] Error: {str(e)}[/{ACCENT_COLOR}]")
    
    # OPENAI flow
    elif provider_name == "OPENAI":
        env_key = "OPENAI_API_KEY"
        existing_key = env_values.get(env_key)
        
        if existing_key:
            console.print(f"[dim]OPENAI API key already configured[/dim]")
            api_key = existing_key
        else:
            api_key = console.input(f"[{THEME_COLOR}]Enter OPENAI API key:[/{THEME_COLOR}] ").strip()
            if not api_key:
                console.print(f"[{ACCENT_COLOR}][x] API key cannot be empty[/{ACCENT_COLOR}]")
                return
        
        set_key(env_path, env_key, api_key)
        load_dotenv(override=True)
        config.API_KEYS["openai"] = api_key
        config.reload_keys()
        
        # Fetch models
        console.print(f"[dim]Fetching available models...[/dim]")
        try:
            client = OpenAI(api_key=api_key)
            models_response = client.models.list()
            model_count = 0
            
            for model_obj in models_response.data:
                add_to_catalog(
                    model_id=model_obj.id,
                    base_url="https://api.openai.com/v1",
                    endpoint_type="openai",
                    api_key_env="OPENAI_API_KEY",
                    source="refresh"
                )
                model_count += 1
            
            console.print(f"[green][ok] OPENAI key saved. {model_count} models added.[/green]\n")
        except Exception as e:
            console.print(f"[{ACCENT_COLOR}][x] Error: {str(e)}[/{ACCENT_COLOR}]")
            console.print(f"[yellow]Key saved but model fetch failed. Use 'Update Existing Key' if key is wrong.[/yellow]\n")
    
    # ANTHROPIC flow
    elif provider_name == "ANTHROPIC":
        env_key = "ANTHROPIC_API_KEY"
        existing_key = env_values.get(env_key)
        
        if existing_key:
            console.print(f"[green][ok] ANTHROPIC API key already configured[/green]\n")
            return
        
        api_key = console.input(f"[{THEME_COLOR}]Enter ANTHROPIC API key:[/{THEME_COLOR}] ").strip()
        if not api_key:
            console.print(f"[{ACCENT_COLOR}][x] API key cannot be empty[/{ACCENT_COLOR}]")
            return
        
        if not api_key.startswith("sk-ant-"):
            console.print(f"[{ACCENT_COLOR}][x] Invalid format. Must start with sk-ant-[/{ACCENT_COLOR}]")
            return
        
        set_key(env_path, env_key, api_key)
        load_dotenv(override=True)
        config.API_KEYS["anthropic"] = api_key
        config.reload_keys()
        console.print(f"[green][ok] ANTHROPIC API key saved[/green]\n")
    
    # Custom flow
    elif provider_name == "Custom":
        provider = console.input(f"[{THEME_COLOR}]Provider name (e.g. GROQ):[/{THEME_COLOR}] ").strip().upper()
        if not provider:
            console.print(f"[{ACCENT_COLOR}][x] Provider name cannot be empty[/{ACCENT_COLOR}]")
            return
        
        base_url = console.input(f"[{THEME_COLOR}]Base URL (e.g. https://api.groq.com/v1):[/{THEME_COLOR}] ").strip()
        if not base_url:
            console.print(f"[{ACCENT_COLOR}][x] Base URL cannot be empty[/{ACCENT_COLOR}]")
            return
        
        api_key = console.input(f"[{THEME_COLOR}]API Key:[/{THEME_COLOR}] ").strip()
        if not api_key:
            console.print(f"[{ACCENT_COLOR}][x] API key cannot be empty[/{ACCENT_COLOR}]")
            return
        
        console.print(f"[dim]Fetching models...[/dim]")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0
                )
                
                if response.status_code != 200:
                    console.print(f"[{ACCENT_COLOR}][x] Failed: HTTP {response.status_code}[/{ACCENT_COLOR}]")
                    return
                
                models_data = response.json()
                model_ids = [m["id"] for m in models_data.get("data", [])]
                
                if not model_ids:
                    console.print(f"[{ACCENT_COLOR}][x] No models found[/{ACCENT_COLOR}]")
                    return
                
                env_key = f"{provider}_API_KEY"
                set_key(env_path, env_key, api_key)
                load_dotenv(override=True)
                config.API_KEYS[provider.lower()] = api_key
                config.reload_keys()
                
                for model_id in model_ids:
                    add_to_catalog(
                        model_id=model_id,
                        base_url=base_url,
                        endpoint_type="custom",
                        api_key_env=env_key,
                        source="custom"
                    )
                
                console.print(f"[green][ok] {provider} saved. {len(model_ids)} models added.[/green]\n")
        
        except Exception as e:
            console.print(f"[{ACCENT_COLOR}][x] Error: {str(e)}[/{ACCENT_COLOR}]")


async def _update_existing_key(env_path: str) -> None:
    """Update an existing API key."""
    # Read directly from .env file (not os.getenv which may have stale values)
    env_values = dotenv_values(env_path)
    
    # Find existing keys
    existing_keys = []
    key_map = {
        "NVIDIA_API_KEY": "NVIDIA",
        "OPENAI_API_KEY": "OPENAI", 
        "ANTHROPIC_API_KEY": "ANTHROPIC"
    }
    
    for env_var, name in key_map.items():
        if env_values.get(env_var):
            existing_keys.append(name)
    
    if not existing_keys:
        console.print(f"[yellow]No existing API keys found. Add a new provider first.[/yellow]")
        return
    
    existing_keys.append("Cancel")
    
    selected = await arrow_select(
        "Select key to update:",
        existing_keys
    )
    
    if selected is None or selected == "Cancel":
        console.print("[dim]Cancelled[/dim]")
        return
    
    env_var = f"{selected}_API_KEY"
    
    # Show current key from .env file (masked)
    current_key = env_values.get(env_var, "")
    if current_key:
        masked = current_key[:10] + "..." + current_key[-5:]
        console.print(f"[dim]Current: {masked}[/dim]")
    
    new_key = console.input(f"[{THEME_COLOR}]Enter new {selected} API key:[/{THEME_COLOR}] ").strip()
    
    if not new_key:
        console.print(f"[{ACCENT_COLOR}][x] API key cannot be empty[/{ACCENT_COLOR}]")
        return
    
    # Validate Anthropic format
    if selected == "ANTHROPIC" and not new_key.startswith("sk-ant-"):
        console.print(f"[{ACCENT_COLOR}][x] Invalid format. Must start with sk-ant-[/{ACCENT_COLOR}]")
        return
    
    # Save new key
    set_key(env_path, env_var, new_key)
    load_dotenv(override=True)
    config.API_KEYS[selected.lower()] = new_key
    config.reload_keys()
    
    console.print(f"[green][ok] {selected} API key updated![/green]\n")
