---
type: guide
title: 18 — Lanceurs & fichiers services
status: draft
resource: repo://docs/wiki/18-Launchers.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 18 — Lanceurs & fichiers services

<!-- revu-le: 2026-08-27 -->
> Mise à jour : 2026-08-27

> 🌐 [English](18-Launchers.md) · **Français**

Nokido ship **40+ lanceurs** pour usage quotidien : fichiers `.bat` pour double-clic Windows, lanceurs Python cross-OS, units `.service` pour systemd, `.plist` pour launchd. Cette page liste tous et ce que chacun démarre.

## 🪟 Windows — points d'entrée double-clic

Localisés dans `tools/` — invoke via Explorer double-clic ou raccourci pinné.

| Lanceur | Action |
|---|---|
| `tools/LaForge Control Panel.bat` | Ouvre le panneau de contrôle TUI (overview + actions) |
| `tools/LaForge Tray.bat` | Démarre l'icône systray (`nokido_tray.py`) |
| `tools/nokido_start.bat` | Boot stack hub + worker (via NSSM) |
| `tools/nokido_autonomous_loops.bat` | Démarre les daemons d'évolution autonome |
| `tools/nokido_llamacpp_native.bat` | Lance `llama-server` (qwen2.5-coder:7b CPU) |
| `tools/nokido_llamacpp_router.bat` | Lance la couche routing llama.cpp |
| `tools/nokido_llamacpp_symlinks.bat` | Crée symlinks `models/` vers blobs Ollama (évite stockage doublé) |
| `tools/nokido_deno_webhub.bat` | Démarre le bus event Deno sur :7401 |
| `tools/nokido_deno_proxy.bat` | Démarre la couche proxy Deno |
| `tools/nokido_deno_hub_mcp.bat` | Démarre le proxy MCP Deno |
| `tools/wake_respawn.bat` | Auto-respawn après wake Windows (paire avec `tools/tasks/LaForge-WakeRespawn.xml`) |

### Installers NSSM service (run une fois, admin)

| Installer | Service créé |
|---|---|
| `tools/install_nokido_master.bat` | `LaForge-Master` (supervisor :8765) |
| `tools/install_hub_service.bat` | `LaForgeMCP` (hub :8766) |
| `tools/install_gemini_daemon_nssm.bat` | Gemini poll daemon |
| `tools/install_woodpecker_agent.bat` | Agent CI Woodpecker (optionnel) |
| `go_services/brain_worker/install_nssm.bat` | BrainWorker (Rust + ONNX) |
| `go_services/forge_dispatcher/install_nssm.bat` | Dispatcher Go (routing HTTP) |

Après run une fois, services persistent cross-reboots. Manage via :

```powershell
nssm status LaForge-Master
nssm restart LaForge-Master         # jamais restart LaForgeMCP direct !
nssm stop LaForge-Master
```

### Autres utilitaires Windows

| Fichier | Usage |
|---|---|
| `tools/embed_rebuild_job.bat` | Rebuild embeddings one-shot |
| `tools/embed_stop_after.bat` | Stop rebuild après N minutes |
| `tools/create_restart_task.bat` | Crée tâche planifiée restart hub périodique |
| `tools/forge_desktop_audit.ps1` | Audit config sandbox desktop |
| `tools/forge_nssm_hardening.py` | Quote NSSM AppParameters proprement |
| `tools/forge_pid_gc.py` | PID file GC (boot hook) |

## 🐧 Linux / macOS — fichiers service

| Fichier | Où installer | Action |
|---|---|---|
| `deploy/laforge-master.service` | `/etc/systemd/system/` | `sudo systemctl enable --now laforge-master` |
| `deploy/com.nokido.master.plist` | `~/Library/LaunchAgents/` (macOS) | `launchctl load -w ~/Library/LaunchAgents/com.nokido.master.plist` |

### Scripts natifs usage quotidien

| Script | OS | Usage |
|---|---|---|
| `tools/nokido_launcher.py` | Tous | Lanceur Python cross-OS pour hub + deps |
| `tools/nokido_start.bat` | Win | Wrapper Windows du ci-dessus |
| `tools/forge_services_launcher.py` | Tous | Lance stack services (llama.cpp, brain_worker, ollama) |
| `tools/forge_runas_launcher.py` | Win | Spawn process sous UID sandbox (`LaForgeSbxOnline/Offline`) |

