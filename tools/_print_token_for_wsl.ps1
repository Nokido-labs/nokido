# tools/_print_token_for_wsl.ps1
# Imprime FORGE_MCP_TOKEN sur stdout pour export WSL.
# Usage WSL :
#   export FORGE_MCP_TOKEN=$(/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -File "$env:USERPROFILE/Script python IA/Nokido/tools/_print_token_for_wsl.ps1" | tr -d '\r\n')
# Param optionnel : -Key <NomCle> pour un autre secret coffre.
param([string]$Key = "FORGE_MCP_TOKEN")
& "$env:USERPROFILE/miniforge3/python.exe" -c "import sys; sys.path.insert(0,'$env:USERPROFILE/Script python IA/Nokido/app'); from forge_machine_vault import vault_get; v=vault_get('$Key'); print(v or '')"
