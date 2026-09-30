# run_v6.ps1 — load Nokido.env into env vars and execute promptfoo eval for Bench V6
# Usage: pwsh -File run_v6.ps1

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$EnvFile = "$env:USERPROFILE\Script python IA\LaForge\LaForge.env"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutputJson = Join-Path $ScriptDir "bench_v6_$Stamp.json"
$ConfigFile = Join-Path $ScriptDir "promptfooconfig.v6.yaml"

# Load env vars from Nokido.env (KEY=VALUE format, skip comments / empty)
Write-Host "[v6] Loading env from $EnvFile" -ForegroundColor Cyan
$loaded = 0
Get-Content $EnvFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -match "^\s*#" -or $line -eq "") { return }
    if ($line -match "^([A-Za-z_][A-Za-z0-9_\.]*)=(.*)$") {
        $key = $Matches[1]
        $val = $Matches[2].Trim('"').Trim("'")
        # Remap SambaNova key (illegal Windows env name)
        if ($key -eq "cloud.sambanova.ai_API_KEY") {
            $key = "SAMBANOVA_API_KEY"
        }
        # Skip if dotted (Windows-incompatible)
        if ($key -notmatch '\.') {
            [System.Environment]::SetEnvironmentVariable($key, $val, "Process")
            $loaded++
        }
    }
}
Write-Host "[v6] $loaded env vars loaded" -ForegroundColor Green

# Provider key checks
$keys = @{
    "GROQ_API_KEY"        = $env:GROQ_API_KEY
    "MISTRAL_API_KEY"     = $env:MISTRAL_API_KEY
    "OPENROUTER_API_KEY"  = $env:OPENROUTER_API_KEY
    "GITHUB_MODELS_TOKEN" = $env:GITHUB_MODELS_TOKEN
    "HF_TOKEN"            = $env:HF_TOKEN
    "SAMBANOVA_API_KEY"   = $env:SAMBANOVA_API_KEY
}
foreach ($k in $keys.Keys) {
    if ($keys[$k]) {
        $len = $keys[$k].Length
        Write-Host "  $k = SET ($len chars)"
    } else {
        Write-Host "  $k = MISSING"
    }
}

# Output target
Write-Host "`n[v6] Output JSON: $OutputJson" -ForegroundColor Cyan
Write-Host "[v6] Config:      $ConfigFile" -ForegroundColor Cyan

# Override outputPath via -o flag (so each run is timestamped)
Push-Location $ScriptDir
try {
    $LogFile = Join-Path $ScriptDir "bench_v6_$Stamp.log"
    Write-Host "[v6] Running promptfoo... check log at $LogFile" -ForegroundColor Yellow
    & "$env:USERPROFILE\AppData\Roaming\npm\promptfoo.cmd" eval `
        --config $ConfigFile `
        --output $OutputJson `
        --max-concurrency 2 `
        --no-cache `
        --no-progress-bar `
        --no-table `
        *> $LogFile
    $exit = $LASTEXITCODE
    Write-Host "`n[v6] promptfoo exit: $exit" -ForegroundColor $(if ($exit -eq 0) { "Green" } else { "Yellow" })
} finally {
    Pop-Location
}

Write-Host "`n[v6] Done. JSON at $OutputJson"
