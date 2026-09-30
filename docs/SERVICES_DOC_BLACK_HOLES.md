# Nokido Doc Black Holes — Audit 2026-05-02

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `NokidoGraphExplorer :7474` est **arrete depuis le 2026-08-10** (boot-trim RAM) — reveil a la demande.


> Auto-généré par audit AI pour ingestion RAG. Chaque entrée = 1 section H3.
> Source : audit statique `app/`, `tools/`, `docs/`, `proxy_deno/` post-création
> de `tools/SERVICES.md`. Périmètre : trous noirs **bloquants** pour debug ou
> onboarding, pas cosmétiques. Cible : 25 entrées. Vectorisable BM25/FAISS.
>
> **Anti-duplication** : les services NSSM sont déjà couverts par
> `tools/SERVICES.md`. Les orphelins de code v13.6 sont couverts par
> `docs/v13_6_orphan_inventory.md`. Les API publiques dormantes sont couvertes
> par `docs/API_DORMANTE.md`. Ce fichier ne ré-explore PAS ces axes.

## TOC

- [Black Hole 1 : Port 7474 graph_explorer non documenté](#black-hole-1--port-7474-graph_explorer-non-documenté)
- [Black Hole 2 : Port 8090 llamacpp_python non documenté](#black-hole-2--port-8090-llamacpp_python-non-documenté)
- [Black Hole 3 : Port 8080 sur-réservé (collision multi-services)](#black-hole-3--port-8080-sur-réservé-collision-multi-services)
- [Black Hole 4 : Collision env LAFORGE_HUB_PORT (8766 vs 7400)](#black-hole-4--collision-env-nokido_hub_port-8766-vs-7400)
- [Black Hole 5 : INFRA.md référence port 8765 (drift)](#black-hole-5--infra-md-référence-port-8765-drift)
- [Black Hole 6 : NokidoDenoHubMCP / DenoWebHub statut shadow](#black-hole-6--nokidodenohubmcp--denowebhub-statut-shadow)
- [Black Hole 7 : Port NokidoLlamaRouter dans bat = 8092 non doc](#black-hole-7--port-nokidollamarouter-dans-bat--8092-non-doc)
- [Black Hole 8 : forge_autonomous_loops pointe vers :8080 fantôme](#black-hole-8--forge_autonomous_loops-pointe-vers-8080-fantôme)
- [Black Hole 9 : LAFORGE_LLAMACPP_PORT défaut 1234 mais doc dit 8090/8080](#black-hole-9--nokido_llamacpp_port-défaut-1234-mais-doc-dit-80908080)
- [Black Hole 10 : Hebbian / Homeostasis / Endocrine — rôle réel opaque](#black-hole-10--hebbian--homeostasis--endocrine--rôle-réel-opaque)
- [Black Hole 11 : tools/nokido_homeostasis.py vs forge_homeostasis_orchestrator.py](#black-hole-11--toolsnokido_homeostasispy-vs-forge_homeostasis_orchestratorpy)
- [Black Hole 12 : ports BROADCAST_PORT 9765 / 5558 swarm/PUB non doc](#black-hole-12--ports-broadcast_port-9765--5558-swarmpub-non-doc)
- [Black Hole 13 : env vars critiques absentes de Nokido.env.example](#black-hole-13--env-vars-critiques-absentes-de-nokidoenvexample)
- [Black Hole 14 : LAFORGE_ADMIN_TOKEN obligatoire mais non dans sample.env](#black-hole-14--nokido_admin_token-obligatoire-mais-non-dans-sampleenv)
- [Black Hole 15 : ADR-002 plan migration SSE non daté d exécution](#black-hole-15--adr-002-plan-migration-sse-non-daté-d-exécution)
- [Black Hole 16 : netcfg-agent vit hors Nokido/ (chemin ~\Script python IA\netcfg-agent*)](#black-hole-16--netcfg-agent-vit-hors-laforge-chemin-cusersnaarobscript-python-ianetcfg-agent)
- [Black Hole 17 : NokidoAutonomousLoops opaque — 6 patterns non listés en surface](#black-hole-17--nokidoautonomousloops-opaque--6-patterns-non-listés-en-surface)
- [Black Hole 18 : forge_handler_advanced subprocess git sans audit](#black-hole-18--forge_handler_advanced-subprocess-git-sans-audit)
- [Black Hole 19 : env vars CIRCADIAN_* / LAFORGE_HEBBIAN_* / HOMEO_* invisibles](#black-hole-19--env-vars-circadian--nokido_hebbian--homeo_-invisibles)
- [Black Hole 20 : forge_swarm UDP broadcast 9765 non firewallé](#black-hole-20--forge_swarm-udp-broadcast-9765-non-firewallé)
- [Black Hole 21 : forge_proxy_guard (port 8080 uvicorn) sans NSSM ni service](#black-hole-21--forge_proxy_guard-port-8080-uvicorn-sans-nssm-ni-service)
- [Black Hole 22 : MCP_HTTP_PORT 8765 dans tools/forge_mcp_http.py vs hub 8766](#black-hole-22--mcp_http_port-8765-dans-toolsforge_mcp_httppy-vs-hub-8766)
- [Black Hole 23 : tokens hardcodés dans nokido_mcp_proxy.py](#black-hole-23--tokens-hardcodés-dans-nokido_mcp_proxypy)
- [Black Hole 24 : Modules entry-point-only (rss_watcher / hebbian / graph) jamais importés](#black-hole-24--modules-entry-point-only-rss_watcher--hebbian--graph-jamais-importés)
- [Black Hole 25 : Mismatch Python NokidoHomeostasis (3.12) vs autres daemons (py314)](#black-hole-25--mismatch-python-nokidohomeostasis-312-vs-autres-daemons-py314)

---

### Black Hole 1 : Port 7474 graph_explorer non documenté

**What** : `forge_graph_explorer.py` lance un serveur web sur **:7474** (cytoscape.js GUI) — port absent de `tools/SERVICES.md`, `INFRA.md`, `LANCER.md`.
**Where** : `app/forge_graph_explorer.py:8` (commentaire `→ http://localhost:7474`) ; cross-ref `app/forge_health_diagnostic.py:232` (`graph_explorer: http://127.0.0.1:7474/`).
**Why** : LLM agent qui fait `Get-NetTCPConnection` voit un listener inconnu → faux positif "service inconnu" / réflexe "kill -9". NSSM `NokidoGraph` ne déclare pas de port mais en bind un.
**Fix** : Ajouter ligne dans `tools/SERVICES.md` § NokidoGraph : `Port : 7474 (Cytoscape GUI HTTP)`.

### Black Hole 2 : Port 8090 llamacpp_python non documenté

**What** : Endpoint `llama-cpp-python` server sur **:8090** monitoré par `forge_health_diagnostic.audit_services_http()` mais aucun service NSSM ne le démarre.
**Where** : `app/forge_health_diagnostic.py:231` (`llamacpp_python: http://127.0.0.1:8090/v1/models`) ; `docs/llamacpp_setup.md:13` mentionne 8090 ; aucun bat NSSM.
**Why** : Health check signale "DOWN" en permanence → bruit dans alertes. Onboarding LLM croit qu'un service est cassé alors qu'il n'a jamais existé en NSSM.
**Fix** : Soit créer NSSM `NokidoLlamaPython` (bat dédié), soit retirer la cible du health check et marquer "manuel uniquement" dans `llamacpp_setup.md`.

### Black Hole 3 : Port 8080 sur-réservé (collision multi-services)

**What** : Le port **:8080** est revendiqué par 4 composants concurrents : searxng Docker, `app/nokido_proxy_guard.py:148` (uvicorn), default de `tools/nokido_tui_bridge.py:11`, et URL hardcodée dans `app/forge_autonomous_loops.py:44`.
**Where** : `SITUATION.md:25` (searxng:8080 Docker UP), `app/nokido_proxy_guard.py:148`, `app/forge_autonomous_loops.py:44`, `app/forge_web_fallback.py:10`, `app/forge_research_agent.py:46`.
**Why** : Premier service qui bind gagne, les autres bind échouent silencieusement → comportements aléatoires post-reboot. Faire-Savoir pour LLM : `:8080 = searxng` est le contrat de fait, mais pas écrit.
**Fix** : Rédiger dans `INFRA.md` une **réservation de ports** : `:8080 = searxng (locked)`. Patcher `forge_autonomous_loops.py:44` pour lire `LAFORGE_LLAMACPP_URL` au lieu de hardcoder 8080.

### Black Hole 4 : Collision env LAFORGE_HUB_PORT (8766 vs 7400)

**What** : La variable d'env `LAFORGE_HUB_PORT` est lue avec deux defaults différents selon le module.
**Where** :
- `tools/nokido_hub.py:52` → `LAFORGE_HUB_PORT` default `8766` (MCP hub)
- `app/web_hub/__init__.py:17` → `LAFORGE_HUB_PORT` default `7400` (FastAPI dashboard)

**Why** : Si l'utilisateur set `LAFORGE_HUB_PORT=9000` (croit configurer une seule chose), les deux services se déplacent en même temps avec collision certaine. Black hole de réutilisation de variable.
**Fix** : Renommer `app/web_hub/__init__.py:17` en `LAFORGE_WEBHUB_PORT` (cohérent avec siblings RECON/GRAPH/CTF/TUI déjà préfixés). Documenter la séparation MCP vs WebHub.

### Black Hole 5 : INFRA.md référence port 8765 (drift)

**What** : `INFRA.md` (manifest racine, généré 2026-04-18) déclare `MCP HTTP : 127.0.0.1:8765/mcp`. Réalité actuelle = 8766.
**Where** : `INFRA.md` ligne ~32 ; `tools/forge_mcp_http.py:20` mentionne `MCP_HTTP_PORT=8765` (legacy).
**Why** : Tout LLM qui lit INFRA.md d'abord (point d'entrée évident) tape 8765, échec connexion, perd 10 min. Premier doc lu = premier doc faux.
**Fix** : Régénérer `INFRA.md` ou ajouter en tête `> ⚠️ obsolète depuis hub-v18 (2026-04-24) — voir tools/SERVICES.md pour port officiel 8766`.

### Black Hole 6 : NokidoDenoHubMCP / DenoWebHub statut shadow

**What** : Deno hub :8769 et Deno webhub :7401 sont lancés en NSSM mais leur statut "production" vs "shadow A/B" n'est pas écrit.
**Where** : `proxy_deno/hub_mcp/main.ts:4` (commentaire `parallèle au Python :8766 — switch quand validé`) ; `tools/SERVICES.md` § NokidoDenoHubMCP marque seulement "À auditer".
**Why** : Sans clarification, un LLM pense doublon obsolète et propose suppression → casse l'expérimentation Phase B.2 Deno port.
**Fix** : Annoter dans `tools/SERVICES.md` : `STATUT : shadow/canary — switch prévu commit X. Ne pas supprimer.` + ajouter `proxy_deno/README.md` une ligne d'objectif.

### Black Hole 7 : Port NokidoLlamaRouter dans bat = 8092 non doc

**What** : `tools/nokido_llamacpp_router.bat:18` set `PORT=8092`, mais `tools/SERVICES.md` ligne 16 dit `Port : ?`.
**Where** : `tools/nokido_llamacpp_router.bat:18`.
**Why** : LLM cherche le port → tape `Get-NetTCPConnection` puis devine. Donnée triviale absente.
**Fix** : Patcher `tools/SERVICES.md` ligne 16 : `NokidoLlamaRouter | Auto | bat | ... | 8092`.

### Black Hole 8 : forge_autonomous_loops pointe vers :8080 fantôme

**What** : `app/forge_autonomous_loops.py:44` hardcode `LLAMACPP_URL = "http://127.0.0.1:8080/v1/chat/completions"`. Aucun llamacpp ne tourne sur 8080 (Native=8091, Router=8092, python=8090).
**Where** : `app/forge_autonomous_loops.py:44`.
**Why** : Tous les patterns "tool_effectiveness", "lessons_consolidate", "forge_missing_tool" qui appellent un LLM **échouent silencieusement** → fonctionnalité morte mais le service NSSM affiche `Running`. Faux signal de santé.
**Fix** : Lire `LAFORGE_LLAMACPP_URL` env ou par défaut tomber sur `:8091` (NokidoLlamaNative quand Auto).

### Black Hole 9 : LAFORGE_LLAMACPP_PORT défaut 1234 mais doc dit 8090/8080

**What** : `app/forge_llm_router.py:191` et `tools/forge_services_launcher.py:187` utilisent default `1234` (LM Studio). `docs/llamacpp_setup.md:48` dit de set `LAFORGE_LLAMACPP_PORT=8090`. `docs/roadmap_master_llamacpp.md:46` dit `8080`.
**Where** : 3 sources, 3 valeurs.
**Why** : Configuration impossible à reproduire sans lire les 3 fichiers. Onboarding cassé.
**Fix** : Choisir UNE valeur canonique (probablement 8091 = NokidoLlamaNative en production, fallback 1234 LM Studio si absent). Mettre à jour les 3 docs + `Nokido.env.example`.

### Black Hole 10 : Hebbian / Homeostasis / Endocrine — rôle réel opaque

**What** : Les services `NokidoHebbian`, `NokidoHomeostasis` ont des noms biomimétiques mais leur action concrète sur la DB / système n'est documentée qu'en docstring du `.py`. Pas de page surface listant ce qu'ils écrivent et où.
**Where** : `app/forge_hebbian_linker.py:1-30` (modifie `biblio_link`) ; `app/forge_homeostasis_orchestrator.py:1-42` (orchestre 9 cycles) ; `app/forge_endocrine.py` (table `endocrine_state` non doc).
**Why** : Si un LLM doit auditer "qui touche la table biblio_link ?", il ne le saura sans `grep` profond. Black hole pour debug "pourquoi mon weight a baissé ?".
**Fix** : Créer `docs/COGNITIVE_LOOPS.md` (ou ajouter à `tools/SERVICES.md`) section "Effets de bord par service" : Hebbian → biblio_link.weight, Homeostasis → orchestre N modules in-process, Endocrine → endocrine_state hormones.

### Black Hole 11 : tools/nokido_homeostasis.py vs forge_homeostasis_orchestrator.py

**What** : Deux fichiers "homeostasis" coexistent. `tools/nokido_homeostasis.py` = ancien daemon SymbioticCore + RenalClearance. `app/forge_homeostasis_orchestrator.py` = nouveau orchestrateur 9 cycles. Aucun signe de qui remplace qui.
**Where** : `tools/nokido_homeostasis.py:1-30` (utilise `forge_symbiotic_core`) ; `app/forge_homeostasis_orchestrator.py` (NSSM `NokidoHomeostasis` pointe sur ce dernier).
**Why** : Le fichier `tools/nokido_homeostasis.py` est mort code mais évident lors de fuzzy search → confusion garantie. Risque : LLM patche le mauvais fichier.
**Fix** : Déplacer `tools/nokido_homeostasis.py` → `app/_attic/` ou ajouter docstring "OBSOLÈTE — voir forge_homeostasis_orchestrator.py".

### Black Hole 12 : ports BROADCAST_PORT 9765 / 5558 swarm/PUB non doc

**What** : `app/forge_swarm.py:63` ouvre UDP broadcast `9765`. `app/brain_worker.py:73` ouvre ZMQ PUB `5558` (en plus de :5557 REP). Aucun listé dans `INFRA.md` ni `tools/SERVICES.md`.
**Where** : `app/forge_swarm.py:63` ; `app/brain_worker.py:73` ; `app/forge_brain_client.py:39`.
**Why** : Pare-feu Windows peut bloquer (UDP 9765 surtout) → discovery swarm muet. Health check ne détecte pas. Black hole majeur pour topologie réseau.
**Fix** : Ajouter dans `INFRA.md` une table "Ports internes (loopback)" listant 5557/5558/9765 avec rôle.

### Black Hole 13 : env vars critiques absentes de Nokido.env.example

**What** : `Nokido.env.example` liste 25 vars. Le code en référence ~50+ supplémentaires : `LLAMACPP_*` (10 vars), `BROWSER_MCP_PORT/SECRET`, `CRAWL4AI_URL`, `KAGGLE_API_TOKEN`, `MCP_DEV_SECRET`, `FORGE_DEV_MODE`, `LAFORGE_AIRGAP`, `LAFORGE_ALLOW_CRITICAL_WRITE`, `LAFORGE_ALLOW_SECRETS_READ`, `HUB_JWT_SECRET`, `LAFORGE_TOPIC_MODEL`, `LAFORGE_BIBLIO_*`, `LAFORGE_TIMECODE_*`.
**Where** : grep `os.environ.get` dans `app/forge_*.py` retourne 100+ uniques ; `Nokido.env.example` n'en couvre que ~25.
**Why** : Onboarding ne sait jamais quelles vars activent quel comportement. Tuning impossible. Faux negative "pourquoi ma feature X ne tourne pas".
**Fix** : Générer `tools/regen_env_example.py` qui scanne `os.environ.get/getenv` du codebase + dump dans `Nokido.env.example` regroupé par module.

### Black Hole 14 : LAFORGE_ADMIN_TOKEN obligatoire mais non dans sample.env

**What** : `LANCER.md:9` dit "Le hub exige `LAFORGE_ADMIN_TOKEN` (32 chars min)". Mais `sample.env` (template public) n'en parle pas. `Nokido.env.example` non plus.
**Where** : `LANCER.md:9` ; `tests/nr/test_hub_config.py:74` (le test échoue sans cette var) ; `app/web_hub/auth.py`.
**Why** : Premier `laforge-start.cmd` post-clone échoue avec erreur cryptique. Mauvaise première impression / blocker onboarding.
**Fix** : Ajouter dans `sample.env` : `LAFORGE_ADMIN_TOKEN=  # python -c "import secrets; print(secrets.token_urlsafe(48))"`.

### Black Hole 15 : ADR-002 plan migration SSE non daté d exécution

**What** : `docs/ADR-002-netcfg-streamable-http.md` dit "PLANIFIÉ — deadline mi-2026". On est 2026-05-02. Aucun update sur l'état actuel SSE vs Streamable HTTP.
**Where** : `docs/ADR-002-netcfg-streamable-http.md`.
**Why** : Drift potentiel entre ADR (intention) et code (réalité). LLM ne sait pas si la migration est faite, en cours, ou abandonnée.
**Fix** : Ajouter en tête de l'ADR : `Statut au 2026-05-02 : <DONE|IN_PROGRESS|BLOCKED>` + lien vers commit ou issue.

### Black Hole 16 : netcfg-agent vit hors Nokido/ (chemin ~\Script python IA\netcfg-agent*)

**What** : Le projet `netcfg-agent` (et ses 3 cousins -mcp/-tui/-web) vit dans `~\Script python IA\netcfg-agent*` — **PAS** sous `LaForge\`. CLAUDE.md y fait référence 5+ fois sans préciser le chemin réel.
**Where** : Aucun chemin absolu dans `CLAUDE.md` § 8 ; `app/forge_inspector.py:69` mentionne le port 8767 mais pas le repo source.
**Why** : LLM cherche `LaForge/netcfg-agent` → introuvable → conclut "code manquant". Vérité : repo séparé, géré par un NSSM service .exe distinct.
**Fix** : Ajouter dans `CLAUDE.md` § 8 ligne `netcfg-agent-mcp* = repos séparés sous ~\Script python IA\netcfg-agent{,-mcp,-tui,-web}`. Cross-link dans `tools/SERVICES.md`.

### Black Hole 17 : NokidoAutonomousLoops opaque — 6 patterns non listés en surface

**What** : Le service `NokidoAutonomousLoops` orchestre 6 patterns (health_check 5min, git_hygiene 1h, rag_warmup_delta 6h, tool_effectiveness 24h, forge_missing_tool 24h, lessons_consolidate 48h). Listés UNIQUEMENT dans la docstring `app/forge_autonomous_loops.py:9-15`.
**Where** : `app/forge_autonomous_loops.py:9-15`.
**Why** : Onboarding ne sait pas que ce service touche à `git`, à la DB RAG, et appelle un LLM local. Risque "service mystère qui consomme CPU".
**Fix** : Étoffer `tools/SERVICES.md` § NokidoAutonomousLoops avec liste des 6 patterns + cadence + effets de bord (touche `git stash`, `rag_chunks`, `RAG/embeddings.db`).

### Black Hole 18 : forge_handler_advanced subprocess git sans audit

**What** : `app/forge_handler_advanced.py:197,199` exécute `subprocess.run(["git","add",rel])` + `git commit -m ...` directement, sans passer par `LAFORGE_PYTHON` ni audit.
**Where** : `app/forge_handler_advanced.py:197,199,367` ; cf. CLAUDE.md § 11 TODO "Commit Guard AST avec python brut".
**Why** : Commits autonomes peuvent shipper du code sans Sentinel review. Subprocess opaque pour audit. Black hole sécurité.
**Fix** : Wrapper via `app/forge_python_bin.run_python()` + log dans `audit_log` (ring 0). Documenter dans `docs/SECURITY_MCP_BACKLOG.md`.

### Black Hole 19 : env vars CIRCADIAN_* / LAFORGE_HEBBIAN_* / HOMEO_* invisibles

**What** : 9 vars de tuning rythmes biomimétiques : `CIRCADIAN_DORMANCY_MIN`, `CIRCADIAN_CHECK_S`, `CIRCADIAN_DREAM_WALKS`, `LAFORGE_HEBBIAN_INTERVAL_S`, `LAFORGE_HEBBIAN_DECAY`, `LAFORGE_HOMEO_TICK_S`, `LAFORGE_COAG_INTERVAL_S`, `LAFORGE_HEALTH_INTERVAL_S`, `LAFORGE_IMMUNE_INTERVAL_S`. Aucune dans env files.
**Where** : `app/forge_circadian_loop.py:39-43` ; `app/forge_hebbian_linker.py:48-49` ; `app/forge_homeostasis_orchestrator.py:65` ; `app/forge_coagulation_cascade.py:45` ; `app/forge_health_diagnostic.py:44` ; `app/forge_immune_adaptive.py:44`.
**Why** : Tuning de cadence (impact perfs / coût LLM local) impossible sans lire le code de chaque organe. Onboarding "comment réduire la fréquence du rss_watcher ?" → 30 min de grep.
**Fix** : Ajouter section "## Cycles biomimétiques (cadence ajustable)" dans `Nokido.env.example` listant les 9 vars + valeur par défaut + impact.

### Black Hole 20 : forge_swarm UDP broadcast 9765 non firewallé

**What** : `app/forge_swarm.py:63` lance un UDP broadcast `255.255.255.255:9765` pour discovery. Pas de doc de pare-feu, pas de mention dans `tools/SERVICES.md` ou `INFRA.md`.
**Where** : `app/forge_swarm.py:63` ; build artefacts `app/build_cython/.../forge_swarm.c:18218`.
**Why** : Sur LAN partagé (ex : test lab Exegol), broadcast peut être détecté comme suspect par EDR. Pour LLM debug "pourquoi swarm ne se forme pas ?" sans cette info, fausse piste garantie.
**Fix** : Documenter dans `INFRA.md` § Réseau interne : `UDP 9765 broadcast = forge_swarm discovery (LAN scope, opt-out via env LAFORGE_SWARM_DISABLE=1 — à implémenter)`.

### Black Hole 21 : forge_proxy_guard (port 8080 uvicorn) sans NSSM ni service

**What** : `app/nokido_proxy_guard.py:148` lance un uvicorn sur `127.0.0.1:8080` mais aucune entrée NSSM, aucun lanceur ne l'appelle, sauf import dans `forge_agent_proxy.py`.
**Where** : `app/nokido_proxy_guard.py:148` ; `app/forge_agent_proxy.py` (référence unique).
**Why** : Si jamais déclenché en parallèle de searxng, écran noir port:8080 collision. Utilité réelle floue.
**Fix** : Soit promouvoir en NSSM `NokidoProxyGuard` avec port distinct (ex 7480), soit retirer le `__main__` block de `nokido_proxy_guard.py`.

### Black Hole 22 : MCP_HTTP_PORT 8765 dans tools/forge_mcp_http.py vs hub 8766

**What** : `tools/forge_mcp_http.py:20` documente `MCP_HTTP_PORT=8765` en docstring. Le vrai hub tourne sur 8766 (SERVICES.md). Source : ancien hub MCP avant migration.
**Where** : `tools/forge_mcp_http.py:20`.
**Why** : Si un LLM lit `forge_mcp_http.py` (nommé évident), il infère `:8765`. Re-itération du Black Hole 5.
**Fix** : Soit archiver `tools/forge_mcp_http.py` (legacy, antérieur à `tools/nokido_hub.py`), soit ajouter docstring `# OBSOLETE depuis 2026-04, hub réel = nokido_hub.py:8766`.

### Black Hole 23 : tokens hardcodés dans nokido_mcp_proxy.py

**What** : `tools/nokido_mcp_proxy.py:20` contient `FORGE_MCP_TOKEN = os.getenv("FORGE_MCP_TOKEN", "f9b3c74d1b...a080f")` — token de fallback 64 chars en clair dans le code.
**Where** : `tools/nokido_mcp_proxy.py:20`.
**Why** : Risque secret leak si commit. Trust score du token compromis pour environnement multi-machine. Probable artefact de dev.
**Fix** : Retirer le default fallback (laisser vide → erreur explicite si non set) ; rotation du token actuel.

### Black Hole 24 : Modules entry-point-only (rss_watcher / hebbian / graph) jamais importés

**What** : `forge_rss_watcher.py`, `forge_hebbian_linker.py`, `forge_graph_explorer.py`, `forge_homeostasis_orchestrator.py` ne sont **jamais importés** depuis un autre `forge_*.py`. Lancement uniquement via NSSM `--daemon` ou CLI.
**Where** : Vérifié via `Grep "from forge_rss_watcher|from forge_hebbian_linker|from forge_graph_explorer"` → 0 match production.
**Why** : Ce sont des entry points externes — OK en soi, mais sans doc de cette convention, un LLM voit "fichier non importé" et propose suppression "dead code".
**Fix** : Ajouter en tête de chaque module la ligne `# ENTRY_POINT_ONLY — appelé via NSSM service <NomService>, ne pas importer`. Ou créer `docs/ENTRY_POINTS.md`.

### Black Hole 25 : Mismatch Python NokidoHomeostasis (3.12) vs autres daemons (py314)

**What** : Comme noté dans `tools/SERVICES.md` § Anomalies #3, `NokidoHomeostasis` utilise `miniforge3` (3.12) alors que `NokidoGraph`, `NokidoHebbian`, `NokidoRSSWatcher`, `NokidoGeminiDaemon` utilisent `laforge_py314`.
**Where** : `tools/SERVICES.md` ligne 99-102 ; matrice détaillée dans `docs/python_version_matrix.md`.
**Why** : Le module `forge_homeostasis_orchestrator.py` importe (in-process) `forge_hebbian_linker.run_cycle`, `forge_renal_clearance`, `forge_immune_adaptive`, `forge_coagulation_cascade`, `forge_pluripotent_workers`. Si un de ces sous-modules a une dep py314-only, l'orchestrateur 3.12 plante au runtime.
**Fix** : Tester `PYTHONNOUSERSITE=1 miniforge3/python.exe -c "from forge_hebbian_linker import run_cycle"` → si fail, switcher Homeostasis sur py314 OU figer Hebbian sur 3.12.

---

## Synthèse table

| # | Type | Where | Severity | Fix effort |
|---|---|---|---|---|
| 1 | Port non-doc | `forge_graph_explorer.py:8` (:7474) | Medium | 5min |
| 2 | Port fantôme | `forge_health_diagnostic.py:231` (:8090) | Low | 10min |
| 3 | Port collision | `:8080` (searxng vs autonomous_loops vs proxy_guard) | **High** | 1h |
| 4 | Env collision | `LAFORGE_HUB_PORT` 8766↔7400 | **High** | 30min |
| 5 | Doc drift | `INFRA.md` :8765 vs réel :8766 | **High** | 5min |
| 6 | Statut shadow | DenoHubMCP/DenoWebHub | Medium | 15min |
| 7 | Port non-doc | NokidoLlamaRouter :8092 | Low | 1min |
| 8 | URL morte | `forge_autonomous_loops.py:44` :8080 | **High** | 15min |
| 9 | Tri-source drift | `LAFORGE_LLAMACPP_PORT` 1234/8090/8080 | High | 30min |
| 10 | Effet de bord opaque | Hebbian/Homeostasis/Endocrine tables DB | Medium | 1h |
| 11 | Doublon dead | `tools/nokido_homeostasis.py` legacy | Medium | 5min |
| 12 | Ports internes non-doc | UDP 9765, ZMQ 5558 | Medium | 15min |
| 13 | Env vars manquantes | 50+ vars hors `Nokido.env.example` | **High** | 2h |
| 14 | Onboarding bloqué | `LAFORGE_ADMIN_TOKEN` hors sample.env | **High** | 5min |
| 15 | ADR pas tracé | ADR-002 statut figé | Low | 5min |
| 16 | Repo externe non-doc | netcfg-agent hors `LaForge/` | Medium | 5min |
| 17 | Service opaque | NokidoAutonomousLoops 6 patterns cachés | Medium | 15min |
| 18 | Sécurité subprocess | `forge_handler_advanced.py:197` git unwrapped | High | 1h |
| 19 | Tuning invisible | CIRCADIAN/HEBBIAN/HOMEO env vars | Medium | 30min |
| 20 | Réseau non-doc | UDP broadcast 9765 swarm | Medium | 10min |
| 21 | Service fantôme | `nokido_proxy_guard.py` orphelin | Low | 30min |
| 22 | Port legacy | `tools/forge_mcp_http.py:20` :8765 | Medium | 5min |
| 23 | Secret hardcodé | `nokido_mcp_proxy.py:20` token fallback | **High** | 15min |
| 24 | Convention non-doc | Modules entry-point-only | Low | 15min |
| 25 | Mismatch Python | NokidoHomeostasis 3.12 vs py314 | Medium | 30min |

**Top priorités (HIGH severity = 7 entries)** : #3, #4, #5, #8, #13, #14, #18, #23.
Si 1h budget : faire #5 + #14 + #23 (5+5+15 min) — débloque onboarding.
Si 1 jour budget : ajouter #4, #8, #13 (collision env + URL morte + env_example regen).

---

## Notes de méthode

- Audit fait sur snapshot 2026-05-02 (post-création `tools/SERVICES.md`).
- Ne couvre PAS : code mort dans `_attic/` (déjà géré par `docs/v13_6_orphan_inventory.md`), API publiques dormantes (cf. `docs/API_DORMANTE.md`), bugs connus (cf. `docs/forge_known_bugs.md`).
- Source des findings : grep récursif `os.environ.get|getenv|port=|PORT=|subprocess|from forge_*`.
- Format optimisé pour ingestion FAISS+BM25+FTS5 : H3 = unité chunk, table = vue tabulaire dédiée.
