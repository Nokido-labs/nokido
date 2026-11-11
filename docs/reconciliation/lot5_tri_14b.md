| sha | verdict (INTEGRER/ARCHIVER/ILLISIBLE) | preuve (fichier:ligne d'alpha ou fichier lu) | raison (≤ 20 mots) |
|---|---|---|---|
| 3e3ac28c03 | ARCHIVER | tools/nokido_hub.py:941 | Tokens dérivés en dur remplacés par chargement dynamique DPAPI via forge_secrets dans tools/nokido_hub.py:941. |
| db7622f21e | ARCHIVER | tools/forge_services_launcher.py:69 | SERVICES_TOKEN au coffre via get_secret et X_AGENT_NAME déjà présents ; laforge_tray obsolète. |
| ceb3721bed | ARCHIVER | app/forge_mcp_registry.py:6293 | Orchestrator autonome et intent intégrés via forge_runner.spawn dans app/forge_mcp_registry.py:6293. |
| 1cc2ba8588 | ARCHIVER | tools/mcp_stdio_bridge.py:418 | Keep-alive et timeouts gérés via urllib.request et SSE streaming dans tools/mcp_stdio_bridge.py:418. |
| 4afd9a1a08 | ARCHIVER | tools/forge_services_launcher.py:215 | Fichiers racines 2026 obsolètes ; service brain_worker port 5557 géré dans forge_services_launcher.py:215. |
| b7081b8961 | ARCHIVER | app/forge_rag_engine.py:161 | Recherche FTS5 SQLite intégrée et éprouvée via requete_fts dans forge_rag_engine.py:161. |
| c324b3caf5 | ARCHIVER | tools/nokido_hub.py:129 | Chargement dynamique hub_middleware via importlib présent dans tools/nokido_hub.py:129. |
| 7466733958 | ARCHIVER | tools/restart_claude.py:81 | Script tools/restart_claude.py présent et fonctionnel avec restart_hub et restart_claude. |
| c276b3bbba | ARCHIVER | app/forge_mcp_registry.py:4939 | Lecture et unlink du fichier temporaire code_file intégrés dans forge_mcp_registry.py:4939. |
| de89633e7e | ARCHIVER | app/forge_rag_engine.py:612 | Découpage et détection role_hint intégrés dans forge_rag_engine.py:612 ; COMMUNICATIONS.md obsolète. |
| c0d64bce2b | ARCHIVER | tools/nokido_hub.py:941 | Tokens des 9+ agents résolus dynamiquement via DPAPI et agent_identities.json dans tools/nokido_hub.py:941. |
