"""Ancienne application Textual qui affiche un arbre de compétences coloré par état.

Classes : SkillNode (nœud rendu avec icône selon waiting, searching, learning ou
mastered), SkillTree (add_or_update_skill crée ou met à jour un nœud) et
AdvancedRagTUI (disposition journal plus panneau de compétences, lancée via __main__).
run_demo_cycle simule des changements d'état, mais on_mount l'appelle sans await :
la démo ne s'exécute pas en l'état.
Aucun import de cette copie legacy dans le dépôt : Nokido.py, forge_mixin_ui et les
scripts _sandbox importent app/skilltree.py, pas celui-ci. Aucun effet de bord.
"""
import asyncio

from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Static, Log, Label, ProgressBar
from textual.reactive import reactive


# Règle de l'Incrémentalité : "Toute connaissance apprise via @disco doit être
# taguée UNVERIFIED. Elle ne passe en VERIFIED que si elle est utilisée avec succès
# dans 3 tâches différentes sans erreur système."
# --- COMPOSANT SKILL TREE ---
class SkillNode(Static):
    """Un nœud de compétence qui change de couleur selon l'état."""

    status = reactive("waiting")

    def render(self) -> str:
        icons = {"waiting": "⚪", "searching": "🔍", "learning": "🧪", "mastered": "✅"}
        colors = {"waiting": "gray", "searching": "blue", "learning": "yellow", "mastered": "green"}
        return f"[{colors[self.status]}]{icons[self.status]} {self.renderable}[/]"


class SkillTree(Vertical):
    """Conteneur pour l'animation des compétences en bas à gauche."""

    def add_or_update_skill(self, name, status):
        try:
            node = self.query_one(f"#{name}", SkillNode)
            node.status = status
        except:
            new_node = SkillNode(name, id=name)
            new_node.status = status
            self.mount(new_node)


# --- APPLICATION PRINCIPALE ---
class AdvancedRagTUI(App):
    CSS = """
    #main-layout { layout: grid; grid-size: 2; grid-columns: 1fr 3fr; }
    #left-sidebar { border-right: tall $primary; padding: 1; height: 100%; }
    #skill-tree-area { 
        height: 40%; 
        border-top: dashed $accent; 
        margin-top: 1;
        padding-top: 1;
    }
    .status-mastered { color: green; bold; }
    .status-learning { color: yellow; italic; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main-layout"):
            with Vertical(id="left-sidebar"):
                yield Label("[bold]SYSTÈME RAG[/]")
                yield ProgressBar(id="overall-progress", total=100)
                yield Label("\n[bold]CONNAISSANCES RÉSEAU[/]")
                with ScrollableContainer(id="skill-tree-area"):
                    yield SkillTree(id="tree")

            with Vertical(id="right-content"):
                yield Log(id="main-log")
        yield Footer()

    def on_mount(self):
        self.log = self.query_one("#main-log")
        self.tree = self.query_one("#tree")
        self.log.write_line("🤖 Agentic RAG prêt. En attente d'une commande complexe...")

        # Simulation d'une détection de compétences pour l'exemple
        self.run_demo_cycle()

    async def run_demo_cycle(self):
        """Démonstration du flux Agentic."""
        steps = [
            ("Analyse_Sémantique", "searching"),
            ("Analyse_Sémantique", "mastered"),
            ("ML_Regression", "searching"),
            ("ML_Regression", "learning"),
            ("ML_Regression", "mastered"),
            ("Sécurité_Sandbox", "searching"),
            ("Sécurité_Sandbox", "learning"),
        ]

        for name, status in steps:
            await asyncio.sleep(1.5)
            self.tree.add_or_update_skill(name, status)
            self.log.write_line(f"Mise à jour compétence: {name} -> {status}")


if __name__ == "__main__":
    app = AdvancedRagTUI()
    app.run()
