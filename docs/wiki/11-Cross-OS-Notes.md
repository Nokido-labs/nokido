---
type: guide
title: 11 — Cross-OS notes
status: draft
resource: repo://docs/wiki/11-Cross-OS-Notes.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 11 — Cross-OS notes

<!-- revu-le: 2026-08-27 -->
> Updated: 2026-08-27

Nokido supports **Linux · macOS · Windows**. This page lists OS-specific
behaviors, gotchas, and the path each subsystem takes per platform.

## ✅ Support matrix

| Subsystem | Linux | macOS | Windows | Notes |
|---|:-:|:-:|:-:|---|
| Hub MCP `:8766` | ✅ | ✅ | ✅ | Pure Python, Starlette. No OS-specific code. |
| RAG (FTS5 + FAISS) | ✅ | ✅ | ✅ | SQLite + faiss-cpu cross-platform. |
| `brain_worker` (BGE-M3) | ✅ | ✅ | ✅ | Rust + ONNX. Backend selection per OS (see below). |
| Vault | ✅ | ✅ | ✅ | DPAPI / Keychain / libsecret (see [08](08-Vault-and-Secrets.md)). |
| `forge_semantic_firewall` | ✅ | ✅ | ✅ | Pure Python. |
| `forge_sovereign_membrane` | ✅ | ✅ | ✅ | SQLite WAL — cross-platform. |
| MCP clients (Claude/Gemini/Codex/Cline) | ✅ | ✅ | ✅ | Client-side, OS-agnostic. |
| TUI (Textual) | ✅ | ✅ | ✅ | Modern Terminal recommended on Win (Windows Terminal, not cmd.exe). |
| Docker compose | ✅ | ✅ | ✅ | Docker Desktop required on Win/macOS. |
| `tools/restart_claude.py` | ❌ | ❌ | ✅ | **Windows-only** (NSSM + PowerShell). |
| NSSM services | — | — | ✅ | Windows-only service manager. |
| Sandbox accounts | — | — | ✅ | `LaForgeSbxOnline`, `LaForgeSbxOffline` are Win-specific. |
| netcfg-agent | ✅ | ✅ | ✅ | asyncssh works everywhere. |
| `bash_guard` hook | ✅ | ✅ | ✅ | Hook runs in the Claude Code harness — OS-agnostic. |

## 🧭 Python interpreter

Nokido requires Python **3.12+**. Recommendations :

- **Linux** : distro Python ≥ 3.12 or `pyenv install 3.12.8`. Use a venv :
  `python3 -m venv .venv && source .venv/bin/activate`.
- **macOS** : Homebrew `brew install python@3.12`. Same venv pattern.
- **Windows** : we use **miniforge3** (Conda-forge ecosystem). Memory
  `python_toolchain` documents the split : `~/miniforge3/python.exe`
  is the canonical interpreter ; 3.14.3 installed but unused by Nokido.

The `install.sh` / `install.ps1` scripts detect the right Python
automatically. If you have multiple Pythons in PATH, set `LAFORGE_PYTHON`
env var explicitly.

⚠ **Never run `python` raw** in any Nokido-touching script — always
use the venv's absolute path. See `CLAUDE.md` rule #11.

## 🗂️ Path conventions

Nokido code uses :

```python
ROOT = Path(__file__).resolve().parent.parent
```

…and `os.environ.get("LAFORGE_ROOT", str(...))` for override. **No
hardcoded `~/` paths** in tracked code (audit Phase 4 pre-public).

If you find one, open an issue.

### Forward vs backslashes

- Python : always use forward slashes or `Path` objects. They work
  everywhere.
