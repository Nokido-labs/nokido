<!-- DEPORTE depuis RULES_SHARED.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de RULES_SHARED.md, re-facture a chaque tour. -->

# Gouvernance des clients SANS hooks — MCP-only (garde-fou par émanation)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## Gouvernance des clients SANS hooks — MCP-only (garde-fou par émanation)

Les garde-fous d'exécution (`bash_guard`, `hook_search_guard`, PostToolUse AST)
sont des HOOKS Claude Code. Les clients SANS système de hooks (Antigravity
agy/agi, certains IDE) ne peuvent PAS les enforcer → aucun filet automatique.
Un garde-fou ne s'expose à un client que s'il est (a) un hook natif du client,
(b) une règle émanée ICI (lue via `@import`), OU (c) imposé côté hub (videur /
firewall / exec_tier sur tout appel `run`). Les clients hook-less reposent sur
(b)+(c) — donc DISCIPLINE stricte, c'est le seul contrôle :

1. JAMAIS d'exécution shell/python native. TOUT passe par le hub `run`
   (action=shell/python/run_job) — gouverné (videur + firewall + exec_tier).
2. **MCP-only** : ne pas exposer de tool fichier/shell natif dans la config ;
   le serveur `laforge-sovereign-hub` est le SEUL chemin d'action. Shell natif
   non désactivable → client réputé non-gouverné, ne lui confier aucune action
   système.
3. Lecture fenêtrée (`read_function_body`/`rag`), jamais de dump de gros fichier.
4. Sans hook qui bloque, l'auto-discipline EST le contrôle — la respecter à 100 %.

