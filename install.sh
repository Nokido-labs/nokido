#!/usr/bin/env bash
# Nokido — install.sh (Linux / macOS)
# Cross-OS bootstrap : detect Python 3.12+, create venv, install via pyproject.toml extras.
#
# Usage:
#   bash install.sh                              # default: hub + rag + llm + docs
#   EXTRAS=full bash install.sh                  # tout sauf ML lourd
#   EXTRAS=all bash install.sh                   # vraiment tout (~5 GB)
#   EXTRAS=hub bash install.sh                   # juste hub serveur (~450 MB)
#   EXTRAS=core bash install.sh                  # client SDK uniquement (~10 MB)
#
# Optional:
#   WITH_SANDBOX_USERS=1 sudo bash install.sh    # provision laforge-sandbox-online,
#                                                # laforge-sandbox-offline UNIX users
#                                                # + laforge-trusted group. Requires sudo.
#   WITH_ATREST=1 bash install.sh                # provision at-rest encrypted container
#   bash install.sh --with-atrest                # (LUKS/VeraCrypt) for RAG/embeddings.db
#   bash install.sh --docker-up=full             # bring up Docker stack (core|full|all)
#   LAFORGE_DOCKER_PROFILE=all bash install.sh    # same, via env
set -euo pipefail

LAFORGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_MIN_MINOR=12
VENV_DIR="$LAFORGE_DIR/.venv"
EXTRAS="${EXTRAS:-hub,rag,llm,docs}"  # default modular stack

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
info() { echo -e "${BLUE}→${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
die()  { echo -e "${RED}✗${NC} $*" >&2; exit 1; }

# ── OS detect ─────────────────────────────────────────────────────────────────
case "$(uname -s)" in
    Linux*)   OS=Linux ;;
    Darwin*)  OS=macOS ;;
    MINGW*|MSYS*|CYGWIN*)  die "Windows detected. Use install.ps1 instead." ;;
    *)        die "Unsupported OS: $(uname -s)" ;;
esac

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Nokido — Autonomous Local-First AI Operating System"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
info "OS detected: $OS"
info "Install extras: $EXTRAS"

