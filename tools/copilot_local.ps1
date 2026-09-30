param(
    [string]$Model = "qwen2.5-coder:7b-instruct-q4_K_M",
    [switch]$NoProxy
)

if (-not $NoProxy) {
    # Redirige le trafic vers le proxy OpenAI de LaForge
    $env:COPILOT_PROVIDER_BASE_URL = "http://localhost:7777/v1"
    $env:COPILOT_PROVIDER_TYPE = "openai"
    
    # Spécifie le modèle à utiliser (LaForge le routera vers Ollama, Groq, etc. selon tes clés)
    # Par défaut, on utilise un bon modèle pour le Tool Calling.
    $env:COPILOT_MODEL = $Model
    
    # Coupe la télémétrie
    $env:COPILOT_OFFLINE = "true"
    
    Write-Host "[LaForge] Copilot CLI est débranché du cloud." -ForegroundColor Green
    Write-Host "[LaForge] Modèle ciblé : $env:COPILOT_MODEL" -ForegroundColor Cyan
    Write-Host "[LaForge] Routage via : $env:COPILOT_PROVIDER_BASE_URL`n" -ForegroundColor Cyan
}

# Lancement de copilot avec les flags restrictifs
copilot --no-remote --disable-builtin-mcps --stream on $args