- Shell scripts : `install.sh` uses `/`. `install.ps1` uses `\` (PowerShell
  native) but is fine with `/` too.

### Home directory

- Linux/macOS : `~` or `Path.home()`.
- Windows : `%USERPROFILE%` env var, mapped to `Path.home()` by Python.

The vault store goes to :

- Linux : `~/.local/share/nokido/machine_vault.dat` (XDG) or
  `<repo>/data/machine_vault.dat` (current default).
- macOS : Keychain (no file).
- Windows : `<repo>/data/machine_vault.dat` (DPAPI machine-scope).

## 🔌 NPU / GPU backend selection (brain_worker)

> ⚠️ `brain_worker` (:5557) has been **disabled since 2026-06-03** (BGE-M3 ONNX, bad
> allocation). The live embedder is `NokidoLlamaEmbed` (:8099), reached through
> `forge_embed_router`. This section is kept as an archive, should :5557 be repaired.

`brain_worker` (Rust + ONNX) auto-detects :

| Platform | Default backend | Alternatives |
|---|---|---|
| Windows | DirectML (Radeon 780M, Intel Arc, NVIDIA) | Vulkan, CPU |
| Linux | OpenVINO (Intel), ROCm (AMD), CUDA (NVIDIA) | Vulkan, CPU |
| macOS | CoreML (M1+) | Metal, CPU |

Override : `BRAIN_WORKER_BACKEND=cpu|directml|vulkan|openvino|coreml|cuda`.

Memory `npu_xdna1_limits` documents : AMD NPU XDNA1 (in Radeon 780M /
Strix Point) is **ops-light only** — can't do BGE-M3 batch or LLM
inference. Use the iGPU via DirectML/Vulkan instead.

## 🔐 Vault behavior by OS

See [08 — Vault & secrets](08-Vault-and-Secrets.md). Summary :

- **Windows** : DPAPI machine-scope (`CRYPTPROTECT_LOCAL_MACHINE`).
  Multi-account readable. Pure `ctypes`, zero deps.
- **macOS** : Keychain via `keyring` package. Per-user, hardware-attested
  on Apple Silicon.
- **Linux** : libsecret / Secret Service via `keyring`. Requires
  `libsecret-1-0` + a running keyring daemon (GNOME Keyring or KWallet).
  Install hint :
  - Debian/Ubuntu : `sudo apt install libsecret-1-0 gnome-keyring`
  - Fedora : `sudo dnf install libsecret`
  - Arch : `sudo pacman -S libsecret gnome-keyring`

If no keyring daemon is running on Linux (e.g. headless server), `keyring`
falls back to the chain : WCM → `.env` → `os.environ`. For headless
deployments, use a `.env` with chmod 600 OR mount a Docker secret.

## 📦 Service supervision

| OS | Tool | Config |
|---|---|---|
| Windows | NSSM | Services : `LaForge-Master`, `LaForgeMCP`, `BrainWorker`, etc. See `tools/forge_nssm_hardening.py`. |
| Linux | systemd | Service files in `deploy/*.service`. Install via `sudo cp deploy/*.service /etc/systemd/system/ && sudo systemctl enable --now laforge-master`. |
| macOS | launchd | Plist in `deploy/com.nokido.master.plist`. Install via `cp deploy/com.nokido.master.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.nokido.master.plist`. |

On all OSes, you can also run the hub directly (no service manager) for
dev :

```bash
laforge-hub
# or
python -m tools.nokido_hub
```

## 🐳 Docker behavior

Docker abstracts most OS differences. Two notes :

- **Windows** : Docker Desktop must use the **WSL2** backend (not Hyper-V)
  for best performance + faiss support.
- **macOS** : Docker Desktop on Apple Silicon : `linux/amd64` images run
  via Rosetta 2 (slow). The Dockerfile multi-stage builds **arch-native**
  when you build locally on M1+ — no manual cross-compile needed.

## 🖥️ Native install caveats

### Linux

- `libsecret` needed for vault (see above).
- For `ml` extras : CUDA wheels assume NVIDIA + matching driver. ROCm or
  CPU-only torch via `--extra-index-url https://download.pytorch.org/whl/cpu`.
- systemd unit files in `deploy/` — review user/group before enabling.

### macOS

- M1/M2/M3 : torch CPU wheels work, MPS backend works. CUDA does not
  exist on macOS — skip `ml` extras if you only need inference (use Ollama
  with CoreML / Metal).
- Brew `python@3.12` recommended over the system Python.

### Windows

- **PowerShell 7+** required (not PS 5.1) for some scripts.
- Long paths : enable Win10/11 long path support
  (`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`)
  — fixes FAISS build issues.
- Antivirus : exclude the Nokido dir from real-time scan — Windows
  Defender on `embeddings.db` (380k rows, frequent writes) cripples
  performance.

## 🧪 Cross-OS testing

CI matrix runs on `ubuntu-latest`, `macos-latest`, `windows-latest` with
Python 3.12. See `.github/workflows/ci.yml`.

Run locally on all three :

```bash
# Linux/macOS
EXTRAS=hub,rag,llm bash install.sh
source .venv/bin/activate
pytest tests/test_forge_scorecard.py

# Windows
.\install.ps1
.\.venv\Scripts\Activate.ps1
pytest tests/test_forge_scorecard.py
```

## 🚨 Known cross-OS bugs

- **CRLF normalization** : Git auto-normalizes line endings on Windows
  (`core.autocrlf=true`). Don't fight it — `.gitattributes` handles most
  cases. If a Python file fails to import after a checkout, run
  `git checkout -- <file>` to reset.
- **SQLite WAL** on Windows : `.db-wal` files don't always release on
  process exit. The hub force-checkpoints on shutdown ; if you see
  `database is locked`, kill stale Python processes.
- **NTFS reserved characters** : `:` `?` `|` etc. break under WSL mounts.
  Don't use them in chunk IDs.

## 🌍 Locale & encoding

- Always set `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` in the
  environment before launching anything Nokido-related. The
  Dockerfile + `install.sh` do this automatically.
- On Windows, the console is `cp1252` by default → emoji and non-ASCII
  in log lines fail. The `forge_vault_seed_agent_tokens.py` script uses
  ASCII-only output for this reason.
- French / English source comments coexist. Public-facing docs (this
  wiki, MANIFESTO, README) are bilingual or English ; code comments may
  be either.
