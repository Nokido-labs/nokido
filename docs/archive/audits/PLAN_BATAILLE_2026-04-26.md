# PLAN DE BATAILLE NOKIDO — 2026-04-26

## Contexte chiffré
- 187,743 lignes Python dans app/
- 75 modules forge_* actifs (importés dans Nokido.py)
- 122 modules forge_* ORPHELINS (jamais importés)
- 109 modules en DOUBLON (copies dans shadow_mutation, archive, attic)
- 27,594 fichiers dans sandbox/ (test_repos 16k, inspirations 7.8k)
- 110MB de logs > 5MB (dont 99MB d'erreurs service)
- 94 checkpoints shadow_mutation
- 210/211 modules sans test
- 13 clés API en clair dans Nokido.env

---

## PHASE 1 — HYGIÈNE (Claude, 1 session, depuis PowerShell)
Objectif : réduire le bruit, voir clair

### 1A. Purge logs > 5MB
```powershell
Remove-Item "logs\mcp_service_err-20260425T182500.055.log"  # 99MB
Remove-Item "logs\mcp_service_err-20260425T180918.004.log"  # 11MB
```

### 1B. Purge sandbox/ dossiers non-Nokido
Conserver : fichiers racine sandbox/, benchmarks/, longmemeval/
Purger : test_repos/ (16k fichiers), inspirations/ (7.8k), apk_extracted/, nxshield_apk/, ctf_challenges/, stego_viz/
→ Gain estimé : ~25,000 fichiers, ~500MB

### 1C. Purge shadow_mutation/checkpoints
Garder : gen01 et gen02 les plus récents (2026-03-25)
Purger : les 92 autres checkpoints antérieurs
→ Gain estimé : ~90 dossiers

### 1D. Identifier les 122 modules orphelins
Script : comparer forge_*.py dans app/ vs imports dans Nokido.py
Résultat → liste dans docs/ORPHANS.md
NE PAS supprimer sans validation user

---

## PHASE 2 — SÉCURITÉ (Claude + user, session dédiée)
Objectif : fermer les risques ouverts

### 2A. Rotation 13 clés API (PRIORITÉ ABSOLUE)
Clés exposées dans Nokido.env :
GITHUB_TOKEN×2, FORGE_MCP_TOKEN, LAFORGE_ADMIN_TOKEN, MCP_DEV_SECRET,
OPENROUTER_API_KEY, XAI_API_KEY, DEEPSEEK_API_KEY, GEMINI_API_KEY,
GROQ_API_KEY, HF_TOKEN, CODEBERG_TOKEN, SMITHERY_API

Migration : tools/migrate_secrets_to_wcm.py --force
Wrapper : tools/launch-nokido.ps1 (charge WCM au boot)

### 2B. SecretGuard — restreindre pattern dotenv
app/forge_secret_guard.py : r"\bdotenv\b" → r"load_dotenv\s*\("

### 2C. Rapport fuite schémas MCP
docs/POC-MCP-SCHEMA-LEAK-2026-04-25.md → envoyer à security@anthropic.com
Décision : oui/non ?

---

## PHASE 3 — INFRASTRUCTURE (Claude, sessions courtes)
Objectif : stabiliser ce qui tourne

### 3A. Tray v3 authority/ring (depuis VSCode)
Fonctions manquantes dans tools/nokido_tray.py :
- _hard_kill_reboot() + _do_hard_kill()
- _acquire_master() + _release_master() + _transfer(agent)
- Items menu : Hard Kill+Reboot, Authority submenu
Anchor : ligne ~271, def _restart_hub(icon, item)
→ Faire depuis VSCode/Cursor, PAS via MCP write

### 3B. netcfg-agent-mcp stable
Vérifier : %APPDATA%\Claude\logs\mcp-server-netcfg-agent-mcp.log
Si absent : tester args ["serve", "--stdio"] ou ["serve", "--port", "8767"]

### 3C. Bridge write — débloquer les patterns
Identifier exactement quel handler dans forge_mcp_registry.py filtre
Pattern suspect : handle_write() → SecretGuard scan du contenu ?
→ Si oui : exclure les fichiers sandbox/ du scan

---

## PHASE 4 — TESTS (Gemini, en parallèle, sans conflit)
Objectif : filet de sécurité sur les modules critiques

Modules prioritaires (actifs + sans test) :
1. forge_mcp_registry.py — 24 tools handlers
2. forge_boot.py — séquence de démarrage
3. forge_cascade_oracle.py — routing LLM
4. forge_agents.py — orchestration agents (3381 lignes)
5. forge_agent_authority.py — ring system

Format : tests/test_<module>_nr.py
Même pattern que test_secret_guard_nr.py de Gemini
Lancer : pytest tests/ -v --tb=short

---

## PHASE 5 — DOCUMENTATION (Gemini, sans conflit)
Objectif : savoir ce qui tourne vraiment

### 5A. ORPHANS.md — liste des 122 modules non importés
### 5B. CHANGELOG.md — sessions 2026-04-25/26
### 5C. PANORAMA.md — mise à jour architecture réelle vs documentée
### 5D. map.md — mettre à jour avec bridge v3.1, SecretGuard v3

---

## RÉPARTITION AGENTS

| Tâche | Agent | Conflit ? |
|---|---|---|
| Phase 1 hygiène | Claude | Non — purge uniquement |
| Phase 2A rotation clés | user + Claude | Non |
| Phase 2B SecretGuard | Claude | Non |
| Phase 3A tray | user (VSCode) | Non |
| Phase 3B netcfg | Claude | Non |
| Phase 4 tests | Gemini | Non — tests/ seulement |
| Phase 5 docs | Gemini | Non — docs/ seulement |

---

## ORDRE D'EXÉCUTION RECOMMANDÉ

```
Aujourd'hui    : Phase 1 (hygiène) + Phase 2B (SecretGuard)
Cette semaine  : Phase 2A (rotation clés) + Phase 3A (tray VSCode)
Semaine proch. : Phase 3B + 3C + Phase 4 (tests Gemini) + Phase 5
```

---
Généré : 2026-04-26 05:45