# ── Python 3.12+ ──────────────────────────────────────────────────────────────
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "")
        major=${version%%.*}; minor=${version##*.}
        if [[ -n "$version" && $major -ge 3 && $minor -ge $PYTHON_MIN_MINOR ]]; then
            PYTHON="$candidate"; break
        fi
    fi
done
[[ -z "$PYTHON" ]] && die "Python 3.${PYTHON_MIN_MINOR}+ required. https://python.org/downloads/"
ok "Python: $("$PYTHON" --version)"

# ── System deps note (per OS) ─────────────────────────────────────────────────
if [[ "$OS" == "Linux" ]]; then
    # libsecret needed for vault keyring backend
    if ! ldconfig -p 2>/dev/null | grep -q libsecret; then
        warn "libsecret not detected — vault keyring backend may fall back."
        warn "  Debian/Ubuntu: sudo apt install libsecret-1-0 gnome-keyring"
        warn "  Fedora:        sudo dnf install libsecret"
        warn "  Arch:          sudo pacman -S libsecret gnome-keyring"
    fi
fi
if [[ "$OS" == "macOS" ]]; then
    info "Keychain available natively — vault backend OK."
fi

# ── Docker (optional but recommended) ─────────────────────────────────────────
DOCKER_OK=false
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    DOCKER_OK=true; ok "Docker: $(docker --version | awk '{print $3}' | tr -d ',')"
else
    warn "Docker not found — will run hub natively (no auto-ollama)"
fi

# ── Venv ──────────────────────────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating venv at $VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR"
fi
# shellcheck source=/dev/null
PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"
ok "Venv ready"

# ── Install via pyproject.toml extras ─────────────────────────────────────────
info "Installing 'laforge-agent[$EXTRAS]' from local pyproject..."
"$PIP" install --quiet --upgrade pip wheel
"$PIP" install --quiet -e ".[${EXTRAS}]"
ok "Installed: laforge-agent[$EXTRAS]"

# Optional: keyring on macOS/Linux for cross-OS vault
if [[ "$OS" != "Windows" ]]; then
    if ! "$PY" -c "import keyring" &>/dev/null; then
        info "Installing 'keyring' for cross-OS vault backend..."
        "$PIP" install --quiet keyring
        ok "keyring installed"
    fi
fi

# ── Nokido.env ───────────────────────────────────────────────────────────────
ENV_FILE="$LAFORGE_DIR/LaForge.env"
if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$LAFORGE_DIR/LaForge.env.example" ]]; then
        cp "$LAFORGE_DIR/LaForge.env.example" "$ENV_FILE"
        TOKEN=$("$PY" -c "import secrets; print(secrets.token_urlsafe(32))")
        # sed compat macOS BSD vs GNU
        if [[ "$OS" == "macOS" ]]; then
            sed -i '' "s/votre_token_secret_ici/$TOKEN/" "$ENV_FILE" || true
        else
            sed -i "s/votre_token_secret_ici/$TOKEN/" "$ENV_FILE" || true
        fi
        ok "Nokido.env created (token auto-generated)"
        warn "Edit Nokido.env to configure providers (API keys, model names)"
    else
        warn "Nokido.env.example not found — create Nokido.env manually."
    fi
else
    ok "Nokido.env already exists"
fi

# ── Ollama (optionnel) ────────────────────────────────────────────────────────
if command -v ollama &>/dev/null; then
    ok "Ollama: $(ollama --version 2>/dev/null | head -1)"
elif $DOCKER_OK; then
    info "Ollama not installed locally — use Docker compose profile"
else
    warn "Ollama not found. Install: https://ollama.com/download"
    warn "Or use Docker: docker compose --profile core -f docker/nokido/docker-compose.yml up -d"
fi

# ── Bootstrap RAG seeds (fresh clones only) ──────────────────────────────────
RAG_DB="$LAFORGE_DIR/RAG/embeddings.db"
if [[ ! -f "$RAG_DB" ]] || [[ "$(stat -c%s "$RAG_DB" 2>/dev/null || stat -f%z "$RAG_DB" 2>/dev/null || echo 0)" -lt 1048576 ]]; then
    info "Fresh DB detected — bootstrapping from seed/*.jsonl..."
    mkdir -p "$LAFORGE_DIR/RAG"
    if "$PY" "$LAFORGE_DIR/tools/forge_db_bootstrap.py" 2>&1; then
        ok "RAG seeds imported (~3k chunks bootstrap)"
        warn "Embeddings are generated lazily by brain_worker — first searches may be slow"
    else
        warn "Seed bootstrap failed — run manually: python tools/forge_db_bootstrap.py"
    fi
else
    ok "RAG/embeddings.db already populated — skipping bootstrap"
fi

# ── .mcp.json bootstrap (Claude Code / Cline / VSCode MCP clients) ──────────
# Template ships in repo as .mcp.json.example (placeholder bearers).
# forge_mcp_json_sync reads vault DPAPI -> writes real Bearer tokens.
# Skip if .mcp.json already exists (user customized it).
MCP_JSON="$LAFORGE_DIR/.mcp.json"
MCP_EXAMPLE="$LAFORGE_DIR/.mcp.json.example"
if [[ ! -f "$MCP_JSON" && -f "$MCP_EXAMPLE" ]]; then
    info "Creating .mcp.json from template..."
    cp "$MCP_EXAMPLE" "$MCP_JSON"
    if "$PY" "$LAFORGE_DIR/tools/forge_mcp_json_sync.py" --path "$MCP_JSON" 2>&1; then
        ok ".mcp.json bootstrapped (Bearer tokens read from vault DPAPI)"
    else
        warn ".mcp.json created but vault tokens missing — run vault seed first:"
        warn "  $PY tools/forge_vault_seed_agent_tokens.py --from-env-file Nokido.env"
        warn "  $PY tools/forge_mcp_json_sync.py --path $MCP_JSON"
    fi
fi

# ── Propagate MCP to ALL installed CLIs (.mcp.json above = Claude Code/Cline/VSCode only) ──
# forge_client_bootstrap propage aux AUTRES : Gemini/agy, Codex, Claude Desktop (token+config+skills).
if [ -t 0 ]; then
    printf "  Propager la config MCP Nokido a tes autres CLI (Gemini/agy, Codex, Claude Desktop) ? [Y/n] "
    read -r _propmcp
else
    _propmcp="y"  # non-interactif (CI / install tiers) : propage par defaut
fi
case "${_propmcp:-y}" in
    [nN]*) info "Propagation MCP CLI sautee." ;;
    *)
        info "Propagation MCP -> CLI installes (forge_client_bootstrap --apply)..."
        if "$PY" "$LAFORGE_DIR/tools/forge_client_bootstrap.py" --apply 2>&1; then
            ok "Config MCP propagee (token + config MCP + skills par CLI detecte)."
        else
            warn "Bootstrap partiel — relance: $PY tools/forge_client_bootstrap.py --apply"
        fi
        ;;
