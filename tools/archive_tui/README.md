# Archive: TUI Swarm Dashboard (Expérimentation Textual)

## Contexte (30 Avril 2026)
Création d'une interface utilisateur en terminal (TUI) utilisant le framework `textual` pour visualiser en temps réel l'activité de l'essaim d'agents (Swarm) de Nokido.
L'objectif initial était de visualiser les logs du Routeur (Cervelet 1.5B), du Coder (Cortex 7B), du Proxy Cloud (Ollama), et l'EventBus de Nokido simultanément.

Une Version 2 a ajouté des terminaux interactifs (PS7, WSL, Docker) directement intégrables dans l'interface, ainsi qu'une vue arborescente de l'état du système.

## Décision architecturale
Bien que fonctionnelle et esthétique ("effet Matrix"), l'interface TUI a été mise de côté pour le moment au profit d'une interface web plus professionnelle et moderne, inspirée de projets comme Lobe Chat. 

**Cependant, cette TUI est précieuse et conservée pour un usage ultérieur**, spécifiquement pour la gestion purement CLI, les environnements sans serveur graphique, ou le débogage bas niveau.

## Fichiers conservés
Les fichiers suivants ont été déplacés dans ce dossier pour archivage propre :
- `swarm_dashboard.py` / `swarm_dashboard.tcss` : Première version (Quadrants de logs).
- `swarm_dashboard_v2.py` / `swarm_dashboard_v2.tcss` : Deuxième version (Panoptique avec terminaux interactifs PTY et arbres d'état).

## Comment tester à l'avenir
```powershell
~\miniforge3\python.exe "~\Script python IA\Nokido\tools\archive_tui\swarm_dashboard_v2.py"
```