#Requires -Version 5.1
# Nokido - Arret manuel de la flotte.
#
# Enumeration DYNAMIQUE (Get-Service 'Nokido*') : arrete tout service reel sauf
# LaForge-Master + NokidoMCP, qu'on arrete en DERNIER et dans l'ordre (MCP avant
# Master, sinon Master tue son enfant -> conflit port 8766).
# Le nettoyage des orphelins Python est SCOPE a la cmdline Nokido (l'ancienne
# version faisait Get-Process python = kill machine-wide, tuant tout python
# interactif/jupyter/hook hors Nokido -> bug corrige).
#
# -GarderHub (2026-09-26) : restart full-stack SANS couper les clients MCP. Claude
# Code retente 5 fois en 15 s (+0/+1/+2/+4/+8 s) puis abandonne ; l'arret complet
# laissait le hub a terre ~4 min 20 (Tier 0 ici, puis tout le reste, 2e UAC,
# preflights, boot) => `/mcp` a la main. Avec -GarderHub le superviseur et le hub
# RESTENT DEBOUT : la flotte, faite de ses ENFANTS, s'arrete par SON API, puis les
# process externes comme d'habitude. Le hub rebondit ensuite seul, en ~9 s, dans
# `nokido_start.ps1 -RelanceHub`. Enchaine par le panneau (nokido_launcher, restart).

param([switch]$NoWait, [switch]$GarderHub)

# SENTINELLE DE FIN (2026-08-17) - pourquoi le Restart ne marchait pas.
# Ce script s'auto-eleve : l'appelant reprend la main DES la ligne `exit`
# ci-dessous, alors que le vrai arret ne fait que commencer dans une AUTRE
# fenetre. Et il se termine par une attente de touche : il ne rend jamais la
# main tout seul. Les deux Restart (nokido_restart.ps1 et le panneau ASCII)
# DEVINAIENT donc la fin de l'arret en sondant un port (20 s / 80 s) et
# lancaient le Start pendant que le Stop tuait encore -> flotte massacree.
# Seul le stop-puis-start MANUEL fonctionnait, parce que l'humain ferme la
# fenetre entre les deux : ce geste EST le signal de fin qui manquait.
# Desormais le Stop ecrit ce signal lui-meme, et `-NoWait` saute la touche.
$DoneFlag = Join-Path (Split-Path -Parent (Split-Path -Parent $PSCommandPath)) "sandbox\nokido_stop.done"
try { if (Test-Path $DoneFlag) { Remove-Item $DoneFlag -Force -ErrorAction Stop } } catch {}

if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    # Le drapeau doit SUIVRE l'elevation, sinon la copie elevee attend une
    # touche que personne ne tapera et la sentinelle n'arrive jamais.
    $relArgs = "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($NoWait) { $relArgs += " -NoWait" }
    if ($GarderHub) { $relArgs += " -GarderHub" }
    Start-Process powershell -ArgumentList $relArgs -Verb RunAs
    exit
}

$Host.UI.RawUI.WindowTitle = "Nokido - STOP"

