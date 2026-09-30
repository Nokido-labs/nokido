param (
    [string]$DestDir = "%NOKIDO_ROOT%\data\rfc_mirror"
)

Write-Host "=================================================="
Write-Host "  LaForge - Synchronisation du Miroir IETF (RFC)"
Write-Host "=================================================="

# Création du dossier de stockage froid
if (-not (Test-Path $DestDir)) {
    New-Item -ItemType Directory -Force -Path $DestDir | Out-Null
    Write-Host "[+] Dossier cible créé : $DestDir"
}

# Détection de rsync (Git Bash ou WSL)
$GitRsync = "C:\Program Files\Git\usr\bin\rsync.exe"
$UseWsl = $false

if (Test-Path $GitRsync) {
    Write-Host "[i] Moteur rsync détecté : Git Bash ($GitRsync)"
    $RsyncExe = $GitRsync
} elseif (Get-Command rsync.exe -ErrorAction SilentlyContinue) {
    $RsyncExe = (Get-Command rsync.exe).Source
    Write-Host "[i] Moteur rsync détecté dans le PATH : $RsyncExe"
} elseif (Get-Command wsl -ErrorAction SilentlyContinue) {
    Write-Host "[i] Moteur rsync détecté : Sous-système WSL"
    $UseWsl = $true
} else {
    Write-Error "[!] Impossible de trouver rsync (ni via Git Bash, ni dans le PATH, ni via WSL)."
    Write-Host "Veuillez installer Git for Windows ou exécuter 'wsl sudo apt install rsync' dans votre terminal WSL."
    exit 1
}

Write-Host "[i] Lancement du miroir (Ne télécharge que les .txt et l'index)..."
Write-Host "[i] Les fichiers existants seront mis à jour (delta sync)."

if ($UseWsl) {
    # Vérifier que rsync est bien installé dans WSL
    $wslRsyncCheck = wsl which rsync
    if ([string]::IsNullOrWhiteSpace($wslRsyncCheck)) {
        Write-Error "[!] rsync n'est pas installé dans WSL."
        Write-Host "Veuillez exécuter 'wsl sudo apt install rsync' dans un terminal, ou installez Git for Windows."
        exit 1
    }
    
    # Convertir le chemin Windows en chemin WSL (ex: /mnt/c/Users/...)
    $WslDest = (wsl wslpath -a "$DestDir").Trim()
    wsl rsync -avz --include="rfc*.txt" --include="rfc-index.txt" --exclude="*" rsync.ietf.org::rfc $WslDest/
} else {
    & $RsyncExe -avz --include="rfc*.txt" --include="rfc-index.txt" --exclude="*" rsync.ietf.org::rfc/ "$DestDir/"
}

Write-Host "[+] Synchronisation terminée avec succès. Données stockées dans : $DestDir"