## 🦙 Spécifiques llama.cpp

Nokido ship **trois** lanceurs llama.cpp complémentaires :

### 1. `tools/nokido_llamacpp_native.bat`

Launch direct llama-server avec `qwen2.5-coder:7b-instruct-q4_K_M` :

```batch
@echo off
set MODEL=C:\path\to\qwen2.5-coder-7b-instruct-q4_k_m.gguf
llama-server.exe -m %MODEL% -c 8192 --port 8080 --jinja
```

À utiliser quand tu veux une instance llama.cpp stable seule sur :8080. Par défaut pour le provider `llamacpp_native` dans `forge_provider_specs.py`.

### 2. `tools/nokido_llamacpp_router.bat`

Router multi-modèle (setup plus récent, ports 8091-8095). Lance plusieurs instances llama.cpp per use-case (code, reasoning, vision-text). Le tool `orchestrate` utilise :8091 par défaut.

### 3. `tools/nokido_llamacpp_symlinks.bat`

Crée symlinks sous `models/` pointant vers blob storage Ollama. Économise disque — pas de duplication du même modèle dans deux dossiers.

```batch
mklink "models\qwen2.5-coder.gguf" "%USERPROFILE%\.ollama\models\blobs\sha256-..."
```

Run une fois après `ollama pull qwen2.5-coder:latest`.

### 4. `tools/nokido_llamacpp_ui_patcher.py` (Python)

Patche l'UI web llama.cpp (HTML built-in sur :8080) pour match le thème dark Nokido. Cosmétique only.

## 🎨 Desktop GUI — repo séparé

`forge_desktop/` (app desktop Electron + React) est **standalone** et vit dans son propre repo. **Pas dans la release core Nokido** :

```
.gitignore:
# Apps standalone (se versionnent séparément)
forge_desktop/
spin_md_query/
/skills/
```

Raisons :
- L'app desktop a son propre cycle release.
- Flexibilité licensing différente (peut être MIT pendant que Nokido reste AGPLv3).
- Pipeline build lourd (Tauri / Electron + Node).
- Tous les users ne veulent pas la GUI — TUI + admin web couvre la plupart des workflows.

Lien ajouté une fois ce repo publié.

## 🧭 Intégration Start Menu (Windows)

`install.ps1 -WithStartMenuShortcuts` (planifié) créera :

- "Nokido Hub" → `nokido_start.bat`
- "Nokido Tray" → `Nokido Tray.bat`
- "Nokido Control Panel" → `Nokido Control Panel.bat`
- "Nokido llama.cpp Server" → `nokido_llamacpp_native.bat`

Pour l'instant, drag les fichiers `.bat` manuellement vers `%APPDATA%\Microsoft\Windows\Start Menu\Programs\LaForge\`.

## 🐳 Entry points Docker

Docker compose handle ses propres lanceurs via le bloc `services:`. Pas de fichiers `.bat`/`.sh` nécessaires dans le container.

Voir [10 — Profils Docker](10-Docker-Profiles.fr.md).

## 🔧 Template lanceur custom

```batch
@echo off
cd /d "%~dp0\.."
"C:\Users\%USERNAME%\miniforge3\python.exe" tools/your_tool.py %*
pause
```

POSIX :

```bash
#!/usr/bin/env bash
cd "$(dirname "$0")/.."
source .venv/bin/activate
python tools/your_tool.py "$@"
```

## ⚠️ Notes importantes

- **Jamais `nssm restart LaForgeMCP` direct** — toujours passer par `LaForge-Master` (le supervisor). Crash loop sinon.
- Les fichiers `.bat` assument **miniforge3 path par défaut** (`C:\Users\<toi>\miniforge3\`). Sinon édite les BAT ou set env `LAFORGE_PYTHON`.
- Tous les NSSM service installers requièrent **élévation admin**.
- `forge_desktop/` est **pas dans ce repo**. Watch le site / GitHub org pour annonce release standalone.
