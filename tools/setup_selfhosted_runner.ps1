<#
setup_selfhosted_runner.ps1 — installe un runner GitHub Actions SELF-HOSTED.

FALLBACK pendant le blocage billing (repo privé) : exécute les workflows
`runs-on: [self-hosted]` sur CETTE machine, gratuitement, sans passer public.

Token : généré AUTOMATIQUEMENT via gh (GitHub CLI déjà authentifié — rien à
copier, indépendant du vault DPAPI). Override manuel possible avec -Token.

Usage :
    pwsh tools/setup_selfhosted_runner.ps1                  # token auto via gh
    pwsh tools/setup_selfhosted_runner.ps1 -Token "AXXX"    # token manuel

Désinstaller plus tard (quand billing réglé / repo public) :
    cd C:/laforge-runner ; ./svc.cmd stop ; ./svc.cmd uninstall ; ./config.cmd remove --token <token>
#>
param(
  [string]$Token     = "",   # vide = généré automatiquement via gh (recommandé)
  [string]$RepoUrl   = "https://github.com/user/Nokido",
  [string]$RunnerDir = "C:/laforge-runner",
  [string]$Version   = "2.321.0",   # cf https://github.com/actions/runner/releases
  [string]$Labels    = "self-hosted,nokido,windows"
)

$ErrorActionPreference = "Stop"

# Token : si non fourni, le générer via gh (auth GitHub CLI, indépendant du
# vault DPAPI — gh a sa propre auth). Token éphémère (~1h), non stocké.
if (-not $Token) {
  $slug = ($RepoUrl -replace '^https?://github.com/', '')
  Write-Host "Token non fourni -> génération via gh pour $slug ..."
  $Token = (gh api -X POST "repos/$slug/actions/runners/registration-token" --jq .token)
  if ($Token) { $Token = "$Token".Trim() }
  if (-not $Token) { throw "gh n'a pas pu générer le token (vérifie: gh auth status)" }
  Write-Host "Token obtenu (éphémère)."
}

New-Item -ItemType Directory -Force -Path $RunnerDir | Out-Null
Set-Location $RunnerDir

$zip = "actions-runner-win-x64-$Version.zip"
if (-not (Test-Path "./config.cmd")) {
  Write-Host "Téléchargement runner v$Version ..."
  Invoke-WebRequest -Uri "https://github.com/actions/runner/releases/download/v$Version/$zip" -OutFile $zip
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  [System.IO.Compression.ZipFile]::ExtractToDirectory((Resolve-Path $zip), (Get-Location))
}

Write-Host "Configuration (non-interactif) ..."
& ./config.cmd --url $RepoUrl --token $Token --labels $Labels --unattended --replace
if ($LASTEXITCODE -ne 0) { throw "config.cmd a échoué (token expiré ? régénère-le)" }

# Auto-démarrage. Service Windows (svc.cmd) = survit au reboot mais exige ADMIN.
# Sinon : tâche planifiée au logon (sans admin). Sinon : run.cmd manuel.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
          ).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)

if ((Test-Path "./svc.cmd") -and $isAdmin) {
  Write-Host "Installation comme service Windows (survit au reboot) ..."
  & ./svc.cmd install
  & ./svc.cmd start
  Write-Host "✅ Runner en service Windows."
}
elseif (Test-Path "./svc.cmd") {
  Write-Host "⚠ Service Windows = besoin d'ADMIN. Deux options :"
  Write-Host "   1) Relance dans un pwsh ADMIN -> service reboot-proof."
  Write-Host "   2) Maintenant, sans admin : cd $RunnerDir ; ./run.cmd"
}
else {
  Write-Host "svc.cmd absent -> tâche planifiée au logon (run.cmd, sans admin) ..."
  try {
    $action = New-ScheduledTaskAction -Execute "$RunnerDir/run.cmd"
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    Register-ScheduledTask -TaskName "NokidoActionsRunner" -Action $action -Trigger $trigger -Force | Out-Null
    Start-ScheduledTask -TaskName "NokidoActionsRunner"
    Write-Host "✅ Tâche 'NokidoActionsRunner' créée + démarrée (relance au logon)."
  } catch {
    Write-Host "⚠ Tâche planifiée échouée ($_). Lance manuellement : cd $RunnerDir ; ./run.cmd"
  }
}

Write-Host ""
Write-Host "Vérifie : GitHub -> Settings -> Actions -> Runners (statut 'Idle')."
Write-Host "Les jobs runs-on:[self-hosted] tourneront ici — 0 minute facturée."
Write-Host "⚠ Temporaire : retire-le quand billing réglé ou repo public."
