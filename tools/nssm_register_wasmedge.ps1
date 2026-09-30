#Requires -RunAsAdministrator
# Enregistre NokidoWasmedge comme service NSSM
# IMPORTANT: le service doit tourner comme user (pas SYSTEM) pour que WSL fonctionne

$svc = "NokidoWasmedge"
$wsl = "$env:SystemRoot\System32\wsl.exe"
$args = "-d Debian -- bash /mnt/c/tmp/wasm_start.sh"
$log = "$env:USERPROFILE\Script python IA\Nokido\sandbox\wasmedge_cervelet.log"

# Supprimer si existe
$existing = Get-Service -Name $svc -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing $svc..."
    & nssm remove $svc confirm
    Start-Sleep -Seconds 2
}

Write-Host "Installing $svc..."
& nssm install $svc $wsl $args

& nssm set $svc DisplayName  "Nokido WasmEdge Cervelet"
& nssm set $svc Description  "WasmEdge llama-api-server nomic-embed :55555 via WSL Debian"
& nssm set $svc Start        SERVICE_DEMAND_START
& nssm set $svc AppStdout    $log
& nssm set $svc AppStderr    $log
& nssm set $svc AppRotateFiles 0
& nssm set $svc AppStdoutCreationDisposition 1

# CRITIQUE: tourner comme user, pas SYSTEM — WSL necessite compte utilisateur normal
# Remplacer <MOT_DE_PASSE> par le vrai mot de passe ou laisser vide si login sans mdp
$user = ".\user"
$pass = Read-Host -Prompt "Mot de passe Windows de user (pour ObjectName)" -AsSecureString
$passPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pass)
)
& nssm set $svc ObjectName $user $passPlain

Write-Host ""
Write-Host "Service $svc cree. Status:"
Get-Service -Name $svc | Select-Object Name, Status, StartType
Write-Host ""
Write-Host "Tester: nssm start $svc"
Write-Host "Log:    $log"