function Write-Step([string]$msg) { Write-Host "  $msg" -ForegroundColor DarkYellow }
function Write-Ok([string]$msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  [!]  $msg" -ForegroundColor Yellow }
function Write-Fail([string]$msg) { Write-Host "  [X]  $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "=====================================" -ForegroundColor DarkYellow
Write-Host "          Nokido - ARRET            " -ForegroundColor DarkYellow
Write-Host "=====================================" -ForegroundColor DarkYellow
Write-Host ""

$stopped = 0; $skipped = 0; $failed = 0

function Stop-Svc([string]$name) {
    $s = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $s) { return }
    if ($s.Status -eq "Stopped") { Write-Step "$name deja arrete"; $script:skipped++; return }
    Write-Step "Arret $name..."
    try {
        Stop-Service -Name $name -Force
        $s.Refresh()
        Write-Ok $name; $script:stopped++
    } catch { Write-Fail "$name - $_"; $script:failed++ }
}

# multi_llm_daemon : process detache (pas service NSSM) -> kill par cmdline
Write-Host "  --- Daemon detache ---" -ForegroundColor DarkGray
$mlPids = (Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
           Where-Object { $_.CommandLine -like '*multi_llm_daemon*' }).ProcessId
foreach ($p in @($mlPids) | Where-Object { $_ }) {
    try { Stop-Process -Id $p -Force; Write-Ok "multi_llm_daemon PID=$p killed"; $stopped++ }
    catch { Write-Warn "multi_llm_daemon PID=$p - $_" }
}

# --- Flotte (dynamique) : tout Nokido* sauf Master/MCP, arret en premier ---
Write-Host ""
Write-Host "  --- Flotte (enumeration dynamique) ---" -ForegroundColor DarkGray
$fleet = Get-Service | Where-Object {
    ($_.Name -like 'Nokido*' -or $_.Name -eq 'gemini_poll_daemon') -and
    ($_.Name -ne 'LaForge-Master') -and ($_.Name -ne 'NokidoMCP')
} | Sort-Object Name
foreach ($svc in $fleet) { Stop-Svc $svc.Name }

# --- Tier 0 : MCP puis Master (ordre imperatif) ---
# Mode -GarderHub : la flotte supervisee s'arrete par l'API du superviseur, jamais par
# un kill -- un enfant tue de l'exterieur est RELANCE avec backoff (supervisor.ts,
# scheduleRestart) ; `service/stop` le marque `stopped` et il n'est pas relance. Ces
# marques vivent en MEMOIRE du superviseur : son redemarrage (start -RelanceHub) relance
# toute la flotte en vagues. Sans jeton ou sans superviseur joignable, garder le hub
# n'est pas possible proprement : on le DIT et on fait l'arret complet d'avant.
$hubPid = 0
if ($GarderHub) {
    Write-Host ""
    Write-Host "  --- Flotte supervisee : arret par l'API, hub + superviseur gardes ---" -ForegroundColor DarkGray
    $AppDir = Join-Path (Split-Path -Parent $PSScriptRoot) "app"
    $pyExe = "$env:USERPROFILE\miniforge3\python.exe"
    $garde = $false
    try {
        $supTok = & $pyExe -c "import sys; sys.path.insert(0, r'$AppDir'); from forge_machine_vault import vault_get; print(vault_get('LAFORGE_SUPERVISOR_TOKEN') or vault_get('FORGE_MCP_TOKEN') or '')" | Select-Object -Last 1
        $supTok = "$supTok".Trim()
        if ([string]::IsNullOrWhiteSpace($supTok)) { throw "jeton superviseur absent du coffre" }
        $etat = (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/supervisor/status -TimeoutSec 8).Content | ConvertFrom-Json
        $svcs = @($etat.services.PSObject.Properties)
        $hubSvc = @($svcs | Where-Object { $_.Name -eq 'NokidoMCP' })
        if ($hubSvc.Count -and $hubSvc[0].Value.pid) { $hubPid = [int]$hubSvc[0].Value.pid }
        # Vague la plus haute d'abord, comme l'arret gracieux du superviseur : les
        # consommateurs tombent avant ce qu'ils consomment.
        $cibles = @($svcs | Where-Object { ($_.Name -ne 'NokidoMCP') -and ($_.Value.status -ne 'stopped') } |
                    Sort-Object { [int]$_.Value.wave } -Descending)
        foreach ($c in $cibles) {
            try {
                $null = Invoke-RestMethod -Method POST -Uri ("http://127.0.0.1:8765/supervisor/service/stop/" + $c.Name) `
                    -Headers @{Authorization = "Bearer $supTok"} -TimeoutSec 10
                Write-Ok "$($c.Name) (vague $($c.Value.wave)) arrete par le superviseur"; $stopped++
            } catch {
                Write-Warn ("$($c.Name) - arret refuse : " + (($_.Exception.Message -split "`r?`n")[0])); $failed++
            }
        }
        $garde = $true
    } catch {
        Write-Warn ("hub NON gardable : " + (($_.Exception.Message -split "`r?`n")[0]) + " -> arret complet (reconnexion MCP a la main)")
    }
    if (-not $garde) { $GarderHub = $false }
}
Write-Host ""
if ($GarderHub) {
    Write-Host "  --- Tier 0 : GARDE (hub PID $hubPid + superviseur) - rebond au start -RelanceHub ---" -ForegroundColor DarkGray
} else {
    Write-Host "  --- Tier 0 : Hub + Supervisor ---" -ForegroundColor DarkGray
    Stop-Svc "NokidoMCP"
    Start-Sleep -Seconds 2
    Stop-Svc "LaForge-Master"
}

# --- Nettoyage orphelins Python SCOPE Nokido (pas machine-wide) ---
Write-Host ""
Write-Host "  --- Orphelins Python Nokido ---" -ForegroundColor DarkGray
# EXCLUSION nokido_tray : le tray n'est PAS un membre de la flotte, c'est l'UI
# qui permet de la relancer. Sa cmdline contient 'nokido' -> il tombait dans ce
# reaping et se faisait tuer a chaque stop. Pire : au demarrage, le tray declenche
# lui-meme un restart de la flotte quand :7400 est ferme, donc il se SUICIDAIT
# quelques secondes apres son lancement, sans laisser la moindre trace (kill, pas
# d'exception). C'est la regression qui rendait l'icone tray introuvable.
# EXCLUSION mcp_stdio_bridge : le pont stdio->HTTP est un ENFANT DU CLIENT (Claude
# Desktop, Claude Code, Gemini), pas un membre de la flotte. Il se reconnecte au hub
# par HTTP a chaque appel, donc il SURVIT a un restart du hub - mais pas a un kill.
# Mesure 2026-09-06 11:47:23 : ce reaping l'a tue pendant le restart de la stack et
# Claude Desktop a affiche "Server disconnected" ; seul un redemarrage de Desktop
# relance son pont. Meme famille que nokido_tray : sa cmdline contient 'nokido'.
# ---------------------------------------------------------------------------
# CONTRAT D'ARRET (2026-09-11) : un PID numerique n'est PAS une identite.
#
# Windows recycle les PID, et vite. Tuer un numero revient a parier que rien
# n'a change entre l'enumeration et le kill -- le meme pari que celui qui a
# fait declarer un job "running" apres un kill externe, et qui a abattu le pont
# stdio d'un CLIENT le 2026-09-06.
#
# La primitive existe DEJA cote Python (app/forge_process_identity.py, decision
# owner du 2026-08-21 : "plus jamais ps | grep python", identite = signature +
# registre pid/start_time). Ce script ne l'appelait pas : on porte ici la meme
# regle, avec les moyens de PowerShell -- creation time + ligne de commande.
# ---------------------------------------------------------------------------

function Stop-NokidoPid {
    <#
      Arrete UN process apres avoir verifie que c'est bien LUI.
      Trois issues, jamais deux :
        arrete            le process attendu a ete termine
        deja arrete       la cible est absente -> SUCCES (STOP idempotent)
        REFUSE            le PID existe mais ce n'est plus le process attendu
    #>
    param(
        [int]$CiblePid,              # PAS $Pid : variable automatique PowerShell
        $NeLe,                       # CreationDate relevee a l'enumeration
        [string]$Attendu,            # fragment de cmdline qui identifie la cible
        [string]$Etiquette = "process"
    )
    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$CiblePid" -ErrorAction SilentlyContinue
    if (-not $p) {
        Write-Step "$Etiquette PID $CiblePid deja arrete (STOP idempotent)"
        return $true
    }
    if ($NeLe -and $p.CreationDate -and ($p.CreationDate -ne $NeLe)) {
        Write-Warn "$Etiquette PID $CiblePid REFUSE - PID RECYCLE (ne le $($p.CreationDate), attendu $NeLe) : un process etranger occupe ce numero"
        return $false
    }
    if ($Attendu -and $p.CommandLine -and ($p.CommandLine -notlike "*$Attendu*")) {
        Write-Warn "$Etiquette PID $CiblePid REFUSE - identite differente de celle attendue"
        return $false
    }
    try {
        Stop-Process -Id $CiblePid -Force -ErrorAction Stop
        Write-Ok "$Etiquette PID $CiblePid arrete"
        return $true
    } catch {
        if ($_.FullyQualifiedErrorId -like "NoProcessFound*") {
            Write-Step "$Etiquette PID $CiblePid deja arrete (STOP idempotent)"
            return $true
        }
        Write-Warn "$Etiquette PID $CiblePid - $_"
        return $false
    }
}

function Get-NokidoDescendants {
    <#
      Descendance COMPLETE d'un ou plusieurs process racines.
      C'est ce qui remplace le balayage par classe de runtime : on arrete le
      proprietaire du lifecycle et les enfants qu'il POSSEDE, pas tout ce qui
      porte le meme nom d'executable sur la machine.
    #>
    param([int[]]$RootPids)
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
             Select-Object ProcessId, ParentProcessId, Name, CommandLine, CreationDate)
    $vus = @{}
    $file = New-Object System.Collections.Queue
    foreach ($r in $RootPids) { $file.Enqueue([int]$r) }
    while ($file.Count -gt 0) {
        $cur = [int]$file.Dequeue()
        if ($vus.ContainsKey($cur)) { continue }
        $vus[$cur] = $true
        foreach ($c in $all) {
            if ([int]$c.ParentProcessId -eq $cur) { $file.Enqueue([int]$c.ProcessId) }
        }
    }
    return @($all | Where-Object { $vus.ContainsKey([int]$_.ProcessId) })
}

# EXCLUSION nokido_launcher (2026-09-26) : le panneau de controle ORCHESTRE le restart --
# il lance ce stop, attend sandbox/nokido_stop.done, PUIS lance le start. Sa cmdline
# contient 'Nokido' : abattu ici, il mourait avant le start et la stack restait a terre.
# Meme famille que nokido_tray : une UI de l'owner, pas un membre de la flotte. Le tray
# lance aussi le panneau pour executer un redemarrage confirme par elicitation.
$orphans = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -and ($_.CommandLine -like '*Script python IA\Nokido*' -or $_.CommandLine -like '*nokido*') -and
    ($_.CommandLine -notlike '*nokido_tray*') -and
    ($_.CommandLine -notlike '*nokido_launcher*') -and
    ($_.CommandLine -notlike '*mcp_stdio_bridge*')
}
# JOBS DETACHES (run_job) : ils SURVIVENT au restart, full-stack compris (doctrine
# "detache, survit au restart" ; rappel owner 2026-09-26). Mesure du jour sur une CI
# en cours : le wrapper `sandbox\jobs\job_<id>_wrap.py` (compte LaForgeSbx*) et une part
# de sa descendance (pytest sous nokido_proof) portent 'Nokido' dans leur cmdline -> ce
# reaping les visait. On epargne chaque wrapper ET toute sa descendance, quel que soit le
# hub qui l'a lance : un job lance par un hub PRECEDENT n'est pas un descendant du hub garde.
$jobsGardes = @{}
$wrappers = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
              Where-Object { $_.CommandLine -match '(?i)[\\/]sandbox[\\/]jobs[\\/]job_[^\\/"]*_wrap\.py' })
if ($wrappers.Count -gt 0) {
    foreach ($g in @(Get-NokidoDescendants -RootPids @($wrappers | ForEach-Object { [int]$_.ProcessId }))) { if ($g) { $jobsGardes[[int]$g.ProcessId] = $true } }
    $avantJobs = @($orphans).Count
    $orphans = @($orphans | Where-Object { -not $jobsGardes.ContainsKey([int]$_.ProcessId) })
    Write-Step "jobs detaches : $($wrappers.Count) run_job epargne(s), $($avantJobs - $orphans.Count) process python gardes avec leur descendance"
}
# -GarderHub : le hub et ses descendants ne sont PAS des orphelins -- le superviseur les
# tient encore, et leur arret est le rebond de `nokido_start.ps1 -RelanceHub`.
if ($GarderHub -and $orphans) {
    $gardes = @{}
    if ($hubPid -gt 0) {
        foreach ($g in @(Get-NokidoDescendants -RootPids @($hubPid))) { if ($g) { $gardes[[int]$g.ProcessId] = $true } }
    }
    $avant = @($orphans).Count
    $orphans = @($orphans | Where-Object { (-not $gardes.ContainsKey([int]$_.ProcessId)) -and ($_.CommandLine -notlike '*nokido_hub*') })
    Write-Step "hub garde : $($avant - $orphans.Count) process python epargnes (hub PID $hubPid et sa descendance)"
}
if ($orphans) {
    foreach ($p in $orphans) {
        # Identite verifiee AVANT le kill : creation time releve a l'enumeration
        # ci-dessus, plus un fragment de cmdline. Entre l'enumeration et l'appel,
        # le PID a pu changer de proprietaire.
        $null = Stop-NokidoPid -CiblePid $p.ProcessId -NeLe $p.CreationDate `
                               -Attendu "python" -Etiquette "python Nokido"
        $stopped++
    }
} else {
    Write-Step "Aucun orphelin Python Nokido"
}

# --- Orphelins deno / node / netcfg-agent (incident 2026-06-03) ---
# Stop-Service sort le SERVICE mais le process peut survivre (detache, ou Master
# tue mal son enfant deno) -> il TIENT le port -> au prochain start, rebind
# impossible + service coince en "Paused". On reape ici, sinon recovery manuelle.
# deno = 100% Nokido sur cette machine (supervisor :8765 + proxies) -> tout.
# node/netcfg = scope cmdline Nokido (evite de tuer un node tiers).
# DANGER node : sur cette machine node.exe = Claude Code / Zed ACP
# (@zed-industries/claude-code-acp + @anthropic-ai/claude-agent-sdk) = la SESSION
# IA elle-meme, PAS Nokido. JAMAIS de blanket-kill node : ca tue l'agent en cours.
# Garder le scope cmdline strict (nokido|Script python IA).
Write-Host ""
Write-Host "  --- Orphelins deno / node / netcfg ---" -ForegroundColor DarkGray
$reaped = 0
# CHANGE le 2026-09-11 : ne plus tuer une CLASSE de runtime.
# L'ancienne version faisait `Get-Process deno | Stop-Process -Force`, en
# s'appuyant sur le commentaire ci-dessus (" deno = 100% Nokido sur cette
# machine "). C'est une hypothese d'ENVIRONNEMENT, vraie aujourd'hui et muette
# le jour ou un autre projet Deno sera installe -- exactement la meme
# imprudence que le filtre '*nokido*' qui a abattu le pont stdio d'un client.
# On arrete desormais le PROPRIETAIRE du lifecycle (le superviseur) et ses
# descendants POSSEDES, plus les deno dont la ligne de commande est Nokido.
$denoSup = @(Get-CimInstance Win32_Process -Filter "Name='deno.exe'" -ErrorAction SilentlyContinue |
             Where-Object { $_.CommandLine -match '(?i)supervisor\.ts' })
$denoCibles = @()
if ($denoSup) {
    $denoCibles = @(Get-NokidoDescendants -RootPids @($denoSup | ForEach-Object { [int]$_.ProcessId }) |
                    Where-Object { $_.Name -eq 'deno.exe' })
}
$denoCibles += @(Get-CimInstance Win32_Process -Filter "Name='deno.exe'" -ErrorAction SilentlyContinue |
                 Where-Object { $_.CommandLine -match '(?i)proxy_deno|nokido|Script python IA' })
$denoVus = @{}
if ($GarderHub -and $denoSup) {
    # Le superviseur est GARDE : il tient le hub. Son arret est le rebond du start ; ses
    # proxies deno, eux, ont ete arretes par son API plus haut.
    foreach ($sp in $denoSup) { $denoVus[[int]$sp.ProcessId] = $true }
    Write-Step "superviseur deno garde (PID $(@($denoSup | ForEach-Object { $_.ProcessId }) -join ', '))"
}
foreach ($d in $denoCibles) {
    if (-not $d) { continue }
    if ($denoVus.ContainsKey([int]$d.ProcessId)) { continue }
    $denoVus[[int]$d.ProcessId] = $true
    $null = Stop-NokidoPid -CiblePid $d.ProcessId -NeLe $d.CreationDate `
                           -Attendu "deno" -Etiquette "deno Nokido"
    $stopped++; $reaped++
}
$denoEtrangers = @(Get-CimInstance Win32_Process -Filter "Name='deno.exe'" -ErrorAction SilentlyContinue |
                   Where-Object { -not $denoVus.ContainsKey([int]$_.ProcessId) })
if ($denoEtrangers.Count -gt 0) {
    Write-Step "$($denoEtrangers.Count) process deno EPARGNE(S) - hors flotte Nokido (ni descendant du superviseur, ni cmdline Nokido)"
}
$extra = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -match '(?i)netcfg') -or
    ($_.Name -eq 'node.exe' -and $_.CommandLine -match '(?i)nokido|Script python IA')
}
# Un job detache peut lancer node (playwright des gates UI) : sa descendance reste gardee.
$extra = @($extra | Where-Object { $_ -and -not $jobsGardes.ContainsKey([int]$_.ProcessId) })
foreach ($p in @($extra) | Where-Object { $_ }) {
    try { Stop-Process -Id $p.ProcessId -Force; Write-Ok "Kill $($p.Name) PID $($p.ProcessId)"; $stopped++; $reaped++ }
    catch { Write-Warn "$($p.Name) PID $($p.ProcessId) - $_" }
}
if ($reaped -eq 0) { Write-Step "Aucun orphelin deno/node/netcfg" }

# --- Ollama (inference locale :11434) ---
# Absent jusqu'ici => survivait a chaque stop. Pas un service NSSM : app user
# lancee au login (ollama app.exe tray) qui spawn ollama.exe serve +
# ollama_llama_server.exe (runner modele). On coupe le service eventuel PUIS
# tous les process ollama* (tray d'abord empeche le respawn du serve).
Write-Host ""
Write-Host "  --- Ollama ---" -ForegroundColor DarkGray
foreach ($s in @(Get-Service -Name 'Ollama*' -ErrorAction SilentlyContinue) | Where-Object { $_ }) { Stop-Svc $s.Name }
$ollamaProcs = Get-Process -Name 'ollama*' -ErrorAction SilentlyContinue
if ($ollamaProcs) {
    foreach ($p in $ollamaProcs) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction Stop; Write-Ok "Kill $($p.Name) PID $($p.Id)"; $stopped++ }
        catch { if ($_.FullyQualifiedErrorId -like "NoProcessFound*") { Write-Step "$($p.Name) PID $($p.Id) deja arrete" } else { Write-Warn "$($p.Name) PID $($p.Id) - $_" } }
    }
} else { Write-Step "Ollama deja arrete" }

# --- Runners llama.cpp (llama-server.exe) --- (2026-07-21)
# Trou constate : non couverts par le motif 'ollama*' ci-dessus. Sur cette
# machine les runners s'appellent llama-server.exe, PAS ollama_llama_server.exe
# (cf. commentaire ligne ~113, faux ici) :
#   - %USERPROFILE%\llama-vulkan\  -> services Nokido :8099 (embed bge-m3)
#                                       et :8100 (reranker bge-v2-m3)
#   - ...\Ollama\lib\ollama\         -> runner modele spawne par ollama.exe
# Enfants du supervisor spawnes SANS Job Object => survivent a la mort du
# parent et gardent port + VRAM jusqu'au reboot (mesure : 3 process, 1948 Mo).
# SCOPE par chemin d'exe : un llama.cpp tiers hors de ces 2 arbos est epargne.
Write-Host ""
Write-Host "  --- Runners llama.cpp ---" -ForegroundColor DarkGray
$llamaProcs = Get-CimInstance Win32_Process -Filter "Name='llama-server.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and ($_.ExecutablePath -like '*llama-vulkan*' -or $_.ExecutablePath -like '*\Ollama\lib\*') }
if ($llamaProcs) {
    foreach ($p in $llamaProcs) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Ok "Kill llama-server PID $($p.ProcessId)"; $stopped++ }
        catch { if ($_.FullyQualifiedErrorId -like "NoProcessFound*") { Write-Step "llama-server PID $($p.ProcessId) deja arrete" } else { Write-Warn "llama-server PID $($p.ProcessId) - $_" } }
    }
} else { Write-Step "Aucun runner llama.cpp" }

# --- Wrappers NSSM bloques ---
Write-Host ""
Write-Host "  --- Wrappers NSSM bloques ---" -ForegroundColor DarkGray
$nssmProcs = Get-Process -Name "nssm" -ErrorAction SilentlyContinue
if ($GarderHub) {
    # LaForge-Master TOURNE sous nssm.exe (parent du superviseur deno, mesure 2026-09-26) :
    # tuer les wrappers abattrait le superviseur et le hub gardes.
    Write-Step "wrappers NSSM epargnes : hub garde (LaForge-Master en est un)"
} elseif ($nssmProcs) {
    foreach ($p in $nssmProcs) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction Stop; Write-Ok "Kill nssm.exe PID $($p.Id)"; $stopped++ }
        catch { if ($_.FullyQualifiedErrorId -like "NoProcessFound*") { Write-Step "nssm.exe PID $($p.Id) deja arrete" } else { Write-Warn "nssm.exe PID $($p.Id) - $_" } }
    }
} else { Write-Step "Aucun wrapper NSSM bloque" }

# --- Docker (on-demand depuis 2026-06-01 : keeper en monitor-only) ---
# Arreter Nokido coupe aussi Docker Desktop : il n'est plus force au boot,
# il est relance a la demande par les consommateurs (Exegol/CTF via ensure_docker).
Write-Host ""
Write-Host "  --- Docker Desktop ---" -ForegroundColor DarkGray
$dockerProcs = Get-Process -Name "Docker Desktop", "com.docker.backend", "com.docker.build" -ErrorAction SilentlyContinue
if ($dockerProcs) {
    foreach ($p in $dockerProcs) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction Stop; Write-Ok "Kill $($p.Name) PID $($p.Id)"; $stopped++ }
        catch { if ($_.FullyQualifiedErrorId -like "NoProcessFound*") { Write-Step "$($p.Name) PID $($p.Id) deja arrete" } else { Write-Warn "$($p.Name) PID $($p.Id) - $_" } }
    }
} else { Write-Step "Docker deja arrete" }

Write-Host ""
Write-Host "-------------------------------------" -ForegroundColor DarkGray
$color = if ($failed -gt 0) { "Yellow" } else { "Green" }
Write-Host "  Arrete : $stopped   Deja stop : $skipped   Echec : $failed" -ForegroundColor $color
Write-Host ""
if ($failed -eq 0) { Write-Host "  Nokido arrete proprement." -ForegroundColor Green }
else { Write-Host "  Certains services resistent. Verifier logs NSSM." -ForegroundColor Yellow }
if ($GarderHub) { Write-Host "  Hub + superviseur GARDES : le hub rebondit au start (nokido_start.ps1 -RelanceHub)." -ForegroundColor Cyan }

# Signal de fin REELLE : ecrit APRES le dernier kill, avant toute attente
# humaine. C'est ce que les Restart attendent pour lancer le Start.
try {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $DoneFlag) | Out-Null
    (Get-Date).ToString("o") | Set-Content -Path $DoneFlag -Encoding UTF8
    Write-Host "  [fin] signal ecrit : $DoneFlag" -ForegroundColor DarkGray
} catch { Write-Host "  [!] signal de fin NON ecrit : $_" -ForegroundColor Yellow }

if (-not $NoWait) {
    Write-Host ""
    Write-Host "  Appuyer sur une touche pour fermer..." -ForegroundColor DarkGray
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
}