esac

# ── Sandbox users (optional, requires sudo) ──────────────────────────────────
# laforge-sandbox-online   : sandbox exec WITH network egress
# laforge-sandbox-offline  : sandbox exec, network blocked via firewall
# laforge-trusted (group)  : members may run trusted_script via the hub
if [[ "${WITH_SANDBOX_USERS:-0}" == "1" ]]; then
    info "Provisioning sandbox UNIX users + group (requires sudo)..."
    if [[ $EUID -ne 0 ]]; then
        warn "WITH_SANDBOX_USERS=1 needs sudo. Re-run with: sudo -E bash install.sh"
    else
        # Create users (skip if exist)
        for u in laforge-sandbox-online laforge-sandbox-offline; do
            if ! id "$u" &>/dev/null; then
                if [[ "$OS" == "macOS" ]]; then
                    # macOS uses dscl
                    dscl . -create "/Users/$u"
                    dscl . -create "/Users/$u" UserShell /usr/bin/false
                    dscl . -create "/Users/$u" RealName "Nokido sandbox ($u)"
                    dscl . -create "/Users/$u" UniqueID 600$((RANDOM % 100))
                    dscl . -create "/Users/$u" PrimaryGroupID 20
                    dscl . -create "/Users/$u" NFSHomeDirectory "/var/empty"
                    ok "Created macOS user: $u"
                else
                    # Linux useradd
                    useradd -r -s /usr/sbin/nologin -d /var/empty -c "Nokido sandbox" "$u"
                    ok "Created Linux user: $u"
                fi
            else
                ok "User exists: $u"
            fi
        done

        # Create group
        if ! getent group laforge-trusted &>/dev/null && \
           ! dscl . -read /Groups/laforge-trusted &>/dev/null 2>&1; then
            if [[ "$OS" == "macOS" ]]; then
                dscl . -create /Groups/laforge-trusted
                dscl . -create /Groups/laforge-trusted PrimaryGroupID 600
                ok "Created macOS group: laforge-trusted"
            else
                groupadd -r laforge-trusted
                ok "Created Linux group: laforge-trusted"
            fi
        else
            ok "Group exists: laforge-trusted"
        fi

        # Add invoking user to laforge-trusted (the original non-root user)
        REAL_USER="${SUDO_USER:-$USER}"
        if [[ "$OS" == "Linux" ]] && [[ -n "$REAL_USER" ]]; then
            usermod -a -G laforge-trusted "$REAL_USER"
            ok "Added $REAL_USER to laforge-trusted"
        elif [[ "$OS" == "macOS" ]] && [[ -n "$REAL_USER" ]]; then
            dscl . -append /Groups/laforge-trusted GroupMembership "$REAL_USER"
            ok "Added $REAL_USER to laforge-trusted (macOS)"
        fi

        # ACLs: grant sandbox users read on Nokido dir
        # (Linux: setfacl ; macOS: chmod +a)
        if command -v setfacl &>/dev/null; then
            for u in laforge-sandbox-online laforge-sandbox-offline; do
                setfacl -R -m "u:$u:rX" "$LAFORGE_DIR" 2>/dev/null || true
            done
            ok "ACLs (setfacl): sandbox users granted read on $LAFORGE_DIR"
        else
            warn "setfacl not installed — manual ACL setup required (apt install acl)"
        fi

        # Firewall block for laforge-sandbox-offline (Linux iptables / macOS pfctl)
        if [[ "$OS" == "Linux" ]] && command -v iptables &>/dev/null; then
            iptables -A OUTPUT -m owner --uid-owner laforge-sandbox-offline -j REJECT 2>/dev/null || \
                warn "iptables rule failed (might already exist or need iptables-save)"
            ok "iptables: outbound block for laforge-sandbox-offline (run iptables-save to persist)"
        elif [[ "$OS" == "macOS" ]]; then
            warn "macOS: configure pfctl manually to block laforge-sandbox-offline outbound"
        fi
    fi
