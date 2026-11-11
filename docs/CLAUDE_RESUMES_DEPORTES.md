# Résumés des sections DEPORTEE de CLAUDE.md (verbatim, 2026-11-05)

Même patron que `docs/RULES_RESUMES_DEPORTES.md`. `CLAUDE.md` est réinjecté à chaque segment de session : chaque section
y garde une ligne et son pointeur, le résumé complet vit ici.

## §2 Carte des capacités — `docs/CLAUDE_CARTE_CAPACITES.md`

- La carte qui fait AUTORITE est le census sandbox/workspace/organ_map_full.json (source versionnee par exception), PAS cette liste d une cinquantaine de modules figee au 2026-05-07 ni une vue narrative derivee.
- Avant d affirmer qu un module n existe pas ou d en creer un : introspect, puis tools/forge_retrieval_sweep.py <terme> -- il cherche les outils par leur NOM, la ou chercher le seul CONTENU echoue.

## §5 Cadrage des LLM externes — `docs/CLAUDE_CADRAGE_LLM_EXTERNES.md`

- `pre_flight` est un garde BINAIRE et jamais un redacteur : des que le DLP mord il rend `ok=False` et un `safe_task` VIDE (mesure 2026-09-12 — une IP · un email · un chemin Windows suffisent). Suivre l'ancienne consigne envoyait donc un PROMPT VIDE au modele en silence. Le redacteur reel est `redact_text(texte)` et pour une sortie d'outil `redact_tool_output(texte · outil)`.
- Chaine complete : `fw.pre_flight(...)` puis l'appel LLM puis `fw.post_flight(reponse ...)` puis `fw.restore(reponse · mapping)`. Pour des donnees sensibles STRUCTUREES : `SovereignMembrane(mission_id=...).wrap()` avant l'envoi et `.unwrap(reponse · tool_calls=...)` au retour.

## §6.bis Planning Mode — `docs/CLAUDE_PLANNING_MODE.md`

- Intent ambigu ou action irreversible detectee (commit · push · kill · restart · secret · ACL · ingest production · suppression) : reconnaissance ciblee, puis annonce du plan en 1-3 phrases (objectif · risques · retour arriere), puis attente de validation si irreversible. Sinon, executer.
- Mappage code : `app/forge_handoff.py::Agent.mode` dans PLANNING ou EXECUTE (defaut EXECUTE) ; `Agent.plan_first()` rend une copie immuable en PLANNING ; `_llm_round()` injecte `PLANNING_PREFIX` dans le system prompt. Tests : `tests/test_forge_handoff_planning_mode.py`. Declencher `plan_first()` avant un transfert vers un agent porteur d'outils sensibles ou sur demande explicite de l'owner.

## §8 Stack services — `docs/CLAUDE_STACK_SERVICES_HISTORIQUE.md`

- La source de verite des services est proxy_deno/core/services.toml (flags enabled, hot-reload /supervisor/reload). La table deportee est datee du 2026-05-07 et etait DEJA marquee HISTORIQUE : elle ne dit plus l etat reel.
- Etat REEL d un service : hub action=whoami (services_degraded) ou le TOML. Un port qui repond ne prouve pas qu un modele est charge -- TRANSPORT n est pas CAPACITE.

## §10 Cartographie anatomique — `docs/CLAUDE_CARTOGRAPHIE_ANATOMIQUE.md`

- La **carte organe→module** qui fait autorite n'est pas la table narrative : c'est le census `sandbox/workspace/organ_map_full.json`, regenere par `LAFORGE_PYTHON tools/forge_module_census.py`. La section deportee en donne la vue humaine, jamais la source.
- Tout nouveau `forge_*.py` **declare son organe** (`__FORGE_COLOR__`, dans les 12 000 premiers caracteres, en debut de ligne) — sinon il ressort `non classe` et personne ne surveille sa regulation. Gate CI : `forge_module_census --check`.
- Diagnostic organe → pathologie → remede = skill `forge-anatomy` ; capacites et etat vivant par organe = `app/forge_organ_agents.py` (`census` / `gaps` / `probe`).

## §11 Contrainte d'exécution Python — `docs/CLAUDE_CONTRAINTE_PYTHON.md`

- `LAFORGE_PYTHON = ~/miniforge3/python.exe` — JAMAIS `python` ni `python3` brut. Source de verite : `app/forge_python_bin.py::LAFORGE_PYTHON` (override par la variable `LAFORGE_PYTHON_BIN`).
- Dans le code Nokido : `from forge_python_bin import LAFORGE_PYTHON · run_python` plutot qu'un `subprocess.run(['python' ...])`. Pour pytest : `PYTHONNOUSERSITE=1` — sinon le user-site charge un `anyio` corrompu et les tests se bloquent (incident 2026-04-29). Le tool MCP `run action=python` est deja propre : il utilise l'interpreteur du hub.

## §13 Protocole ZMQ :5557 — `docs/CLAUDE_PROTOCOLE_ZMQ_5557.md`

- Le port :5557 est DISABLED depuis le 2026-06-03 (BGE-M3 ONNX bad allocation). L embedder VIVANT est :8099 NokidoLlamaEmbed, atteint par forge_embed_router (embed et embed_batch_fast) -- ne jamais rebrancher :5557 en croyant reparer.
- La section deportee est une ARCHIVE utile SI :5557 est un jour repare, pas une consigne courante. DISABLED_BY_POLICY n est pas RESOURCE_UNAVAILABLE.

## §16 Epistemic Drive — `docs/CLAUDE_EPISTEMIC_DRIVE.md`

- Paradigme arrete le 2026-09-06 et a NE PAS coder sans ordre explicite — mais a integrer dans toute reflexion sur le RAG · le Swarm · l'endocrinien. Details en docs/ROADMAP.md section Px.
- Soif epistemique : le systeme detecte ce qu'il ne SAIT pas (UNKNOWN · BLIND_SPOT) et formule des questions candidates ; l'enquete n'est lancee que si le budget metabolique le permet ; une anomalie (attendu different de observe) genere un EPISTEMIC_EVENT ; le statut CONTESTED declenche la boucle et la connaissance empirique l'emporte sur la documentation statique ; la dette epistemique se resout en sommeil paradoxal (`forge_circadian.py`).

## §17 Stratégie et benchmarks — `docs/CLAUDE_STRATEGIE_BENCHMARKS.md`

- Positionnement acte le 2026-09-06 : Nokido n'est pas qu'un framework — c'est un vehicule de benchmark PUBLIC pour l'orchestration multi-agent et l'Edge AI (SWE-bench · BFCL · Terminal-Bench) compare aux modeles isoles. Metriques visees : tokens · latence · cout · resilience · consommation energetique.
- Attendu cote technique : preparer un BENCHMARKS.md exhaustif · rendre la telemetrie et l'audit exportables en metriques standardisees · cadrer la prochaine phase de roadmap sur la Qualification et la Mesure. Demarchage vise : partenaires d'infrastructure en echange de credits compute ou API.
