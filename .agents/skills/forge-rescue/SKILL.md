---
name: forge-rescue
description: >
  Canal de secours Nokido : diagnostic, restart services, restore config,
  ET génération auto de prompt de reprise pour agent perdu (resync
  complet inter-sessions). Utilise quand un agent (Claude/Gemini/Cline)
  vient d'ouvrir une nouvelle session et est désorienté, ou quand
  il faut redémarrer un service critique.
---

# Nokido Rescue — Canal de Secours + Resync Inter-Sessions

## Quand l'invoquer

| Symptôme | Action |
|---|---|
| Agent ouvre nouvelle session, perdu, demande où en sont les choses | `--resume-prompt <agent>` ou `--resync <agent>` |
| Hub :8766 ne répond plus (CLOSE_WAIT, timeout) | `--restart-hub` |
| netcfg-agent-mcp DOWN selon INSPECTOR | `--restart-netcfg` |
| Tout est cassé, plus rien ne répond | `--full` |
| Diagnostic rapide état système | `--status` |
| Question rapide sans LLM cloud | `--ask "..."` (qwen3:8b local) |

## Outil principal : `tools/forge_rescue.py`

### Génération prompt de reprise (NEW)

```bash
# Affiche le prompt sur stdout (à coller dans nouvelle session)
LAFORGE_PYTHON tools/forge_rescue.py --resume-prompt gemini

# Écrit dans sandbox/resume_prompt_<agent>.md + notify autre agent
LAFORGE_PYTHON tools/forge_rescue.py --resync gemini
```

**Le prompt contient (auto-généré, live) :**
1. Identité agent (token, bridge, hub URL)
2. 3 canaux de communication actifs
3. État NSSM (8 services + statut RUNNING/STOPPED)
4. Ports critiques (hub :8766, netcfg :8767, ollama :11434)
5. Heartbeats daemons (gemini_poll_daemon, forge_bell)
6. Containers Docker (via WSL kali-linux)
7. Inbox `agent_messages` SQLite (10 derniers)
8. SITUATION.md tail (200 lignes)
9. PANORAMA tail (80 lignes)
10. Protocoles à respecter (LAFORGE_PYTHON, SecretGuard, SemanticFirewall)
11. Format ACK attendu