else
    warn "Sandbox users NOT provisioned. To enable per-account isolation, re-run as:"
    warn "  WITH_SANDBOX_USERS=1 sudo -E bash install.sh"
fi

# ── Entry points ──────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
# ── Optional: bring up the Docker stack (containers by profile) — opt-in / proposed ──
COMPOSE_FILE="$LAFORGE_DIR/docker/nokido/docker-compose.yml"
DOCKER_UP="${LAFORGE_DOCKER_PROFILE:-}"
for _a in "$@"; do case "$_a" in --docker-up=*) DOCKER_UP="${_a#*=}" ;; --docker-up) DOCKER_UP="core" ;; esac; done
DC_SEARX=false
if [ -z "$DOCKER_UP" ] && $DOCKER_OK && [ -f "$COMPOSE_FILE" ] && [ -t 0 ]; then
  echo ""
  info "Stack Docker Nokido (containers par profil) :"
  echo "    core = laforge-hub + ollama"
  echo "    full = core + deno-webhub + brain-worker"
  echo "    all  = full + netcfg-agent + searxng + adminer"
  printf "  Demarrer la stack Docker maintenant ? [core/full/all/N] "
  read -r _dc
  case "$_dc" in core|full|all) DOCKER_UP="$_dc" ;; *) DOCKER_UP="" ;; esac
  if [ -n "$DOCKER_UP" ] && [ "$DOCKER_UP" != "all" ]; then
    printf "  Ajouter SearXNG (web_search/veille local) ? [y/N] "
    read -r _sx
    case "$_sx" in [yY]*) DC_SEARX=true ;; esac
  fi
fi
if [ -n "$DOCKER_UP" ]; then
  case "$DOCKER_UP" in core|full|all) : ;; *) DOCKER_UP="core" ;; esac
  if ! $DOCKER_OK; then
    warn "Docker indisponible — installe Docker puis relance avec --docker-up=$DOCKER_UP."
  elif [ ! -f "$COMPOSE_FILE" ]; then
    warn "Compose introuvable : $COMPOSE_FILE"
  else
    info "docker compose --profile $DOCKER_UP up -d ..."
    docker compose -f "$COMPOSE_FILE" --profile "$DOCKER_UP" up -d || warn "docker compose erreur — verifie a la main."
    if $DC_SEARX; then docker compose -f "$COMPOSE_FILE" up -d searxng || warn "searxng up erreur."; fi
    ok "Stack Docker '$DOCKER_UP' demarree."
    info "Modele LLM : docker exec laforge-ollama ollama pull qwen2.5-coder:latest"
    warn "exegol (offensif) n'est PAS dans cette stack : module laforge-redteam (opt-in ci-dessous)."
  fi
fi

# ── Optional: at-rest encryption (LUKS / VeraCrypt container) — opt-in / proposed ──
WITH_ATREST=false
for _a in "$@"; do [ "$_a" = "--with-atrest" ] && WITH_ATREST=true; done
[ "${LAFORGE_WITH_ATREST:-}" = "1" ] && WITH_ATREST=true
if ! $WITH_ATREST && [ -t 0 ]; then
  echo ""
  info "Module OPTIONNEL : chiffrement AT-REST (conteneur LUKS/VeraCrypt pour RAG/embeddings.db + secrets)."
  info "  Protege tes donnees au repos. Cle au keyring/vault, jamais en clair sur disque."
  printf "  Activer le chiffrement at-rest maintenant ? [y/N] "
  read -r _atrest
  case "$_atrest" in [yY]*) WITH_ATREST=true ;; esac
fi
if $WITH_ATREST; then
  if [ "$OS" = "Linux" ] && command -v cryptsetup &>/dev/null; then
    info "Backend at-rest : LUKS (cryptsetup detecte)."
  elif command -v veracrypt &>/dev/null; then
    info "Backend at-rest : VeraCrypt detecte."
  else
    warn "Ni cryptsetup ni veracrypt detecte. Installe l'un des deux, puis relance avec --with-atrest :"
    warn "  Debian/Ubuntu : sudo apt install cryptsetup    (ou veracrypt)"
    warn "  macOS         : brew install --cask veracrypt"
    WITH_ATREST=false
  fi
