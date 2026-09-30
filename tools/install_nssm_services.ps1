# install_nssm_services.ps1 — Installer les services NSSM Nokido
# Exécuter en tant qu'Admin : clic-droit -> "Run as Administrator"
# Ou depuis un terminal admin : .\tools\install_nssm_services.ps1

#Requires -RunAsAdministrator

$PY  = "$env:USERPROFILE\miniforge3\python.exe"
$DIR = "$env:USERPROFILE\Script python IA\Nokido"
$LOG = "$DIR\logs"

function Install-NssmService {
    param($Name, $Script, $DisplayName, $Desc, [hashtable]$ExtraEnv = @{})

    Write-Host "`n=== $Name ===" -ForegroundColor Cyan

    # Stop + remove si existant
    $status = nssm status $Name 2>&1
    if ($status -notmatch "does not exist|n.existe pas") {
        nssm stop $Name 2>&1 | Out-Null
        nssm remove $Name confirm 2>&1 | Out-Null
        Write-Host "  Ancien service supprime"
    }

    # Install
    nssm install $Name "$PY" "`"$Script`""
    nssm set $Name AppDirectory $DIR
    nssm set $Name AppStdout "$LOG\${Name}_nssm.log"
    nssm set $Name AppStderr "$LOG\${Name}_nssm.err"
    nssm set $Name AppRotateFiles 1
    nssm set $Name AppRotateBytes 5242880   # 5 MB
    nssm set $Name AppRotateOnline 1
    nssm set $Name Start SERVICE_AUTO_START
    nssm set $Name DisplayName $DisplayName
    nssm set $Name Description $Desc
    nssm set $Name AppRestartDelay 5000     # restart apres 5s si crash
    nssm set $Name AppStopMethodSkip 0

    # Variables d'env supplementaires
    if ($ExtraEnv.Count -gt 0) {
        $envStr = ($ExtraEnv.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "`n"
        nssm set $Name AppEnvironmentExtra $envStr
    }

    # Demarrer
    nssm start $Name
    Start-Sleep 3
    $s = nssm status $Name 2>&1
    $color = if ($s -match "RUNNING") { "Green" } else { "Red" }
    Write-Host "  Status: $s" -ForegroundColor $color
}

# ── 1. nokido_hub ────────────────────────────────────────────────────────────
Install-NssmService `
    -Name        "nokido_hub" `
    -Script      "$DIR\tools\nokido_hub.py" `
    -DisplayName "Nokido Hub :8766" `
    -Desc        "Nokido MCP Hub - orchestrateur multi-agent port 8766"

# ── 2. multi_llm_daemon ───────────────────────────────────────────────────────
Install-NssmService `
    -Name        "multi_llm_daemon" `
    -Script      "$DIR\tools\multi_llm_daemon.py" `
    -DisplayName "Nokido MultiLLM Daemon" `
    -Desc        "Daemon multi-provider: ollama/groq/hf/mistral/cohere/openrouter/lmstudio/llamacpp" `
    -ExtraEnv    @{ MULTI_LLM_POLL_INTERVAL = "15"; LAFORGE_DB = "$DIR\RAG\embeddings.db" }

# ── 3. gemini_poll_daemon (D2+D3) ─────────────────────────────────────────────
Install-NssmService `
    -Name        "gemini_poll_daemon" `
    -Script      "$DIR\tools\gemini_poll_daemon.py" `
    -DisplayName "Nokido Gemini Daemon (D2+D3)" `
    -Desc        "Daemon Gemini CLI OAuth + REST poll agent_messages" `
    -ExtraEnv    @{ GEMINI_POLL_MODE = "active"; GEMINI_POLL_INTERVAL_S = "30" }

Write-Host "`n=== Services installes ===" -ForegroundColor Green
nssm status nokido_hub
nssm status multi_llm_daemon
nssm status gemini_poll_daemon

Write-Host "`nVerification ports:"
Start-Sleep 5
try { (Invoke-RestMethod "http://127.0.0.1:8766/health").status } catch { "hub: $($_.Exception.Message.Substring(0,50))" }
