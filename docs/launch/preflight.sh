#!/usr/bin/env bash
# Nokido — pre-flight check J-0, 14h00 Paris
# Vérifie que tout est prêt avant le flip public.

set -u   # -e off : on veut continuer pour collecter tous les warnings

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*"; ERRS=$((ERRS+1)); }
info() { echo -e "${BLUE}[INFO]${NC}  $*"; }

ERRS=0
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " Nokido — Pre-flight check"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
date +"%Y-%m-%d %H:%M:%S %Z"
echo ""

cd "$(dirname "$0")/../.."   # racine Nokido

# ─── 1. Hub up ──────────────────────────────────────────────
info "Hub :8766 health..."
HEALTH=$(curl -s --max-time 5 http://localhost:8766/health 2>&1)
if echo "$HEALTH" | grep -q '"ok":true'; then
    ok "Hub responds OK"
else
    fail "Hub /health failed: $HEALTH"
fi

# ─── 2. MCP tools/list ──────────────────────────────────────
info "MCP tools/list..."
TOOLS=$(curl -s --max-time 5 -X POST http://localhost:8766/mcp \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' 2>&1)
TOOL_COUNT=$(echo "$TOOLS" | python -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('result',{}).get('tools',[])))" 2>/dev/null || echo "0")
if [[ "$TOOL_COUNT" -ge 20 ]]; then
    ok "MCP exposes $TOOL_COUNT tools (>= 20 expected)"
else
    fail "MCP exposes $TOOL_COUNT tools (expected >= 20)"
fi

# ─── 3. Vault populated ─────────────────────────────────────
info "Vault state..."
if command -v laforge-secrets &>/dev/null; then
    VAULT_OK=$(laforge-secrets status 2>&1 | grep -c "Coffre machine" || true)
    if [[ "$VAULT_OK" -gt 0 ]]; then
        ok "Vault accessible (laforge-secrets status returns data)"
    else
        warn "Vault may not be populated — check 'laforge-secrets status' manually"
    fi
else
    warn "laforge-secrets CLI not installed — try direct python check"
fi

# ─── 4. Provider admin UI ───────────────────────────────────
info "Provider admin UI..."
ADMIN=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" http://localhost:8766/admin/providers 2>&1)
if [[ "$ADMIN" == "200" ]]; then
    ok "/admin/providers returns 200"
else
    fail "/admin/providers returns $ADMIN (expected 200)"
fi

# ─── 5. CI green on alpha ───────────────────────────────────
info "Latest CI status alpha..."
if command -v gh &>/dev/null; then
    LAST_CI=$(gh run list -R user/Nokido --branch alpha --limit 1 --json conclusion -q '.[0].conclusion' 2>&1)
    if [[ "$LAST_CI" == "success" ]]; then
        ok "Latest alpha CI: success"
    else
        fail "Latest alpha CI: $LAST_CI"
    fi
else
    warn "gh CLI not installed — verify CI status manually"
fi

# ─── 6. Beta branch up-to-date ──────────────────────────────
info "beta branch tip..."
ALPHA_TIP=$(git -C Nokido rev-parse alpha 2>&1)
BETA_TIP=$(git -C Nokido rev-parse beta 2>&1 || echo "no-beta")
if [[ "$ALPHA_TIP" == "$BETA_TIP" ]]; then
    ok "beta is up-to-date with alpha ($ALPHA_TIP)"
else
    fail "beta ($BETA_TIP) != alpha ($ALPHA_TIP) — ff-merge needed"
fi

# ─── 7. README in 8 languages ───────────────────────────────
info "README translations..."
README_COUNT=$(ls LaForge/README*.md 2>/dev/null | wc -l)
if [[ "$README_COUNT" -ge 8 ]]; then
    ok "README in $README_COUNT languages"
else
    warn "README in $README_COUNT languages (expected >= 8)"
fi

# ─── 8. Wiki bilingual ──────────────────────────────────────
info "Wiki pages..."
EN_COUNT=$(ls LaForge/docs/wiki/*.md 2>/dev/null | grep -v '\.fr\.md$' | wc -l)
FR_COUNT=$(ls LaForge/docs/wiki/*.fr.md 2>/dev/null | wc -l)
if [[ "$EN_COUNT" -ge 18 && "$FR_COUNT" -ge 18 ]]; then
    ok "Wiki: $EN_COUNT EN pages + $FR_COUNT FR pages"
else
    warn "Wiki: $EN_COUNT EN + $FR_COUNT FR (expected 18+18)"
fi

# ─── 9. Critical metadata files ─────────────────────────────
info "Public release files..."
for f in MANIFESTO.md SECURITY.md CODE_OF_CONDUCT.md CONTRIBUTING.md LICENSE; do
    if [[ -f "LaForge/$f" ]]; then
        ok "$f present"
    else
        fail "$f MISSING"
    fi
done

# ─── 10. Gitleaks clean ─────────────────────────────────────
info "Gitleaks scan (alpha branch HEAD)..."
if command -v gitleaks &>/dev/null || [[ -x C:/tmp/gitleaks_dl/gitleaks.exe ]]; then
    GITLEAKS=${GITLEAKS_BIN:-$(command -v gitleaks || echo "C:/tmp/gitleaks_dl/gitleaks.exe")}
    LEAKS=$("$GITLEAKS" detect --source Nokido --config LaForge/.gitleaks.toml --no-banner 2>&1 | tail -1)
    if echo "$LEAKS" | grep -q "no leaks found"; then
        ok "Gitleaks: no leaks (baseline .gitleaksignore applied)"
    else
        fail "Gitleaks: leaks detected — $LEAKS"
    fi
else
    warn "gitleaks not installed — install with 'gh release download -R gitleaks/gitleaks --pattern \"*windows_x64.zip\"' or apt install"
fi

# ─── 11. Demo media ─────────────────────────────────────────
info "Demo media files..."
for f in docs/launch/media/demo_terminal.gif docs/launch/media/demo_admin_ui.gif; do
    if [[ -f "LaForge/$f" ]]; then
        SIZE=$(stat -c%s "LaForge/$f" 2>/dev/null || stat -f%z "LaForge/$f" 2>/dev/null || echo 0)
        if [[ "$SIZE" -gt 100000 && "$SIZE" -lt 5000000 ]]; then
            ok "$f exists ($((SIZE / 1024)) KB)"
        elif [[ "$SIZE" -gt 5000000 ]]; then
            warn "$f exists but is $(($SIZE / 1024)) KB — too big for Twitter (limit 5 MB)"
        else
            warn "$f exists but is suspiciously small ($SIZE bytes)"
        fi
    else
        warn "$f not yet recorded — see docs/launch/screencast_alternatives.md"
    fi
done

# ─── 12. Currently private ──────────────────────────────────
info "Current repo visibility..."
if command -v gh &>/dev/null; then
    VIS=$(gh repo view user/Nokido --json visibility -q .visibility 2>&1)
    if [[ "$VIS" == "PRIVATE" ]]; then
        ok "Repo is currently PRIVATE — ready for visibility flip"
    elif [[ "$VIS" == "PUBLIC" ]]; then
        warn "Repo is ALREADY PUBLIC — verify this is intentional"
    else
        warn "Could not determine visibility: $VIS"
    fi
fi

# ─── Summary ────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ "$ERRS" -eq 0 ]]; then
    ok "PRE-FLIGHT PASSED — ready to launch"
    echo ""
    echo " Next steps :"
    echo "   1. Record any missing demo GIFs (see screencast_alternatives.md)"
    echo "   2. Open docs/launch/CHECKLIST.md and follow the timing"
    echo "   3. At 14:25 : gh repo edit user/Nokido --visibility public"
    exit 0
else
    fail "$ERRS critical errors — do NOT launch until resolved"
    exit 1
fi
