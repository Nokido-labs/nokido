# install_jea.ps1 -- Enregistrer l'endpoint JEA Nokido
# Nécessite: Run as Administrator

$RolePath = "$env:ProgramFiles\WindowsPowerShell\Modules\NokidoJEA\RoleCapabilities"
New-Item -ItemType Directory -Force -Path $RolePath | Out-Null

# Copier le fichier de rôle
Copy-Item -Path ".\config\jea\Nokido_SysAdmin.psrc" -Destination $RolePath -Force

# Créer le répertoire de transcripts
$TranscriptDir = "$env:USERPROFILE\Script python IA\Nokido\logs\jea_transcripts"
New-Item -ItemType Directory -Force -Path $TranscriptDir | Out-Null

# Enregistrer la session configuration
Register-PSSessionConfiguration `
    -Path ".\config\jea\NokidoEndpoint.pssc" `
    -Name "Nokido_SysAdmin" `
    -Force

Write-Host "JEA endpoint enregistré: Nokido_SysAdmin"
Write-Host "Test: Enter-PSSession -ComputerName localhost -ConfigurationName Nokido_SysAdmin"
