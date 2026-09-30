# Nokido — Plan de remediation NSSM services

> Source : `tools/SERVICES.md` section "Anomalies / TODO" (5 items).
> Auteur : audit 2026-05-02. Toutes les commandes admin supposent
> `$NSSM = "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"`.
> `Set-Service` natif Windows fonctionne aussi pour StartupType / status.

## Tableau synthese

| # | Anomalie | Decision | Risque | Effort |
|---|---|---|---|---|
| 1 | NokidoDenoHubMCP (8769) vs LaForgeMCP (8766) | KEEP both — migration phase B.2 | LOW | 0 (doc) |
| 2 | NokidoDenoWebHub (7401) vs NokidoWebHub (7400) | KEEP both — migration phase B.1 | LOW | 0 (doc) |
| 3 | NokidoHomeostasis sur 3.12 alors que 4 autres sur py314 | RECONFIGURE Homeostasis vers py314 | LOW | 15 min |
| 4 | NokidoLlamaRouter port non documente | DOC ONLY — port = 8092 | LOW | 0 |
| 5 | Tous services en LocalSystem | RECONFIGURE vers `user` (necessite mot de passe) | MED | 30 min + auth |

Plus gros risque : item 5 (passage LocalSystem -> compte user, peut casser
acces aux fichiers UMA/blobs Ollama si ACL pas heritees).
Plus gros gain rapide : item 4 (juste mettre a jour SERVICES.md, port deja
present dans le bat).

---

## #1 — NokidoDenoHubMCP (8769) vs LaForgeMCP (8766)

### Investigation

- `tools/nokido_deno_hub_mcp.bat` lance `proxy_deno/hub_mcp/main.ts` sur
  `:8769` via Deno (ENV `LAFORGE_DENO_HUB_PORT=8769`).
- En-tete du `main.ts` (ligne 4) : *"Port :8768 (parallele au Python :8766
  — switch quand valide)"* / *"Phase B.2"*.
- Le commentaire dit 8768 mais le bat impose 8769 (drift mineur). Bat fait
  foi.
- Le hub Deno **delegue** l'execution des tools au Python via subprocess
  `forge_dispatchers` / `forge_trajectory.dispatch_intent`. Python reste
  source de verite.

### Decision : KEEP both

Ce n'est PAS un doublon — c'est une migration progressive Python -> Deno.
Le but est d'isoler la couche transport HTTP/MCP en Deno (sandbox
permissions natif) tout en gardant le coeur Python.

Action : aligner le commentaire bat -> 8769 dans `main.ts` (cosmetique),
et mettre a jour `tools/SERVICES.md` pour preciser le statut de migration.

### Snippet (admin ou non — pas de NSSM touch)

```powershell
# Verification visuelle des deux services
$NSSM = "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"
& $NSSM get LaForgeMCP Application
& $NSSM get NokidoDenoHubMCP Application

# Si on veut prouver isolation : tester health des deux
Invoke-RestMethod http://127.0.0.1:8766/health
Invoke-RestMethod http://127.0.0.1:8769/health
```

### Rollback

Aucun changement -> aucun rollback. Si on decide plus tard d'arreter
NokidoDenoHubMCP :

```powershell
Stop-Service NokidoDenoHubMCP
Set-Service NokidoDenoHubMCP -StartupType Manual
# Pour suppression complete :
& $NSSM remove NokidoDenoHubMCP confirm
```

---

## #2 — NokidoDenoWebHub (7401) vs NokidoWebHub (7400)

### Investigation

- `proxy_deno/web_hub/main.ts` ligne 4 : *"Phase B.1 - parallele au Python
  :7400 — switch quand valide"*.
- Endpoints portes : `/health`, `/api/opsec/*`, `/api/anatomy/state`,
  `/anatomy`, `/api/events/*`. Lecture state.json + SQLite read-only,
  delegation mutations a Python via subprocess.
- Meme pattern que #1 — migration phase B.1 deliberee.

### Decision : KEEP both

Idem #1. Pas de doublon. Documenter explicitement comme "staging Deno"
dans `tools/SERVICES.md` pour eviter audits futurs qui se reposent la
question.

