# 🗺️ ROADMAP SYNC : NOKIDO V14 → V15
*Date : 16 Juin 2026 | Statut : Transition Active*

## 1. 🏁 BILAN V14 (DAEMON & AUDIT PROFOND) - [TERMINÉ / STABILISÉ]
La V14 a résolu le "Mur de Verre" des CLI OAuth sur Windows (limite `argv` 32KB).
- **Daemon V14** : Serveur FastAPI (:8770) pilotant Claude/Gemini via REPL (stdin).
- **Audit Profond** : Capacité d'injecter des fichiers entiers (>50KB) pour analyse.
- **Sécurité** : 
    - `SemanticFirewall` : Ring MASTER (-1) interdit de sortie cloud.
    - `IntegrityManager` : Time-Lock MASTER (300s) forcé sur les tokens atténués.
    - `SovereignMembrane` : Chiffrement DPAPI systématique des originaux (at-rest).

## 2. 🚀 ROADMAP V15 (SOUVERAINETÉ DÉCENTRALISÉE) - [PAS DÉMARRÉ — vérifié 30/08]

> Ce document se disait « EN COURS » depuis le 16/06. Mesure du 30/08 : le module que
> sa propre dernière ligne annonce comme prochaine étape, `app/forge_gitgrasp.py`,
> **n'existe pas**. Aucun code GitGrasp / NIP-34 / ngit / nak dans le dépôt. Le chantier
> n'a pas commencé : deux mois et demi d'un « en cours » qui ne l'était pas. Il reste
> une INTENTION valide — elle est simplement à requalifier, ou à reprendre.
L'objectif est l'indépendance totale vis-à-vis des forges centralisées (GitHub/Codeberg).
- **GitGrasp Integration** : Support du protocole NIP-34 (Nostr) pour les issues/PRs/clones.
- **Tooling** : Intégration de `ngit` et `nak` dans le hub MCP.
- **Identity Persona** : Signature cryptographique des commits par l'agent via le TPM local.

## 🧠 VISION POUR CLAUDE (SYNC)
*Claude, voici les points de friction résolus et la direction actuelle :*

1.  **Recherche Sécurisée** : Ne lance plus de `Get-ChildItem -Recurse` brut. Utilise les filtres d'exclusion (`.git`, `node_modules`, `.venv`, `*.db`) et limite à `Select-Object -First 30`. Sinon, l'interface se fige en mode "Shift+Tab to unfocus".
2.  **Audit Trail** : Les fichiers dans `LaForge/app/` ont été blindés aujourd'hui contre les fuites de secrets.
3.  **V15 Focus** : On bascule sur l'architecture GitGrasp. L'idée est de traiter le code comme un flux de données décentralisé plutôt que comme des dépôts statiques.

*Prochaine étape : Initialisation du module `app/forge_gitgrasp.py`* — **jamais faite**
(vérifié 30/08 : fichier absent). La signature de commit par TPM et l'intégration Nostr
restent au stade de l'intention.

> Note de méthode : le point 1 de la « vision » ci-dessus (ne pas lancer de
> `Get-ChildItem -Recurse` brut) s'est re-vérifié le 30/08 — deux balayages récursifs du
> dépôt ont expiré au cap de 120 s. La forme qui marche reste `git ls-files`, instantané
> et limité au suivi.
