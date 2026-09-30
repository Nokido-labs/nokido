---
type: guide
title: 18 — Launchers & service files
status: draft
resource: repo://docs/wiki/18-Launchers.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 18 — Launchers & service files

<!-- revu-le: 2026-08-27 -->
> Updated: 2026-08-27

> 🌐 **English** · [Français](18-Launchers.fr.md)

Nokido ships **40+ launchers** for daily use : `.bat` files for Windows
double-click, Python launchers for cross-OS, `.service` units for systemd,
`.plist` for launchd. This page lists them all and what each one starts.

## 🪟 Windows — double-click entry points

Located in `tools/` — invoke via Explorer double-click or pinned shortcut.

| Launcher | What it does |
|---|---|
| `tools/LaForge Control Panel.bat` | Opens the TUI control panel (overview + actions) |
| `tools/LaForge Tray.bat` | Starts the system tray icon (`nokido_tray.py`) |
| `tools/nokido_start.bat` | Boots the hub + worker stack (uses NSSM) |
| `tools/nokido_autonomous_loops.bat` | Starts the autonomous evolution loop daemons |
| `tools/nokido_llamacpp_native.bat` | Launches `llama-server` (qwen2.5-coder:7b CPU) |
| `tools/nokido_llamacpp_router.bat` | Launches the llama.cpp routing layer |
| `tools/nokido_llamacpp_symlinks.bat` | Creates `models/` symlinks to Ollama blobs (avoids dual storage) |
| `tools/nokido_deno_webhub.bat` | Starts the Deno event bus on :7401 |
| `tools/nokido_deno_proxy.bat` | Starts the Deno proxy layer |
| `tools/nokido_deno_hub_mcp.bat` | Starts the Deno MCP proxy |
| `tools/wake_respawn.bat` | Auto-respawn after Windows wake (paired with `tools/tasks/LaForge-WakeRespawn.xml`) |

### NSSM service installers (run once, as admin)

| Installer | Service it creates |
|---|---|
| `tools/install_nokido_master.bat` | `LaForge-Master` (supervisor :8765) |
| `tools/install_hub_service.bat` | `LaForgeMCP` (hub :8766) |
| `tools/install_gemini_daemon_nssm.bat` | Gemini poll daemon |
| `tools/install_woodpecker_agent.bat` | Woodpecker CI agent (optional) |
| `go_services/brain_worker/install_nssm.bat` | BrainWorker (Rust + ONNX) |
| `go_services/forge_dispatcher/install_nssm.bat` | Go dispatcher (HTTP routing) |

After running these once, services persist across reboots. Manage via :

```powershell
nssm status LaForge-Master
nssm restart LaForge-Master         # never restart LaForgeMCP directly !
nssm stop LaForge-Master
```

### Other Windows utilities

| File | Purpose |
|---|---|
| `tools/embed_rebuild_job.bat` | One-shot embedding rebuild (use `schtasks /run /tn LaForge-EmbedRebuild` for scheduled) |
| `tools/embed_stop_after.bat` | Stop the embedding rebuild after N minutes |
| `tools/create_restart_task.bat` | Creates a scheduled task for periodic hub restart |
| `tools/forge_desktop_audit.ps1` | Audits the desktop sandbox configuration |
| `tools/forge_nssm_hardening.py` | Quotes NSSM AppParameters properly (fixes 2026-05-24 BSOD root cause) |
| `tools/forge_pid_gc.py` | PID file garbage collector (boot hook) |

## 🐧 Linux / macOS — service files

| File | Where to install | Action |
|---|---|---|
| `deploy/laforge-master.service` | `/etc/systemd/system/` | `sudo systemctl enable --now laforge-master` |
| `deploy/com.nokido.master.plist` | `~/Library/LaunchAgents/` (macOS) | `launchctl load -w ~/Library/LaunchAgents/com.nokido.master.plist` |
| `deploy/install_nokido_master.cmd` | (Win cmd version of the .bat installer) | — |

### Native daily-use scripts

| Script | OS | Purpose |
|---|---|---|
| `tools/nokido_launcher.py` | All | Cross-OS Python launcher for the hub + dependencies |
| `tools/nokido_start.bat` | Win | Windows wrapper of the above |
| `tools/forge_services_launcher.py` | All | Launches the service stack (llama.cpp, brain_worker, ollama) |
| `tools/forge_runas_launcher.py` | Win | Spawn process under sandbox UID (`LaForgeSbxOnline/Offline`) |

