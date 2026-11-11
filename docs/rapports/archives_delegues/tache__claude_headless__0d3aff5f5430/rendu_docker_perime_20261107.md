# Rendu : catalogue Docker PERIME = 0 outil docker_* liste (07/11/2026)

Accord owner, mesure AGY : ~800 jetons/session economises sur `logs/mcp_audit.log` pour les 8 outils `docker_*` marques perime.

## Changement
- `app/forge_mcp_registry.py` / `ToolRegistry._docker_tools_en_cache` : si `etat == "PERIME"`, rend `[]`.
  Le prefixe « [catalogue perime] » disparait avec la branche (code mort retire).
  Un catalogue FRAIS liste toujours ses outils. `docker_action` (natif) et `handle_docker_action` ne bougent pas.
  `_handle_docker_proxy` reste en place. Aucun redemarrage.

## TDD
- Rouge : `test_catalogue_perime_ne_liste_aucun_outil_docker` echoue (liste `docker_mcp-find`, `docker_code-mode`).
- Vert apres correction.

## Tests
- `tests/nr/test_middleware_outils_docker_du_catalogue_nr.py` : 4 tests ajoutes (perime = 0 outil docker_* ; frais = outils listes ; `docker_action` present si perime ; dispatch `_handle_docker_proxy` present).
- `tests/nr/test_docker_tools_list_nr.py` : **test existant adapte** (signale). `test_catalogue_perime_le_dit` attendait le prefixe « perime » sur `docker_fetch`. Il devient `test_catalogue_perime_ne_liste_aucun_outil` (assertion d'absence). Hors du seul fichier NR initialement prevu, mais c'est le test qui attendait l'ancien comportement.
- Lot : 24 passes (middleware, tools_list, catalogue_cache, proxy_ring, catalogue_rafraichir, appui_forge_docker_bridge).

## Non fait
- `config/agent_identities.json` non touche. Pas de push, pas de commit (fait par l'executeur).
- Le gain de ~800 jetons et les « 0 appel sur logs/mcp_audit.log » sont la mesure AGY rapportee par l'owner ; je ne les ai pas re-mesures.
