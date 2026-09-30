---
type: guide
title: 11 — Notes multi-OS
status: draft
resource: repo://docs/wiki/11-Cross-OS-Notes.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 11 — Notes multi-OS

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](11-Cross-OS-Notes.md) · **Français**

> **Version condensée.** La page anglaise, plus complète, fait référence : en cas d'écart,
> c'est elle qui compte.

Nokido supporte **Linux · macOS · Windows**. Cette page liste comportements OS-spécifiques, pièges, et le chemin que chaque sous-système prend par plateforme.

## ✅ Matrice support

| Sous-système | Linux | macOS | Windows | Notes |
|---|:-:|:-:|:-:|---|
| Hub MCP `:8766` | ✅ | ✅ | ✅ | Python pur, Starlette. |
| RAG (FTS5 + FAISS) | ✅ | ✅ | ✅ | SQLite + faiss-cpu cross-platform. |
| `brain_worker` (BGE-M3) | ✅ | ✅ | ✅ | Rust + ONNX. Backend par OS. |
| Vault | ✅ | ✅ | ✅ | DPAPI / Keychain / libsecret. |
| `forge_semantic_firewall` | ✅ | ✅ | ✅ | Python pur. |
| MCP clients | ✅ | ✅ | ✅ | OS-agnostique. |
| TUI (Textual) | ✅ | ✅ | ✅ | Windows Terminal recommandé (pas cmd.exe). |
| Docker compose | ✅ | ✅ | ✅ | Docker Desktop sur Win/macOS. |
| `tools/restart_claude.py` | ❌ | ❌ | ✅ | **Windows-only** (NSSM + PowerShell). |
| NSSM services | — | — | ✅ | Win-only. |
| Comptes sandbox | — | — | ✅ | `LaForgeSbxOnline`/`Offline` Win-spécifiques. |
| netcfg-agent | ✅ | ✅ | ✅ | asyncssh marche partout. |

## 🧭 Interpréteur Python

Nokido requiert Python **3.12+**. Recommandations :
- **Linux** : distro Python ≥ 3.12 ou `pyenv install 3.12.8`. Venv : `python3 -m venv .venv`.
- **macOS** : Homebrew `brew install python@3.12`.
- **Windows** : **miniforge3**. Memory `python_toolchain` : `~/miniforge3/python.exe` = canonique.

`install.sh` / `install.ps1` détectent automatiquement. Override : `LAFORGE_PYTHON` env var.

⚠ **Jamais `python` brut** dans script touchant Nokido — toujours absolute venv path. CLAUDE.md règle #11.

## 🗂️ Conventions paths

Nokido utilise :
```python
ROOT = Path(__file__).resolve().parent.parent
```
+ `os.environ.get("LAFORGE_ROOT", str(...))` pour override. **Pas de paths hardcodés** `~/` dans le code tracké (audit Phase 4 pre-public).

### Forward vs backslashes

