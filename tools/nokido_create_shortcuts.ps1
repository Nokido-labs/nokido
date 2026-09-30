#Requires -Version 5.1
# (Re)cree les raccourcis Bureau Nokido START et STOP.
# Supprime tout .lnk existant AVANT de regenerer : un .lnk re-pointe
# garde sinon un LinkInfo perime (ex: ancien laforge-start.cmd) qui fait
# croire a Windows que la cible est introuvable.

$toolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktop  = [Environment]::GetFolderPath("Desktop")
$wsh      = New-Object -ComObject WScript.Shell
$psExe    = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

function New-NokidoShortcut {
    param(
        [string]$Name,
        [string]$Script,
        [string]$Desc,
        [int]$IconIndex
    )
    $script = Join-Path $toolsDir $Script
    if (-not (Test-Path -LiteralPath $script)) {
        Write-Host "[X] cible absente : $script" -ForegroundColor Red
        return
    }
    # Tuer les variantes de nom (Windows = casse-insensible, mais on couvre)
    foreach ($n in @("$Name.lnk", ($Name.ToLower() + ".lnk"))) {
        Remove-Item -LiteralPath (Join-Path $desktop $n) -Force -ErrorAction SilentlyContinue
    }
    $path = Join-Path $desktop "$Name.lnk"
    $lnk = $wsh.CreateShortcut($path)
    $lnk.TargetPath       = $psExe
    $lnk.Arguments        = "-ExecutionPolicy Bypass -WindowStyle Normal -File `"$script`""
    $lnk.WorkingDirectory = $toolsDir
    $lnk.Description      = $Desc
    $lnk.IconLocation     = "C:\Windows\System32\imageres.dll,$IconIndex"
    $lnk.Save()
    Write-Host "[OK] $path" -ForegroundColor Green
}

New-NokidoShortcut "Nokido START" "nokido_start.ps1" "Demarrer tous les services Nokido" 77
New-NokidoShortcut "Nokido STOP"  "nokido_stop.ps1"  "Arreter tous les services Nokido"  100

Write-Host ""
Write-Host "Raccourcis regeneres (anciens .lnk supprimes)." -ForegroundColor Cyan
