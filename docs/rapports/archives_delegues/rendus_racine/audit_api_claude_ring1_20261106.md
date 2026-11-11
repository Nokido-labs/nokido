# Audit API Claude en ring 1 (lecture seule, 2026-11-06)
Limite : sources lues par extraits ; app/forge_ring_admin.py, forge_cli_route.py (hors L88), forge_task_executor.py L4264+ non lus : ILLISIBLE.

## 1. Piliers
| Exigence | Etat | Preuve |
|---|---|---|
| A1 Proxy loopback | PROUVE | forge_anthropic_ingress.py:141 (`--host` defaut 127.0.0.1), :155 uvicorn ; services.toml:1580 |
| A2 Jeton interne ephemere verifie a l'entree | ABSENT | `messages` L111-136 ne lit aucun en-tete d'auth ; agent fixe `AGENT` L37 |
| A2b Emission de jetons existante (reutilisable) | PROUVE | forge_auth_tokens.py:108 `login_agent`, bail 30 min (`exp=time.time()+1800`), `dpop_jwk` optionnel |
| A3 Cle reelle au coffre DPAPI seulement | PROUVE (pour le lanceur) | forge_cli_route.py:88-90 (cle du coffre resolue au lancement, jamais sur disque) ; forge_cli_harness.py:295 `ANTHROPIC_API_KEY_ORG`. L'ingress lui-meme : aucune cle lue, ILLISIBLE pour l'amont |
| A4 Validation `tools` | ABSENT cote ingress : `tools` jamais lu (L117-124), perdu sans erreur. Validateur MCP existant mais non branche : payload_validator.py:30 `validate_tools` |
| A5 Validation `tool_choice` | ABSENT | aucune occurrence dans payload_validator.py, forge_llm_format_bridge.py ni l'ingress (git grep) |
| A6 Coupe-circuit budget | PROUVE cote executeur / ABSENT cote ingress | services.toml:1847-1848 (plafond 3 $/6 $ puis SUPPRIME, compteur seul) ; ingress : `max_tokens` du client repris tel quel L120 |
| A7 Coupe-circuit RAM | ILLISIBLE (app/forge_resource_manager.py non lu) ; ingress : `limit_concurrency=64` seulement (L155) |
| B Etat partage MCP/tableau noir | PROUVE (hub existant, outils blackboard_*, zone tree_locks) ; l'ingress ne l'utilise pas : `hub_call("ask")` seul, bridge:170 |
| C Un ecrivain par arbre | PROUVE | forge_task_executor.py:1707-1715 (worktree par tache, refus sans repli sur arbre partage) ; services.toml:1850 |
| D1 Sortie LLM encapsulee non fiable | ABSENT | bridge:177 : `reply` rendu brut comme texte ; seul pare-feu PII (L163-166), pas de balisage de non-confiance |
| D2 Hooks PreToolUse | ABSENT | git grep PreToolUse sur .claude, bridge, validator : 0 resultat |
| D3 Pare-feu entrant | PROUVE | bridge:160-166 `pre_flight` (ring=3 par defaut, L154) |

## 2. Reponse fermee
- Identite ring 1 : CLAUDE_HEADLESS (deja ring 1, executeur services.toml:1851-1856, `claude -p` avec cle du coffre, harness:377-386 refuse sans cle). Elle agit via CapabilityToken du ring 1 et des outils hub, dans un worktree de tache.
- ANTHROPIC_API reste provider ring 3 (agent_identities.json:1269-1271) : un fournisseur ne porte aucune session de client du hub (etabli). Il n'a pas a monter.
- Elever ANTHROPIC_API donnerait-il a un texte de LLM l'acces aux outils du hub ? NON par lui-meme : le texte rendu n'est que `reply` (bridge:177), jamais execute ; le ring s'applique a l'appelant de `hub_call` (bridge:170, `agent=AGENT`), pas au contenu. MAIS le risque reel est autre : si un client rejoue ce texte comme appel d'outil sous un ring 1, il y a escalade. L'elevation ne repare rien et elargirait l'etat actuel (ingress sans auth, A2).
- Plus petit changement sur : ne pas modifier le ring ; exiger a l'entree de `messages` un jeton ephemere (obtenu par `login_agent` en ring 1, expire 30 min) et refuser 401 sans lui ; rejeter 400 toute requete avec `tools`/`tool_choice` tant que non valides (fini la perte silencieuse).

## 3. Lots ordonnes
1. Auth ingress (fichier : forge_anthropic_ingress.py `messages`, + verif via forge_auth_tokens). NR : tests/nr/ nouveau test_ingress_auth_nr.py (sans jeton 401, jeton expire 401, jeton valide 200). Oui owner : choix de l'identite emettrice du jeton.
2. Refus explicite `tools`/`tool_choice` (meme fonction ; reutiliser `validate_tools`, payload_validator.py:30). NR : corps avec tools -> 400, sans -> inchange.
3. Plafonds : `max_tokens` borne, budget et RAM (consulter forge_resource_manager.py, a lire d'abord). NR : depassement -> 429. Oui owner : valeurs de plafond (le 22/10 il a supprime la limite de depenses).
4. Encapsulation sortie LLM : `ask_via_hub` / `messages_to_prompt` balisent la reponse comme donnee non fiable ; aucune execution de contenu. NR : texte contenant un faux appel d'outil rendu inerte.
5. Hooks PreToolUse (.claude/settings, a creer) refusant outils hors liste pour CLAUDE_HEADLESS. Oui owner : liste d'outils autorises, modification de configuration.
6. Etat partage : l'ingress publie ses compteurs au tableau noir (blackboard_propose_fact), tree_locks respecte. NR : un seul ecrivain par arbre. Oui owner : aucun si zone scratch.
Toute cle API, tout redemarrage de service (services.toml) : Oui owner.
