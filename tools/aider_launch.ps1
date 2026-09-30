# Aider launcher Nokido — boucle correction lint via LLM local Qwen-2.5-Coder.
# Doc : https://aider.chat/
# Pre-req : pip install aider-chat
# Pre-req : llama-server :8091 OR Ollama avec qwen2.5-coder

param(
    [string]$Backend = "llama",  # 'llama' (port 8091) | 'ollama' (port 11434)
    [string]$Model = "qwen2.5-coder",
    [switch]$LintLoop  # /lint au demarrage (auto Ruff fix)
)

$ErrorActionPreference = "Stop"
$repoRoot = "$env:USERPROFILE\Script python IA\Nokido"
Push-Location $repoRoot

if ($Backend -eq "llama") {
    $apiBase = "http://127.0.0.1:8091/v1"
    $modelArg = "openai/$Model"
} else {
    $apiBase = "http://127.0.0.1:11434/v1"
    $modelArg = "openai/$Model"
}

Write-Host "Aider launch : backend=$Backend model=$modelArg api=$apiBase"

# Aider args : commit + lint auto loop
$aiderArgs = @(
    "--model", $modelArg,
    "--openai-api-base", $apiBase,
    "--openai-api-key", "ollama-noauth",
    "--auto-commits"
)

if ($LintLoop) {
    $aiderArgs += "--lint-cmd"
    $aiderArgs += "ruff check --fix"
}

# Lance Aider en foreground
& aider @aiderArgs
Pop-Location
