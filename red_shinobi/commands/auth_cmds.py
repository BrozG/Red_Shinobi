"""
RED SHINOBI Authentication Commands Module

Handles the /key command for API key configuration and verification.
"""

import os
from typing import Optional

import httpx
from dotenv import set_key, load_dotenv
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
    for provider in providers:
        key = os.getenv(f"{provider}_API_KEY")
        if key:
            status_symbols.append(f"[green]{provider} [/green][dim]|[/dim]")
        else:
            status_symbols.append(f"[dim]{provider}[/dim] [dim]|[/dim]")
    console.print(" ".join(status_symbols).rstrip(" [dim]|[/dim]"))
    console.print()


def verify_api_key(provider: str, key: str) -> tuple:
    """
    Verify an API key by making a real request to the provider's servers.
    
    Args:
        provider: Provider name (NVIDIA, OPENAI, ANTHROPIC)
        key: The API key to verify
    
    Returns:
        tuple: (is_valid: bool, message: str)
    """
    try:
        if provider == "NVIDIA":
            client = OpenAI(api_key=key, base_url="https://integrate.api.nvidia.com/v1")
            try:
                client.models.list()
                return True, "Valid"
            except AuthenticationError:
                return False, "Invalid API Key"
            except Exception as e:
                return False, f"Connection error: {str(e)}"
        
        elif provider == "OPENAI":
            client = OpenAI(api_key=key)
            try:
                client.models.list()
                return True, "Valid"
            except AuthenticationError:
                return False, "Invalid API Key"
            except Exception as e:
                return False, f"Connection error: {str(e)}"
        
        elif provider == "ANTHROPIC":
            if key.startswith("sk-ant-"):
                return True, "Format valid"
            else:
                return False, "Must start with sk-ant-"
        
        else:
            return True, "OK"
    
    except Exception as e:
        return False, f"Error: {str(e)}"


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
    Verifies the key and saves to .env file.
    
    Args:
        args: Command arguments (unused for /key)
        session: The PromptSession instance
        mcp_manager: The MCPManager instance
        session_history: The conversation history list
    """
    console.print(f"\n[{THEME_COLOR}]Select Provider:[/{THEME_COLOR}]")
    
    provider_name = await arrow_select(
        "Use arrow keys to select, Enter to confirm:",
        ["NVIDIA", "OPENAI", "ANTHROPIC", "Custom"]
    )
    
    if provider_name is None:
        console.print("[dim]Cancelled[/dim]")
        return
    
    env_path = ".env"
    if not os.path.exists(env_path):
        with open(env_path, "w") as f:
            f.write("# RED SHINOBI Environment Configuration\n")
    
    # NVIDIA flow
    if provider_name == "NVIDIA":
        env_key = "NVIDIA_API_KEY"
        existing_key = os.getenv(env_key)
        
        if not existing_key:
            api_key = console.input(f"[{THEME_COLOR}]Enter NVIDIA API key:[/{THEME_COLOR}] ").strip()
            if not api_key:
                console.print(f"[{ACCENT_COLOR}][x] API key cannot be empty[/{ACCENT_COLOR}]")
                return
            
            console.print(f"\n[dim]Verifying key...[/dim]")
            is_valid, msg = verify_api_key("NVIDIA", api_key)
            
            if not is_valid:
                console.print(f"[{ACCENT_COLOR}][x] Authentication failed: {msg}[/{ACCENT_COLOR}]")
                return
            
            set_key(env_path, env_key, api_key)
            load_dotenv(override=True)
            config.API_KEYS["nvidia"] = api_key
            config.reload_keys()
            console.print(f"[green][ok] NVIDIA API key saved[/green]")
        else:
            api_key = existing_key
            console.print(f"[dim]NVIDIA API key already configured[/dim]")
        
        # Model adding loop
        console.print(f"\n[dim]NVIDIA key ready. Add your first model:[/dim]")
        
        while True:
            model_name = await session.prompt_async("model name > ")
            model_name = model_name.strip()
            
            if not model_name:
                continue
            
            # Test model by calling NVIDIA endpoint (two-step verification)
            console.print(f"[dim]Testing model '{model_name}'...[/dim]")
            try:
                async with httpx.AsyncClient() as client:
                    # Step 1: Try chat endpoint
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
                        timeout=10.0
                    )
                    
                    if response.status_code in [200, 400]:
                        # Chat endpoint success
                        add_to_catalog(
                            model_id=model_name,
                            base_url="https://integrate.api.nvidia.com/v1",
                            endpoint_type="nvidia_free",
                            api_key_env="NVIDIA_API_KEY",
                            source="user"
                        )
                        console.print(f"[green][ok] Model added to catalog: {model_name}[/green]")
                    elif response.status_code == 401:
                        console.print(f"[{ACCENT_COLOR}][x] Invalid API key[/{ACCENT_COLOR}]")
                    elif response.status_code == 404:
                        # Step 2: Try image endpoint
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
                            timeout=10.0
                        )
                        
                        if image_response.status_code in [200, 400]:
                            # Image endpoint success
                            add_to_catalog(
                                model_id=model_name,
                                base_url="https://integrate.api.nvidia.com/v1",
                                endpoint_type="nvidia_free_image",
                                api_key_env="NVIDIA_API_KEY",
                                source="user"
                            )
                            console.print(f"[green][ok] Model added to catalog: {model_name}[/green]")
                        elif image_response.status_code == 404:
                            console.print(f"[{ACCENT_COLOR}][x] Model not found: {model_name}[/{ACCENT_COLOR}]")
                        elif image_response.status_code == 401:
                            console.print(f"[{ACCENT_COLOR}][x] Invalid API key[/{ACCENT_COLOR}]")
                        else:
                            console.print(f"[{ACCENT_COLOR}][x] Error {image_response.status_code}: {image_response.text[:100]}[/{ACCENT_COLOR}]")
                    else:
                        console.print(f"[{ACCENT_COLOR}][x] Error {response.status_code}: {response.text[:100]}[/{ACCENT_COLOR}]")
            except Exception as e:
                console.print(f"[{ACCENT_COLOR}][x] Error testing model: {str(e)}[/{ACCENT_COLOR}]")
            
            next_action = await arrow_select(
                "What next?",
                ["Add another model", "Done"]
            )

            if next_action is None or next_action == "Done":
                console.print(f"[green][ok] Done[/green]\n")
                break
    
    # OPENAI flow
    elif provider_name == "OPENAI":
        api_key = console.input(f"[{THEME_COLOR}]Enter OPENAI API key:[/{THEME_COLOR}] ").strip()
        if not api_key:
            console.print(f"[{ACCENT_COLOR}][x] API key cannot be empty[/{ACCENT_COLOR}]")
            return
        
        console.print(f"\n[dim]Verifying key...[/dim]")
        is_valid, msg = verify_api_key("OPENAI", api_key)
        
        if not is_valid:
            console.print(f"[{ACCENT_COLOR}][x] Authentication failed: {msg}[/{ACCENT_COLOR}]")
            return
        
        set_key(env_path, "OPENAI_API_KEY", api_key)
        load_dotenv(override=True)
        config.API_KEYS["openai"] = api_key
        config.reload_keys()
        
        # Fetch and add models to catalog
        console.print(f"[dim]Fetching available models...[/dim]")
        try:
            client = OpenAI(api_key=api_key)
            models_response = client.models.list()
            model_count = 0
            
            for model_obj in models_response.data:
                model_id = model_obj.id
                add_to_catalog(
                    model_id=model_id,
                    base_url="https://api.openai.com/v1",
                    endpoint_type="openai",
                    api_key_env="OPENAI_API_KEY",
                    source="refresh"
                )
                model_count += 1
            
            console.print(f"[green][ok] OPENAI key saved. {model_count} models added to catalog.[/green]\n")
        except Exception as e:
            console.print(f"[{ACCENT_COLOR}][x] Error fetching models: {str(e)}[/{ACCENT_COLOR}]")
            console.print(f"[green][ok] OPENAI key saved (but model fetch failed)[/green]\n")
    
    # ANTHROPIC flow
    elif provider_name == "ANTHROPIC":
        api_key = console.input(f"[{THEME_COLOR}]Enter ANTHROPIC API key:[/{THEME_COLOR}] ").strip()
        if not api_key:
            console.print(f"[{ACCENT_COLOR}][x] API key cannot be empty[/{ACCENT_COLOR}]")
            return
        
        if not api_key.startswith("sk-ant-"):
            console.print(f"[{ACCENT_COLOR}][x] Invalid format. Must start with sk-ant-[/{ACCENT_COLOR}]")
            return
        
        set_key(env_path, "ANTHROPIC_API_KEY", api_key)
        load_dotenv(override=True)
        config.API_KEYS["anthropic"] = api_key
        config.reload_keys()
        console.print(f"[green][ok] ANTHROPIC key saved.[/green]\n")
    
    # Custom flow
    elif provider_name == "Custom":
        provider = console.input(f"[{THEME_COLOR}]Provider name (used as env var prefix, e.g. GROQ):[/{THEME_COLOR}] ").strip()
        if not provider:
            console.print(f"[{ACCENT_COLOR}][x] Provider name cannot be empty[/{ACCENT_COLOR}]")
            return
        
        provider = provider.upper()
        
        base_url = console.input(f"[{THEME_COLOR}]Base URL (e.g. https://api.groq.com/v1):[/{THEME_COLOR}] ").strip()
        if not base_url:
            console.print(f"[{ACCENT_COLOR}][x] Base URL cannot be empty[/{ACCENT_COLOR}]")
            return
        
        api_key = console.input(f"[{THEME_COLOR}]API Key:[/{THEME_COLOR}] ").strip()
        if not api_key:
            console.print(f"[{ACCENT_COLOR}][x] API key cannot be empty[/{ACCENT_COLOR}]")
            return
        
        # Verify by calling /models endpoint
        console.print(f"[dim]Verifying endpoint...[/dim]")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{base_url.rstrip('/')}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0
                )
                
                if response.status_code != 200:
                    console.print(f"[{ACCENT_COLOR}][x] Verification failed: HTTP {response.status_code}[/{ACCENT_COLOR}]")
                    return
                
                models_data = response.json()
                model_ids = [m["id"] for m in models_data.get("data", [])]
                
                if not model_ids:
                    console.print(f"[{ACCENT_COLOR}][x] No models found in response[/{ACCENT_COLOR}]")
                    return
                
                # Save key
                env_key = f"{provider}_API_KEY"
                set_key(env_path, env_key, api_key)
                load_dotenv(override=True)
                config.API_KEYS[provider.lower()] = api_key
                config.reload_keys()
                
                # Add models to catalog
                for model_id in model_ids:
                    add_to_catalog(
                        model_id=model_id,
                        base_url=base_url,
                        endpoint_type="custom",
                        api_key_env=env_key,
                        source="custom"
                    )
                
                console.print(f"[green][ok] {provider} saved. {len(model_ids)} models added to catalog.[/green]\n")
        
        except Exception as e:
            console.print(f"[{ACCENT_COLOR}][x] Error: {str(e)}[/{ACCENT_COLOR}]")