### Snippet

```powershell
# Smoke test parallele
Invoke-RestMethod http://127.0.0.1:7400/health
Invoke-RestMethod http://127.0.0.1:7401/health
```

### Rollback

Aucun. Pour decommissionner Deno plus tard, voir snippet #1.

---

## #3 — NokidoHomeostasis sur 3.12 alors que 4 autres sur py314

### Investigation

- `app/forge_homeostasis_orchestrator.py` : top-level imports = **stdlib
  uniquement** (`argparse`, `json`, `os`, `sys`, `time`, `datetime`,
  `pathlib`).
- Imports forge_* differes (lazy) dans methodes — donc compatibilite
  py314 depend des sous-modules charges.
- Sous-modules invoques : `forge_health_diagnostic`,
  `forge_pluripotent_workers`, `forge_coagulation_cascade`,
  `forge_immune_adaptive`, `forge_hebbian_linker`, `forge_skill_enricher`,
  `forge_renal_clearance`, `forge_tool_efficiency`.
- `docs/python_version_matrix.md` : `forge_hebbian_linker` deja **valide
  3.14** + py314 site-packages contient `torch`, `psutil`, `onnxruntime`.
- Pas de dep `netmiko` / `paramiko` / `pythonnet` dans la chaine
  homeostasis.

### Decision : (a) MIGRER Homeostasis vers laforge_py314

Justification : 1 service a bouger vs 4 services a downgrader. Moins de
deps a verifier. Aligne avec roadmap Phase 6 cognitive (deja py314).
Si un sous-module forge_* a un probleme py314, c'est un bug RAG/cognitive
a corriger de toute facon — autant le decouvrir maintenant.

### Snippet (admin)

```powershell
$NSSM = "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"
$PY314 = "~\miniforge3\envs\laforge_py314\python.exe"

# 1. Smoke test prealable (NON-DESTRUCTIF)
$env:PYTHONNOUSERSITE = "1"
& $PY314 -c "import sys; sys.path.insert(0, r'~\Script python IA\Nokido\app'); import forge_homeostasis_orchestrator; print('OK')"

# 2. Si OK, stop service
Stop-Service NokidoHomeostasis

# 3. Switch interpreter
& $NSSM set NokidoHomeostasis Application $PY314

# 4. Forcer PYTHONNOUSERSITE pour eviter pollution user-site (cf. CLAUDE.md sec 11)
& $NSSM set NokidoHomeostasis AppEnvironmentExtra "PYTHONNOUSERSITE=1"

# 5. Restart + monitoring 5 min
Start-Service NokidoHomeostasis
Start-Sleep -Seconds 30
Get-Service NokidoHomeostasis
Get-Content "~\Script python IA\Nokido\logs\NokidoHomeostasis.stderr.log" -Tail 30
```

### Rollback

```powershell
Stop-Service NokidoHomeostasis
& $NSSM set NokidoHomeostasis Application "~\miniforge3\python.exe"
& $NSSM set NokidoHomeostasis AppEnvironmentExtra ""
Start-Service NokidoHomeostasis
```

---

## #4 — NokidoLlamaRouter port non documente

### Investigation

`tools/nokido_llamacpp_router.bat` ligne 18 :

```
set "PORT=8092"
```

Port = **8092**. Llama-server multi-modeles avec `--models-max 2` et
`--models-autoload`. Coexiste avec NokidoLlamaNative sur :8091.

### Decision : DOC ONLY

Aucun changement service. Mettre a jour `tools/SERVICES.md` :

| **NokidoLlamaRouter** | Auto | bat -> llama-server | `tools/nokido_llamacpp_router.bat` | **8092** |

### Snippet

```powershell
# Verification live (le service doit etre Up)
Invoke-RestMethod http://127.0.0.1:8092/health
```

### Rollback

Aucun (changement doc seulement).

---

## #5 — Tous services en LocalSystem (overprivilege)

### Investigation

NSSM par defaut installe les services en `LocalSystem` (SID
`S-1-5-18`) qui a privileges quasi-root sur la machine. Surface d'attaque
maximale si un service est compromis (ex : NokidoLlamaRouter qui expose
HTTP avec WebUI, ou NokidoDenoProxy qui a `--allow-net --allow-run`).

