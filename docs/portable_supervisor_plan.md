# Nokido — Couche de supervision portable (cross-OS)

Statut : **DESIGN — à relire.** Reformule #3 (migration NSSM) en sa vraie
cible : une gestion de services **transposable** Windows / Linux / macOS.

---

## 1. Le vrai problème

`#3` énoncé comme « déregistrer les ~17 services NSSM legacy » est un
nettoyage **Windows-spécifique**. NSSM n'existe que sur Windows. Si Nokido
doit être porté (Linux, macOS, conteneurs), la couche service ne peut PAS
rester sur NSSM.

État actuel = **deux gestionnaires** qui coexistent :
- ~17 services NSSM `Nokido*` legacy (Windows only)
- `proxy_deno/core/supervisor.ts` — supervisor Deno, déjà code-based

Le supervisor Deno est la **bonne direction** (déclaratif, Deno = cross-OS)
mais il porte des verrues Windows (cf. §4). La cible : UN supervisor
portable, NSSM supprimé.

---

## 2. Architecture cible — 3 couches

```
┌─ Couche 1 : config déclarative ──────────────────────────────┐
│  services.toml — name, cmd, args, cwd, env, deps, wave,      │
│  port, restart-policy + sections [service.X.windows|linux|   │
│  macos] pour les divergences (chemin python, séparateurs…)   │
├─ Couche 2 : supervisor OS-agnostique ────────────────────────┤
│  supervisor.ts — spawn/monitor/restart. Deno.Command porte   │
│  déjà. Les bouts OS-spécifiques (RAM, kill, détection) →     │
│  derrière un shim platform/{windows,linux,macos}.ts          │
├─ Couche 3 : UN hook de boot par OS ──────────────────────────┤
│  Windows → 1 service NSSM (ou Tâche planifiée) : lance le    │
│            supervisor. macOS → launchd plist. Linux →        │
│            unité systemd. C'est le SEUL artefact OS-natif.   │
└──────────────────────────────────────────────────────────────┘
```

Principe : **tout est déclaratif dans la config ; le seul code
OS-spécifique est (a) le shim platform, (b) le hook de boot.** Ajouter un
OS = écrire un shim + un hook, zéro changement au reste.

---

## 3. Couche 1 — `services.toml`

Sortir le tableau `SERVICES` codé en dur de `supervisor.ts` vers un fichier.

```toml
[service.hub]
wave = 1
cmd  = "${PYTHON}"
args = ["tools/nokido_hub.py"]
cwd  = "${ROOT}"
port = 8766
essential = true
restart = "always"

  [service.hub.env]
  FORGE_MCP_TOKEN = "${FORGE_MCP_TOKEN}"   # depuis l'env, jamais en dur

[service.brain_worker]
wave = 3
cmd  = "${PYTHON_NPU}"
args = ["app/brain_worker.py"]
deps = [8766]
```

Variables `${...}` résolues par le supervisor : `ROOT` (auto-detect),
`PYTHON` / `PYTHON_NPU` / `DENO` (résolus per-OS — cf. §4), secrets depuis
l'env. **Aucun `C:\...` en dur, aucun secret en dur.**

Divergences OS via sections : `[service.X.linux] cmd = "python3"`.

---

## 4. Couche 2 — dé-Windows-iser `supervisor.ts`

Verrues Windows actuelles à abstraire :

| Verrue | Aujourd'hui | Cible |
|--------|-------------|-------|
| Chemins | `MINIFORGE="~/miniforge3/python.exe"` etc. en dur | résolution `${PYTHON}` via `platform.resolvePython()` |
| RAM | `getMemUsagePct()` → `powershell Get-CimInstance` | `platform.memUsagePct()` — `/proc/meminfo` (linux), `vm_stat` (macos), CIM (win) |
| Kill | `proc.kill("SIGTERM"/"SIGKILL")` | OK — Deno mappe déjà cross-OS |
| Modèles LLM | blobs `D:/ollama/...` en dur | chemins depuis config + détection |
| Boot | NSSM `LaForge-Master` | hook §5 |

`Deno.Command` (spawn), `Deno.connect` (health-check port), les fetch HTTP
— **déjà portables**. Le cœur du supervisor change peu ; on extrait ~3
fonctions dans `proxy_deno/core/platform/`.

---

## 5. Couche 3 — hooks de boot par OS

Le supervisor doit démarrer au boot. C'est le SEUL artefact OS-natif :

- **Windows** : 1 service NSSM `LaForge-Master` (déjà le cas) OU une Tâche
  planifiée `onstart`. Lance `deno run -A proxy_deno/core/supervisor.ts`.
- **Linux** : unité systemd `laforge-master.service` (`ExecStart=deno run …`).
- **macOS** : `launchd` plist `~/Library/LaunchAgents/laforge-master.plist`.

Un script `tools/install_boot_hook.{ps1,sh}` génère le bon hook selon l'OS.

---

## 6. Séquence de migration (#3, exécution prudente)

1. **Externaliser** : `SERVICES[]` de supervisor.ts → `services.toml`.
   supervisor.ts charge le toml. Comportement identique. Testable.
2. **Shim platform** : extraire RAM/chemins/détection dans
   `platform/windows.ts` (+ stubs linux/macos). Tester sur Windows.
3. **Vérifier** : le supervisor démarre TOUS les services depuis le toml,
   un par un, health-check chacun.
4. **Déregistrer NSSM** : une fois (3) prouvé — `sc delete` les ~17
   `Nokido*` legacy SAUF `LaForge-Master`. Service par service, en
   surveillant que le supervisor reprend bien chacun. Rollback = ré-`sc
   create`.
5. **Hooks boot** : générer les hooks per-OS.

L'étape 4 reste **brick-risk** — à faire en session dédiée, supervisée,
rollback prêt. Mais (1)-(3) la rendent sûre : on ne déregistre QUE ce dont
on a prouvé que le supervisor le reprend.

---

## 7. Lien conteneurs

Les services purement logiciels (RAG, daemons, hub) pourraient à terme
tourner en conteneurs (Docker Compose = déclaratif + cross-OS natif).
Mais les composants matériels (llama-server GPU, NPU embedder, ollama)
résistent à la conteneurisation (passthrough GPU/NPU). Donc : le
`services.toml` + supervisor portable est la base ; la conteneurisation
d'un sous-ensemble est une option par-dessus, pas un prérequis.

---

## 8. Effort honnête

Chantier multi-session. (1)-(2) = refactor cadré, faible risque. (3) =
vérification. (4) = l'opération à risque, session dédiée. (5) = mécanique.

Ne RIEN exécuter tant que ce design n'est pas validé.
