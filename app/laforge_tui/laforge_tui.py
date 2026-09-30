import asyncio

# Import oublie, mesure le 2026-09-08 : json.JSONDecodeError L177 -- dans une
# clause except, donc la NameError aurait masque l'erreur qu'on rattrapait.
import json
import httpx


def _entetes_hub() -> dict:
    """En-tetes d'organe vers le hub : jeton propre TUI, sinon SERVICES -- jamais le maitre."""
    try:
        from nokido_agent.app.forge_hub_client import entetes_organe

        return entetes_organe("TUI")
    except Exception:  # noqa: BLE001 -- sans porteur, le hub rend 401 : l'echec reste visible
        return {}

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, RichLog, Static, TabbedContent, TabPane, Tree

class NokidoTUI(App):
    """A Textual TUI for monitoring the Nokido ecosystem."""

    CSS_PATH = "nokido_tui.tcss"
    TITLE = "Nokido Monitoring Dashboard"

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal():
            with Vertical(id="left_panel"):
                yield Static("SERVICES", classes="panel_title")
                yield Tree("MCP Services", id="services_tree")

            with Vertical(id="main_panel"):
                yield Static("LOGS", classes="panel_title")
                with TabbedContent(initial="tab_hub"):
                    with TabPane("Nokido Hub", id="tab_hub"):
                        yield RichLog(id="hub_log")
                    with TabPane("Agent: Gemini", id="tab_gemini"):
                        yield RichLog(id="gemini_log")
                    with TabPane("Agent: Claude", id="tab_claude"):
                        yield RichLog(id="claude_log")

            with Vertical(id="right_panel"):
                yield Static("STATUS", classes="panel_title")
                yield RichLog(id="status_log", markup=True, highlight=True, wrap=True)

        yield Footer()

    BINDINGS = [
        ("r", "restart_service", "Restart Service"),
        ("q", "quit", "Quit"),
    ]

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        # We use call_later to ensure the worker starts after the UI is fully ready
        self.call_later(self.update_services_tree)
        self.call_later(self.stream_hub_events)
        self.call_later(self.load_history)

    @work
    async def action_restart_service(self) -> None:
        """Restarts the selected service."""
        tree = self.query_one("#services_tree", Tree)
        node = tree.cursor_node
        status_log = self.query_one("#status_log", RichLog)

        if not node or not node.data:
            status_log.write("[red]No service selected.[/red]")
            return

        service_name = node.data.get("name")
        if not service_name:
            # Maybe we selected a parent node
            if node.label.plain.startswith("MCP Services"):
                 status_log.write("[yellow]Select a specific service to restart.[/yellow]")
            else:
                 status_log.write("[red]Cannot determine service name to restart.[/red]")
            return
        
        status_log.write(f"Attempting to restart service: [bold]{service_name}[/bold]...")

        try:
            async with httpx.AsyncClient() as client:
                # Note: This endpoint requires an admin token, which we are not providing here.
                # The request will likely fail with a 401 Unauthorized unless the hub is run
                # without authentication. This is a known limitation for this implementation.
                response = await client.post(f"http://127.0.0.1:8766/api/services/restart/{service_name}")
                
                if response.status_code == 200:
                    status_log.write(f"[green]Successfully sent restart command for {service_name}.[/green]")
                elif response.status_code == 401:
                    status_log.write(f"[bold red]Unauthorized: Cannot restart {service_name}. Admin token required.[/bold red]")
                else:
                    status_log.write(f"[red]Failed to restart {service_name}. Status: {response.status_code}[/red]")
                    try:
                        status_log.write(f"Response: {response.json()}")
                    except Exception:
                        pass # Ignore if response is not json
        
        except httpx.ConnectError as e:
            status_log.write(f"[bold red]Connection Error: Could not send restart command.[/bold red]")


    @work(exclusive=True)
    async def update_services_tree(self) -> None:
        """Updates the services tree with data from the hub."""
        tree = self.query_one("#services_tree", Tree)
        tree.clear()
        tree.root.set_label("MCP Services")
        tree.root.expand()
        
        status_log = self.query_one("#status_log", RichLog)

        try:
            async with httpx.AsyncClient() as client:
                # 2026-09-24 : /api/services/list (topologie) exige une identite prouvee.
                response = await client.get("http://127.0.0.1:8766/api/services/list",
                                            headers=_entetes_hub())
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("ok"):
                        services = result.get("data", {}).get("services", {})
                        tree.root.set_label(f"MCP Services ({len(services)} running)")
                        
                        for name, info in sorted(services.items()):
                            status = info.get("status", "unknown")
                            if status == "running":
                                label = f"[green]● {name}[/green]"
                            elif status == "sleeping":
                                label = f"[yellow]● {name}[/yellow]"
                            else:
                                label = f"[red]● {name}[/red]"
                            
                            info['name'] = name # Ensure the name is in the data dict
                            node = tree.root.add(label, data=info)
                            node.add_leaf(f"PID: {info.get('pid')}")
                            node.add_leaf(f"Uptime: {info.get('uptime_s')}s")

                    else:
                        tree.root.set_label("[red]Error fetching services[/red]")
                        status_log.write(f"[red]Services list error: {result.get('error')}[/red]")
                else:
                    tree.root.set_label("[red]Hub connection failed[/red]")
                    status_log.write(f"[red]Failed to connect to Hub for services: {response.status_code}[/red]")

        except httpx.ConnectError as e:
            tree.root.set_label("[bold red]Hub Unreachable[/bold red]")
            if "Connection refused" in str(e):
                 status_log.write("[bold red]Hub is not running on port 8766.[/bold red]")
            else:
                 status_log.write(f"[bold red]Connection to Hub failed: {e}[/bold red]")
        
        # Refresh periodically
        await asyncio.sleep(30)
        self.update_services_tree()


    @work(exclusive=True, group="hub_stream")
    async def stream_hub_events(self) -> None:
        """Connects to the hub's SSE stream and updates logs."""
        status_log = self.query_one("#status_log", RichLog)
        hub_log = self.query_one("#hub_log", RichLog)
        gemini_log = self.query_one("#gemini_log", RichLog)
        claude_log = self.query_one("#claude_log", RichLog)

        agent_logs = {
            "GEMINI": gemini_log,
            "CLAUDE": claude_log,
            "HUB": hub_log,
        }
        
        try:
            async with httpx.AsyncClient() as client:
                async with client.stream("GET", "http://127.0.0.1:8766/api/network/stream") as response:
                    status_log.write("[green]Successfully connected to Hub event stream.[/green]")
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            try:
                                data = json.loads(line[5:])
                                agent = data.get("agent", "HUB")
                                target_log = agent_logs.get(agent, status_log)
                                
                                # Pretty print the event
                                event_str = f"[{data.get('ts', '')}] {data.get('direction', '')} {data.get('tool', '')} - Status: {data.get('status', 'OK')}"
                                target_log.write(event_str)

                            except json.JSONDecodeError:
                                status_log.write(f"[red]Error decoding SSE data: {line}[/red]")

        except httpx.ConnectError as e:
            status_log.write(f"[bold red]Stream connection failed: {e}. Reconnecting in 10s.[/bold red]")
            await asyncio.sleep(10)
            self.stream_hub_events() # Retry connection
        except Exception as e:
            status_log.write(f"[bold red]An unexpected error occurred in stream: {e}. Reconnecting in 10s.[/bold red]")
            await asyncio.sleep(10)
            self.stream_hub_events() # Retry connection


    @work(exclusive=True, group="history_loader")
    async def load_history(self) -> None:
        """Loads historical logs from the hub."""
        status_log = self.query_one("#status_log", RichLog)
        hub_log = self.query_one("#hub_log", RichLog)
        gemini_log = self.query_one("#gemini_log", RichLog)
        claude_log = self.query_one("#claude_log", RichLog)
        
        agent_logs = {
            "GEMINI": gemini_log,
            "CLAUDE": claude_log,
            "HUB": hub_log,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("http://127.0.0.1:8766/api/network/history?limit=100")
                if response.status_code == 200:
                    history = response.json().get("events", [])
                    status_log.write(f"Loaded {len(history)} historical events.")
                    for event in reversed(history): # aiter_lines is newest first, so we reverse
                        agent = event.get("agent", "HUB")
                        target_log = agent_logs.get(agent, status_log)
                        event_str = f"[{event.get('ts', '')}] {event.get('direction', '')} {event.get('tool', '')} - Status: {event.get('status', 'OK')}"
                        target_log.write(event_str)
                else:
                    status_log.write(f"[red]Failed to load history: {response.status_code}[/red]")
        except httpx.ConnectError as e:
            status_log.write(f"[bold red]Could not load history, connection failed: {e}[/bold red]")




if __name__ == "__main__":
    app = NokidoTUI()
    app.run()
