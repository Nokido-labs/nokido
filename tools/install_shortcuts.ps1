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
    param($Chemin, $Cible, $Description, $Style = 1, $VerifierCible = $true)
    if ($VerifierCible -and -not (Test-Path $Cible)) {
        $script:manquants += $Cible
        Write-Host "[SAUTE] cible absente : $Cible" -ForegroundColor Yellow
        return
    }
    $lnk = $WS.CreateShortcut($Chemin)
    $lnk.TargetPath = $Cible
    if ($VerifierCible) { $lnk.WorkingDirectory = $ROOT }
    $lnk.Description = $Description
    $lnk.WindowStyle = $Style
    $lnk.Save()
    $script:cree++
    Write-Host "[OK] $([System.IO.Path]::GetFileNameWithoutExtension($Chemin))" -ForegroundColor Green
}

# 1. Control Panel : menu interactif (le meme script sert en ligne de commande a tout
#    CLI via --action status|restart-hub|wake|start|stop|restart|list).
New-NokidoShortcut "$Desktop\Nokido Control Panel.lnk" "$ROOT\tools\Nokido Control Panel.bat" "Nokido Hub Control Panel" 1

# 2. Tray : icone de la zone de notification (fenetre minimisee).
New-NokidoShortcut "$Desktop\Nokido Tray.lnk" "$ROOT\tools\Nokido Tray.bat" "Nokido Tray Icon" 7

# 3. Network Monitor : URL, donc pas de cible sur disque a verifier.
New-NokidoShortcut "$Desktop\Nokido Network.lnk" "http://127.0.0.1:8766/forge/network" "Nokido Network Monitor" 1 $false

# 4. Tray au demarrage de session (shell:startup).
New-NokidoShortcut "$Startup\Nokido Tray.lnk" "$ROOT\tools\Nokido Tray.bat" "Nokido Tray Icon (demarrage)" 7

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
Write-Host "Installation terminee. Lance 'Nokido Tray' pour demarrer l'icone maintenant."
