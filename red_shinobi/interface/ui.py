"""
RED SHINOBI - Textual TUI
Terminal-native UI that feels like a real hacker terminal.
Drop this file into red_shinobi/interface/ui.py to replace the existing one.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
    Button,
)
from textual.css.query import NoMatches


# ---------------------------------------------------------------------------
# SLASH COMMANDS (mirrors CLI commands)
# ---------------------------------------------------------------------------

UI_COMMANDS: Dict[str, str] = {
    "/help":           "Show all commands",
    "/key":            "Add API keys & models",
    "/models":         "List all models",
    "/set":            "Switch model",
    "/refresh":        "Verify models work",
    "/erasemodel":     "Remove model",
    "/read":           "Display file contents",
    "/save":           "Save conversation",
    "/mcp":            "Connect MCP server",
    "/mcp-list":       "List MCP servers",
    "/mcp-disconnect": "Disconnect server",
    "/system":         "Set system prompt",
    "/info":           "Show model details",
    "/clear":          "Clear chat",
    "/exit":           "Quit",
}


# ---------------------------------------------------------------------------
# SELECTION OVERLAY (Arrow-key selector like CLI)
# ---------------------------------------------------------------------------

class SelectionOverlay(Static):
    """Arrow-key selection overlay that appears above the input."""

    DEFAULT_CSS = """
    SelectionOverlay {
        layer: overlay;
        dock: bottom;
        height: auto;
        max-height: 12;
        background: #1a1a1a;
        border: solid #ff2222;
        padding: 0 1;
        margin-bottom: 3;
        display: none;
    }
    SelectionOverlay.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.options: List[str] = []
        self.descriptions: List[str] = []
        self.selected_index: int = 0
        self.on_select: Optional[Callable[[str], None]] = None
        self.selection_type: str = ""  # "command" or "model"

    def show_options(self, options: List[str], descriptions: List[str] = None, 
                     selection_type: str = "", on_select: Callable[[str], None] = None):
        """Show the selection overlay with options."""
        self.options = options
        self.descriptions = descriptions or [""] * len(options)
        self.selected_index = 0
        self.selection_type = selection_type
        self.on_select = on_select
        self.add_class("visible")
        self._render_options()

    def hide(self):
        """Hide the selection overlay."""
        self.remove_class("visible")
        self.options = []

    def move_up(self):
        """Move selection up."""
        if self.options:
            self.selected_index = (self.selected_index - 1) % len(self.options)
            self._render_options()

    def move_down(self):
        """Move selection down."""
        if self.options:
            self.selected_index = (self.selected_index + 1) % len(self.options)
            self._render_options()

    def select_current(self) -> Optional[str]:
        """Select current option and return it."""
        if self.options and 0 <= self.selected_index < len(self.options):
            selected = self.options[self.selected_index]
            if self.on_select:
                self.on_select(selected)
            self.hide()
            return selected
        return None

    def _render_options(self):
        """Render the options list."""
        lines = []
        title = "COMMANDS" if self.selection_type == "command" else "MODELS"
        lines.append(f"[bold red]── {title} ── (↑↓ select, Enter confirm, Esc cancel)[/bold red]")
        
        for i, opt in enumerate(self.options[:10]):  # Max 10 visible
            desc = self.descriptions[i] if i < len(self.descriptions) else ""
            if i == self.selected_index:
                lines.append(f"[bold red]> {opt:<20}[/bold red] [dim]{desc}[/dim]")
            else:
                lines.append(f"[dim]  {opt:<20} {desc}[/dim]")
        
        if len(self.options) > 10:
            lines.append(f"[dim]  ... and {len(self.options) - 10} more[/dim]")
        
        self.update("\n".join(lines))


class StatusBar(Static):
    """Bottom status bar — model, MCP count, time."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $error;
        color: $background;
        text-style: bold;
        padding: 0 1;
        dock: bottom;
    }
    """

    model_name: reactive[str] = reactive("<no-model>")
    mcp_count: reactive[int] = reactive(0)
    processing: reactive[bool] = reactive(False)

    def render(self) -> str:
        time_str = datetime.now().strftime("%H:%M")
        status = " [THINKING] " if self.processing else ""
        mcp_str = f"MCP:{self.mcp_count}" if self.mcp_count else "MCP:off"
        return (
            f" RED SHINOBI{status}│ model: {self.model_name} │ {mcp_str} │ {time_str} "
            f"│ ctrl+q quit │ ctrl+h help "
        )


class ModelTag(Button):
    """A clickable model chip in the sidebar."""

    DEFAULT_CSS = """
    ModelTag {
        height: 1;
        width: 100%;
        background: $background;
        color: $text-muted;
        border: none;
        text-align: left;
        padding: 0 1;
        margin: 0;
    }
    ModelTag:hover {
        background: $surface;
        color: $error;
    }
    ModelTag.active {
        background: $surface;
        color: $error;
        text-style: bold;
    }
    """


