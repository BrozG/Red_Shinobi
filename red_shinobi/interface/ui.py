"""
RED SHINOBI Textual User Interface

A rich terminal UI for the RED SHINOBI multi-agent AI system.
Uses the Textual framework for interactive terminal applications.
Supports multi-model selection and MCP tool calling.
"""

import asyncio
from typing import List, Dict, Any, Optional

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, Input, RichLog, Button, Switch, Select
from textual.containers import Horizontal, VerticalScroll, Vertical
from textual.worker import Worker

from red_shinobi.core.brain import (
    MODEL_REGISTRY,
    DEFAULT_MODEL,
    run_agent_conversation,
    get_all_model_names,
    normalize_model_name,
)
from red_shinobi.core.mcp_client import MCPManager


# =============================================================================
# UI SLASH COMMANDS
# =============================================================================

UI_COMMANDS: Dict[str, str] = {
    "/help": "Show available commands",
    "/clear": "Clear the chat log",
    "/models": "List available models",
    "/mcp-list": "List connected MCP servers",
}


class RedShinobiApp(App):
    """RED SHINOBI Multi-agent terminal application with MCP tool support."""
    
    CSS = """
    Screen {
        background: #1a1a1a;
    }
    
    #sidebar {
        width: 25;
        min-width: 25;
        max-width: 25;
        background: #111111;
        border-right: solid #ff0000;
    }
    
    #chat-window {
        width: 1fr;
        background: #1a1a1a;
    }
    
    #agent-list {
        height: auto;
        margin: 1;
        padding: 1;
    }
    
    #controls {
        height: auto;
        margin: 1;
        padding: 1;
    }
    
    RichLog {
        height: 1fr;
        background: #1a1a1a;
        border: solid #ff0000;
        margin: 1;
        scrollbar-size: 1 1;
    }
    
    Input {
        dock: bottom;
        margin: 1;
        border: solid #ff0000;
    }
    
    Button {
        margin: 1 0;
        width: 100%;
    }
    
    #add-model {
        background: #ff0000;
        color: #000000;
    }
    
    #remove-model {
        background: #333333;
        color: #ff0000;
        border: solid #ff0000;
    }
    
    Switch {
        margin: 1;
    }
    
    Select {
        width: 100%;
        margin: 0 0 1 0;
    }
    
    .agent-item {
        height: auto;
        padding: 0 1;
        margin: 0;
    }
    
    .agent-active {
        background: #330000;
        color: #ff0000;
    }
    
    .agent-inactive {
        background: #1a1a1a;
        color: #666666;
    }
    
    #title {
        text-align: center;
        color: #ff0000;
        text-style: bold;
        padding: 1;
    }
    
    #status {
        text-align: center;
        color: #666666;
        padding: 0 1;
    }
    """
    
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
        ("ctrl+n", "new_conversation", "New"),
    ]
    
    def __init__(self, mcp_manager: Optional[MCPManager] = None):
        super().__init__()
        self.active_models: List[str] = [DEFAULT_MODEL]
        self.available_models = get_all_model_names()
        self.conversation_history: List[Dict[str, Any]] = []
        self.is_processing = False
        self.mcp_manager = mcp_manager if mcp_manager else MCPManager()
    
    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(show_clock=True)
        
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("[bold red]RED SHINOBI[/bold red]", id="title")
                yield Static("[dim]Multi-Agent AI[/dim]", id="status")
                
                with VerticalScroll(id="agent-list"):
                    yield Static("[red]Active Models[/red]")
                    for i, model in enumerate(self.available_models[:5]):
                        initial_class = "agent-active" if model == DEFAULT_MODEL else "agent-inactive"
                        yield Button(model, id=f"model-{i}", classes=f"agent-item {initial_class}")
                
                with Vertical(id="controls"):
                    yield Static("[red]Controls[/red]")
                    yield Button("Add Model", id="add-model", variant="primary")
                    yield Button("Remove Model", id="remove-model", variant="default")
                    yield Button("Clear Chat", id="clear-chat", variant="default")
            
            with Vertical(id="chat-window"):
                yield RichLog(highlight=True, markup=True, id="chat-log")
                yield Input(placeholder="Type message or /help for commands (Ctrl+Q to quit)", id="chat-input")
        
        yield Footer()
    
    def on_mount(self) -> None:
        """Called when the app is mounted."""
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.write("[bold red]Welcome to RED SHINOBI[/bold red]")
        chat_log.write(f"[dim]Default model: {DEFAULT_MODEL}[/dim]")
        chat_log.write("[dim]Select models from sidebar or use @ModelName in messages[/dim]")
        chat_log.write("[dim]Type /help for commands, Ctrl+Q to quit[/dim]\n")
        
        self.query_one("#chat-input", Input).focus()
        self.update_status()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        
        if button_id and button_id.startswith("model-"):
            idx = int(button_id.split("-")[1])
            if idx < len(self.available_models):
                model_name = self.available_models[idx]
                self.toggle_model(model_name, event.button)
        
        elif button_id == "add-model":
            self.add_next_available_model()
        
        elif button_id == "remove-model":
            self.remove_last_model()
        
        elif button_id == "clear-chat":
            self.action_clear_log()
    
    def toggle_model(self, model_name: str, button: Button) -> None:
        """Toggle a model's active state."""
        if model_name in self.active_models:
            self.active_models.remove(model_name)
            button.remove_class("agent-active")
            button.add_class("agent-inactive")
        else:
            self.active_models.append(model_name)
            button.remove_class("agent-inactive")
            button.add_class("agent-active")
        
        self.update_status()
    
    def add_next_available_model(self) -> None:
        """Add the next available model to active list."""
        for model in self.available_models:
            if model not in self.active_models:
                self.active_models.append(model)
                idx = self.available_models.index(model)
                if idx < 5:
                    button = self.query_one(f"#model-{idx}", Button)
                    button.remove_class("agent-inactive")
                    button.add_class("agent-active")
                break
        self.update_status()
    
    def remove_last_model(self) -> None:
        """Remove the last model from active list."""
        if self.active_models:
            model = self.active_models.pop()
            if model in self.available_models:
                idx = self.available_models.index(model)
                if idx < 5:
                    button = self.query_one(f"#model-{idx}", Button)
                    button.remove_class("agent-active")
                    button.add_class("agent-inactive")
        self.update_status()
    
    def update_status(self) -> None:
        """Update the status display."""
        status = self.query_one("#status", Static)
        count = len(self.active_models)
        status.update(f"[dim]{count} model{'s' if count != 1 else ''} active[/dim]")
    
    def handle_slash_command(self, command: str, chat_log: RichLog) -> bool:
        """Handle slash commands. Returns True if command was handled."""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        if cmd == "/help":
            chat_log.write("\n[bold red]Available Commands:[/bold red]")
            for cmd_name, desc in UI_COMMANDS.items():
                chat_log.write(f"  [cyan]{cmd_name}[/cyan] - {desc}")
            chat_log.write("\n[dim]Use @ModelName in messages to route to specific model[/dim]")
            return True
        
        if cmd == "/clear":
            self.action_clear_log()
            return True
        
        if cmd == "/models":
            chat_log.write("\n[bold red]Available Models:[/bold red]")
            for model in self.available_models:
                active_marker = "[green]●[/green]" if model in self.active_models else "[dim]○[/dim]"
                chat_log.write(f"  {active_marker} {model}")
            return True
        
        if cmd == "/mcp-list":
            servers = self.mcp_manager.list_servers()
            if servers:
                chat_log.write("\n[bold red]MCP Servers:[/bold red]")
                for s in servers:
                    state = s.get("state", "unknown")
                    color = "green" if state == "ready" else "yellow"
                    chat_log.write(f"  [{color}]{s['name']}[/{color}] ({state})")
            else:
                chat_log.write("[dim]No MCP servers connected[/dim]")
            return True
        
        chat_log.write(f"[yellow]Unknown command: {cmd}. Type /help for commands.[/yellow]")
        return True
    
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        if self.is_processing:
            return
        
        message = event.value.strip()
        if not message:
            return
        
        event.input.value = ""
        chat_log = self.query_one("#chat-log", RichLog)
        
        if message.startswith("/"):
            self.handle_slash_command(message, chat_log)
            return
        
        chat_log.write(f"\n[bold white]You:[/bold white] {message}")
        
        selected_models = self.active_models if self.active_models else [DEFAULT_MODEL]
        
        self.is_processing = True
        chat_log.write("[dim]Processing...[/dim]")
        
        self.run_worker(self.process_message(message, chat_log, selected_models))
    
    async def process_message(
        self,
        message: str,
        chat_log: RichLog,
        selected_models: List[str]
    ) -> None:
        """
        Process a message using run_agent_conversation with MCP support.
        Uses strict 1-on-1 with optional single handoff.
        """
        try:
            self.conversation_history.append({
                "role": "user",
                "content": message
            })
            
            conversation = await run_agent_conversation(
                task=message,
                active_models=selected_models,
                mode="offline",
                max_turns=2,
                mcp_manager=self.mcp_manager
            )
            
            for msg in conversation:
                model = msg.get("model", "Unknown")
                content = msg.get("content", "")
                
                chat_log.write(f"\n[bold red]{model}:[/bold red] {content}")
                
                self.conversation_history.append({
                    "role": "assistant",
                    "content": content,
                    "model": model
                })
                
        except Exception as e:
            chat_log.write(f"[red]Error: {e}[/red]")
        
        finally:
            self.is_processing = False
    
    def action_clear_log(self) -> None:
        """Clear the chat log."""
        chat_log = self.query_one("#chat-log", RichLog)
        chat_log.clear()
        chat_log.write("[bold red]Chat cleared[/bold red]")
        chat_log.write("[dim]Start a new conversation...[/dim]\n")
        self.conversation_history.clear()
    
    def action_new_conversation(self) -> None:
        """Start a new conversation."""
        self.action_clear_log()
    
    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()


def run_ui(mcp_manager: Optional[MCPManager] = None) -> None:
    """Run the RED SHINOBI UI with optional MCP manager."""
    app = RedShinobiApp(mcp_manager=mcp_manager)
    app.run()


if __name__ == "__main__":
    run_ui()