## 🦙 llama.cpp specifics

Nokido ships **three** complementary llama.cpp launchers :

### 1. `tools/nokido_llamacpp_native.bat`

Direct llama-server launch with `qwen2.5-coder:7b-instruct-q4_K_M` :

```batch
@echo off
set MODEL=C:\path\to\qwen2.5-coder-7b-instruct-q4_k_m.gguf
llama-server.exe -m %MODEL% -c 8192 --port 8080 --jinja
```

Use when you want a single stable llama.cpp instance on :8080. Default for
the `llamacpp_native` provider in `forge_provider_specs.py`.

### 2. `tools/nokido_llamacpp_router.bat`

Multi-model router (newer setup, ports 8091-8095). Launches several llama.cpp
instances per use-case (code, reasoning, vision-text). The `orchestrate`
tool uses :8091 by default.

### 3. `tools/nokido_llamacpp_symlinks.bat`

Creates symlinks under `models/` pointing at Ollama's blob storage. Saves
disk space — you don't duplicate the same model in two folders.

```batch
mklink "models\qwen2.5-coder.gguf" "%USERPROFILE%\.ollama\models\blobs\sha256-..."
```

Run once after `ollama pull qwen2.5-coder:latest`.

### 4. `tools/nokido_llamacpp_ui_patcher.py` (Python)

Patches the llama.cpp web UI (built-in HTML on :8080) to match Nokido's
dark theme. Cosmetic only.

## 🎨 Desktop GUI — separate repo

`forge_desktop/` (Electron + React desktop app) is **standalone** and lives
in its own repository. It is **not part of the Nokido core release** :

```
.gitignore:
# Apps and standalone modules (versioned separately)
forge_desktop/
spin_md_query/
/skills/
```

Reasons :

- The desktop app has its own release cycle.
- Different licensing flexibility (it can be MIT while Nokido stays AGPLv3).
- Heavy build pipeline (Tauri / Electron + Node).
- Not all users want the GUI — TUI + web admin covers most workflows.

Link will be added once that repo is published.

## 🧭 Start Menu integration (Windows)

`install.ps1 -WithStartMenuShortcuts` (planned) will create :

- "Nokido Hub" → `nokido_start.bat`
- "Nokido Tray" → `Nokido Tray.bat`
- "Nokido Control Panel" → `Nokido Control Panel.bat`
- "Nokido llama.cpp Server" → `nokido_llamacpp_native.bat`

For now, drag the `.bat` files manually to `%APPDATA%\Microsoft\Windows\Start Menu\Programs\LaForge\`.

## 🐳 Docker entry points

Docker compose handles its own launchers via the `services:` block. No
`.bat`/`.sh` files needed inside the container.

```bash
docker compose -f docker/nokido/docker-compose.yml --profile core up -d
docker compose --profile full up -d
docker compose --profile all up -d
docker compose --profile dev up -d
```

See [10 — Docker profiles](10-Docker-Profiles.md).

## 🔧 Custom launcher template

If you want to wrap a forge_* tool in a `.bat` for double-click :

```batch
@echo off
cd /d "%~dp0\.."
"C:\Users\%USERNAME%\miniforge3\python.exe" tools/your_tool.py %*
pause
```

Or POSIX equivalent :

```bash
#!/usr/bin/env bash
cd "$(dirname "$0")/.."
source .venv/bin/activate
python tools/your_tool.py "$@"
```

## ⚠️ Important notes

- **Never `nssm restart LaForgeMCP` directly** — always go through
  `LaForge-Master` (the supervisor). The supervisor owns `LaForgeMCP`'s
  port :8766 exclusively. Direct restart causes a crash loop. Voir
  [14 — Troubleshooting](14-Troubleshooting.md#-windows-spécifique).

- The `.bat` files assume **miniforge3 in default location**
  (`C:\Users\<you>\miniforge3\`). If you used a different Python distro,
  edit the BAT files or set `LAFORGE_PYTHON` env var. Voir
  [CLAUDE.md](../../CLAUDE.md) §11.

- All NSSM service installers require **admin elevation**. Run an elevated
  PowerShell or `Run as Administrator`.

- `forge_desktop/` is **not in this repo**. Watch the website / GitHub
  organization for the standalone release announcement.