- Python : forward slashes ou `Path` objects. Fonctionne partout.
- `install.sh` : `/`. `install.ps1` : `\` (PowerShell native) ou `/` aussi OK.

### Home dir

- Linux/macOS : `~` ou `Path.home()`.
- Windows : `%USERPROFILE%`, mappé par Python à `Path.home()`.

Vault store :
- Linux : `~/.local/share/nokido/machine_vault.dat` ou `<repo>/data/machine_vault.dat`.
- macOS : Keychain (pas de fichier).
- Windows : `<repo>/data/machine_vault.dat` (DPAPI machine-scope).

## 🔌 Backend NPU/GPU (brain_worker)

> ⚠️ `brain_worker` (:5557) est **coupé depuis le 2026-06-03** (BGE-M3 ONNX, bad allocation).
> L'embedder vivant est `NokidoLlamaEmbed` (:8099), atteint par `forge_embed_router`. La
> section ci-dessous vaut archive, si :5557 est un jour réparé.

Auto-détection :

| Plateforme | Backend défaut | Alternatives |
|---|---|---|
| Windows | DirectML (Radeon 780M, Intel Arc, NVIDIA) | Vulkan, CPU |
| Linux | OpenVINO (Intel), ROCm (AMD), CUDA (NVIDIA) | Vulkan, CPU |
| macOS | CoreML (M1+) | Metal, CPU |

Override : `BRAIN_WORKER_BACKEND=cpu|directml|vulkan|openvino|coreml|cuda`.

Memory `npu_xdna1_limits` : AMD NPU XDNA1 = ops-light only. Pas BGE-M3 batch ni LLM inference. Utiliser iGPU via DirectML/Vulkan.

## 🔐 Vault behavior par OS

Voir [08 — Vault & secrets](08-Vault-and-Secrets.fr.md).

- **Windows** : DPAPI machine-scope. Multi-account readable. Pure `ctypes`, zéro dep.
- **macOS** : Keychain via `keyring`. Per-user, hardware-attested sur Apple Silicon.
- **Linux** : libsecret / Secret Service via `keyring`. Requiert `libsecret-1-0` + daemon keyring (GNOME ou KWallet).
  - Debian/Ubuntu : `sudo apt install libsecret-1-0 gnome-keyring`
  - Fedora : `sudo dnf install libsecret`
  - Arch : `sudo pacman -S libsecret gnome-keyring`

Headless Linux : `keyring` fallback chain → WCM → `.env` → `os.environ`. Pour headless prod, `.env` chmod 600 OU Docker secret.

## 📦 Service supervision

| OS | Tool | Config |
|---|---|---|
| Windows | NSSM | `LaForge-Master`, `LaForgeMCP`, etc. Voir `tools/forge_nssm_hardening.py`. |
| Linux | systemd | `deploy/*.service`. Install : `sudo cp deploy/*.service /etc/systemd/system/`. |
| macOS | launchd | `deploy/com.nokido.master.plist`. Install : `cp ... ~/Library/LaunchAgents/`. |

Tous OS : lancer hub direct (no service manager) pour dev : `laforge-hub`.

## 🐳 Docker

- **Windows** : Docker Desktop **WSL2** backend (pas Hyper-V) pour perf + faiss.
- **macOS** : Apple Silicon : `linux/amd64` images via Rosetta 2 (lent). Build local sur M1+ = arch-native auto.

## 🖥️ Caveats install natif

### Linux
- `libsecret` nécessaire pour vault.
- ML extras : CUDA wheels assument NVIDIA. ROCm ou CPU-only torch via `--extra-index-url`.
- Unit files systemd : review user/group avant enable.

### macOS
- M1/M2/M3 : torch CPU + MPS marchent. CUDA n'existe pas — skip `ml` si besoin que d'inférence.
- Brew `python@3.12` recommandé over system Python.

### Windows
- **PowerShell 7+** requis (pas PS 5.1).
- Long paths : activer Win10/11 long path support (`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`).
- Antivirus : exclure le dir Nokido du real-time scan.

## 🧪 Tests cross-OS

CI matrix sur `ubuntu-latest`, `macos-latest`, `windows-latest` avec Python 3.12. Voir `.github/workflows/ci.yml`.

## 🚨 Bugs cross-OS connus

- **Normalisation CRLF** : Git auto-normalise sur Windows. `.gitattributes` gère la plupart des cas.
- **SQLite WAL** Windows : `.db-wal` ne release pas toujours sur process exit. Hub force-checkpoint sur shutdown.
- **NTFS chars réservés** : `:` `?` `|` cassent sous mounts WSL.

## 🌍 Locale & encoding

- Toujours `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`. Dockerfile + `install.sh` le font auto.
- Sur Windows, console `cp1252` par défaut → emoji et non-ASCII en logs cassent. `forge_vault_seed_agent_tokens.py` utilise ASCII-only pour cette raison.
- Commentaires source français/anglais coexistent. Docs publiques (wiki, MANIFESTO, README) bilingue ou anglais.
