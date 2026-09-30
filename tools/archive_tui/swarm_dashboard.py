import asyncio
import json

from rich.syntax import Syntax
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Footer, Header, RichLog

# L'Event Bus Global (File d'attente Asynchrone)
# Il servira de boîte aux lettres pour tous nos terminaux
event_bus_queue = asyncio.Queue()


class AgentTerminal(Container):
    """Un terminal dédié à un agent spécifique."""

    def __init__(self, agent_name: str, id_name: str, **kwargs):
        super().__init__(**kwargs)
        self.agent_name = agent_name
        self.id_name = id_name
        self.border_title = f"{agent_name.upper()}"

    def compose(self) -> ComposeResult:
        # RichLog est conçu pour recevoir un flux continu sans ralentir l'UI
        yield RichLog(id=f"log_{self.id_name}", markup=True, highlight=True, wrap=True)

    def write_log(self, message: str, is_json: bool = False):
        log_widget = self.query_one(RichLog)
        if is_json:
            # Coloration syntaxique automatique pour les payloads JSON
            try:
                # Si c'est un dict ou une string JSON, on la formatte proprement
                if isinstance(message, dict):
                    formatted_json = json.dumps(message, indent=2, ensure_ascii=False)
                else:
                    formatted_json = json.dumps(json.loads(message), indent=2, ensure_ascii=False)
                log_widget.write(Syntax(formatted_json, "json", theme="monokai", word_wrap=True))
            except:
                log_widget.write(Syntax(str(message), "json", theme="monokai", word_wrap=True))
        else:
            log_widget.write(str(message))


class SwarmDashboard(App):
    """Le Dashboard Principal Nokido."""

    CSS_PATH = "swarm_dashboard.tcss"
    TITLE = "Nokido Swarm Dashboard"

    def compose(self) -> ComposeResult:
        yield Header()
        # Instanciation des 4 terminaux (ajout d'un identifiant sûr pour l'ID du log interne)
        yield AgentTerminal("Routeur (Cervelet 1.5B)", id_name="router", id="term_router")
        yield AgentTerminal("Coder (Cortex 7B)", id_name="coder", id="term_coder")
        yield AgentTerminal("Ollama Cloud Proxy", id_name="cloud", id="term_cloud")
        yield AgentTerminal("Nokido Hub (EventBus)", id_name="hub", id="term_hub")
        yield Footer()

    def on_mount(self) -> None:
        """Démarre la boucle d'écoute dès que l'interface est prête."""
        self.listen_to_swarm()
        # On lance aussi un petit script de démo pour remplir l'écran
        self.run_demo_simulation()

    @work(exclusive=True, thread=False)
    async def listen_to_swarm(self) -> None:
        """La boucle infinie qui lit le bus d'événements et dispatch."""
        self.query_one("#term_hub", AgentTerminal).write_log(
            "[SYSTEM] EventBus démarré. En attente de messages..."
        )

        while True:
            event = await event_bus_queue.get()

            # Exemple de structure d'événement :
            # {"source": "router", "message": "...", "type": "text"}
            source = event.get("source")
            message = event.get("message")
            is_json = event.get("type") == "json"

            # Dispatch vers le bon terminal graphique
            if source == "router":
                self.query_one("#term_router", AgentTerminal).write_log(message, is_json)
            elif source == "coder":
                self.query_one("#term_coder", AgentTerminal).write_log(message, is_json)
            elif source == "cloud":
                self.query_one("#term_cloud", AgentTerminal).write_log(message, is_json)
            elif source == "hub":
                self.query_one("#term_hub", AgentTerminal).write_log(message, is_json)

            event_bus_queue.task_done()

    @work(exclusive=True, thread=False)
    async def run_demo_simulation(self):
        """Fonction de démonstration pour montrer l'effet 'Matrix' en direct."""
        await asyncio.sleep(1)  # Laisse le temps à l'UI de s'afficher

        # 1. Le Routeur capte une question
        await event_bus_queue.put(
            {
                "source": "router",
                "type": "text",
                "message": ">> REQUÊTE REÇUE: 'Analyse mon réseau et trouve l'IP de la passerelle.'",
            }
        )
        await asyncio.sleep(0.5)
        await event_bus_queue.put(
            {
                "source": "router",
                "type": "json",
                "message": '{"is_interesting": true, "category": "action_required", "summary": "Trouver IP passerelle"}',
            }
        )

        # 2. Le Hub intercepte
        await asyncio.sleep(0.8)
        await event_bus_queue.put(
            {
                "source": "hub",
                "type": "text",
                "message": "[ROUTAGE] Tâche technique détectée. Assemblage des schémas d'outils réseaux...",
            }
        )
        await asyncio.sleep(0.5)
        await event_bus_queue.put(
            {
                "source": "hub",
                "type": "text",
                "message": "[ROUTAGE] Transmission du payload vers l'Agent Coder (7B).",
            }
        )

        # 3. Le Coder réfléchit
        await asyncio.sleep(1)
        await event_bus_queue.put(
            {
                "source": "coder",
                "type": "text",
                "message": "Réflexion en cours...\nJe dois exécuter une commande shell pour obtenir l'IP de la passerelle. Sous Windows, je peux utiliser `ipconfig` ou `Get-NetRoute`.",
            }
        )
        await asyncio.sleep(1)
        await event_bus_queue.put(
            {
                "source": "coder",
                "type": "json",
                "message": {
                    "tool_calls": [
                        {"name": "run_local_shell", "arguments": {"command": "ipconfig"}}
                    ]
                },
            }
        )

        # 4. Le Hub exécute
        await asyncio.sleep(0.5)
        await event_bus_queue.put(
            {
                "source": "hub",
                "type": "text",
                "message": "[PARE-FEU] Ordre reçu de l'Agent Coder : `run_local_shell('ipconfig')`",
            }
        )
        await asyncio.sleep(0.5)
        await event_bus_queue.put(
            {"source": "hub", "type": "text", "message": "[EXECUTION] Exécution locale en cours..."}
        )
        await asyncio.sleep(1)
        await event_bus_queue.put(
            {
                "source": "hub",
                "type": "text",
                "message": "Résultat: \nCarte Ethernet Ethernet:\nPasserelle par défaut . . . . . . . . . : localhost\n",
            }
        )

        # 5. Appel au Cloud pour comparer ou valider
        await asyncio.sleep(0.8)
        await event_bus_queue.put(
            {
                "source": "cloud",
                "type": "text",
                "message": "Requête de validation externe: est-ce que localhost est une adresse privée standard ?",
            }
        )
        await asyncio.sleep(1)
        await event_bus_queue.put(
            {
                "source": "cloud",
                "type": "json",
                "message": '{"response": "Oui, localhost est une adresse IP privée de classe C couramment utilisée pour les routeurs/box internet domestiques."}',
            }
        )


if __name__ == "__main__":
    app = SwarmDashboard()
    app.run()
