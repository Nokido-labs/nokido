# install_shortcuts.ps1 - cree les raccourcis bureau Nokido.
# A lancer depuis une console PowerShell de l'owner (les .lnk vivent dans SON profil).
#
# CORRIGE 2026-09-06 : les cibles s'appelaient encore "LaForge Control Panel.bat" et
# "LaForge Tray.bat" alors que les fichiers ont ete renommes en "Nokido ...". Mesure du
# jour : 3 des 4 raccourcis pointaient vers un fichier ABSENT, et le Control Panel ne
# figurait plus sur le Bureau. Un raccourci mort ne dit rien : Windows le cree sans
# broncher et l'echec n'apparait qu'au double-clic. D'ou la verification ci-dessous --
# une cible manquante est NOMMEE et le raccourci n'est pas cree.
#
# ASCII SEULEMENT dans ce fichier : le gate .ps1 refuse tout caractere non-ASCII (un
# .ps1 mal decode casse le demarrage sous PowerShell 5.1).

$ROOT    = "$env:USERPROFILE\Script python IA\Nokido"
$Desktop = [Environment]::GetFolderPath("Desktop")
$Startup = [Environment]::GetFolderPath("Startup")
$WS      = New-Object -ComObject WScript.Shell
$cree = 0
$manquants = @()

function New-NokidoShortcut {
    param($Chemin, $Cible, $Description, $Style = 1, $VerifierCible = $true, $Arguments = "", $Icone = "")
    if ($VerifierCible -and -not (Test-Path $Cible)) {
        $script:manquants += $Cible
        Write-Host "[SAUTE] cible absente : $Cible" -ForegroundColor Yellow
        return
    }
    # Un .lnk re-pointe garde un LinkInfo perime : on le supprime avant de le recreer (le notre, pas un autre).
    Remove-Item -LiteralPath $Chemin -Force -ErrorAction SilentlyContinue
    $lnk = $WS.CreateShortcut($Chemin)
    $lnk.TargetPath = $Cible
    if ($Arguments) { $lnk.Arguments = $Arguments }
    if ($VerifierCible) { $lnk.WorkingDirectory = $ROOT }
    if ($Icone) { $lnk.IconLocation = $Icone }
    $lnk.Description = $Description
    $lnk.WindowStyle = $Style
    $lnk.Save()
    $script:cree++
    Write-Host "[OK] $([System.IO.Path]::GetFileNameWithoutExtension($Chemin))" -ForegroundColor Green
}

# UNE SEULE icone au Bureau (owner 2026-10-13 : "une seule icone Nokido qui lance la stack et le tray").
# "Nokido" -> Control Panel --action lancer : la stack si elle dort (nokido_start.ps1, UAC), puis le tray,
# verifie vivant. Hub deja debout = rien n'est relance, seul le tray est assure. Stop / Restart /
# Restart hub / Statut / Network Monitor : menu du tray (clic droit), qui ouvre le MEME Control Panel.
# cmd /c : succes = la console se ferme seule ; echec = le lanceur la garde ouverte sur le motif.
$panneau = "$ROOT\tools\Nokido Control Panel.bat"
$cmd     = "$env:SystemRoot\System32\cmd.exe"
$python  = "$env:USERPROFILE\miniforge3\python.exe"
$dossier = "$env:LOCALAPPDATA\Nokido"
$ico     = "$dossier\nokido.ico"

# Icone = la marque du tray sur sa tuile sombre, ecrite par le tray lui-meme (une seule source de rendu).
& $python "$ROOT\tools\nokido_tray.py" --ecrire-ico $ico
if ($LASTEXITCODE -eq 0 -and (Test-Path $ico)) {
    $icone = "$ico,0"
} else {
    Write-Host "[REPLI] icone Nokido non ecrite (motif ci-dessus) : icone Windows generique" -ForegroundColor Yellow
    $icone = "$env:SystemRoot\System32\imageres.dll,77"
}

if (Test-Path $panneau) {
    New-NokidoShortcut "$Desktop\Nokido.lnk" $cmd "Lancer Nokido : la stack si elle dort, puis le tray" 1 $true "/c `"`"$panneau`" --action lancer`"" $icone
} else {
    $script:manquants += $panneau
    Write-Host "[SAUTE] cible absente : $panneau (icone Nokido non creee)" -ForegroundColor Yellow
}

# Tray au demarrage de session (shell:startup) : invisible, ce n'est pas une icone du Bureau.
New-NokidoShortcut "$Startup\Nokido Tray.lnk" "$ROOT\tools\Nokido Tray.bat" "Nokido Tray Icon (demarrage)" 7

# Les anciennes icones Nokido du Bureau sont RANGEES, jamais supprimees (on gele) : deplacees hors du
# Bureau, recuperables a la main. Leurs gestes vivent dans le menu du tray.
$retires = "$dossier\raccourcis_retires"
$anciens = @("Nokido START.lnk", "Nokido - Restart stack.lnk", "Nokido STOP.lnk",
             "Nokido Control Panel.lnk", "Nokido Tray.lnk", "Nokido Network.lnk")
foreach ($nom in $anciens) {
    $src = Join-Path $Desktop $nom
    if (Test-Path -LiteralPath $src) {
        New-Item -ItemType Directory -Force -Path $retires | Out-Null
        Move-Item -LiteralPath $src -Destination (Join-Path $retires $nom) -Force
        Write-Host "[RANGE] $nom -> $retires" -ForegroundColor DarkGray
    }
}

# Anciens raccourcis "LaForge ..." : signales, jamais supprimes sans decision (regle du
# corps : on gele, on ne supprime pas). L'owner tranche.
$vieux = @(Get-ChildItem $Desktop -Filter "LaForge *.lnk" -ErrorAction SilentlyContinue) +
         @(Get-ChildItem $Startup -Filter "LaForge *.lnk" -ErrorAction SilentlyContinue)
foreach ($v in $vieux) {
    Write-Host "[ANCIEN] $($v.FullName) - pointe probablement vers un fichier renomme ; a supprimer a la main si inutile" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "$cree raccourci(s) cree(s)."
if ($manquants.Count -gt 0) {
    Write-Host "$($manquants.Count) cible(s) ABSENTE(s) - aucun raccourci mort n'a ete cree :" -ForegroundColor Yellow
    foreach ($m in $manquants) { Write-Host "   $m" }
    exit 1
}
Write-Host "Installation terminee. Bureau : une seule icone 'Nokido' (stack + tray) ; le reste est dans le menu du tray."
