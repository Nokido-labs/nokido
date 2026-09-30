# hub_restart_watcher.ps1
# Watcher de relance du hub - surveille sandbox/hub_restart.trigger.
#
# ASCII PUR, VOLONTAIREMENT. Un .ps1 accentue casse l'analyse de PowerShell 5.1
# (le fichier est lu en ANSI, les caracteres multi-octets corrompent le parsing).
# Ce script a d'abord ete ecrit avec des accents et des tirets cadratins : la
# tache planifiee rendait rc=1 avec "accolade fermante manquante", une erreur
# qui ne designait PAS la vraie cause. Ne pas reintroduire de non-ASCII ici.
#
# POURQUOI CE FICHIER A ETE REECRIT (2026-08-17)
# L'ancienne version lancait `nssm restart NokidoHub`. Ce service N'EXISTE PAS :
# il faisait partie des noms fantomes mesures le meme jour. Le dispositif etait
# donc MORT, et son echec SILENCIEUX - ni process, ni tache planifiee.
#
# Le hub n'est pas un service NSSM : il est SPAWNE par le superviseur Deno
# (LaForge-Master) sous le nom declare dans proxy_deno/core/services.toml. On
# s'adresse donc au superviseur, seul proprietaire du process.

$ErrorActionPreference = "Continue"
$root     = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$trigger  = Join-Path $root "sandbox\hub_restart.trigger"
$logfile  = Join-Path $root "sandbox\hub_watcher.log"
# Nom du hub COTE SUPERVISEUR (proxy_deno/core/services.toml), pas le service
# NSSM homonyme : ce sont deux objets distincts. Renomme en NokidoMCP le
# 2026-08-17, en meme temps que services.toml — les deux doivent bouger ensemble,
# sinon le watcher demande un service que le superviseur ne connait plus.
$svc      = if ($env:NOKIDO_HUB_SERVICE) { $env:NOKIDO_HUB_SERVICE } else { "NokidoMCP" }
$sup      = "http://127.0.0.1:8765"
$interval = 2

function Write-Log($msg) {
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $logfile -Value $line -Encoding UTF8
}

function Get-SupervisorToken {
    # Le superviseur exige un Bearer pour toute MUTATION (les GET de statut
    # passent sans).
    #
    # SOURCE DE VERITE = LE COFFRE DPAPI. Une tache planifiee SYSTEM n'herite pas
    # de l'environnement du superviseur : le watcher tombait donc en 401 et
    # repliait sur un redemarrage de TOUTE la flotte. La tentation etait de
    # publier le jeton en variable MACHINE — c'est-a-dire un secret en clair dans
    # le registre, lisible par tout administrateur. Inutile : le coffre le
    # contient deja, et il est lisible en SYSTEM (verifie le 2026-08-17).
    # La valeur n'est JAMAIS journalisee, seulement passee en en-tete.
    $py = "%USERPROFILE%\miniforge3\python.exe"
    if (Test-Path $py) {
        try {
            $code = "import sys; sys.path.insert(0, r'" + (Join-Path $root 'app') + "'); from forge_secrets import get_secret; print(get_secret('LAFORGE_SUPERVISOR_TOKEN') or '')"
            $v = & $py -c $code 2>$null
            if ($v) {
                # -replace plutot que .Trim() : les appels de methode sont
                # interdits si ce script herite d'un mode de langage contraint.
                $v = ($v | Select-Object -First 1) -replace '\s', ''
                if ($v.Length -gt 20) { return $v }
            }
        } catch {
            Write-Log "coffre illisible : $($_.Exception.Message)"
        }
    }
    if ($env:LAFORGE_SUPERVISOR_TOKEN) { return $env:LAFORGE_SUPERVISOR_TOKEN }
    $reg = "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
    try {
        $v = (Get-ItemProperty -Path $reg -Name LAFORGE_SUPERVISOR_TOKEN -ErrorAction Stop).LAFORGE_SUPERVISOR_TOKEN
        if ($v) { return $v }
    } catch { }
    $envFile = Join-Path $root "Nokido.env"
    if (Test-Path $envFile) {
        foreach ($l in Get-Content $envFile -ErrorAction SilentlyContinue) {
            if ($l -match '^\s*LAFORGE_SUPERVISOR_TOKEN\s*=\s*(.+?)\s*$') { return $Matches[1].Trim('"') }
        }
    }
    return ""
}

function Invoke-Supervisor($path, $token) {
    $headers = @{}
    if ($token) { $headers["Authorization"] = "Bearer $token" }
    return Invoke-WebRequest -Uri "$sup$path" -Method POST -Headers $headers -UseBasicParsing -TimeoutSec 15
}

function Restart-Hub {
    $token = Get-SupervisorToken
    if (-not $token) { Write-Log "ATTENTION: jeton superviseur introuvable - tentative sans jeton" }
    try {
        try {
            [void](Invoke-Supervisor "/supervisor/service/stop/$svc" $token)
        } catch {
            Write-Log "stop $svc : $($_.Exception.Message) (normal si deja arrete)"
        }
        Start-Sleep -Seconds 2
        $r = Invoke-Supervisor "/supervisor/service/start/$svc" $token
        Write-Log "start $svc -> HTTP $($r.StatusCode)"
        return $true
    } catch {
        Write-Log "ECHEC via superviseur : $($_.Exception.Message)"
        # Dernier recours : relancer le superviseur lui-meme, qui remonte la
        # flotte. Plus lourd, mais seule main restante si :8765 ne repond pas.
        try {
            $out = & nssm restart laforge-master 2>&1
            Write-Log "repli nssm restart laforge-master -> $out"
            return $true
        } catch {
            Write-Log "ECHEC TOTAL : $($_.Exception.Message)"
            return $false
        }
    }
}

Write-Log "HubWatcher demarre - surveillance de $trigger (service=$svc)"

while ($true) {
    if (Test-Path $trigger) {
        Remove-Item $trigger -Force -ErrorAction SilentlyContinue
        Write-Log "Trigger detecte - relance du hub demandee au superviseur"
        [void](Restart-Hub)
        # Preuve d'EFFET : on ne declare pas le hub reparti parce qu'une commande
        # a rendu 0, mais parce que /health repond.
        $up = $false
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 3
            try {
                $h = Invoke-WebRequest -Uri "http://127.0.0.1:8766/health" -UseBasicParsing -TimeoutSec 4
                Write-Log "Hub UP : $($h.Content)"
                $up = $true
                break
            } catch { }
        }
        if (-not $up) { Write-Log "Hub TOUJOURS DOWN apres 90s - intervention humaine requise" }
    }
    Start-Sleep -Seconds $interval
}