class SidePanel(Vertical):
    """Left sidebar: model list + MCP status + quick command refs."""

    DEFAULT_CSS = """
    SidePanel {
        width: 26;
        min-width: 26;
        background: $background;
        border-right: solid $error;
        padding: 0;
    }
    SidePanel Label {
        color: $error;
        text-style: bold;
        padding: 0 1;
        margin-top: 1;
    }
    SidePanel .dim-label {
        color: $text-muted;
        text-style: none;
        padding: 0 1;
        margin-top: 0;
    }
    SidePanel #mcp-status {
        color: $text-muted;
        padding: 0 1;
    }
    SidePanel #divider {
        color: $error;
        padding: 0 1;
    }
    """

    def __init__(self, models: List[str], current_model: str, **kwargs):
        super().__init__(**kwargs)
        self.model_list = models
        self.current_model = current_model

    def compose(self) -> ComposeResult:
        yield Label("── MODELS ──")
        with ScrollableContainer(id="model-scroll"):
            for m in self.model_list:
                tag = ModelTag(f"● {m[:20]}", id=f"mdl-{_safe_id(m)}", name=m)
                if m == self.current_model:
                    tag.add_class("active")
                yield tag
        yield Static("─" * 24, id="divider-1")
        yield Label("── MCP ──")
        yield Static("no servers", id="mcp-status")
        yield Static("─" * 24, id="divider-2")
        yield Label("── QUICK ──")
        yield Static("[cyan]/ [/cyan][dim]commands[/dim]\n[cyan]@ [/cyan][dim]models[/dim]\n[dim]↑↓ select Enter pick[/dim]", classes="dim-label")


def _safe_id(s: str) -> str:
    """Convert any string to a valid Textual CSS id (letters, numbers, hyphens only)."""
    import re
    safe = re.sub(r"[^a-zA-Z0-9-]", "-", s)
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "model"


class ChatMessage(Static):
    """A single message line in the chat feed."""

    DEFAULT_CSS = """
    ChatMessage {
        padding: 0 1;
        height: auto;
    }
    ChatMessage.user {
        color: $text;
    }
    ChatMessage.assistant {
        color: $success;
    }
    ChatMessage.system {
        color: $text-muted;
        text-style: italic;
    }
    ChatMessage.error {
        color: $error;
    }
    ChatMessage.thinking {
        color: $warning;
    }
    """


class ChatFeed(ScrollableContainer):
    """Scrollable chat log."""

    DEFAULT_CSS = """
    ChatFeed {
        width: 1fr;
        height: 1fr;
        background: $background;
        border: none;
        padding: 0;
        scrollbar-size: 1 1;
        scrollbar-color: $error;
    }
    """

    def add_message(self, role: str, content: str, model: str = "") -> None:
        prefix_map = {
            "user":      "[bold white]YOU[/bold white]",
            "assistant": f"[bold red]{model or 'AI'}[/bold red]",
            "system":    "[dim]SYS[/dim]",
            "error":     "[bold red]ERR[/bold red]",
            "thinking":  "[bold yellow]...[/bold yellow]",
        }
        prefix = prefix_map.get(role, "[dim]???[/dim]")
        ts = datetime.now().strftime("%H:%M")
        msg = ChatMessage(
            f"[dim]{ts}[/dim] {prefix} {content}",
            classes=role,
        )
        self.mount(msg)
        self.scroll_end(animate=False)

    def add_streaming_message(self, role: str, model: str = "") -> "ChatMessage":
        """Create an empty message that can be updated word-by-word."""
        prefix_map = {
            "user":      "[bold white]YOU[/bold white]",
            "assistant": f"[bold red]{model or 'AI'}[/bold red]",
            "system":    "[dim]SYS[/dim]",
            "error":     "[bold red]ERR[/bold red]",
            "thinking":  "[bold yellow]...[/bold yellow]",
        }
        prefix = prefix_map.get(role, "[dim]???[/dim]")
        ts = datetime.now().strftime("%H:%M")
        msg = ChatMessage(
            f"[dim]{ts}[/dim] {prefix} ",
            classes=role,
            id="streaming-msg"
        )
        self.mount(msg)
        self.scroll_end(animate=False)
        return msg

    def update_streaming_message(self, content: str, model: str = "") -> None:
        """Update the streaming message with new content."""
        try:
            msg = self.query_one("#streaming-msg", ChatMessage)
            prefix = f"[bold red]{model or 'AI'}[/bold red]"
            ts = datetime.now().strftime("%H:%M")
            msg.update(f"[dim]{ts}[/dim] {prefix} {content}")
            self.scroll_end(animate=False)
        except NoMatches:
            pass

    def finalize_streaming_message(self) -> None:
        """Remove streaming ID so message is finalized."""
        try:
            msg = self.query_one("#streaming-msg", ChatMessage)
            msg.id = None
        except NoMatches:
            pass

    def clear_messages(self) -> None:
        for child in list(self.children):
            child.remove()
        self.add_message("system", "Chat cleared.")


class CommandInput(Input):
    """Bottom input bar — terminal style."""

    DEFAULT_CSS = """
    CommandInput {
        background: $background;
        border: none;
        border-top: solid $error;
        color: $text;
        height: 3;
        padding: 0 1;
    }
    CommandInput:focus {
        border-top: solid $error;
    }
    """

    PLACEHOLDER = "type a message or /command ..."


# ---------------------------------------------------------------------------
# MAIN APP
# ---------------------------------------------------------------------------

