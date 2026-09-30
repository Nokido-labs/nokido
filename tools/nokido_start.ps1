#Requires -Version 5.1
# Nokido - Demarrage manuel de la flotte de services.
#
# Modele : la flotte Nokido* n'est PAS composee de services Windows -- ce sont des
# ENFANTS spawnes par le supervisor. `Get-Service 'Nokido*'` ne matche donc rien ;
# l'etat reel se lit sur http://127.0.0.1:8765/supervisor/status (cf. plus bas).
# Seul LaForge-Master est un vrai service Windows, demarre en Tier 0.
#
# LaForge-Master (supervisor :8765) demarre en premier : il possede NokidoMCP
# et orchestre les vagues. On demarre ensuite tout le reste sauf les services
# LOURDS / GATED que le supervisor ou l'utilisateur lance a la demande.
#
# -RelanceHub (2026-09-26) : second temps du restart hub garde. `nokido_stop.ps1
# -GarderHub` a arrete la flotte en laissant superviseur + hub debout ; ici, au Tier 0
# et APRES les preflights, LaForge-Master est redemarre. Il ne tient plus que le hub,
# qui tombe aussitot et revient ~9 s plus tard avec la flotte en vagues : sous les 15 s
# de reconnexion de Claude Code (5 essais, +0/+1/+2/+4/+8 s), le MCP se reconnecte seul.
param([switch]$RelanceHub)

if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    # Le drapeau doit SUIVRE l'elevation (meme regle que nokido_stop.ps1 -NoWait).
    $relArgs = "-ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($RelanceHub) { $relArgs += " -RelanceHub" }
    Start-Process powershell -ArgumentList $relArgs -Verb RunAs
    exit
}

$Host.UI.RawUI.WindowTitle = "Nokido - START"

