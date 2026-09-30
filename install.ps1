# Nokido — install.ps1 (Windows)
# Run: Set-ExecutionPolicy Bypass -Scope Process; .\install.ps1
# Optional flags:
#   -ML                 install heavy ML deps (torch, sentence-transformers)
#   -Docker             prefer Docker compose path (skips native checks)
#   -WithSandboxUsers   create LaForgeSbxOnline / LaForgeSbxOffline /
#                       LaForgeTrustedRunners local accounts + ACLs (admin)
#   -WithAtRest         provision VeraCrypt at-rest container for RAG/embeddings.db
#                       (encrypted-at-rest, key in DPAPI vault) + boot auto-mount
#   -WithRedteam        clone optional offensive / dual-use laforge-redteam repo
#   -DockerUp           bring up the Docker container stack after install
#   -DockerProfile <p>  which stack: core | full | all (default core)
param(
    [switch]$Docker,
    [switch]$ML,
    [switch]$WithSandboxUsers,
    [switch]$WithRedteam,
    [switch]$WithAtRest,
    [switch]$DockerUp,
    [string]$DockerProfile
)

$ErrorActionPreference = "Stop"
$NokidoDir = $PSScriptRoot

function Ok   { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn { param($msg) Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Die  { param($msg) Write-Host "  [X]  $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host " Nokido — Sovereign AI Orchestrator"      -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""

# ── Python ────────────────────────────────────────────────────────────────────
$Python = $null
foreach ($candidate in @("python3.12","python3","python")) {
    try {
        $ver = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        $major, $minor = $ver.Split(".")
        if ([int]$major -ge 3 -and [int]$minor -ge 12) { $Python = $candidate; break }
    } catch {}
}
if (-not $Python) {
    # Check miniforge3 default location
    $miniforge = "C:\Users\$env:USERNAME\miniforge3\python.exe"
    if (Test-Path $miniforge) {
        $Python = $miniforge
    } else {
        Die "Python 3.12+ required. Get Miniforge: https://github.com/conda-forge/miniforge"
    }
}
Ok "Python: $Python ($( & $Python --version))"

# ── Pip install ───────────────────────────────────────────────────────────────
$ReqFile = Join-Path $NokidoDir "requirements.txt"
Write-Host "  Installing core dependencies..."
& $Python -m pip install --quiet --upgrade pip
& $Python -m pip install --quiet -r $ReqFile
Ok "Core deps installed"

if ($ML) {
    Write-Host "  Installing ML deps (torch, sentence-transformers)..."
    & $Python -m pip install --quiet -r (Join-Path $NokidoDir "requirements-ml.txt")
    Ok "ML deps installed"
}

# ── Nokido.env ───────────────────────────────────────────────────────────────
$EnvFile = Join-Path $NokidoDir "Nokido.env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $NokidoDir "Nokido.env.example") $EnvFile
    $token = & $Python -c "import secrets; print(secrets.token_urlsafe(32))"
    (Get-Content $EnvFile) -replace "votre_token_secret_ici", $token | Set-Content $EnvFile
    Ok "Nokido.env created (token auto-generated)"
    Warn "Edit Nokido.env to set API keys and model names"
} else {
    Ok "Nokido.env already exists"
}

# ── Docker ────────────────────────────────────────────────────────────────────
$DockerOk = $false
try {
    docker info 2>$null | Out-Null
    $DockerOk = $true
    Ok "Docker available"
} catch {
    Warn "Docker not found — install: https://www.docker.com/products/docker-desktop"
}

# ── Ollama ────────────────────────────────────────────────────────────────────
$OllamaOk = (Get-Command ollama -ErrorAction SilentlyContinue) -ne $null
if ($OllamaOk) {
    Ok "Ollama: $(ollama --version 2>$null)"
} elseif ($DockerOk) {
    Warn "Ollama not installed locally — Docker will provide it"
} else {
    Warn "Ollama not found. Install: https://ollama.com/download"
}

# ── Bootstrap RAG seeds (fresh clones only) ──────────────────────────────────
$RagDb = Join-Path $NokidoDir "RAG\embeddings.db"
if (-not (Test-Path $RagDb) -or (Get-Item $RagDb).Length -lt 1MB) {
    Write-Host "  Fresh DB detected — bootstrapping from seed/*.jsonl..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Path (Join-Path $NokidoDir "RAG") -Force | Out-Null
    try {
        & $Python (Join-Path $NokidoDir "tools\forge_db_bootstrap.py")
        Ok "RAG seeds imported (~3k chunks bootstrap)"
        Warn "Embeddings are generated lazily by brain_worker — first searches may be slow"
    } catch {
        Warn "Seed bootstrap failed — run manually: python tools/forge_db_bootstrap.py"
    }
} else {
    Ok "RAG/embeddings.db already populated — skipping bootstrap"
}

# ── .mcp.json bootstrap (Claude Code / Cline / VSCode MCP clients) ──────────
# .mcp.json.example ships with placeholder bearers. forge_mcp_json_sync.py
# reads vault DPAPI -> writes the real Bearer tokens per agent.
$McpJson    = Join-Path $NokidoDir ".mcp.json"
$McpExample = Join-Path $NokidoDir ".mcp.json.example"
if (-not (Test-Path $McpJson) -and (Test-Path $McpExample)) {
    Write-Host "  Creating .mcp.json from template..." -ForegroundColor Cyan
    Copy-Item -Path $McpExample -Destination $McpJson
    try {
        & $Python (Join-Path $NokidoDir "tools\forge_mcp_json_sync.py") --path $McpJson
        Ok ".mcp.json bootstrapped (Bearer tokens read from vault DPAPI)"
    } catch {
        Warn ".mcp.json created but vault tokens missing — run vault seed first:"
        Warn "  $Python tools/forge_vault_seed_agent_tokens.py --from-env-file Nokido.env"
        Warn "  $Python tools/forge_mcp_json_sync.py --path $McpJson"
    }
}

# ── Propagate MCP to ALL installed CLIs (.mcp.json above = Claude Code/Cline/VSCode only) ──
# forge_client_bootstrap propagates to the OTHERS: Gemini/agy, Codex, Claude Desktop.
$propMcp = $true
if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    $a = Read-Host "  Propager la config MCP Nokido a tes autres CLI (Gemini/agy, Codex, Claude Desktop) ? [Y/n]"
    if ($a -match '^[nN]') { $propMcp = $false }
}
if ($propMcp) {
    Write-Host "  Propagation MCP -> CLI installes (forge_client_bootstrap --apply)..." -ForegroundColor Cyan
    & $Python (Join-Path $NokidoDir "tools\forge_client_bootstrap.py") --apply
    if ($LASTEXITCODE -eq 0) { Ok "Config MCP propagee (token + config MCP + skills par CLI detecte)." }
    else { Warn "Bootstrap partiel - relance: $Python tools/forge_client_bootstrap.py --apply" }
} else { Write-Host "  Propagation MCP CLI sautee." }

# ── Sandbox user accounts (optional, requires admin) ─────────────────────────
# LaForgeSbxOnline   — network egress allowed, sandboxed exec
# LaForgeSbxOffline  — offline-only sandbox (no network)
# LaForgeTrustedRunners — privileged group for trusted_script / git push
# All have ACLs scoped to the Nokido directory + machine vault (read-only).
function Ensure-SandboxUser {
    param([string]$Name, [string]$Desc)
    $u = Get-LocalUser -Name $Name -ErrorAction SilentlyContinue
    if (-not $u) {
        $pwd = ConvertTo-SecureString -String ([System.Web.Security.Membership]::GeneratePassword(24,4)) -AsPlainText -Force
        New-LocalUser -Name $Name -Password $pwd -PasswordNeverExpires `
            -AccountNeverExpires -Description $Desc -UserMayNotChangePassword | Out-Null
        Ok "Created local user: $Name"
    } else {
        Ok "User exists: $Name"
    }
}

function Ensure-LocalGroup {
    param([string]$Name, [string]$Desc)
    $g = Get-LocalGroup -Name $Name -ErrorAction SilentlyContinue
    if (-not $g) {
        New-LocalGroup -Name $Name -Description $Desc | Out-Null
        Ok "Created local group: $Name"
    } else {
        Ok "Group exists: $Name"
    }
}

if ($WithSandboxUsers) {
    $isAdmin = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Warn "WithSandboxUsers requires admin. Re-run PowerShell as Administrator and retry."
    } else {
        Write-Host "  Provisioning sandbox accounts + ACLs..." -ForegroundColor Cyan

        # Required for password generator
        Add-Type -AssemblyName System.Web -ErrorAction SilentlyContinue

        Ensure-SandboxUser -Name "LaForgeSbxOnline" `
            -Desc "Nokido sandbox account — online (network egress for cloud calls)"
        Ensure-SandboxUser -Name "LaForgeSbxOffline" `
            -Desc "Nokido sandbox account — offline (no network)"
        Ensure-LocalGroup  -Name "LaForgeTrustedRunners" `
            -Desc "Nokido trusted runners group — allowed to run trusted_script"

        # Add main user to trusted runners group
        $me = $env:USERNAME
        $current = (Get-LocalGroupMember "LaForgeTrustedRunners" -ErrorAction SilentlyContinue).Name
        if (-not ($current -like "*\$me")) {
            Add-LocalGroupMember -Group "LaForgeTrustedRunners" -Member $me
            Ok "Added $me to LaForgeTrustedRunners"
        }

        # ACL: grant Nokido dir read to sandbox accounts, write to sandbox/ only
        $acl = Get-Acl $NokidoDir
        foreach ($sbx in @("LaForgeSbxOnline","LaForgeSbxOffline")) {
            $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
                $sbx, "ReadAndExecute", "ContainerInherit,ObjectInherit", "None", "Allow")
            $acl.AddAccessRule($rule)
        }
        Set-Acl $NokidoDir $acl
        Ok "ACLs: ReadAndExecute granted to LaForgeSbxOnline / LaForgeSbxOffline on Nokido dir"

        # Network deny rule for Offline (Windows Firewall outbound block)
        try {
            New-NetFirewallRule -DisplayName "Nokido_Sbx_Offline_BlockOut" `
                -Direction Outbound -Action Block -Profile Any -Enabled True `
                -LocalUser "O:LSD:(D;;CC;;;LaForgeSbxOffline)" `
                -ErrorAction SilentlyContinue | Out-Null
            Ok "Firewall: outbound block for LaForgeSbxOffline"
        } catch {
            Warn "Firewall rule already exists or insufficient privileges"
        }
        Write-Host ""
    }
} else {
    Warn "Sandbox users NOT provisioned. To enable per-account isolation, re-run as admin with -WithSandboxUsers"
}

# ── Optional: bring up the Docker stack (containers by profile) — opt-in / proposed ──
$ComposeFile = Join-Path $NokidoDir "docker\nokido\docker-compose.yml"
$dcProfile = $DockerProfile
$dcUp = [bool]$DockerUp -or [bool]$dcProfile
$dcSearx = $false
if (-not $dcUp -and $DockerOk -and (Test-Path $ComposeFile) -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    Write-Host ""
    Write-Host "  Stack Docker Nokido (containers par profil) :" -ForegroundColor Cyan
    Write-Host "    core = laforge-hub + ollama"
    Write-Host "    full = core + deno-webhub + brain-worker"
    Write-Host "    all  = full + netcfg-agent + searxng + adminer"
    $c = Read-Host "  Demarrer la stack Docker maintenant ? [core/full/all/N]"
    if ($c -match '^(core|full|all)$') { $dcUp = $true; $dcProfile = $Matches[1] }
    if ($dcUp -and $dcProfile -ne "all") {
        $s = Read-Host "  Ajouter SearXNG (web_search/veille local) ? [y/N]"
        if ($s -match '^[yY]') { $dcSearx = $true }
    }
}
if ($dcUp) {
    if (-not $dcProfile) { $dcProfile = "core" }
    if (-not $DockerOk) {
        Warn "Docker indisponible — installe Docker Desktop puis relance avec -DockerUp -DockerProfile $dcProfile."
    } elseif (-not (Test-Path $ComposeFile)) {
        Warn "Compose introuvable : $ComposeFile"
    } else {
        Write-Host "  docker compose --profile $dcProfile up -d ..." -ForegroundColor Cyan
        docker compose -f $ComposeFile --profile $dcProfile up -d
        if ($dcSearx) { docker compose -f $ComposeFile up -d searxng }
        if ($LASTEXITCODE -eq 0) {
            Ok "Stack Docker '$dcProfile' demarree."
            Write-Host "  Modele LLM : docker exec laforge-ollama ollama pull qwen2.5-coder:latest"
        } else { Warn "docker compose a renvoye une erreur — verifie 'docker compose ... up -d' a la main." }
        Warn "  exegol (offensif) n'est PAS dans cette stack : il vient avec laforge-redteam (opt-in ci-dessous)."
    }
}

# ── Optional: at-rest encryption (VeraCrypt container for RAG/embeddings.db) — opt-in / proposed ──
$vcInstall = [bool]$WithAtRest
if (-not $vcInstall -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    Write-Host ""
    Warn "Module OPTIONNEL : chiffrement AT-REST (conteneur VeraCrypt pour RAG/embeddings.db + secrets)."
    Warn "  Protege tes donnees au repos (disque vole / backup). Cle au vault DPAPI, jamais en clair sur disque."
    $p = Read-Host "  Activer le chiffrement at-rest maintenant ? [y/N]"
    if ($p -match '^[yY]') { $vcInstall = $true }
}
if ($vcInstall) {
    $vcBin = "C:\Program Files\VeraCrypt\VeraCrypt.exe"
    if (-not (Test-Path $vcBin)) {
        Warn "VeraCrypt introuvable. Installe-le, puis relance avec -WithAtRest :"
        Warn "  winget install -e --id IDRIX.VeraCrypt"
        Warn "  (ou https://www.veracrypt.fr/en/Downloads.html)"
    } else {
        Write-Host "  Provisioning conteneur at-rest (init-key -> create -> migrate -> boot mount)..." -ForegroundColor Cyan
        & $Python (Join-Path $NokidoDir "tools\forge_at_rest_veracrypt.py") --init-key
        & $Python (Join-Path $NokidoDir "tools\forge_at_rest_veracrypt.py") --create --size-gb 16
        if ($LASTEXITCODE -eq 0) {
            & $Python (Join-Path $NokidoDir "tools\forge_at_rest_veracrypt.py") --migrate
            & $Python (Join-Path $NokidoDir "tools\forge_install_boot_mount.py") --install
            Ok "Chiffrement at-rest actif (conteneur monte au boot via tache SYSTEM)."
        } else {
            Warn "Creation du conteneur echouee. Relance manuellement :"
            Warn "  $Python tools\forge_at_rest_veracrypt.py --init-key"
            Warn "  $Python tools\forge_at_rest_veracrypt.py --create --size-gb 16"
            Warn "  $Python tools\forge_at_rest_veracrypt.py --migrate"
            Warn "  $Python tools\forge_install_boot_mount.py --install"
        }
    }
}

# ── Optional: laforge-redteam (OFFENSIVE / dual-use) — opt-in / proposed ────────
$rtInstall = [bool]$WithRedteam
if (-not $rtInstall -and [Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    Write-Host ""
    Warn "Module OPTIONNEL : laforge-redteam (offensif / dual-use, depot prive, MCP dedie)."
    $p = Read-Host "  L'installer maintenant ? [y/N]"
    if ($p -match '^[yY]') { $rtInstall = $true }
}
if ($rtInstall) {
    Write-Host ""
    Warn "=== laforge-redteam — OFFENSIVE / DUAL-USE MODULE ==="
    Warn "  exegol / CTF / exploit dev / recon / CVE — separate PRIVATE repo, dedicated MCP (LAFORGE_REDTEAM_MCP_PORT)."
    Warn "  * AUTHORIZED USE ONLY: systems you own, with explicit written authorization,"
    Warn "    CTF, or security research. Unauthorized scanning/exploitation is ILLEGAL —"
    Warn "    you assume FULL legal responsibility."
    Warn "  * LLM POLICY: many providers (cloud + some local) REFUSE or degrade offensive"
    Warn "    requests. Redteam features routed to such models may be BLOCKED at the model"
    Warn "    layer — prefer local uncensored models or expect refusals."
    Warn "  * NOT bundled by default — installing it is your explicit choice."
    $consent = Read-Host "  Type EXACTLY 'I-UNDERSTAND' to install laforge-redteam"
    if ($consent -ceq "I-UNDERSTAND") {
        $repo = if ($env:LAFORGE_REDTEAM_REPO) { $env:LAFORGE_REDTEAM_REPO } else { "git@github.com:user/laforge-redteam.git" }
        $dest = Join-Path (Split-Path $NokidoDir -Parent) "laforge-redteam"
        Write-Host "  Cloning $repo -> $dest (private; needs your git access)..."
        git clone $repo $dest
        if ($LASTEXITCODE -eq 0) { Ok "laforge-redteam cloned. Finish: cd $dest; .\install.ps1 (wires its dedicated MCP + token)." }
        else { Warn "Clone failed (access? URL?). Set LAFORGE_REDTEAM_REPO and retry, or clone manually." }
    } else {
        Write-Host "  laforge-redteam skipped (no consent)."
    }
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host " Installation complete."
Write-Host ""
Write-Host " Option A — Docker (recommended):"
Write-Host "   cd docker\nokido"
Write-Host "   docker compose up -d"
Write-Host "   docker exec laforge-ollama ollama pull qwen2.5-coder:latest"
Write-Host ""
Write-Host " Option B — Native (Windows):"
Write-Host "   ollama serve"
Write-Host "   $Python tools\nokido_hub.py"
Write-Host ""
Write-Host " Hub: http://localhost:8766"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
