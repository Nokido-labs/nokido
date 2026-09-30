# Chemin vers NSSM
$nssmPath = "nssm"
$serviceName = "LaForge-EmbedDaemon"
$pythonPath = "$env:USERPROFILE/miniforge3/python.exe"
$scriptPath = "$env:USERPROFILE/Script python IA/Nokido/tools/forge_rag_embed_daemon.py"

try {
    # Vérifier si NSSM existe
    if (-not (Test-Path $nssmPath -or (Get-Command nssm -ErrorAction SilentlyContinue))) {
        throw "NSSM n'est pas installé ou n'est pas dans le PATH."
    }

    # Vérifier si le service existe déjà
    if (& $nssmPath status $serviceName) {
        & $nssmPath stop $serviceName
        & $nssmPath remove $serviceName confirm
    }

    # Installer le service
    & $nssmPath install $serviceName $pythonPath $scriptPath
    & $nssmPath set $serviceName AppDirectory "$env:USERPROFILE/Script python IA/Nokido"
    & $nssmPath set $serviceName AppStdout "$env:USERPROFILE/Script python IA/Nokido/logs/embed_daemon.log"
    & $nssmPath set $serviceName AppStderr "$env:USERPROFILE/Script python IA/Nokido/logs/embed_daemon_err.log"
    & $nssmPath set $serviceName Start SERVICE_AUTO_START

    # Démarrer le service
    & $nssmPath start $serviceName
    Write-Host "Service $serviceName installé et démarré avec succès."
} catch {
    Write-Error "Erreur lors de l'installation du service: $_"
}