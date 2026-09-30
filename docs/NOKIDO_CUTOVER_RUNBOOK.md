# Runbook de cutover Nokido → Nokido (renommage profond / infra)

> **Rôle.** Ce document est exécuté **par l'owner (user)** en session privilégiée.
> L'assistant l'a rédigé et le pilote (explique, vérifie les sorties) mais **n'exécute
> rien sur le live** : le cutover casse le binding MCP de la session de l'assistant au
> restart (l'id-mcp `laforge-sovereign-hub` disparaît). Zéro autonome sur le live.
>
> **Statut prérequis (déjà livrés, branche `alpha`) :**
> - Renommage prose/UI/pycode/pystr : FAIT (voir `nokido_rename_project_2026-07-08`).
> - Shim env dual-read `app/forge_env_alias.py` : câblé dans le hub (commit 60c8f267) —
>   miroir `LAFORGE_`↔`NOKIDO_` au boot, donc les 2 jeux de variables marchent.
> - RBAC `wrk_nokido` seedé miroir de `wrk_laforge` (commit 6a8bd95e), `TRUSTED_EXECUTORS`
>   accepte les deux.
> - Outil renommage profond `tools/nokido_deep_rename.py` (déterministe, case-preserving,
>   garde `forge_`, protège le dossier submodule `LaForge/`) — vérifié en worktree isolé :
>   2010 fichiers / 117 renames / **0 import cassé**.
> - Helper migration runtime-state `tools/nokido_cutover_migrate.py` (commit 4b400cf6).

## Invariants — NE PAS violer
1. **Garder `forge_`** : `forge_*` ne contient pas "laforge" → jamais renommé (substring).
2. **Garder le dossier `LaForge/`** : le nom physique du submodule reste `LaForge/`
   (chemins durs `Script python IA\LaForge` préservés — protégés par `DIR_SEG` + fixup).
3. **Fallback `Agent-Name` = pont** : le hub lit `LaForge-Agent-Name` **ou** `Agent-Name`
   **ou** `X-Agent-Name` (`nokido_hub.py:705`). Après renommage il lira `Nokido-Agent-Name`
   ou `Agent-Name` ou `X-Agent-Name`. Le générique `Agent-Name` marche des deux côtés →
   c'est le pont de transition côté clients.
4. **Additif d'abord, suppression après** : `wrk_laforge` **reste** (ring-0 vivant). On
   ajoute `wrk_nokido`, on ne retire rien tant que le live n'a pas basculé et validé.
5. **Coordonner** : quiescer les surfaces autonomes (cowork/daemons) avant, annoncer au
   blackboard. Aucun `git add -A`.

## Point de rollback
- **HEAD alpha avant cutover** : `git -C "…/LaForge" rev-parse alpha` → noter le hash `H0`.
- **Backup DB** : `RAG/embeddings.db` copié vers `D:\backup\embeddings.db.pre-nokido`.
- **Backup .env** : `Nokido.env` (+ `.secrets`) copiés.
- **Export NSSM** : dump des services avant reconfig (Phase 3).
Rollback = `git reset --hard H0` + restaurer DB/.env/NSSM/schtasks/configs clients (§ Rollback).

---

## Phase 0 — Snapshot & quiescence (privilégié)
```powershell
# 0.1 Noter le point de reprise
$H0 = git -C "%NOKIDO_WORKSPACE%\LaForge" rev-parse alpha
$H0 | Out-File "D:\backup\nokido_cutover_H0.txt"

# 0.2 Backups froids
Copy-Item "%NOKIDO_WORKSPACE%\LaForge\RAG\embeddings.db" "D:\backup\embeddings.db.pre-nokido"
Copy-Item "%NOKIDO_WORKSPACE%\LaForge\LaForge.env" "D:\backup\LaForge.env.pre-nokido"
if (Test-Path "%NOKIDO_WORKSPACE%\LaForge\LaForge.env.secrets") { Copy-Item "%NOKIDO_WORKSPACE%\LaForge\LaForge.env.secrets" "D:\backup\" }

# 0.3 Inventorier l'existant (noms EXACTS pour Phase 3)
Get-Service | Where-Object { $_.Name -match 'nokido|nokido' } | Select Name,Status,StartType | Format-Table -Auto
schtasks /query /fo LIST | Select-String 'TaskName:' | Select-String 'aforge|okido'
foreach ($s in (Get-Service | ? { $_.Name -match 'laforge' })) { nssm dump $s.Name | Out-File "D:\backup\nssm_$($s.Name).txt" }

# 0.4 Quiescer les surfaces autonomes (éviter le clobber pendant le cutover)
#   - Arrêter les tâches cowork/daemons planifiées (schtasks /change /disable ...).
#   - Fermer les sessions Gemini/agy actives.
#   - Annoncer au blackboard : zone tree_locks, key=OWNER, "cutover Nokido — freeze".
```
**GATE 0** : backups présents (DB > 0 octet, .env copié), `H0` noté, inventaire capturé,
autre surface = zéro. Sinon STOP.

---

## Phase 1 — Renommage code (in-tree, déterministe)
Le tool `nokido_deep_rename.py` est **committé et validé en worktree isolé** (protection
FUNC_STR **défaut-on** : préserve env NSSM / conteneurs docker / tâches / logs / RBAC /
id-mcp — leur rename est STAGÉ, cf Phase +N). On le lance sur le live via `trusted_script`
(privilégié). Séquence : baseline → dry → apply → verify.

```powershell
$PY   = "%USERPROFILE%\miniforge3\python.exe"
$ROOT = "%NOKIDO_WORKSPACE%/LaForge"

# 1.0 BASELINE landmines — capturer les counts KEEP AVANT
& $PY "$ROOT/tools/nokido_cutover_verify.py" --root "$ROOT"

# 1.1 DRY — inspecter le plan, attendu ~1716 fichiers / ~90 renames (protégé)
& $PY "$ROOT/tools/nokido_deep_rename.py" --root "$ROOT"

# 1.2 APPLY (protection défaut-on ; JAMAIS --blind sur le live)
& $PY "$ROOT/tools/nokido_deep_rename.py" --root "$ROOT" --apply

# 1.3 VERIFY — les counts KEEP doivent être IDENTIQUES à 1.0
& $PY "$ROOT/tools/nokido_cutover_verify.py" --root "$ROOT"
```
Effets : contenu `nokido→nokido` (case-preserving) + renommage des fichiers/dossiers dont
le basename contient `nokido` — dont **`tools/nokido_hub.py` → `tools/nokido_hub.py`**,
`tools/nokido.py → nokido.py`, `app/nokido_core.py → app/nokido_core.py`, etc. `forge_*`
et `LaForge/` intacts.

**GATE 1** — vérifs (doivent toutes passer) :
```powershell
# a) LANDMINES KEEP CONSTANTS : sortie 1.3 == sortie 1.0 pour TOUS les counts KEEP
#    (LAFORGE_env, agt_/wrk_laforge, exegol-/searxng-laforge, id-mcp, glob_log, sql_default,
#     schtask_laforge, dist_/lora_laforge, LaForgeMCP, task_camel). Un count qui BAISSE =
#     protection a raté un fonctionnel -> STOP, ne pas appliquer sur le live.
# b) entrypoint renommé
Test-Path "$ROOT\tools\nokido_hub.py"    # -> True
Test-Path "$ROOT\tools\nokido_hub.py"   # -> False
# c) compilation, 0 régression
& $PY -m compileall "$ROOT\app" -q       # -> silencieux
#    NOTE : tools\forge_exegol_worker.py a une SyntaxError PRÉ-EXISTANTE (global CONTAINER)
#    SANS lien avec le rename -> l'ignorer (présente aussi sur le live avant cutover).
```
Résidus bénins attendus : `import_nokido=1` (doc UI_CONSOLIDATION_PLAN : `@import
laforge-tokens.css`, kebab CSS KEPT volontaire) ; `nokido_lower_prefix=0`.

---

## Phase 2 — Migration runtime-state (DB + chemins durs + .env)
Parties **déterministes non-code** que le renommage de code ne couvre pas.
```powershell
# 2.1 DRY
& $PY "$ROOT/tools/nokido_cutover_migrate.py" --root "$ROOT"
# 2.2 APPLY
& $PY "$ROOT/tools/nokido_cutover_migrate.py" --root "$ROOT" --apply
```
Fait, idempotent :
1. **RAG DB** : `rag_chunks.domain` `laforge_*` → `nokido_*` (~43k lignes : nokido_code
   30096, nokido_digest 7085, nokido_doc 6032, nokido_architecture 304, + config/tools/
   docs/collab/memory). *Note : le hub doit être **arrêté** pendant le UPDATE si l'accès DB
   n'est pas WAL-safe concurrent → faire ce sous-pas dans la fenêtre restart (Phase 5) OU
   avec le hub stoppé.*
2. **Fixup chemins durs** : `Script python IA\LaForge` → `Nokido` repo-wide (rattrape les
   2 résiduels bash_guard.py / forge_tool_gate.py que `DIR_SEG` a manqués).
3. **Rename .env** : `Nokido.env(.secrets)` → `Nokido.env(.secrets)` (le hub renommé lit
   `Nokido.env` ; le shim env_alias couvre les variables `LAFORGE_`↔`NOKIDO_`).

**GATE 2** :
```powershell
# DB : plus aucun domaine laforge_*
& $PY -c "import sqlite3;print(sqlite3.connect(r'$ROOT\RAG\embeddings.db').execute(\"select count(*) from rag_chunks where domain like '%nokido%'\").fetchone())"  # -> (0,)
Test-Path "$ROOT\Nokido.env"   # -> True
Select-String -Path "$ROOT\tools\bash_guard.py","$ROOT\tools\forge_tool_gate.py" -Pattern 'Script python IA[\\/]Nokido'  # -> vide
```

---

## Phase 3 — Services (NSSM + schtasks) — privilégié
Utiliser les **noms EXACTS** capturés en Phase 0.3. Le hub s'exécute via NSSM et pointe le
chemin `…\tools\nokido_hub.py`, désormais renommé → il faut repointer **avant** restart.

```powershell
# 3.1 Repointer l'AppParameters du service hub vers nokido_hub.py
#     (remplacer <SVC_HUB> par le nom réel, ex LaForgeMCP)
$svc = "<SVC_HUB>"
$ap  = nssm get $svc AppParameters
$ap2 = $ap -replace 'nokido_hub\.py','nokido_hub.py'
nssm set $svc AppParameters $ap2
# vérifier aussi AppDirectory / AppEnvironmentExtra (LAFORGE_* restent valides via shim)
nssm get $svc AppParameters   # doit montrer nokido_hub.py

# 3.2 (Optionnel, cosmétique) renommer le service Nokido* -> Nokido*
#     ATTENTION : bash_guard passthrough live = 'nssm restart Nokido*' déjà en place ;
#     si tu renommes le service, la passthrough couvre le nouveau nom. Sinon, garder
#     l'ancien nom de service marche aussi (le nom de service != marque exposée).
#     Renommer proprement = réinstaller : nssm install Nokido<...> ; nssm remove <ancien> confirm

# 3.3 schtasks : les tâches Nokido-* dont l'action pointe un script renommé
#     Pour chaque tâche listée en 0.3 :
schtasks /query /tn "LaForge-P1-Runner" /xml > "D:\backup\task_LaForge-P1-Runner.xml"
#   éditer le XML (chemins laforge_*.py -> nokido_*.py si concernés ; sinon inchangé),
#   puis recréer sous le nouveau nom si souhaité :
#   schtasks /create /tn "Nokido-P1-Runner" /xml "…edited.xml" /f  ; schtasks /delete /tn "LaForge-P1-Runner" /f
#   (le renommage de tâche est cosmétique ; garder Nokido-* fonctionne — bash_guard
#    passthrough live = 'schtasks Nokido-*'. Si tu renommes en Nokido-*, il faudra
#    d'abord que bash_guard.py (renommé Phase 1) accepte 'Nokido-*' — VÉRIFIER le regex
#    de passthrough dans le bash_guard.py post-rename avant de renommer les tâches.)
```
**GATE 3** : `nssm get <SVC_HUB> AppParameters` montre `nokido_hub.py` ; XML tâches
sauvegardés ; décision explicite sur rename service/tâches (défaut recommandé : **garder
les noms de service/tâche, ne repointer que les chemins de script**, car service-name ≠
marque exposée → moindre risque).

---

## Phase 4 — Configs clients (id-mcp + header) — **casse la session assistant au restart**
Les configs vivent **hors repo** (home utilisateur) → non touchées par Phase 1.
Fichiers typiques : `~/.claude.json` (Claude Code), `~/.gemini/settings.json`,
`<vscode>/mcp.json`, config Codex, LobeHub. Chercher la clé `laforge-sovereign-hub` et le
header `LaForge-Agent-Name`.

```powershell
# 4.1 Localiser
Select-String -Path "$env:USERPROFILE\.claude.json","$env:USERPROFILE\.gemini\settings.json" -Pattern 'laforge-sovereign-hub|LaForge-Agent-Name' -List

# 4.2 Réécrire (faire un backup .bak d'abord) :
#   "laforge-sovereign-hub"  -> "nokido-sovereign-hub"
#   header "LaForge-Agent-Name" -> "Nokido-Agent-Name"   (ou "Agent-Name" = pont générique)
#   URL/port :8766 INCHANGÉS.
```
> **Transition douce recommandée** : basculer le header client vers le générique
> `Agent-Name` (accepté par le hub AVANT et APRÈS renommage) découple le rollout client de
> la Phase 1. Le nom de la clé mcp (`…-sovereign-hub`) reste, lui, un couplage dur : au
> restart du client, les tools passent de `mcp__laforge-sovereign-hub__*` à
> `mcp__nokido-sovereign-hub__*`. **C'est l'étape irréversible pour la session** — la faire
> en dernier, puis **redémarrer le client**.

**GATE 4** : backups `.bak` des configs ; un seul id-mcp par client (pas de doublon
nokido+nokido → sinon liste de tools dupliquée).

---

## Phase 5 — Restart & vérification
Séquence (hub arrêté pendant le UPDATE DB si pas fait en Phase 2) :
```powershell
# 5.1 Stop hub
nssm stop <SVC_HUB>
# 5.2 (si non fait) UPDATE DB domaines — hub stoppé = accès exclusif
& $PY "$ROOT/tools/nokido_cutover_migrate.py" --root "$ROOT" --apply
# 5.3 Start hub (lit maintenant nokido_hub.py + Nokido.env + shim env)
nssm start <SVC_HUB>
Start-Sleep 8
# 5.4 Health
curl -s http://127.0.0.1:8766/health
```
**GATE 5 — acceptation** :
1. `/health` = OK, hub up.
2. RAG : une recherche renvoie des hits (`rag search` via un client) — domaines `nokido_*`
   servis, 0 cold-wedge.
3. RBAC : un appel gouverné (`governed_edit` dry / `run`) passe avec l'identité attendue
   (`wrk_nokido` **ou** `wrk_laforge` — les deux acceptés).
4. Client redémarré : les tools `mcp__nokido-sovereign-hub__*` apparaissent, un appel
   simple (ex `hub` status) répond.
5. `bash_guard` : un git passthrough marche (le regex de passthrough post-rename couvre les
   noms réels de service/tâche).

Si tout passe → cutover réussi. Committer l'état renommé sur `alpha` (commits séparés :
code / migration-state), pousser, mettre à jour la mémoire projet.