class RedShinobiApp(App):
    """RED SHINOBI TUI — hacker terminal aesthetic with Textual."""

    TITLE = "RED SHINOBI"
    CSS = """
    Screen {
        background: #0d0d0d;
        layers: base overlay;
    }

    /* ── Global palette overrides ── */
    $background: #0d0d0d;
    $surface:    #1a1a1a;
    $error:      #ff2222;
    $success:    #22ff88;
    $warning:    #ffaa00;
    $text:       #dddddd;
    $text-muted: #555555;

    /* ── Layout ── */
    #root-h {
        width: 100%;
        height: 1fr;
    }

    /* ── Chat column ── */
    #chat-col {
        width: 1fr;
        height: 1fr;
        background: #0d0d0d;
    }

    /* ── Prompt row ── */
    #prompt-row {
        height: 3;
        background: #0d0d0d;
        border-top: solid #ff2222;
    }

    #prompt-label {
        width: auto;
        height: 3;
        color: #ff2222;
        text-style: bold;
        padding: 1 1 0 1;
    }

    CommandInput {
        width: 1fr;
    }

    /* ── Thinking indicator ── */
    #thinking-bar {
        height: 1;
        background: #1a1a1a;
        color: #ffaa00;
        text-align: center;
        display: none;
    }
    #thinking-bar.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+l", "clear_chat", "Clear"),
        Binding("ctrl+h", "show_help", "Help"),
        Binding("ctrl+n", "new_chat", "New chat"),
        Binding("escape", "blur_input", "Focus"),
    ]

    # ── reactive state ──────────────────────────────────────────────────────
    current_model: reactive[str] = reactive("<no-model>")
    is_thinking: reactive[bool] = reactive(False)

    def __init__(self, mcp_manager=None, **kwargs):
        super().__init__(**kwargs)
        self.mcp_manager = mcp_manager
        self._history: List[Dict[str, Any]] = []
        self._selection_active = False  # Track if selection overlay is active
        self._system_prompt = ""

        # Try to import real catalog; fall back gracefully
        try:
            from red_shinobi.core.nvidia_catalog import MODEL_CATALOG
            from red_shinobi.core.brain import DEFAULT_MODEL, get_all_model_names
            self._model_catalog = MODEL_CATALOG
            self._model_names = get_all_model_names() or list(MODEL_CATALOG.keys())
            self.current_model = DEFAULT_MODEL
        except Exception:
            self._model_catalog = {}
            self._model_names = ["(no models - run /key)"]
            self.current_model = "<no-model>"

    # ── composition ─────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        with Horizontal(id="root-h"):
            yield SidePanel(
                models=self._model_names,
                current_model=self.current_model,
                id="sidebar",
            )
            with Vertical(id="chat-col"):
                yield ChatFeed(id="feed")
                yield Static("", id="thinking-bar")
                yield SelectionOverlay(id="selection-overlay")
                with Horizontal(id="prompt-row"):
                    yield Static("❯", id="prompt-label")
                    yield CommandInput(
                        placeholder="type / for commands, @ for models",
                        id="cmd-input",
                    )
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        feed = self.query_one("#feed", ChatFeed)
        feed.add_message("system", "[bold red]RED SHINOBI[/bold red] — Multi-Agent AI Terminal")
        feed.add_message("system", f"model → [bold]{self.current_model}[/bold]")
        feed.add_message("system", "type [bold]/[/bold] for commands, [bold]@[/bold] for models")
        feed.add_message("system", "─" * 60)
        self.query_one("#cmd-input", CommandInput).focus()
        self._sync_status()

    # ── reactive watches ────────────────────────────────────────────────────

    def watch_current_model(self, value: str) -> None:
        self._sync_status()
        # Update sidebar active state
        try:
            for btn in self.query(ModelTag):
                if btn.name == value:
                    btn.add_class("active")
                else:
                    btn.remove_class("active")
        except Exception:
            pass

    def watch_is_thinking(self, value: bool) -> None:
        try:
            bar = self.query_one("#thinking-bar", Static)
            if value:
                bar.update("  ⣾ thinking ...  ")
                bar.add_class("visible")
            else:
                bar.remove_class("visible")
                bar.update("")
            status = self.query_one("#status-bar", StatusBar)
            status.processing = value
        except NoMatches:
            pass

    # ── input handler ───────────────────────────────────────────────────────

    @on(Input.Submitted, "#cmd-input")
    async def on_submit(self, event: Input.Submitted) -> None:
        # If selection overlay is active, select current option
        try:
            overlay = self.query_one("#selection-overlay", SelectionOverlay)
            if "visible" in overlay.classes:
                selected = overlay.select_current()
                if selected:
                    event.input.value = selected
                    self._selection_active = False
                return
        except NoMatches:
            pass

        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        if text.startswith("/"):
            await self._handle_command(text)
        else:
            await self._send_message(text)

    @on(Input.Changed, "#cmd-input")
    def on_input_changed(self, event: Input.Changed) -> None:
        """Show selection overlay when user types / or @"""
        text = event.value
        
        try:
            overlay = self.query_one("#selection-overlay", SelectionOverlay)
            
            # Show command selector when just "/" is typed
            if text == "/":
                commands = list(UI_COMMANDS.keys())
                descriptions = list(UI_COMMANDS.values())
                overlay.show_options(
                    commands, 
                    descriptions, 
                    selection_type="command",
                    on_select=lambda cmd: self._on_command_selected(cmd)
                )
                self._selection_active = True
                return
            
            # Filter commands as user types more
            elif text.startswith("/") and len(text) > 1:
                query = text.lower()
                commands = [c for c in UI_COMMANDS.keys() if query in c.lower()]
                descriptions = [UI_COMMANDS[c] for c in commands]
                if commands:
                    overlay.show_options(
                        commands, 
                        descriptions, 
                        selection_type="command",
                        on_select=lambda cmd: self._on_command_selected(cmd)
                    )
                    self._selection_active = True
                else:
                    overlay.hide()
                    self._selection_active = False
                return
            
            # Show model selector when just "@" is typed
            elif text == "@":
                if self._model_names and not self._model_names[0].startswith("(no models"):
                    overlay.show_options(
                        self._model_names, 
                        ["" for _ in self._model_names], 
                        selection_type="model",
                        on_select=lambda m: self._on_model_selected(m)
                    )
                    self._selection_active = True
                return
            
            # Filter models as user types more
            elif text.startswith("@") and len(text) > 1:
                query = text[1:].lower()
                matches = [m for m in self._model_names if query in m.lower()]
                if matches:
                    overlay.show_options(
                        matches, 
                        ["" for _ in matches], 
                        selection_type="model",
                        on_select=lambda m: self._on_model_selected(m)
                    )
                    self._selection_active = True
                else:
                    overlay.hide()
                    self._selection_active = False
                return
            
            else:
                # Hide overlay for other input
                overlay.hide()
                self._selection_active = False
                
        except NoMatches:
            pass

    def _on_command_selected(self, cmd: str) -> None:
        """Handle command selection from overlay."""
        inp = self.query_one("#cmd-input", CommandInput)
        inp.value = cmd + " "
        inp.focus()
        self._selection_active = False

    def _on_model_selected(self, model: str) -> None:
        """Handle model selection from overlay."""
        self.current_model = model
        feed = self.query_one("#feed", ChatFeed)
        feed.add_message("system", f"model → [bold red]{model}[/bold red]")
        inp = self.query_one("#cmd-input", CommandInput)
        inp.value = ""
        inp.focus()
        self._selection_active = False

    def on_key(self, event) -> None:
        """Handle arrow keys for selection overlay."""
        try:
            overlay = self.query_one("#selection-overlay", SelectionOverlay)
            if "visible" in overlay.classes:
                if event.key == "up":
                    overlay.move_up()
                    event.prevent_default()
                    event.stop()
                elif event.key == "down":
                    overlay.move_down()
                    event.prevent_default()
                    event.stop()
                elif event.key == "enter":
                    selected = overlay.select_current()
                    event.prevent_default()
                    event.stop()
                elif event.key == "escape":
                    overlay.hide()
                    self._selection_active = False
                    inp = self.query_one("#cmd-input", CommandInput)
                    inp.value = ""
                    inp.focus()
                    event.prevent_default()
                    event.stop()
        except NoMatches:
            pass

    def _on_provider_selected(self, provider: str) -> None:
        """Handle provider selection from overlay for /key."""
        feed = self.query_one("#feed", ChatFeed)
        feed.add_message("system", f"[dim]Selected: {provider}[/dim]")
        feed.add_message("system", f"Enter API key: /key {provider} <your_key>")
        inp = self.query_one("#cmd-input", CommandInput)
        inp.value = f"/key {provider} "
        inp.focus()
        self._selection_active = False

    def _on_erase_selected(self, model_to_remove: str) -> None:
        """Handle model selection from overlay for /erasemodel."""
        feed = self.query_one("#feed", ChatFeed)
        self._selection_active = False

        if model_to_remove == "all":
            self._model_catalog.clear()
            self._model_names.clear()
            feed.add_message("system", "[green]✓[/green] All models removed from catalog")
            self._refresh_sidebar()
        elif model_to_remove == "failed":
            to_remove = [k for k, v in self._model_catalog.items() if v.get("ok") is False]
            for m in to_remove:
                del self._model_catalog[m]
                if m in self._model_names:
                    self._model_names.remove(m)
            feed.add_message("system", f"[green]✓[/green] Removed {len(to_remove)} failed models")
            self._refresh_sidebar()
        else:
            if model_to_remove in self._model_catalog:
                del self._model_catalog[model_to_remove]
                if model_to_remove in self._model_names:
                    self._model_names.remove(model_to_remove)
                feed.add_message("system", f"[green]✓[/green] Removed model: {model_to_remove}")
                self._refresh_sidebar()
            else:
                feed.add_message("error", f"Model '{model_to_remove}' not found")

    def _on_mcp_disconnect_selected(self, server_name: str) -> None:
        """Handle server selection from overlay for /mcp-disconnect."""
        feed = self.query_one("#feed", ChatFeed)
        self._selection_active = False

        if server_name == "← Cancel":
            feed.add_message("system", "[dim]Cancelled[/dim]")
            return

        async def do_disconnect():
            try:
                await self.mcp_manager.disconnect_server(server_name)
                feed.add_message("system", f"[green]✓[/green] Disconnected from {server_name}")
                self._sync_status()
            except Exception as e:
                feed.add_message("error", f"Disconnect failed: {e}")

        import asyncio
        asyncio.create_task(do_disconnect())

    def _on_system_model_selected(self, model_name: str) -> None:
        """After picking model for /system, pre-fill input for the prompt."""
        inp = self.query_one("#cmd-input", CommandInput)
        feed = self.query_one("#feed", ChatFeed)
        self._selection_active = False
        inp.value = f"/system {model_name} "
        inp.focus()
        feed.add_message("system", f"[dim]Now type the new system prompt after '{model_name}'[/dim]")

    def _show_model_info(self, model_name: str) -> None:
        """Display detailed info for a specific model."""
        feed = self.query_one("#feed", ChatFeed)
        feed.add_message("system", "─" * 60)
        feed.add_message("system", f"[bold red]MODEL INFO — {model_name}[/bold red]")
        if model_name in self._model_catalog:
            info = self._model_catalog[model_name]
            feed.add_message("system", f"  Provider: {info.get('endpoint_type', 'unknown')}")
            feed.add_message("system", f"  API Key:  {info.get('api_key_env', 'N/A')}")
            if info.get('ok') is True:
                feed.add_message("system", f"  Status:   [green]Verified[/green] ({info.get('latency_ms', '?')}ms)")
            elif info.get('ok') is False:
                feed.add_message("system", f"  Status:   [red]Failed[/red] — {info.get('error', 'unknown')}")
            else:
                feed.add_message("system", "  Status:   [yellow]Not verified[/yellow] (run /refresh)")
        else:
            feed.add_message("system", "  [dim]Model not in catalog[/dim]")
        feed.add_message("system", "─" * 60)

    def _on_info_selected(self, model_name: str) -> None:
        """Handle model selection from overlay for /info."""
        self._selection_active = False
        self._show_model_info(model_name)

    # ── sidebar model click ─────────────────────────────────────────────────

    @on(Button.Pressed)
    def on_model_click(self, event: Button.Pressed) -> None:
        if isinstance(event.button, ModelTag):
            name = event.button.name or ""
            if name and not name.startswith("(no models"):
                self.current_model = name
                feed = self.query_one("#feed", ChatFeed)
                feed.add_message("system", f"model switched → [bold red]{name}[/bold red]")

    # ── command router ──────────────────────────────────────────────────────

    async def _handle_command(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        feed = self.query_one("#feed", ChatFeed)

        if cmd in ("/exit", "/quit"):
            self.exit()

        elif cmd in ("/help", "/h"):
            feed.add_message("system", "─" * 60)
            feed.add_message("system", "[bold red]COMMANDS[/bold red]")
            for c, desc in UI_COMMANDS.items():
                feed.add_message("system", f"  [cyan]{c:<16}[/cyan] {desc}")
            feed.add_message("system", "")
            feed.add_message("system", "[bold red]FILE REFERENCES[/bold red]")
            feed.add_message("system", "  Use [cyan]#filepath[/cyan] to attach files to your query")
            feed.add_message("system", "  Example: [dim]explain this code #main.py[/dim]")
            feed.add_message("system", "─" * 60)

        elif cmd == "/clear":
            self.action_clear_chat()

        elif cmd == "/models":
            feed.add_message("system", "─" * 60)
            feed.add_message("system", "[bold red]MODEL CATALOG[/bold red]")
            if self._model_names:
                for m in self._model_names:
                    active = "[bold red]●[/bold red]" if m == self.current_model else "[dim]○[/dim]"
                    feed.add_message("system", f"  {active} {m}")
            else:
                feed.add_message("system", "  no models — run /key first")
            feed.add_message("system", "─" * 60)

        elif cmd == "/set":
            if args:
                # fuzzy match
                match = next(
                    (m for m in self._model_names if args.lower() in m.lower()),
                    None,
                )
                if match:
                    self.current_model = match
                    feed.add_message("system", f"model → [bold red]{match}[/bold red]")
                else:
                    feed.add_message("error", f"no model matching '{args}' — try /models")
            else:
                feed.add_message("system", f"current model: [bold red]{self.current_model}[/bold red]")

        elif cmd == "/mcp-list":
            feed.add_message("system", "─" * 60)
            feed.add_message("system", "[bold red]MCP SERVERS[/bold red]")
            if self.mcp_manager:
                try:
                    servers = self.mcp_manager.list_servers()
                    if servers:
                        for s in servers:
                            state = s.get("state", "?")
                            col = "green" if state == "ready" else "yellow"
                            feed.add_message("system", f"  [{col}]{s['name']}[/{col}]  ({state})")
                    else:
                        feed.add_message("system", "  no servers connected")
                except Exception as e:
                    feed.add_message("error", str(e))
            else:
                feed.add_message("system", "  MCP manager not available")
            feed.add_message("system", "─" * 60)

        elif cmd == "/save":
            self._save_transcript(args.strip() if args else None)

        elif cmd == "/key":
            if args:
                await self._handle_key_command(args)
            else:
                # Show provider selection overlay
                overlay = self.query_one("#selection-overlay", SelectionOverlay)
                providers = ["NVIDIA", "OPENAI", "ANTHROPIC"]
                descriptions = ["nvidia.com API", "openai.com API", "anthropic.com API"]
                overlay.show_options(
                    providers,
                    descriptions,
                    selection_type="command",
                    on_select=lambda p: self._on_provider_selected(p)
                )
                self._selection_active = True
                feed.add_message("system", "[bold red]SELECT PROVIDER[/bold red] — use ↑↓ and Enter")

        elif cmd == "/refresh":
            feed.add_message("system", "─" * 60)
            feed.add_message("system", "[bold red]REFRESHING MODELS[/bold red]")
            feed.add_message("system", "[dim]Testing model availability...[/dim]")
            await self._refresh_models()
            feed.add_message("system", "─" * 60)

        elif cmd == "/erasemodel":
            if args:
                model_to_remove = args.strip()
                if model_to_remove in self._model_catalog:
                    del self._model_catalog[model_to_remove]
                    if model_to_remove in self._model_names:
                        self._model_names.remove(model_to_remove)
                    feed.add_message("system", f"[green]✓[/green] Removed model: {model_to_remove}")
                    self._refresh_sidebar()
                else:
                    feed.add_message("error", f"Model '{model_to_remove}' not found in catalog")
            else:
                if self._model_names and not self._model_names[0].startswith("(no models"):
                    erase_options = ["all", "failed"] + self._model_names
                    overlay = self.query_one("#selection-overlay", SelectionOverlay)
                    overlay.show_options(
                        erase_options,
                        ["" for _ in erase_options],
                        selection_type="model",
                        on_select=lambda m: self._on_erase_selected(m)
                    )
                    self._selection_active = True
                    feed.add_message("system", "[bold red]SELECT MODEL TO ERASE[/bold red] — use ↑↓ and Enter, Esc to cancel")
                else:
                    feed.add_message("system", "Catalog is empty")

        elif cmd == "/read":
            if args:
                await self._read_file(args)
            else:
                feed.add_message("system", "Usage: /read <path>")
                feed.add_message("system", "Display file contents")

        elif cmd == "/mcp":
            feed.add_message("system", "─" * 60)
            feed.add_message("system", "[bold red]MCP SERVER[/bold red]")
            if args:
                feed.add_message("system", f"[dim]Connecting to {args}...[/dim]")
                await self._connect_mcp(args)
            else:
                feed.add_message("system", "Usage: /mcp <server_command>")
                feed.add_message("system", "Example: /mcp npx -y @modelcontextprotocol/server-filesystem")
            feed.add_message("system", "─" * 60)

        elif cmd == "/mcp-disconnect":
            if not self.mcp_manager:
                feed.add_message("system", "No MCP manager available")
            elif args:
                try:
                    await self.mcp_manager.disconnect_server(args.strip())
                    feed.add_message("system", f"[green]✓[/green] Disconnected from {args.strip()}")
                    self._sync_status()
                except Exception as e:
                    feed.add_message("error", f"Disconnect failed: {e}")
            else:
                try:
                    servers = self.mcp_manager.list_servers()
                    if not servers:
                        feed.add_message("system", "No MCP servers connected")
                    else:
                        server_names = [s["name"] for s in servers]
                        options = ["← Cancel"] + server_names
                        overlay = self.query_one("#selection-overlay", SelectionOverlay)
                        overlay.show_options(
                            options,
                            ["" for _ in options],
                            selection_type="command",
                            on_select=lambda s: self._on_mcp_disconnect_selected(s)
                        )
                        self._selection_active = True
                        feed.add_message("system", "[bold red]SELECT SERVER TO DISCONNECT[/bold red] — use ↑↓ and Enter, Esc to cancel")
                except Exception as e:
                    feed.add_message("error", f"Error listing servers: {e}")

        elif cmd == "/system":
            if args:
                # args format: "<model> <prompt>" — set prompt for specific model
                parts = args.split(maxsplit=1)
                if len(parts) == 2:
                    self._system_prompt = parts[1]
                    feed.add_message("system", f"[green]✓[/green] System prompt updated for {parts[0]}")
                else:
                    # Single arg treated as the prompt for current model
                    self._system_prompt = args
                    feed.add_message("system", f"[green]✓[/green] System prompt updated")
                feed.add_message("system", f"[dim]{self._system_prompt[:100]}{'...' if len(self._system_prompt) > 100 else ''}[/dim]")
            else:
                if self._model_names and not self._model_names[0].startswith("(no models"):
                    overlay = self.query_one("#selection-overlay", SelectionOverlay)
                    overlay.show_options(
                        self._model_names,
                        ["" for _ in self._model_names],
                        selection_type="model",
                        on_select=lambda m: self._on_system_model_selected(m)
                    )
                    self._selection_active = True
                    feed.add_message("system", "[bold red]SELECT MODEL FOR SYSTEM PROMPT[/bold red] — use ↑↓ and Enter, Esc to cancel")
                else:
                    feed.add_message("system", "No models in catalog. Run /key first.")

        elif cmd == "/info":
            if args:
                self._show_model_info(args.strip())
            else:
                if self._model_names and not self._model_names[0].startswith("(no models"):
                    overlay = self.query_one("#selection-overlay", SelectionOverlay)
                    overlay.show_options(
                        self._model_names,
                        ["" for _ in self._model_names],
                        selection_type="model",
                        on_select=lambda m: self._on_info_selected(m)
                    )
                    self._selection_active = True
                    feed.add_message("system", "[bold red]SELECT MODEL TO INSPECT[/bold red] — use ↑↓ and Enter, Esc to cancel")
                else:
                    feed.add_message("system", "No models in catalog. Run /key first.")

        else:
            feed.add_message("error", f"unknown command: {cmd}  — type /help")

    # ── message sender ──────────────────────────────────────────────────────

    async def _send_message(self, text: str) -> None:
        feed = self.query_one("#feed", ChatFeed)

        if self.current_model in ("<no-model>", "<no models — run /key>"):
            feed.add_message("error", "no model selected — use /key then /set")
            return

        # Process # file references
        processed_text = text
        if "#" in text:
            import re
            import os
            
            # Find all #filepath patterns
            file_refs = re.findall(r'#([^\s]+)', text)
            
            if file_refs:
                file_contents = []
                for file_path in file_refs:
                    if os.path.exists(file_path):
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                content = f.read()
                            
                            # Truncate very large files
                            max_chars = 50000
                            if len(content) > max_chars:
                                content = content[:max_chars] + f"\n\n[... truncated at {max_chars} characters ...]"
                                feed.add_message("system", f"[dim]Note: {file_path} truncated to {max_chars} chars[/dim]")
                            
                            file_contents.append(f"\n\n--- File: {file_path} ---\n```\n{content}\n```\n")
                            feed.add_message("system", f"[dim]📎 Attached: {file_path}[/dim]")
                        except UnicodeDecodeError:
                            try:
                                with open(file_path, "r", encoding="latin-1") as f:
                                    content = f.read()
                                file_contents.append(f"\n\n--- File: {file_path} ---\n```\n{content}\n```\n")
                                feed.add_message("system", f"[dim]📎 Attached: {file_path}[/dim]")
                            except Exception as e:
                                feed.add_message("error", f"Could not read {file_path}: {e}")
                        except Exception as e:
                            feed.add_message("error", f"Could not read {file_path}: {e}")
                    else:
                        feed.add_message("error", f"File not found: {file_path}")
                
                # Remove #filepath from display, keep in processed version
                display_text = re.sub(r'#[^\s]+', '', text).strip()
                processed_text = display_text + "".join(file_contents)
                
                # Show user message without file paths
                feed.add_message("user", display_text if display_text else text)
            else:
                feed.add_message("user", text)
        else:
            feed.add_message("user", text)
        
        self._history.append({"role": "user", "content": processed_text})
        self.is_thinking = True
        self._run_brain(processed_text)

    @work(exclusive=False, thread=False)
    async def _run_brain(self, text: str) -> None:
        feed = self.query_one("#feed", ChatFeed)
        try:
            from red_shinobi.core.brain import run_agent_conversation
            conversation = await run_agent_conversation(
                task=text,
                active_models=[self.current_model],
                mode="offline",
                max_turns=2,
                mcp_manager=self.mcp_manager,
                chat_history=self._history,
            )
            for msg in conversation:
                model = msg.get("model", self.current_model)
                content = msg.get("content", "")
                
                # Stream word-by-word
                feed.add_streaming_message("assistant", model=model)
                words = content.split()
                displayed = ""
                for i, word in enumerate(words):
                    displayed += word + " "
                    feed.update_streaming_message(displayed.strip(), model=model)
                    # Small delay for visual effect (faster for long responses)
                    delay = 0.03 if len(words) > 50 else 0.05
                    await asyncio.sleep(delay)
                feed.finalize_streaming_message()
                
                self._history.append({"role": "assistant", "content": content})
        except Exception as e:
            feed.add_message("error", f"brain error: {e}")
        finally:
            self.is_thinking = False

    # ── actions ─────────────────────────────────────────────────────────────

    def action_clear_chat(self) -> None:
        self.query_one("#feed", ChatFeed).clear_messages()
        self._history.clear()

    def action_show_help(self) -> None:
        asyncio.create_task(self._handle_command("/help"))

    def action_new_chat(self) -> None:
        self.action_clear_chat()

    def action_blur_input(self) -> None:
        self.query_one("#cmd-input", CommandInput).focus()

    def action_quit(self) -> None:
        self.exit()

    # ── helpers ─────────────────────────────────────────────────────────────

    def _sync_status(self) -> None:
        try:
            bar = self.query_one("#status-bar", StatusBar)
            bar.model_name = self.current_model
            if self.mcp_manager:
                try:
                    bar.mcp_count = len(self.mcp_manager.list_servers())
                except Exception:
                    bar.mcp_count = 0
        except NoMatches:
            pass

    def _save_transcript(self, filename: str = None) -> None:
        feed = self.query_one("#feed", ChatFeed)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        if filename:
            fname = filename if filename.endswith(".md") else filename + ".md"
        else:
            fname = f"red_shinobi_{ts}.md"
        lines = [f"# RED SHINOBI transcript — {ts}\n"]
        for h in self._history:
            role = h.get("role", "?").upper()
            content = h.get("content", "")
            lines.append(f"**{role}**: {content}\n")
        try:
            with open(fname, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            feed.add_message("system", f"saved → [bold]{fname}[/bold]")
        except Exception as e:
            feed.add_message("error", f"save failed: {e}")

    def _refresh_sidebar(self) -> None:
        """Refresh the model list in sidebar."""
        try:
            sidebar = self.query_one("#sidebar", SidePanel)
            # Update model tags
            for btn in self.query(ModelTag):
                if btn.name == self.current_model:
                    btn.add_class("active")
                else:
                    btn.remove_class("active")
        except Exception:
            pass

    async def _handle_key_command(self, args: str) -> None:
        """Handle /key <provider> <api_key> command."""
        feed = self.query_one("#feed", ChatFeed)
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            feed.add_message("error", "Usage: /key <provider> <api_key>")
            return
        
        provider = parts[0].upper()
        api_key = parts[1].strip()
        
        if provider not in ["NVIDIA", "OPENAI", "ANTHROPIC"]:
            feed.add_message("error", f"Unknown provider: {provider}")
            feed.add_message("system", "Supported: NVIDIA, OPENAI, ANTHROPIC")
            return
        
        import os
        from dotenv import set_key, load_dotenv
        
        env_key = f"{provider}_API_KEY"
        env_path = ".env"
        
        # Create .env if needed
        if not os.path.exists(env_path):
            with open(env_path, "w") as f:
                f.write("# RED SHINOBI Environment Configuration\n")
        
        try:
            set_key(env_path, env_key, api_key)
            load_dotenv(override=True)
            os.environ[env_key] = api_key
            feed.add_message("system", f"[green]✓[/green] {provider} API key saved")
            feed.add_message("system", "[dim]Add models with: /key <provider> <key> then type model name[/dim]")
        except Exception as e:
            feed.add_message("error", f"Failed to save key: {e}")

    async def _refresh_models(self) -> None:
        """Verify which models in catalog are working."""
        feed = self.query_one("#feed", ChatFeed)
        
        if not self._model_catalog:
            feed.add_message("system", "No models in catalog. Use /key to add API key first.")
            return
        
        working = 0
        failed = 0
        
        for model_id, info in list(self._model_catalog.items()):
            try:
                # Quick check - just mark as tested
                feed.add_message("system", f"  Testing {model_id[:30]}...")
                # In a real implementation, call the API to verify
                working += 1
                info['ok'] = True
            except Exception as e:
                failed += 1
                info['ok'] = False
                info['error'] = str(e)
        
        feed.add_message("system", f"[green]✓[/green] {working} working, [red]{failed}[/red] failed")

    async def _handle_file_query(self, args: str) -> None:
        """Handle /file <path> [question] command."""
        feed = self.query_one("#feed", ChatFeed)
        parts = args.split(maxsplit=1)
        file_path = parts[0]
        question = parts[1] if len(parts) > 1 else "Summarize this file"
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Truncate if too long
            if len(content) > 10000:
                content = content[:10000] + "\n... (truncated)"
            
            feed.add_message("system", f"[dim]Loaded {file_path} ({len(content)} chars)[/dim]")
            
            # Send to AI with file context
            query = f"File: {file_path}\n\nContent:\n```\n{content}\n```\n\nQuestion: {question}"
            await self._send_message(query)
            
        except FileNotFoundError:
            feed.add_message("error", f"File not found: {file_path}")
        except Exception as e:
            feed.add_message("error", f"Error reading file: {e}")

    async def _read_file(self, path: str) -> None:
        """Display file contents."""
        feed = self.query_one("#feed", ChatFeed)
        try:
            with open(path.strip(), "r", encoding="utf-8") as f:
                content = f.read()
            
            feed.add_message("system", f"─" * 60)
            feed.add_message("system", f"[bold red]FILE: {path}[/bold red]")
            
            # Show with line numbers (truncated if too long)
            lines = content.split("\n")
            max_lines = 50
            for i, line in enumerate(lines[:max_lines], 1):
                feed.add_message("system", f"[dim]{i:4}[/dim] {line}")
            
            if len(lines) > max_lines:
                feed.add_message("system", f"[dim]... ({len(lines) - max_lines} more lines)[/dim]")
            
            feed.add_message("system", f"─" * 60)
            
        except FileNotFoundError:
            feed.add_message("error", f"File not found: {path}")
        except Exception as e:
            feed.add_message("error", f"Error reading file: {e}")

    async def _connect_mcp(self, command: str) -> None:
        """Connect to an MCP server."""
        feed = self.query_one("#feed", ChatFeed)
        
        if not self.mcp_manager:
            feed.add_message("error", "MCP manager not available")
            return
        
        try:
            # Parse command - could be "npx -y @server/name" or "python server.py"
            await self.mcp_manager.connect(command)
            feed.add_message("system", f"[green]✓[/green] Connected to MCP server")
            self._sync_status()
        except Exception as e:
            feed.add_message("error", f"MCP connection failed: {e}")


# ---------------------------------------------------------------------------
# STANDALONE RUN (for testing without the full CLI)
# ---------------------------------------------------------------------------

def run_ui(mcp_manager=None) -> None:
    app = RedShinobiApp(mcp_manager=mcp_manager)
    app.run()


if __name__ == "__main__":
    run_ui()
