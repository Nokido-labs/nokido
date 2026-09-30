<#
    wol_props_reapply.ps1 -- Filet anti-regression WOL sur la carte RJ45 Realtek 2.5GbE.
    Machine : ASUS B650E MAX GAMING WIFI W.

    PROBLEME MESURE (2026-07-22) : le driver Realtek REMET ses defauts apres un
    cycle d'arret ou une reactivation de la carte. Constate ce jour :
        *EEE             Disabled -> Enabled
        PowerSavingMode  Disabled -> Enabled
    Consequence : le PHY bascule en LPI quand la machine est eteinte, le magic
    packet n'est plus vu, le PC ne se reveille plus. Preuve par le LOG et non
    par une sonde : journal System / Power-Troubleshooter, TOUS les reveils
    depuis le 2026-07-17 ont pour source "Power Button" ; le dernier reveil par
    la carte ("Device -PCI Express Root Port") date du 2026-07-08.

    wol_setup.ps1 corrigeait bien ces proprietes, mais RIEN ne le relancait :
    d'ou une regression silencieuse a chaque cycle. Ce script est le chainon
    manquant -- conçu pour etre rejoue au demarrage par une tache planifiee.

    PERIMETRE VOLONTAIREMENT ETROIT : proprietes du driver + armement du reveil,
    RIEN d'autre. Ni IP, ni routage, ni pare-feu, ni RDP -- ceux-la restent le
    role de wol_setup.ps1, qu'on ne veut surtout pas rejouer a chaque boot.

    ETATS COUVERTS : S3 (veille) et S5 (arret complet).
    S4 est hors scope : l'hibernation est volontairement desactivee ici
    (choix owner 2026-07-22), donc "veille prolongee" n'existe pas sur la machine.

    RAPPEL : ces proprietes ne suffisent pas seules. Cote BIOS il faut
    Advanced > APM Configuration > "ErP Ready" = Disabled (ErP coupe le +5VSB :
    plus aucune alimentation du PHY a l'arret, donc aucun WOL possible depuis S5)
    et "Power On By PCI-E" = Enabled.

    Fichier en ASCII pur : PowerShell 5.1 relit les .ps1 sans BOM en CP1252, et
    un caractere UTF-8 accentue y casse le parsing.

    Manuel, console ELEVEE :
        powershell -NoProfile -ExecutionPolicy Bypass -File C:\...\wol_props_reapply.ps1

    Audit seul, sans rien modifier :
        ... -File wol_props_reapply.ps1 -CheckOnly
#>
[CmdletBinding()]
param(
    # 'Not Speed Down' = le lien reste a pleine vitesse quand le PC est eteint.
    # Repli si le WOL echoue depuis S5 alors qu'il marche depuis S3 : '10 Mbps First'
    # (certains rails +5VSB n'alimentent pas le PHY a pleine vitesse).
    [ValidateSet('Not Speed Down', '100 Mbps First', '10 Mbps First')]
    [string]$LinkSpeed = 'Not Speed Down',

    # Le restart de la carte coupe le lien ~5 s. Inoffensif au boot ; a eviter
    # si une session RDP passe par cette carte au moment du lancement manuel.
    [switch]$NoRestartAdapter,

    # N'ecrit rien : se contente de rapporter les derives. Code de sortie 2 si derive.
    [switch]$CheckOnly,

    [string]$LogPath = 'C:\tmp\wol_props_reapply.log',

    # Installe (ou met a jour) la tache planifiee qui rejoue ce script a chaque
    # demarrage. C'est ELLE qui ferme la regression : sans relance automatique,
    # le driver Realtek remet ses defauts au premier cycle d'arret et le WOL
    # meurt en silence, exactement comme entre le 2026-07-12 et le 2026-07-22.
    # Le script continue ensuite son execution normale.
    [switch]$InstallTask
)

$ErrorActionPreference = 'Stop'
$RJ45_HWID = 'PCI\VEN_10EC&DEV_8125'   # Realtek RTL8125 2.5GbE

$script:Drifted = 0
$script:Failed  = 0

function Say($level, $text) {
    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $level, $text
    switch ($level) {
        'OK'    { Write-Host "  $line" -ForegroundColor Green }
        'DRIFT' { Write-Host "  $line" -ForegroundColor Yellow }
        'FAIL'  { Write-Host "  $line" -ForegroundColor Red }
        default { Write-Host "  $line" -ForegroundColor Gray }
    }
    if ($LogPath) {
        try {
            $dir = Split-Path -Parent $LogPath
            if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            Add-Content -Path $LogPath -Value $line -Encoding ASCII
        } catch { }
    }
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Say 'FAIL' 'Console NON elevee : les proprietes du driver ne sont pas modifiables. Relancer en Administrateur.'
    exit 1
}

Say 'INFO' ('--- wol_props_reapply demarre (CheckOnly={0}) ---' -f [bool]$CheckOnly)

# ---------------------------------------------------------------- 0. Tache planifiee
if ($InstallTask) {
    $me = $PSCommandPath
    if (-not $me) { $me = $MyInvocation.MyCommand.Definition }
    $taskName = 'NokidoWolReapply'
    $arg = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -LinkSpeed "{1}"' -f $me, $LinkSpeed
    $action  = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg
    # +2 min apres le boot : laisse le driver reseau finir de s'initialiser,
    # sinon on ecrit des proprietes qu'il ecrasera juste apres.
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $trigger.Delay = 'PT2M'
    $princ = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
               -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    $desc = 'Nokido : reapplique les proprietes WOL de la carte RJ45 Realtek. Le driver remet ses defauts (EEE, PowerSavingMode) apres un cycle d arret, ce qui tue le reveil a distance.'
    try {
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
            -Principal $princ -Settings $set -Description $desc -Force | Out-Null
        Say 'OK' ("Tache planifiee '{0}' installee : au demarrage +2 min, compte SYSTEM." -f $taskName)
    } catch {
        Say 'FAIL' ("Register-ScheduledTask : {0}" -f $_.Exception.Message)
        $script:Failed++
    }
}

# ---------------------------------------------------------------- 1. La carte
$nic = Get-NetAdapter | Where-Object { $_.PnPDeviceID -like "$RJ45_HWID*" } | Select-Object -First 1
if (-not $nic) {
    Say 'FAIL' "Carte Realtek RTL8125 introuvable (HWID $RJ45_HWID). Desactivee dans le BIOS ?"
    exit 1
}
Say 'INFO' ("Carte '{0}' ifIndex={1} MAC={2} lien={3} {4}" -f $nic.Name, $nic.ifIndex, $nic.MacAddress, $nic.Status, $nic.LinkSpeed)
if ($nic.Status -ne 'Up') {
    Say 'DRIFT' 'Lien DOWN : un cable RJ45 doit relier le PC a un port LAN de la Freebox, sinon aucun WOL.'
}

# ---------------------------------------------------------------- 2. Proprietes
# Les 2 dernieres etaient ABSENTES de wol_setup.ps1 (il visait 'AutoPowerSaveModeEnabled',
# keyword que ce driver n'expose pas) : c'est par la que la derive est passee.
$targets = [ordered]@{
    '*WakeOnMagicPacket'  = 'Enabled'    # le reveil lui-meme
    'S5WakeOnLan'         = 'Enabled'    # "Shutdown Wake-On-Lan" : reveil depuis S5
    '*WakeOnPattern'      = 'Disabled'   # evite les reveils intempestifs
    '*EEE'                = 'Disabled'   # Energy-Efficient Ethernet : cause n1 de WOL rate
    'AdvancedEEE'         = 'Disabled'
    'EnableGreenEthernet' = 'Disabled'
    'PowerSavingMode'     = 'Disabled'   # <-- derive constatee le 2026-07-22
    'GigaLite'            = 'Disabled'   # <-- derive constatee le 2026-07-22
}
$targets['WolShutdownLinkSpeed'] = $LinkSpeed

$needRestart = $false

foreach ($kw in $targets.Keys) {
    $want = $targets[$kw]

    # -RegistryKeyword traite '*' comme un joker ('*EEE' matche aussi AdvancedEEE) :
    # on refiltre sur l'egalite stricte.
    $prop = Get-NetAdapterAdvancedProperty -Name $nic.Name -RegistryKeyword $kw -ErrorAction SilentlyContinue |
            Where-Object { $_.RegistryKeyword -eq $kw } | Select-Object -First 1

    if (-not $prop) { Say 'INFO' "$kw : non expose par ce driver (ignore)"; continue }
    if ($prop.DisplayValue -eq $want) { Say 'OK' "$kw = $want"; continue }

    $script:Drifted++
    Say 'DRIFT' ("{0} : '{1}' au lieu de '{2}'" -f $kw, $prop.DisplayValue, $want)
    if ($CheckOnly) { continue }

    if (-not (@($prop.ValidDisplayValues) -contains $want)) {
        Say 'FAIL' ("{0} : '{1}' hors des valeurs valides ({2}) - laisse tel quel" -f $kw, $want, ($prop.ValidDisplayValues -join ', '))
        $script:Failed++
        continue
    }
    try {
        Set-NetAdapterAdvancedProperty -Name $nic.Name -RegistryKeyword $kw -DisplayValue $want -NoRestart
        Say 'OK' ("{0} : corrige -> {1}" -f $kw, $want)
        $needRestart = $true
    } catch {
        Say 'FAIL' ("{0} : echec - {1}" -f $kw, $_.Exception.Message)
        $script:Failed++
    }
}

if ($needRestart -and -not $NoRestartAdapter -and -not $CheckOnly) {
    Say 'INFO' 'Reinitialisation de la carte pour appliquer les proprietes (lien coupe ~5 s)...'
    try {
        Restart-NetAdapter -Name $nic.Name -Confirm:$false
        Start-Sleep -Seconds 5
        Say 'OK' 'Carte reinitialisee'
    } catch {
        Say 'FAIL' ("Restart-NetAdapter : {0}" -f $_.Exception.Message)
        $script:Failed++
    }
} elseif ($needRestart -and $NoRestartAdapter) {
    Say 'DRIFT' 'Proprietes ecrites mais carte NON reinitialisee (-NoRestartAdapter) : effectif au prochain cycle.'
}

# ---------------------------------------------------------------- 3. Armement du reveil
# Get-/Set-NetAdapterPowerManagement casse sur cette machine (CimException
# "Windows System Error 31") a cause d'un autre adaptateur de la classe en
# erreur : on essaie, et on ne bloque pas dessus. Les valeurs du registre
# posees en section 2 couvrent deja WakeOnMagicPacket / WakeOnPattern.
if (-not $CheckOnly) {
    try {
        Set-NetAdapterPowerManagement -Name $nic.Name -WakeOnMagicPacket Enabled -WakeOnPattern Disabled -DeviceSleepOnDisconnect Disabled -ErrorAction Stop
        Say 'OK' 'NetAdapterPowerManagement : magic packet arme, sleep-on-disconnect off'
    } catch {
        Say 'INFO' ("Set-NetAdapterPowerManagement indisponible ({0}) - couvert par le registre" -f $_.Exception.Message)
    }

    # "Autoriser ce peripherique a sortir l'ordinateur de veille" (plan d'alimentation).
    try {
        powercfg /deviceenablewake "$($nic.InterfaceDescription)" 2>&1 | Out-Null
        Say 'OK' ("powercfg : reveil arme pour '{0}'" -f $nic.InterfaceDescription)
    } catch {
        Say 'FAIL' ("powercfg /deviceenablewake : {0}" -f $_.Exception.Message)
        $script:Failed++
    }
}

# ---------------------------------------------------------------- 4. Demarrage rapide
# Fast Startup transforme l'arret en hibernation partielle : la carte n'est pas
# reinitialisee proprement et le WOL depuis S5 devient aleatoire. Doit rester a 0.
$pk = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power'
$hb = (Get-ItemProperty $pk -Name HiberbootEnabled -ErrorAction SilentlyContinue).HiberbootEnabled
if ($hb -eq 0) {
    Say 'OK' 'HiberbootEnabled = 0 (demarrage rapide desactive)'
} else {
    $script:Drifted++
    Say 'DRIFT' ("HiberbootEnabled = {0} : le demarrage rapide est revenu" -f $hb)
    if (-not $CheckOnly) {
        try {
            Set-ItemProperty $pk -Name HiberbootEnabled -Value 0 -Type DWord
            Say 'OK' 'HiberbootEnabled remis a 0'
        } catch {
            Say 'FAIL' ("HiberbootEnabled : {0}" -f $_.Exception.Message)
            $script:Failed++
        }
    }
}

# ---------------------------------------------------------------- 5. Verdict
Say 'INFO' 'Peripheriques autorises a reveiller la machine :'
$armed = @(powercfg /devicequery wake_armed)
$armed | ForEach-Object { if ($_ -and $_.Trim()) { Say 'INFO' ("  - {0}" -f $_.Trim()) } }

$nicArmed = @($armed | Where-Object { $_ -like "*$($nic.InterfaceDescription)*" }).Count -gt 0
if ($nicArmed) {
    Say 'OK' 'La carte RJ45 est armee pour le reveil.'
} else {
    Say 'FAIL' "La carte RJ45 n'apparait PAS dans wake_armed : le reveil ne partira pas."
    $script:Failed++
}

Say 'INFO' ("--- termine : derives={0} echecs={1} ---" -f $script:Drifted, $script:Failed)

if ($script:Failed -gt 0) { exit 1 }
if ($CheckOnly -and $script:Drifted -gt 0) { exit 2 }
exit 0