---

## Rollback (si un GATE échoue)
```powershell
# Code
git -C "%NOKIDO_WORKSPACE%\LaForge" reset --hard (Get-Content D:\backup\nokido_cutover_H0.txt)
git -C "%NOKIDO_WORKSPACE%\LaForge" clean -fd   # ATTENTION : retire untracked — vérifier d'abord
# DB / .env
nssm stop <SVC_HUB>
Copy-Item "D:\backup\embeddings.db.pre-nokido" "$ROOT\RAG\embeddings.db" -Force
Copy-Item "D:\backup\LaForge.env.pre-nokido" "$ROOT\LaForge.env" -Force
# NSSM : repointer AppParameters vers nokido_hub.py (depuis D:\backup\nssm_*.txt)
nssm set <SVC_HUB> AppParameters "<...nokido_hub.py...>"
# Configs clients : restaurer les .bak
nssm start <SVC_HUB>
```
Le shim env_alias et `wrk_nokido`/`TRUSTED_EXECUTORS` sont **additifs** → les laisser en
place ne casse rien même après rollback (ils tolèrent l'ancien monde).

---

## Phase +N — dé-couplage STAGÉ des identifiants fonctionnels (post-cutover, incrémental)
Le rename protégé PRÉSERVE volontairement les strings couplés à de l'état externe. Zéro-trace
complet = migrer chaque couplage DERRIÈRE SON ALIAS, un domaine à la fois, vérifié live entre
chaque étape. JAMAIS big-bang. Ordre suggéré (moins → plus risqué) :
1. **Env `LAFORGE_*` → `NOKIDO_*`** : `forge_env_alias` mirror déjà les deux. Basculer NSSM
   `AppEnvironmentExtra` vers `NOKIDO_*`, garder le shim un cycle, puis retirer `LAFORGE_*`.
2. **Conteneurs docker `exegol-laforge`/`searxng-laforge`** : `docker rename` (ou recréer via
   `nokido_ensure_service`) + les refs code (KEPT) suivent en lockstep.
3. **Tâches `Nokido-*` → `Nokido-*`** : réenregistrer schtask + MAJ passthrough bash_guard
   (`/tn "?nokido-` → `nokido-`) DANS LE MÊME commit (sinon le git-guard casse).
4. **RBAC `agt_laforge`/`wrk_laforge`** : bascule producteur → `agt_nokido`/`wrk_nokido`
   (`wrk_nokido` déjà seedé), puis retrait des lignes nokido.
5. **id-mcp / header** `laforge-sovereign-hub` / `LaForge-Agent-Name` : clients → `Agent-Name`
   générique (pont), puis renommer la clé mcp. Casse le binding session au restart → EN DERNIER.
6. **SQL `DEFAULT 'laforge'` + logs `laforge_*.log`** : migrer les DEFAULT ; laisser les logs
   tourner (rotation naturelle) ou renommer glob+fichiers ensemble.
Chaque étape = un mini-cutover : alias en place → bascule → vérif live → retrait de l'ancien.

## Ce qui reste APRÈS un cutover réussi (non bloquant)
- Retirer `wrk_laforge` (une fois `wrk_nokido` prouvé producteur partout : hub_gate,
  orchestration_gate, mcp_registry) — bascule producteur, pas juste allowlist.
- Re-publish du mirror `nokido-dist` pour parité `.py` (source déjà Nokido).
- Mirrors Codeberg.
- Réactiver les surfaces autonomes quiescées en Phase 0.4.