Compte cible : `DESKTOP-XXXX\user` (utilisateur courant). Privileges
limites a son profil. Acces au RAG/embeddings.db, miniforge3, blobs
Ollama deja heritables car fichiers proprietaires de user.

### Decision : RECONFIGURE vers compte user `user` [REQUIRES PASSWORD]

Ne PAS executer en auto. Necessite :
1. Mot de passe Windows local de user.
2. Verification ACL sur `LaForge/RAG/`, `LaForge/logs/`, blobs Ollama
   (`%USERPROFILE%\.ollama\models\blobs\*`), llama-vulkan binary.
3. Test 1 service pilote (recommande : NokidoRSSWatcher, faible impact)
   AVANT de migrer le hub.

### Snippet (admin) — A LANCER MANUELLEMENT [REQUIRES PASSWORD]

```powershell
$NSSM = "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm.exe"
$ACCOUNT = ".\user"   # ou "$env:COMPUTERNAME\user"
# REQUIRES PASSWORD : remplacer <password> par mot de passe Windows local
$PWD_PLAIN = "<password>"

# PILOTE : 1 service faible impact
Stop-Service NokidoRSSWatcher
& $NSSM set NokidoRSSWatcher ObjectName $ACCOUNT $PWD_PLAIN
Start-Service NokidoRSSWatcher
Start-Sleep -Seconds 30
Get-Service NokidoRSSWatcher       # doit etre Running
Get-Content "~\Script python IA\Nokido\logs\NokidoRSSWatcher.stderr.log" -Tail 20

# Si OK apres 30 min sans crash, etendre :
$SERVICES = @(
    "LaForgeMCP","NokidoWebHub","NokidoDenoHubMCP","NokidoDenoProxy",
    "NokidoDenoWebHub","NokidoLlamaNative","NokidoLlamaRouter",
    "NokidoAutonomousLoops","NokidoGeminiDaemon","NokidoGraph",
    "NokidoHebbian","NokidoHomeostasis"
)
foreach ($s in $SERVICES) {
    Stop-Service $s -ErrorAction SilentlyContinue
    & $NSSM set $s ObjectName $ACCOUNT $PWD_PLAIN
    Start-Service $s
    Start-Sleep -Seconds 5
}
```

### Rollback

Pour un service :

```powershell
Stop-Service NokidoRSSWatcher
& $NSSM set NokidoRSSWatcher ObjectName LocalSystem
Start-Service NokidoRSSWatcher
```

Pour tous :

```powershell
foreach ($s in $SERVICES) {
    Stop-Service $s -ErrorAction SilentlyContinue
    & $NSSM set $s ObjectName LocalSystem
    Start-Service $s
}
```

### Pre-flight ACL check (avant migration)

```powershell
# Verifier que user a R/W sur les paths critiques
$PATHS = @(
    "~\Script python IA\Nokido\RAG\embeddings.db",
    "~\Script python IA\Nokido\logs",
    "~\.ollama\models\blobs",
    "~\miniforge3\python.exe",
    "~\llama-vulkan\llama-server.exe"
)
foreach ($p in $PATHS) {
    Get-Acl $p | Format-List Path, Owner
}
```

Si l'owner est `NT AUTHORITY\SYSTEM` ou `Administrators`, faire un
`icacls $p /grant user:(M)` avant de switcher l'ObjectName.

---

## Annexe — Mise a jour `tools/SERVICES.md`

Modifications a appliquer (hors scope de ce doc, mais a tracker) :

1. Ligne 16 (NokidoLlamaRouter) : remplacer `?` par `8092`.
2. Ligne 70 : ajouter sous-section `**Port** : 8092 (OpenAI-compat,
   multi-modeles autoload, max 2)`.
3. Section "Anomalies / TODO" : marquer #4 comme **RESOLU** (port
   documente) une fois la modif faite.
4. Ajouter mention "phase B.1/B.2 migration Python -> Deno staging" pour
   #1 et #2 pour clarifier qu'il ne s'agit PAS de doublons accidentels.
