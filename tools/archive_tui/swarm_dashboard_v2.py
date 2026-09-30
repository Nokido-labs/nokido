import asyncio

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static, TabbedContent, TabPane, Tree


class PseudoTerminal(Vertical):
    """Un terminal interactif simulé pour envoyer des commandes au système."""

    def __init__(self, name: str, cmd_prefix: list, **kwargs):
        super().__init__(**kwargs)
        self.terminal_name = name
        self.cmd_prefix = cmd_prefix

    def compose(self) -> ComposeResult:
        yield RichLog(
            id=f"out_{self.terminal_name.replace(' ', '_')}",
            classes="terminal_output",
            markup=True,
            highlight=True,
            wrap=True,
        )
        yield Input(
            placeholder=f"Taper une commande pour {self.terminal_name}...",
            classes="terminal_input",
            id=f"in_{self.terminal_name.replace(' ', '_')}",
        )

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        cmd = message.value
        if not cmd.strip():
            return

        # Clear input
        message.input.value = ""

        log = self.query_one(RichLog)
        log.write(f"\n[bold green]>[/bold green] [white]{cmd}[/white]")

        # Construction de la commande en fonction de l'environnement (WSL, Docker, PS)
        try:
            if "wsl" in self.cmd_prefix[0]:
                process = await asyncio.create_subprocess_exec(
                    self.cmd_prefix[0],
                    "--",
                    "bash",
                    "-c",
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            elif "docker" in self.cmd_prefix[0]:
                # On exécute dans docker (exegol-nokido) via sh
                process = await asyncio.create_subprocess_exec(
                    *self.cmd_prefix,
                    "sh",
                    "-c",
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                # Powershell 7 (pwsh) ou CMD
                process = await asyncio.create_subprocess_exec(
                    self.cmd_prefix[0],
                    self.cmd_prefix[1],
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

            stdout, stderr = await process.communicate()

            # Décodage intelligent (gestion des accents Windows/Linux)
            if stdout:
                try:
                    text_out = stdout.decode("utf-8")
                except:
                    text_out = stdout.decode("cp850", errors="replace")
                log.write(text_out.strip())

            if stderr:
                try:
                    text_err = stderr.decode("utf-8")
                except:
                    text_err = stderr.decode("cp850", errors="replace")
                log.write(f"[bold red]{text_err.strip()}[/bold red]")

        except Exception as e:
            log.write(f"[bold red]Erreur système: {e}[/bold red]")


class SwarmDashboardV2(App):
    """Le Dashboard Panoptique Nokido : Contrôle de toute la flotte."""

    CSS_PATH = "swarm_dashboard_v2.tcss"
    TITLE = "Nokido Master Control (Panoptique)"

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal():
            # ===============================================
            # PANNEAU GAUCHE: État global du système (Arbres)
            # ===============================================
            with Vertical(id="left_panel"):
                yield Static("ÉTAT DU SWARM", classes="panel_title")

                # Arbre des Agents
                tree_agents = Tree("Agents Actifs")
                tree_agents.root.expand()
                tree_agents.root.add_leaf("🧠 Cortex (7B) - Idle")
                tree_agents.root.add_leaf("⚡ Cervelet (1.5B) - Routing")
                tree_agents.root.add_leaf("☁️ Proxy Cloud - Listening")
                yield tree_agents

                # Arbre des Serveurs MCP
                tree_mcp = Tree("Serveurs MCP")
                tree_mcp.root.expand()
                tree_mcp.root.add_leaf("🔌 Nokido Hub (:8766)")
                tree_mcp.root.add_leaf("🐳 MCP Docker")
                tree_mcp.root.add_leaf("🕸️ Netcfg Agent")
                yield tree_mcp

                # Arbre des Tâches de Fond
                tree_tasks = Tree("Tâches de fond")
                tree_tasks.root.expand()
                tree_tasks.root.add_leaf("🔄 Polling Nokido")
                tree_tasks.root.add_leaf("💾 SQLite Ledger Sync")
                tree_tasks.root.add_leaf("🌐 Watch Agent (Crawl)")
                yield tree_tasks

            # ===============================================
            # PANNEAU CENTRAL: Terminaux interactifs à onglets
            # ===============================================
            with Vertical(id="main_panel"):
                yield Static("TERMINAUX D'EXÉCUTION (PTY SIMULÉS)", classes="panel_title")
                with TabbedContent(initial="tab_ps7"):
                    with TabPane("PowerShell 7", id="tab_ps7"):
                        yield PseudoTerminal("PS7", ["pwsh", "-Command"])
                    with TabPane("WSL (Ubuntu)", id="tab_wsl"):
                        yield PseudoTerminal("WSL", ["wsl"])
                    with TabPane("Docker (Exegol)", id="tab_docker"):
                        yield PseudoTerminal("Docker", ["docker", "exec", "-i", "exegol-laforge"])
                    with TabPane("Windows CMD", id="tab_cmd"):
                        yield PseudoTerminal("CMD", ["cmd", "/c"])

            # ===============================================
            # PANNEAU DROIT: Event Bus & Heartbeat
            # ===============================================
            with Vertical(id="right_panel"):
                yield Static("RÉSEAU & SUPERVISION", classes="panel_title")
                yield Static("❤️ HEARTBEAT: 60 BPM | Sync OK", id="heartbeat")
                yield RichLog(id="event_bus_log", markup=True, highlight=True, wrap=True)

        yield Footer()

    def on_mount(self) -> None:
        self.run_heartbeat()
        self.simulate_event_bus()

    @work(exclusive=True, thread=False)
    async def run_heartbeat(self):
        """Maintient l'affichage du rythme cardiaque du daemon."""
        heartbeat = self.query_one("#heartbeat", Static)
        toggle = True
        while True:
            char = "💓" if toggle else "🖤"
            # Changement de couleur pour l'effet visuel
            color = "#ff6b35" if toggle else "#883311"
            heartbeat.update(f"[{color}]{char} HEARTBEAT: 60 BPM | Sync OK[/{color}]")
            toggle = not toggle
            await asyncio.sleep(1)

    @work(exclusive=True, thread=False)
    async def simulate_event_bus(self):
        """Simule un flux d'événements sur le bus de messages de droite."""
        bus = self.query_one("#event_bus_log", RichLog)
        bus.write("[bold purple][SYSTEM] EventBus Nokido initialisé.[/bold purple]")
        bus.write("[dim]Écoute sur le port 8766...[/dim]")

        events = [
            "[green][INFO] Agent Netcfg connecté.[/green]",
            "[cyan][ROUTER] Message reçu de Claude (ID: 9482).[/cyan]",
            "[yellow][WARNING] Latence Ollama > 2000ms.[/yellow]",
            "[purple][HUB] Polling terminé (0 nouveaux messages).[/purple]",
            "[green][INFO] Snapshot SQLite sauvegardé.[/green]",
        ]

        import random

        while True:
            await asyncio.sleep(random.randint(2, 6))
            event = random.choice(events)
            bus.write(event)


if __name__ == "__main__":
    app = SwarmDashboardV2()
    app.run()