fi
if $WITH_ATREST; then
  info "Provisioning conteneur at-rest (init-key -> create -> migrate -> boot mount)..."
  "$PY" "$LAFORGE_DIR/tools/forge_at_rest_veracrypt.py" --init-key || true
  if "$PY" "$LAFORGE_DIR/tools/forge_at_rest_veracrypt.py" --create --size-gb 16; then
    "$PY" "$LAFORGE_DIR/tools/forge_at_rest_veracrypt.py" --migrate || warn "Migration DB echouee — relance --migrate plus tard (services arretes)."
    "$PY" "$LAFORGE_DIR/tools/forge_install_boot_mount.py" --install || warn "Install boot-mount echouee (sudo requis ?)."
    ok "Chiffrement at-rest actif (conteneur monte au boot)."
  else
    warn "Creation du conteneur echouee — verifie le backend, puis relance manuellement."
  fi
fi

# ── Optional: laforge-redteam (OFFENSIVE / dual-use) — opt-in only ─────────────
WITH_REDTEAM=false
for _a in "$@"; do [ "$_a" = "--with-redteam" ] && WITH_REDTEAM=true; done
[ "${LAFORGE_WITH_REDTEAM:-}" = "1" ] && WITH_REDTEAM=true
# Proposition interactive (module optionnel) si pas de flag + terminal interactif
if ! $WITH_REDTEAM && [ -t 0 ]; then
  echo ""
  info "Module OPTIONNEL : laforge-redteam (offensif / dual-use, depot prive, MCP dedie)."
  printf "  L'installer maintenant ? [y/N] "
  read -r _propose
  case "$_propose" in [yY]*) WITH_REDTEAM=true ;; esac
fi
if $WITH_REDTEAM; then
  echo ""
  warn "═══ laforge-redteam — OFFENSIVE / DUAL-USE MODULE ═══"
  warn "  exegol · CTF · exploit dev · recon · CVE — separate PRIVATE repo, dedicated MCP (LAFORGE_REDTEAM_MCP_PORT)."
  warn "  • AUTHORIZED USE ONLY: systems you own, with explicit written authorization,"
  warn "    CTF, or security research. Unauthorized scanning/exploitation is ILLEGAL —"
  warn "    you assume FULL legal responsibility."
  warn "  • LLM POLICY: many providers (cloud + some local) REFUSE or degrade offensive"
  warn "    requests. Redteam features routed to such models may be BLOCKED at the model"
  warn "    layer — prefer local uncensored models or expect refusals."
  warn "  • NOT bundled by default — installing it is your explicit choice."
  printf "  Type EXACTLY 'I-UNDERSTAND' to install laforge-redteam: "
  read -r _consent
  if [ "$_consent" = "I-UNDERSTAND" ]; then
    REPO="${LAFORGE_REDTEAM_REPO:-git@github.com:user/laforge-redteam.git}"
    DEST="$(dirname "$LAFORGE_DIR")/laforge-redteam"
    info "Cloning $REPO -> $DEST (private; needs your git access)..."
    if git clone "$REPO" "$DEST"; then
      ok "laforge-redteam cloned. Finish: cd $DEST && ./install.sh (wires its dedicated MCP + token)."
    else
      warn "Clone failed (access? URL?). Set LAFORGE_REDTEAM_REPO and retry, or clone manually."
    fi
  else
    info "laforge-redteam skipped (no consent)."
  fi
fi

echo " Installation complete."
echo ""
echo " Activate venv:"
echo "   source $VENV_DIR/bin/activate"
echo ""
echo " Entry points:"
echo "   laforge-hub        # start hub :8766"
echo "   laforge-cli        # TUI client"
echo "   laforge-vault      # CRUD secret vault"
echo "   laforge-secrets    # secrets diagnostic"
echo ""
echo " Or Docker:"
echo "   docker compose --profile core -f docker/nokido/docker-compose.yml up -d"
echo "   docker exec laforge-ollama ollama pull qwen2.5-coder:latest"
echo ""
echo " Hub URL: http://localhost:8766"
echo " Manifesto: ./MANIFESTO.md"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