# --- Instrumentation demarrage (2026-06-11) : "demarrage trop lent" -> tracer OU
# le temps part. Transcript complet + chrono cumulatif [+Xs] sur chaque ligne.
# Log horodate : logs/nokido_start_<ts>.log
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$LogDir = Join-Path (Split-Path -Parent $PSCommandPath) "..\logs"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }
$LogFile = Join-Path $LogDir ("nokido_start_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
try { Start-Transcript -Path $LogFile -Force | Out-Null } catch {}
function T { "{0,6:N1}s" -f $sw.Elapsed.TotalSeconds }

function Write-Step([string]$msg) { Write-Host "  [$(T)] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "  [$(T)] [OK] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  [$(T)] [!]  $msg" -ForegroundColor Yellow }
function Write-Fail([string]$msg) { Write-Host "  [$(T)] [X]  $msg" -ForegroundColor Red }

# Services NON demarres automatiquement par le bouton (lourds / gated / on-demand).
# Grounded : NokidoBrainWorkerRust = BSOD 0x119 DirectML iGPU (incident 2026-05-24),
# BrainWorkerCPU = variante (evite double brain worker), trainers = on-demand,
# LlamaNative = gate pool LLM (active via supervisor API plus bas),
# SelfPatcher = auto-modification de code (lancement delibere uniquement).
$Excluded = @(
    'LaForge-Master',           # demarre explicitement en Tier 0
    'NokidoBrainWorkerRust',
    'NokidoBrainWorkerCPU',
    'NokidoNightTrainer',
    'NokidoOfflineTrainer',
    'NokidoLlamaNative',
    'NokidoSelfPatcher'
)

Write-Host ""
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host "        Nokido - DEMARRAGE          " -ForegroundColor Cyan
Write-Host "=====================================" -ForegroundColor Cyan
Write-Host ""

# --- Preflight syntaxe (rend solide, incident 2026-06-16) : un .py casse sur disque
# (WIP non-committe / clobber multi-agent) charge au reboot fait fail-close le gate du
# hub SANS message -> le hub bind :8766 quand meme (l'import du gate est au runtime),
# donc le boot affichait "hub up" en vert pendant que TOUT appel etait GATE_DENIED.
# AST-compile app/ + tools/ AVANT la flotte -> rend la panne VISIBLE + PRECOCE. Non bloquant.
Write-Step "Preflight syntaxe (app/ + tools/)..."
$pyExe = "$env:USERPROFILE\miniforge3\python.exe"
# Derive du script, JAMAIS ecrit en dur : le chemin fige "...\Script python IA\Nokido\app"
# a survecu au renommage LaForge -> Nokido et faisait echouer tous les probes vault
# ("ModuleNotFoundError: No module named 'forge_machine_vault'"), donc NokidoLlamaNative
# skipped a chaque demarrage (incident 2026-08-12).
$AppDir = Join-Path (Split-Path -Parent $PSScriptRoot) "app"
$chkOut = & $pyExe "$PSScriptRoot\forge_boot_syntax_check.py" 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Ok "Syntaxe OK (aucun module casse)"
} else {
    Write-Fail "PREFLIGHT: $LASTEXITCODE module(s) Python CASSE(S) -> le hub va fail-close !"
    $chkOut | ForEach-Object { Write-Host "      $_" -ForegroundColor Red }
    Write-Host "  >>> CORRIGE ces fichiers : le hub montera mais le gate sera FERME (tous agents ejectes). <<<" -ForegroundColor Red
}
Write-Host ""

# --- Preflight volume RAG (2026-07-10) : LaForge/RAG est une JONCTION vers %NOKIDO_DATA%\
# (volume chiffre). V: absent -> la jonction pend -> forge_access_switches ne peut pas
# ouvrir RAG/embeddings.db -> le check GOUVERNE 'switches' RAISE -> gate fail-closed
# (forge_hub_gate.py:41). Le hub bind :8766 quand meme, donc le probe de port dit
# "hub up" en vert pendant que TOUT appel renvoie GATE_DENIED. Meme classe de
# faux-vert que le preflight syntaxe ci-dessus.
#
# 2026-08-12 : le montage ne vivait QUE dans la tache boot 'LaForge-VC-Boot', dont le
# wrapper etait genere sous C:\tmp (VOLATILE). Un nettoyage de C:\tmp l'a emporte ->
# la tache tournait sur un .cmd inexistant, plus aucun montage au boot, et ce lanceur
# se contentait de RALER puis de demarrer 14 services dans un hub fail-closed (= le mur
# d'erreurs a chaque demarrage). Le montage est desormais fait ICI aussi : ce script
# est deja eleve (RunAs en tete) et VeraCrypt exige l'elevation. Redondance voulue
# avec la tache boot : deux chemins independants, la panne de l'un ne coute plus rien.
Write-Step "Preflight volume RAG (V:)..."
# 2026-09-28 (decision owner, apres l'incident V:) : la cle de V: ne vit plus qu'au coffre
# RESERVE, lisible par SYSTEM seul. Ce lanceur tourne dans la session de l'owner : il ne lit
# plus la cle, il DECLENCHE la tache SYSTEM LaForge-VC-Boot (meme --mount, sous SYSTEM) et
# attend le volume. NR : tests/nr/test_demarrage_monte_v_par_system_nr.py.
if (-not (Test-Path -LiteralPath "%NOKIDO_DATA%\")) {
    Write-Warn "V: absent -> montage par la tache SYSTEM LaForge-VC-Boot"
    schtasks /run /tn "LaForge-VC-Boot" 2>&1 |
        ForEach-Object { Write-Host "         $_" -ForegroundColor DarkGray }
    $vcDebut = Get-Date
    while (-not (Test-Path -LiteralPath "%NOKIDO_DATA%\embeddings.db") -and ((Get-Date) - $vcDebut).TotalSeconds -lt 90) {
        Start-Sleep -Seconds 2
    }
    if (-not (Test-Path -LiteralPath "%NOKIDO_DATA%\embeddings.db")) {
        $vcResultat = (schtasks /query /tn "LaForge-VC-Boot" /v /fo list 2>&1 |
            Select-String "Dernier|Last Result|tat de la t|Scheduled Task State") -join " | "
        Write-Warn "montage par la tache NON abouti ($vcResultat) -- diagnostic sous SYSTEM : forge_at_rest_veracrypt --verifier-cle"
    }
}
if (Test-Path -LiteralPath "%NOKIDO_DATA%\embeddings.db") {
    Write-Ok "V: monte (embeddings.db present)"
    # 2026-09-01 : ce preflight validait la PRESENCE du volume, jamais la PLACE.
    # Incident du jour : V: sature (0 octet libre) et WAL a 53 Go apres trois
    # ingestions concurrentes -> 'disk I/O error' sur toute ecriture RAG, sidecar
    # de traces en quarantine, hub tombe deux fois. Un volume monte mais PLEIN
    # produit exactement la meme flotte verte-et-morte que V: absent -- meme
    # classe de faux-vert que les deux preflights ci-dessus.
    $walPath = "%NOKIDO_DATA%\embeddings.db-wal"
    $walGo = 0
    if (Test-Path -LiteralPath $walPath) {
        $walGo = [math]::Round((Get-Item -LiteralPath $walPath).Length / 1GB, 2)
    }
    $vol = Get-PSDrive V -ErrorAction SilentlyContinue
    $freeGo = if ($vol) { [math]::Round($vol.Free / 1GB, 2) } else { -1 }
    Write-Host "         V: libre $freeGo Go | WAL $walGo Go" -ForegroundColor DarkGray
    # Le boot est le SEUL moment ou personne ne tient la base : un TRUNCATE y rend
    # le fichier au disque, alors qu'en pleine journee un lecteur du hub le laisse
    # a busy=1 (mesure du 01/09 : 99,998 pourcent des pages versees, 0 octet rendu).
    if ($walGo -gt 2) {
        Write-Warn "WAL $walGo Go -> checkpoint TRUNCATE (aucun ecrivain au boot)"
        & $pyExe -c "import sqlite3; c=sqlite3.connect(r'%NOKIDO_DATA%\embeddings.db', timeout=900); print('checkpoint', c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()); c.close()" 2>&1 |
            ForEach-Object { Write-Host "         $_" -ForegroundColor DarkGray }
    }
    if ($freeGo -ge 0 -and $freeGo -lt 5) {
        Write-Fail "V: n'a plus que $freeGo Go libres -> les ecritures RAG vont echouer (disk I/O error)"
    }
} elseif (Test-Path -LiteralPath "%NOKIDO_DATA%\") {
    Write-Fail "V: monte mais embeddings.db ABSENT -> mauvais volume ? le gate hub va fail-close"
} else {
    # ARRET DUR : demarrer la flotte sans V: ne produit QUE des GATE_DENIED. Mieux vaut
    # une panne nette et lisible qu'une flotte entiere verte-mais-morte.
    Write-Fail "V: NON MONTE (montage auto en echec) -> TOUT appel hub serait GATE_DENIED"
    Write-Host "  >>> ARRET : demarrer la flotte maintenant ne produirait que des erreurs. <<<" -ForegroundColor Red
    Write-Host "  >>> Diag volume : LAFORGE_PYTHON tools\forge_at_rest_veracrypt.py --status" -ForegroundColor Red
    Write-Host "  >>> Diag tache  : LAFORGE_PYTHON tools\forge_install_boot_mount.py --status" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch {}
    Write-Host ""
    Read-Host "  Appuyer sur Entree pour fermer"
    exit 1
}
Write-Host ""

$started = 0; $skipped = 0; $failed = 0; $collisions = 0

function Start-Svc($svc, [int]$delay = 1) {
    if ($null -eq $svc) { return }
    if ($svc.Status -eq "Running") { Write-Ok "$($svc.Name) deja actif"; $script:started++; return }
    try {
        # -ErrorAction Stop : l'echec devient catchable (1 ligne propre, pas le
        # dump ErrorRecord 6 lignes). -WarningAction Silent : tue le spam
        # "Attente du demarrage...".
        Start-Service -Name $svc.Name -ErrorAction Stop -WarningAction SilentlyContinue
        if ($delay -gt 0) { Start-Sleep -Seconds $delay }
        $svc.Refresh()
        if ($svc.Status -eq "Running") { Write-Ok $svc.Name; $script:started++ }
        else { Write-Warn "$($svc.Name) -> $($svc.Status)"; $script:skipped++ }
    } catch {
        # Sur cette archi, les ENFANTS (hub/Deno/daemons) sont possedes par le
        # SUPERVISOR (LaForge-Master), pas par NSSM : Start-Service echoue par
        # DESIGN (port deja pris par l'enfant supervisor / entree NSSM legacy).
        # Pas une vraie panne -> affichage doux + compte en "gere", pas "echec".
        # Ce compteur ne mesure PAS ce que son nom laisse croire. Il ne s'incremente
        # QUE dans ce catch, c'est-a-dire quand un demarrage NSSM ECHOUE parce que
        # l'enfant appartient deja au supervisor. Un service que le supervisor a
        # correctement demarre est deja Running et compte en `started` (ligne 120).
        # Donc "0" signifie "aucune collision NSSM", PAS "le supervisor ne gere
        # rien" -- l'owner l'a legitimement lu a l'envers le 2026-08-12. L'etat reel
        # de possession se lit sur :8765/supervisor/status, pas ici.
        Write-Step "$($svc.Name) -> gere par le supervisor (skip NSSM)"; $script:collisions++
    }
}

# --- Preflight CI (2026-08-26) : redemarrer la flotte TUE un job CI en cours.
# Mesure : run 33016991626, worker mort a 21:49:15Z, ce script demarre a 21:49:32Z,
# job conclu 'failure' a 21:58:52Z avec l'etape 4 en conclusion VIDE -- elle n'a
# JAMAIS conclu. Aucun test rouge, aucun verdict : un rouge qui ne dit rien, et qui
# a fait chercher la panne dans le code pendant que la cause etait ici. Le worker
# n'existe QUE pendant un job : signal REELLEMENT emis, pas un drapeau qu'il
# faudrait que quelqu'un pense a poser.
# NOTE ENCODAGE : ce fichier est ASCII PUR. PS 5.1 le lit hors UTF-8, et un tiret
# cadratin ou un guillemet typographique y casse le parse (paye ici meme).
# Non bloquant : on attend, on n'interdit pas. NOKIDO_START_SKIP_CI_WAIT=1 passe outre.
$CiAttente = 180
if ($env:NOKIDO_START_SKIP_CI_WAIT -eq '1') { $CiAttente = 0 }
Write-Step "Preflight CI (job self-hosted en cours ?)..."
try {
    $w = @(Get-Process -Name 'Runner.Worker' -ErrorAction SilentlyContinue)
    if ($w.Count -gt 0 -and $CiAttente -gt 0) {
        Write-Warn "$($w.Count) job(s) CI en cours sur le runner - redemarrer MAINTENANT les tuerait"
        Write-Warn "  attente jusqu'a $CiAttente s (Ctrl+C pour passer outre, ou NOKIDO_START_SKIP_CI_WAIT=1)"
        $t0 = Get-Date
        while ((@(Get-Process -Name 'Runner.Worker' -ErrorAction SilentlyContinue)).Count -gt 0) {
            if (((Get-Date) - $t0).TotalSeconds -ge $CiAttente) {
                # On le DIT au lieu de partir en silence : le job va mourir, et le
                # rouge qui suivra n'aura rien a voir avec le code.
                Write-Warn "toujours en cours apres $CiAttente s - on continue, le job CI va etre coupe"
                break
            }
            Start-Sleep -Seconds 5
        }
        if ((@(Get-Process -Name 'Runner.Worker' -ErrorAction SilentlyContinue)).Count -eq 0) {
            Write-Ok "job CI termine - la flotte peut redemarrer sans le couper"
        }
    } elseif ($w.Count -gt 0) {
        Write-Warn "$($w.Count) job(s) CI en cours - attente desactivee, ils vont etre coupes"
    } else {
        Write-Ok "aucun job CI en cours"
    }
} catch {
    # Troisieme etat : ni "job en cours" ni "aucun" -- on n'a PAS PU regarder.
    Write-Warn "etat CI ILLISIBLE ($($_.Exception.Message)) - on continue sans garantie"
}

# --- Tier 0 : Supervisor (proprietaire exclusif de NokidoMCP) ---
Write-Step "Tier 0 - Supervisor LaForge-Master :8765"
$master = Get-Service -Name "LaForge-Master" -ErrorAction SilentlyContinue
if ($null -eq $master) {
    Write-Fail "LaForge-Master introuvable - flotte non geree, abandon"
} else {
    if ($RelanceHub -and $master.Status -eq 'Running') {
        Write-Step "Rebond du hub : arret de LaForge-Master (flotte deja arretee, il ne tient plus que le hub)"
        try {
            Stop-Service -Name "LaForge-Master" -Force -ErrorAction Stop -WarningAction SilentlyContinue
            Write-Ok "LaForge-Master arrete"
        } catch { Write-Warn ("arret LaForge-Master : " + (($_.Exception.Message -split "`r?`n")[0])) }
        # Sous Windows l'arret du superviseur ne passe pas toujours par son arret gracieux
        # (supervisor.ts, commentaire de l'orphan reaper) : un hub survivant tiendrait :8766
        # et le nouveau mourrait au bind. On n'arrete que ce qui ECOUTE sur :8766 ET dont la
        # ligne de commande est nokido_hub ; un autre occupant est nomme et epargne.
        foreach ($l in @(Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue)) {
            $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($l.OwningProcess)" -ErrorAction SilentlyContinue
            if ($p -and $p.CommandLine -like '*nokido_hub*') {
                try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Ok "hub survivant PID $($p.ProcessId) arrete" }
                catch { Write-Warn "hub survivant PID $($p.ProcessId) - $_" }
            } elseif ($p) {
                Write-Warn ":8766 tenu par PID $($p.ProcessId) ($($p.Name)) qui n'est pas nokido_hub - epargne"
            }
        }
        $master.Refresh()
    }
    Start-Svc $master 4
    # Le hub :8766 est spawne par le SUPERVISOR (process enfant), PAS par le
    # service NSSM "NokidoMCP" (qui reste Stopped par design). On sonde donc le
    # PORT reel, pas le statut du service (sinon faux "pas running"). Warmup
    # rag 7GB -> jusqu'a 60s.
    Write-Step "Attente hub :8766 (spawn par supervisor, warmup rag)..."
    $up = $false
    for ($i = 0; $i -lt 45; $i++) {
        try {
            $c = New-Object Net.Sockets.TcpClient
            $c.Connect("127.0.0.1", 8766); $c.Close(); $up = $true; break
        } catch { Start-Sleep -Seconds 2 }
    }
    # Un hub injoignable est un ECHEC, pas un avertissement : sans lui rien ne
    # repond. Le compter permet au verdict final de dire NON (2026-07-31 : $failed
    # n'etait incremente NULLE PART, donc la fenetre affichait toujours
    # "Nokido operationnel" en vert, hub down et flotte degradee comprises).
    if ($up) { Write-Ok "hub :8766 up" }
    else { Write-Fail "hub :8766 pas up apres 90s (verifier logs supervisor)"; $script:failed++ }
}

# --- Flotte : SPAWNEE par le supervisor (LaForge-Master), PAS des services Windows.
# Les enfants du supervisor (Nokido*) ne sont PAS des services Windows ; les
# services NSSM legacy sont restes 'LaForge*' (nom = etat externe non renomme).
# Donc `Get-Service 'Nokido*'` ne matchait RIEN -> "Demarre: 1" trompeur. On
# INTERROGE le supervisor :8765 pour l'etat REEL (le demarrage est deja fait par
# Master en Tier 0 ci-dessus).
Write-Host ""
Write-Host "  --- Flotte (etat reel via supervisor :8765) ---" -ForegroundColor DarkCyan
try {
    $sup = (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/supervisor/status -TimeoutSec 8).Content | ConvertFrom-Json
    $props = @($sup.services.PSObject.Properties)
    $counts = $props | Group-Object { $_.Value.status } | ForEach-Object { "{0}={1}" -f $_.Name, $_.Count }
    $run = @($props | Where-Object { $_.Value.status -eq 'running' }).Count
    $bad = @($props | Where-Object { $_.Value.status -in 'quarantine', 'down' } | ForEach-Object { $_.Name })
    Write-Ok ("Flotte {0} services : {1}" -f $props.Count, ($counts -join '  '))
    $script:started += $run
    if ($bad.Count) { Write-Fail ("DEGRADES: " + ($bad -join ', ')); $script:failed += $bad.Count } else { Write-Ok "0 quarantine / 0 down" }
} catch {
    Write-Warn ("supervisor :8765 injoignable pour l'etat flotte -- " + ($_.Exception.Message -split "`r?`n")[0])
}

# --- LlamaNative :8091 via supervisor pool (gate GPU, evite saturation) ---
Write-Host ""
Write-Host "  --- LLM gated ---" -ForegroundColor DarkCyan
Write-Step "Llama native :8091 via supervisor pool"
try {
    $tok = & $pyExe -c "import sys; sys.path.insert(0, r'$AppDir'); from forge_machine_vault import vault_get; print(vault_get('LAFORGE_SUPERVISOR_TOKEN') or vault_get('FORGE_MCP_TOKEN') or '')"
    if ([string]::IsNullOrWhiteSpace($tok)) {
        Write-Warn "NokidoLlamaNative skipped - vault token absent"
    } else {
        $r = Invoke-RestMethod -Method POST `
            -Uri http://127.0.0.1:8765/supervisor/llm/activate/NokidoLlamaNative `
            -Headers @{Authorization = "Bearer $tok"} -TimeoutSec 10
        if ($r.ok) { Write-Ok "NokidoLlamaNative activating"; $script:started++ }
        else { Write-Warn "NokidoLlamaNative activate refused: $($r | ConvertTo-Json -Compress)"; $script:skipped++ }
    }
} catch {
    # 'not in llm pool' / refus = ATTENDU : LlamaNative est on-demand/disabled
    # (gate GPU pool). Activation best-effort -> pas une vraie panne : skip doux,
    # pas de Echec (evite le faux "Certains services ont echoue").
    $emsg = ($_.Exception.Message -split "`r?`n")[0]
    # 2026-08-20 : ce 404 n'est PAS un incident. NokidoLlamaNative porte
    # disabled=true (mlock 7.1 Go au boot), donc supervisor.ts:656 ne l'instancie
    # pas dans `states`, et la route llm/activate teste `state?.def.llmPool` ->
    # 404 "not in llm pool", toujours. Reveil volontaire = la route
    # /supervisor/service/start/ (supervisor.ts:1726), qui porte le fix
    # wake-disabled. ATTENTION 2026-08-20 : j'avais ecrit /supervisor/start/ en recopiant
    # un COMMENTAIRE de services.toml sans lire le code -> cette route N'EXISTE
    # PAS (404). Un commentaire n'est pas une mesure.
    Write-Step "NokidoLlamaNative on-demand, NON reveille (mlock 7.1 Go, disabled=true) - reveil volontaire = POST :8765/supervisor/service/start/NokidoLlamaNative"; $script:skipped++
}

# --- Wheel probe mensuel (2026-07-18) : deplace du schtasks LaForge-WheelProbe (3h du
# mat, hub souvent down => notify CLAUDE perdu => tache jamais fired, rc=jamais-lance).
# Rattache ICI, en fin de demarrage : le hub :8766 est confirme up ($up), donc le notify
# aboutit. Garde de cadence 28j (latest.json) => reste "mensuel" meme si le lanceur tourne
# chaque jour. Detache (Start-Process) : ne bloque pas la fenetre. Idempotent : disable
# l'ancien schtasks (le lanceur est deja eleve). Reversible (Enable-ScheduledTask).
Write-Host ""
Write-Host "  --- Wheel probe (cp314t) ---" -ForegroundColor DarkCyan
try { Disable-ScheduledTask -TaskName "LaForge-WheelProbe" -ErrorAction SilentlyContinue | Out-Null } catch {}
if ($up) {
    $probeLatest = Join-Path $PSScriptRoot "..\sandbox\wheel_matrix_history\latest.json"
    $due = $true
    if (Test-Path -LiteralPath $probeLatest) {
        try {
            $snap = Get-Content -LiteralPath $probeLatest -Raw | ConvertFrom-Json
            # Skip seulement si <28j ET snapshot REEL (>=1 env sans "error"). Un
            # snapshot tout-en-erreur (mauvais HOME, env absent) ne DOIT PAS
            # verrouiller la sonde 28j -> on re-sonde au lieu de se croire "a jour".
            $hasReal = @($snap.envs.PSObject.Properties | Where-Object { -not $_.Value.error }).Count -gt 0
            if ($snap.ts -and $hasReal) {
                $due = (([DateTime]::UtcNow) - ([DateTime]::Parse($snap.ts)).ToUniversalTime()).TotalDays -ge 28
            }
        } catch { $due = $true }
    }
    if ($due) {
        # Token vault -> env herite par le process detache (sinon notify CLAUDE = 401).
        try {
            $probeTok = & $pyExe -c "import sys; sys.path.insert(0, r'$AppDir'); from forge_machine_vault import vault_get; print(vault_get('FORGE_MCP_TOKEN') or '')"
            if (-not [string]::IsNullOrWhiteSpace($probeTok)) { $env:FORGE_MCP_TOKEN = $probeTok.Trim() }
        } catch { Write-Warn "wheel probe: token vault indisponible (notify best-effort)" }
        # 2026-08-20 (decision owner) : plus AUCUN spawn hors supervision. Un one-shot
        # mensuel n'est pas un service, donc pas de fiche services.toml -- mais il passe
        # desormais par le hub, qui le GOUVERNE : cap RSS (famine memoire 2026-08-02),
        # cap log (211 Go ecrits par 3 jobs le 2026-07-28), et un job_id pollable au
        # lieu d'un process orphelin dont plus personne ne connait le sort.
        Write-Step "Wheel probe DUE (>=28j) -> job GOUVERNE par le hub"
        try {
            $wbody = @{ script = (Join-Path $PSScriptRoot 'forge_wheel_probe_monthly.py'); online = $true } | ConvertTo-Json -Compress
            $wr = Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8766/admin/run_job `
                -Headers @{Authorization = "Bearer $env:FORGE_MCP_TOKEN"} `
                -ContentType 'application/json' -Body $wbody -TimeoutSec 20
            if ($wr.ok) { Write-Ok "wheel probe job_id=$($wr.job_id) (cap RSS + cap log, poll job_status)" }
            else { Write-Warn "wheel probe refuse par le hub: $($wr | ConvertTo-Json -Compress)" }
        } catch {
            Write-Warn ("wheel probe non lance - " + ($_.Exception.Message -split "`r?`n")[0])
        }
    } else {
        Write-Ok "wheel probe pas du (<28j depuis dernier snapshot) - skip"
    }
} else {
    Write-Warn "hub :8766 down -> wheel probe reporte (notify echouerait)"
}

# --- Embed drain daemon (2026-07-18) : draine les chunks NULL hot-tier en continu via
# forge_embed_router :8099 (BGE-M3). Etait stale 22j (non boot-persistent) => le stall
# embed venait de la (fix deec1b20 = anti-poison microglie). Rattache ICI pour survivre
# au reboot. Idempotent : skip si heartbeat frais (<3min) pour ne pas doubler le daemon.
Write-Host ""
Write-Host "  --- Embed drain daemon ---" -ForegroundColor DarkCyan
if ($up) {
    $embedHb = Join-Path $PSScriptRoot "..\sandbox\embed_auto_trigger.heartbeat"
    $embedFresh = $false
    if (Test-Path -LiteralPath $embedHb) {
        try {
            $age = ([DateTime]::UtcNow - (Get-Item -LiteralPath $embedHb).LastWriteTimeUtc).TotalSeconds
            $embedFresh = $age -lt 180
        } catch {}
    }
    if ($embedFresh) {
        Write-Ok "embed daemon deja actif (heartbeat frais) - skip"
    } else {
        # 2026-08-20 (decision owner) : PLUS AUCUN daemon hors supervision. Le service
        # supervise EXISTE deja -- NokidoEmbedTrigger dans services.toml, args
        # tools/forge_embed_auto_trigger.py, deps 8099. Ce Start-Process le DOUBLAIT
        # hors du superviseur : donc hors autoregulation, hors quarantaine GPU, hors
        # comptage de flotte, et impossible a arreter par nokido_ensure_service (qui
        # rend success:true sans rien tuer sur un process non tenu par le supervisor).
        # /supervisor/service/start/ (supervisor.ts:1726) porte le fix wake-disabled
        # et sait reveiller un `disabled=true`. La forme SANS `service/` n'existe pas
        # et rend 404 : c'est ce qui a empeche le drain de demarrer le 2026-08-20.
        try {
            $dtok = & $pyExe -c "import sys; sys.path.insert(0, r'$AppDir'); from forge_machine_vault import vault_get; print(vault_get('LAFORGE_SUPERVISOR_TOKEN') or vault_get('FORGE_MCP_TOKEN') or '')"
            $dr = Invoke-RestMethod -Method POST `
                -Uri http://127.0.0.1:8765/supervisor/service/start/NokidoEmbedTrigger `
                -Headers @{Authorization = "Bearer $($dtok.Trim())"} -TimeoutSec 15
            if ($dr.ok) {
                # ACCEPTED n'est pas ACHIEVED. `$dr.ok` dit seulement que le superviseur
                # a PRIS la commande. Mesure du 2026-09-05 : cette ligne affichait
                # "[OK] embed drain SUPERVISE" alors que NokidoEmbedTrigger est
                # `disabled = true`, que son heartbeat etait ABSENT et que la cible :8099
                # ne repondait pas -- un drain qui ne draine rien, annonce en vert au
                # demarrage. On verifie donc l'EFFET, et on nomme les deux etages
                # separement : le drain tourne-t-il, et sa cible repond-elle ?
                Start-Sleep -Seconds 3
                $hbOk = Test-Path -LiteralPath $embedHb
                $tgtOk = Test-NetConnection -ComputerName 127.0.0.1 -Port 8099 `
                    -InformationLevel Quiet -WarningAction SilentlyContinue
                if ($hbOk -and $tgtOk) {
                    Write-Ok "embed drain ACTIF (pouls present, cible :8099 joignable)"
                } elseif ($hbOk) {
                    # Les embedders sont eteints PAR DECISION (boot-trim RAM) : c'est une
                    # politique, pas une panne -- donc un avertissement, jamais un echec.
                    Write-Warn "embed drain demarre mais CIBLE :8099 INJOIGNABLE (embedder eteint par politique) - rien ne sera vectorise"
                } else {
                    Write-Warn "embed drain ACCEPTE par le supervisor mais SANS POULS - pas demarre en fait"
                }
            }
            else { Write-Warn "embed drain refuse par le supervisor: $($dr | ConvertTo-Json -Compress)"; $script:failed++ }
        } catch {
            Write-Fail ("embed drain NON demarre - " + ($_.Exception.Message -split "`r?`n")[0])
            $script:failed++
        }
    }
} else {
    Write-Warn "hub :8766 down -> embed daemon reporte"
}

Write-Host ""
Write-Host "-------------------------------------" -ForegroundColor DarkGray
$color = if ($failed -gt 0) { "Yellow" } else { "Green" }
Write-Host "  Demarre : $started   Collision NSSM : $collisions   Ignore : $skipped   Echec : $failed" -ForegroundColor $color
Write-Host "  (exclus on-demand : $($Excluded -join ', '))" -ForegroundColor DarkGray
Write-Host ""

if ($failed -eq 0) {
    Write-Host "  Nokido operationnel." -ForegroundColor Green
    Write-Host "  Supervisor -> http://127.0.0.1:8765" -ForegroundColor DarkGray
    Write-Host "  Hub        -> http://127.0.0.1:8766" -ForegroundColor DarkGray
    Write-Host "  UI         -> http://127.0.0.1:7400" -ForegroundColor DarkGray
    Write-Host "  OAI        -> http://127.0.0.1:7777" -ForegroundColor DarkGray
    Write-Host "  Netcfg     -> http://127.0.0.1:7500" -ForegroundColor DarkGray
    Write-Host "  Ollama     -> http://127.0.0.1:11434" -ForegroundColor DarkGray
} else {
    Write-Host "  Certains services ont echoue. Verifier logs NSSM." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  Appuyer sur une touche pour fermer..." -ForegroundColor DarkGray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