**Sources de vérité lues** :
- `SITUATION.md` (état centralisé)
- `COMMUNICATIONS.md` (PANORAMA registre)
- `LAFORGE_ATLAS.md` (vue d'ensemble + mermaid)
- `RAG/embeddings.db::agent_messages` (inbox structuré)
- `RAG/embeddings.db::network_log` (50 derniers appels MCP de l'agent)
- `sandbox/*.heartbeat` (daemons live)
- `nssm status <service>` (services NSSM)
- `wsl -d kali-linux -- docker ps -a` (containers)
- `socket.connect()` ports critiques

**Spécifique GEMINI** (si `--resync gemini`) — extrait `_gemini_session_state()` :
- `~/.gemini/inbox.md` (markdown inbox actif, tail 60 lignes)
- `~/.gemini/skills/` (7 skills custom : laforge-autonomie, cognitive-sync, env, hub, pipeline, quota, rescue)
- `~/.gemini/projects.json` (projets actifs)
- `network_log` filtré agent=GEMINI (15/50 derniers appels MCP)
- `sandbox/gemini_poll_daemon.log` (tail 30 lignes activité daemon)

### Diagnostic + restart

```bash
# Status complet (services, configs, ports)
LAFORGE_PYTHON tools/forge_rescue.py --status

# Restore claude_desktop_config.json (si MCP cassé)
LAFORGE_PYTHON tools/forge_rescue.py --restore --force

# Restart hub via NSSM (admin auto-elevate)
LAFORGE_PYTHON tools/forge_rescue.py --restart-hub

# Restart netcfg-agent-mcp.exe
LAFORGE_PYTHON tools/forge_rescue.py --restart-netcfg

# Tout redémarrer
LAFORGE_PYTHON tools/forge_rescue.py --restart-all

# Pipeline full : status + restore + restart si besoin
LAFORGE_PYTHON tools/forge_rescue.py --full

# Question au modèle local (rescue offline)
LAFORGE_PYTHON tools/forge_rescue.py --ask "comment relancer le hub ?"
```

## Architecture interne

```
forge_rescue.py
├── _is_admin() / _elevate_and_rerun()  → UAC auto-elevate Windows
├── _canonical()                         → state machine dict (paths, ports, tokens)
├── validate_config()                    → vérifie claude_desktop_config.json
├── cmd_status()                         → dump JSON état complet
├── cmd_restore(force)                   → restaure config depuis backup canonique
├── cmd_restart_hub()                    → nssm restart LaForgeMCP (admin)
├── cmd_restart_netcfg()                 → taskkill + restart .exe (admin)
├── cmd_full()                           → orchestration tout-en-un
├── cmd_ask(q)                           → Ollama qwen3:8b local
├── check_all_services()                 → ping ports + nssm status
├── check_known_bug(keyword)             → recherche docs/forge_known_bugs.md
├── _read_tail(path, n)                  → lecture tail fichier UTF-8
├── _query_inbox(agent_id, limit)        → SELECT agent_messages SQLite
├── _docker_state()                      → docker ps via WSL kali-linux
├── _nssm_state()                        → status 8 services NSSM
├── _heartbeats()                        → parse JSON sandbox/*.heartbeat
└── cmd_resume_prompt(agent)             → assemble prompt 17KB+ structuré
```

## Pattern usage par les agents

### Quand un agent se réveille (start-of-session)

```python
# Si pas de contexte récent, query auto-prompt :
import subprocess
r = subprocess.run([
    "~/miniforge3/python.exe",
    "tools/forge_rescue.py",
    "--resume-prompt", "gemini"  # ou "claude"
], capture_output=True, text=True, encoding="utf-8")
print(r.stdout)
# → 17KB+ prompt avec état live, à utiliser comme contexte de boot
```

### Quand un autre agent est perdu

```bash
# Génère + écrit + notify hub
python tools/forge_rescue.py --resync gemini
# → sandbox/resume_prompt_gemini.md écrit
# → notify CLAUDE via hub action=notify
# → user copie/colle dans nouvelle session GEMINI
```

### Cycle complet recovery

```bash
# 1. Diagnostic
python tools/forge_rescue.py --status

# 2. Si hub coma : restart
python tools/forge_rescue.py --restart-hub

# 3. Vérifier
python tools/forge_rescue.py --status

# 4. Re-générer prompt reprise pour agent affecté
python tools/forge_rescue.py --resync gemini
```

## Intégrations

- **NSSM** : auto-elevate UAC pour `nssm restart` / `nssm set`
- **Docker** : via `wsl -d kali-linux -- docker ps` (Docker Desktop = WSL2 backend)
- **Ollama** : fallback `qwen3:8b` pour `--ask` quand cloud KO
- **agent_messages** : table `RAG/embeddings.db` lue pour inbox
- **NSSM services connus** : LaForgeMCP, NokidoWebHub, NokidoGraph, NokidoHebbian, NokidoLlamaNative, NokidoLlamaRouter, NokidoRSSWatcher, NokidoGeminiDaemon

## Logs

- `logs/rescue_agent.log` : actions rescue
- `logs/service_monitor.log` : check_all_services périodique
- `sandbox/resume_prompt_<agent>.md` : prompts générés persistés

## Dépendances

- `LAFORGE_PYTHON = ~/miniforge3/python.exe` (jamais `python` brut)
- Hub :8766 UP pour notify côté `--resync`
- WSL kali-linux pour docker ps
- NSSM dans PATH (`C:/ProgramData/chocolatey/bin/nssm.exe`)
- Admin pour restart NSSM (auto-elevate via UAC)

## Anti-patterns

- ❌ Lancer `--restart-all` sans `--status` préalable (peut couper agent actif)
- ❌ Coller le prompt résumé sur ancienne session (overwrite contexte intact)
- ❌ Skipper `--restore` si claude_desktop_config.json cassé
- ❌ Utiliser `--ask` pour décisions critiques (qwen3:8b limité)

## Évolutions futures

- [ ] Diff PANORAMA depuis dernière session de l'agent (delta only)
- [ ] Prompt par profil (recon / dev / analyst) plutôt qu'agent
- [ ] Auto-trigger `--resync` quand inactivité > N minutes détectée
- [ ] Intégration ATLAS mermaid dans prompt (visuel ASCII)
