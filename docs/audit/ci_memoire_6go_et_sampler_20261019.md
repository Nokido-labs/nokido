# Enquête vague 0 (19/10) — sampler dans pytest et plafond 6 Go par job

**Enquête en lecture seule** (hors ce rapport). Aucune suite complète relancée.
Doctrine `RULES_SHARED.md` : une source muette ne prouve rien (UNKNOWN ≠ NO) ; tout ce
qui reste non mesuré est DIT.

Jobs du même run hub `20261019-160057-95ef43` :

| Job | Commande (fiche `_wrap.py`) | `rss_cap_mb` | Sort `fin` |
|---|---|---|---|
| `job_d24986a1cee5` | `ci_local.py --impacte --impacte-fichiers sandbox/workspace/impacte_fichiers_20261019b.txt` | **6000** | `PLAFOND_RSS`, rc 137, **6008 Mo** |
| `job_129a965fb6b4` | `ci_local.py --impacte --impacte-fichiers sandbox/workspace/impacte_fichiers_20261019c.txt` | **6000** | `PLAFOND_RSS`, rc 137, **6003 Mo** |
| `job_18ebfba6e38a` | `ci_local.py --reference --trace-import pyarrow` | **8000** | (encore `running` à la lecture ; CI de référence) |

Aucun des trois jobs ne passe `--turbo`. Le plafond par défaut est 6000 Mo
(`app/forge_job_runner.py:205-207`, `LAFORGE_JOB_RSS_CAP_MB` sinon `"6000"`).

---

## (A) Le sampler tourne DANS le processus pytest — CAUSE PROUVÉE

### Ce que montre la pile

Au timeout de `tests/nr/test_capture_sans_perte_nr.py`
(`sandbox/jobs/job_18ebfba6e38a.log:74599`), pytest-timeout a vidé les piles de TOUS
les threads du processus. Trois d'entre eux sont des daemons de Nokido :

- **`forge_auto_evict`** (`:74600`) :
  `request_resources` → `_supervisor_auth_headers` → `_gs(...)` →
  `forge_secrets.get_secret` → `_sonder` → `_wcm` → `import keyring`
  (`app/forge_resource_manager.py:5019`, `:1263` ; `app/forge_secrets.py:750,529,564`).
- **`forge_arbitrage`** (`:74624`) :
  `_arbitrage_consolidation_tick` → `_demande_active_llama` → `forge_organ_demand.demandes_actives`
  → `forge_signal_coupling._conn` → `cx.execute("CREATE INDEX IF NOT EXISTS idx_journal_signal_ts …")`
  (`app/forge_resource_manager.py:1885,1643` ; `app/forge_organ_demand.py:289,93` ;
  `app/forge_signal_coupling.py:226`).
- **`forge_resource_sampler`** (`:74640`) :
  `_sampler_loop` → `_sample_once` → `_sample_top_procs` → `psutil.process_iter`
  (`app/forge_resource_manager.py:1974,915,508`).

### Qui lance ces threads

Le **seul** point d'allumage est `get_snapshot()`
(`app/forge_resource_manager.py:2370-2386`) :

```python
if _SAMPLER_THREAD is None or not _SAMPLER_THREAD.is_alive():
    if _should_autostart_sampler():      # <-- décide qui a le droit
        start_sampler()
```

`start_sampler()` (`:2216`) démarre le daemon `forge_resource_sampler`, dont la boucle
`_sampler_loop` **spawne à son tour** `forge_arbitrage` (`:2114`), `forge_auto_evict`
(`:2180`), `forge_lmstudio_idle`, `forge_baux_expiration`, `forge_regulation_disque`,
`forge_hamilton_arme`. Donc « voir `forge_arbitrage` et `forge_auto_evict` » == preuve
que **le sampler a été démarré dans ce processus**.

`_should_autostart_sampler()` (`:2336-2367`) répond OUI si :
1. `LAFORGE_SAMPLER_AUTOSTART` vaut `1`/`true`/`yes` (posé par le hub via
   `proxy_deno/core/services.toml:224` — c'est le propriétaire LÉGITIME) ; ou
2. `argv[0]` est `nokido_hub.py` ; ou
3. **l'état publié `sandbox/resource_state.json` est absent ou plus vieux que 120 s**
   (`_SAMPLER_TAKEOVER_AFTER_S`, `:2325`) — « le propriétaire est mort ou absent et le
   premier appelant reprend la main ».

Dans la CI, le processus est `ci_local.py` (ni hub, ni flag `1`), et le worktree de
référence est détaché (`…\nokido_proof\ci-reference-b5fc85e27e1a\worktree`) : la
condition 3 s'applique — **le premier test (ou module importé) qui appelle
`get_snapshot()` devient propriétaire et allume le sampler pour tout le reste du
processus pytest**. Le flag est ensuite à `True` en dur pour ce process : aucun test
ultérieur ne peut l'éteindre.

C'est un fait déjà consigné, non une hypothèse : le commentaire du test lui-même
(`tests/nr/test_capture_sans_perte_nr.py:21-24`) dit que « la cause probable (threads
du sampler de `forge_resource_manager` vivants dans le processus pytest) est instruite à
part ».

### Effet mesuré (pourquoi ce n'est pas cosmétique)

- `forge_arbitrage` fait un `CREATE INDEX …` sur la base du couplage de signaux
  **pendant** que les tests écrivent leurs bases : contention/verrous SQLite
  (`database is locked`) au pire moment.
- `forge_auto_evict` déclenche `import keyring` (import lourd, sous verrou GIL) et
  `request_resources` (réveil superviseur) : un chemin de production actif dans un test.
- `forge_resource_sampler` appelle `psutil.process_iter` sur **tous** les PID toutes
  les 3 s, et `_sample_once` a un chemin de sonde GPU PowerShell synchrone.

### Ce qui reste INMESURABLE pour (A)

- **Le test exact qui a amorcé** le sampler : la pile ne montre que l'état à
  l'expiration, pas le premier appel `get_snapshot()`. Aucun marqueur d'allumage n'est
  journalisé (pas de log « sampler started by <test> »). Non mesuré, non deviné.
- **Le moment exact** où `sandbox/resource_state.json` est devenu périmé pendant la CI
  (le hub peut l'écrire et reprendre la main) : non tracé.

### Correctif proposé (sans coder)

1. **Garde d'environnement en tête de `tests/conftest.py`** (et de `tests/nr/conftest.py`) :
   `os.environ.setdefault("LAFORGE_SAMPLER_AUTOSTART", "0")` **au niveau module**, avant
   tout import d'`app`. La branche `flag in ("0","false","no")` de
   `_should_autostart_sampler` court-circuite déjà : c'est le remède minimal, honoré par
   le code existant, et il couvre les workers xdist comme le séquentiel.
2. **Ceinture et bretelles (autouse session)** : une fixture `autouse` session qui importe
   `forge_resource_manager`, force `stop_sampler()`, remet `_SAMPLER_THREAD = None` et
   `_SAMPLER_STOP.clear()` — pour tuer un sampler démarré par un import de collection
   *avant* le premier test. À poser APRÈS le `setdefault` (1).
3. **Ne pas** se reposer sur `_should_autostart_sampler` seul : sa règle 3 (reprise sur
   état périmé) est ce qui ouvre la porte en CI ; un test ne doit jamais hériter d'un
   rôle de propriétaire de daemon.

---

## (B) Dépassement du plafond de 6 Go — CAUSE PROUVÉE, et la prémisse est à corriger

### Le fait qui renverse l'énoncé

Les deux jobs `--impacte` **n'ont jamais lu leur liste de fichiers**. À l'instant où
`ci_local` a résolu la sélection, le journal porte (aux deux runs) :

```
[selection] TOUT joue — diff ILLISIBLE(liste FileNotFoundError: [Errno 2]
  No such file or directory: 'sandbox\workspace\impacte_fichiers_20261…)
  — ne rien savoir des changements ne vaut pas 'rien n'a change'
```
(`job_d24986a1cee5.log` ~ligne 231236 ; `job_129a965fb6b4.log:237262`, juste avant
`── pytest (suite pure) ──`).

Donc la **suite ENTIÈRE** (~10 800 tests) a été jouée — pas 6 fichiers. Le fichier
`impacte_fichiers_20261019c.txt` (171 o, **exactement 6 lignes** : 5 modules `app/` +
1 test) **existait pourtant** (mtime 16:42, job `job_129a965fb6b4` démarré 16:42:27).
Le repli de sûreté du sélecteur a fait son travail : `etat_diff` non `PRESENT` ⇒
`_tout()` (`tools/forge_ci_selection.py:144-146,191-201`).

### Cause racine du repli : chemin relatif résolu contre un `cwd` qui n'est pas la racine

- `tools/ci_local.py:5748-5751` passe l'argument **tel quel** :
  `liste_depuis_fichier(_liste)` — sans l'ancrer sur `ROOT`.
- `tools/forge_ci_selection.py:110` le résout par `Path(chemin).read_text()` : le chemin
  est **relatif au `cwd` du processus**, pas à `ROOT` (qui, lui, est calculé depuis
  `__file__`).
- Le job est lancé par l'arbre `forge_job_runner.launch_job` → `spawn_as_sandbox_detached`
  (`app/forge_job_runner.py:341-345`) → `forge_runas_launcher` avec
  `cwd=os.getcwd()` (`tools/forge_runas_launcher.py:280`). Le wrapper fait
  `subprocess.Popen([py, sp] + extra)` **sans** `cwd=`
  (`app/forge_job_runner.py:231`), donc `ci_local` **hérite du `cwd` du hub**. Sous le
  compte de service, ce `cwd` n'est pas la racine du dépôt — et
  `sandbox/workspace/impacte_fichiers_20261019b.txt` n'y existe pas. (Preuve par
  contradiction : le fichier existe bel et bien à la racine, donc le `cwd` résolu n'était
  pas la racine.)

Conséquence : `--impacte-fichiers` **n'a aucun effet dès que la CI tourne via `run_job`**
— précisément la voie visée par le mode (voir le docstring de `liste_depuis_fichier`,
`:99-103`).

### Quel processus de l'arbre grossit — RÉPONSE

- **Pas les workers turbo** : aucun job ne passe `--turbo` ; `xdist`/`_workers_turbo`
  (`tools/ci_local.py:3800-3815`, `:5909`) n'est **jamais** atteint.
- **Pas des gates parallèles** : `_run` est le point de passage **unique** et **bloquant**
  de tous les gates (`tools/ci_local.py:4165-4185` : `Popen` puis boucle sur `stdout`
  puis `wait()`) ; les blocs isolés tournent **après**, séquentiellement (`:6013+`).
- **Le processus qui grossit est le pytest unique** (le suite pure séquentielle), dont le
  RSS de l'arbre (pytest + ses enfants) franchit 6000 Mo. Le wrapper somme le RSS de
  `_pr.children(recursive=True)` (`app/forge_job_runner.py:306-311`) : sont donc comptés
  les sous-processus que les tests et le sampler spawnent (sondes PowerShell du sampler,
  CLI py314t, etc.).

Le pic vient du **cumul résident** d'une suite séquentielle jouée en un seul interpréteur :
imports lourds qui restent chargés (`pyarrow`/`arrow.dll` — d'où le `--trace-import
pyarrow` de la CI de référence, et l'isolation documentée de
`tests/nr/test_router_dt_dimension_modele_nr.py`), caches SQLite, plus les threads/daemons
du (A). La CI de référence (`--reference`, 8000 Mo) joue la même suite par conception :
elle **a dû** être montée à 8 Go parce que la suite complète ne tient pas dans 6 Go.

### Ce qui reste INMESURABLE pour (B)

- **La répartition exacte du RSS** (quel import / quel test / quel thread pèse combien) :
  le garde ne journalise que le **total de l'arbre au franchissement du cap** ; aucun
  tracé RSS par phase n'est écrit, et les deux jobs tués n'ont produit **aucun dump
  faulthandler** (le kill est externe).
- **Le `cwd` réel du processus hub** au moment du spawn : non journalisé dans les fiches
  `.json` ni `.log`. Déduit par contradiction (le fichier existe et n'est pas trouvé),
  pas lu.
- **Le RSS seul du sampler** dans ce processus : non isolé.

### Correctif proposé (sans coder)

1. **Ancrer la liste sur `ROOT` dans `ci_local`** (le vrai bug) : dans la branche
   `--impacte`, résoudre `Path(_liste)` et, s'il est relatif, le préfixer par `ROOT`
   avant `liste_depuis_fichier` — ou rendre le chemin **absolu** côté appelant/`run_job`.
   Alternative : envelopper la lecture dans `os.chdir(ROOT)` (moins propre) ou passer
   `cwd=root` au `Popen` du wrapper (`app/forge_job_runner.py:231`).
2. **Ne pas traiter un repli `TOUT` comme « petit »** : quand `_selection["mode"] == TOUT`,
   le run est une **suite complète** — il doit en tirer les conséquences (cap de job
   dimensionné comme une référence, ou refus explicite) au lieu de mourir à 6 Go. Le
   cap par défaut `6000` (`forge_job_runner.py:205-207`) reste la valeur juste pour un
   `--impacte` réellement partiel ; il est faux pour un repli complet.
3. **Rendre le repli VISIBLE au verdict** : un `TOUT` sur `--impacte` est exactement le
   cas que le docstring du sélecteur désigne comme « faux vert parfait » inversé (ici, un
   « faux petit »). Le dire dans le bilan de fin de job évite qu'il se relise comme une
   exécution ciblée.
4. **(A)+(B) combinés** : neutraliser le sampler en test (cf. A.1-2) retire aussi une
   source de sous-processus et de fuite RSS dans l'arbre du job.

---

## Synthèse

| | Cause racine | Preuve |
|---|---|---|
| **A** | `get_snapshot()` autostart du sampler quand l'état publié est absent/périmé (`_should_autostart_sampler`, règle 3) ; la boucle du sampler spawne `forge_arbitrage`/`forge_auto_evict` qui tournent dans le processus pytest | pile complète `job_18ebfba6e38a.log:74599-74640` ; `app/forge_resource_manager.py:2114,2180,2336-2379` |
| **B** | `--impacte-fichiers` résolu **relatif au `cwd`** (≠ racine) ⇒ `FileNotFoundError` ⇒ repli **TOUT** ⇒ suite **complète** séquentielle dans **un seul** pytest ⇒ arbre > 6000 Mo | `[selection] TOUT joue — … FileNotFoundError` dans les 2 logs ; `tools/ci_local.py:5748-5751`, `tools/forge_ci_selection.py:110`, `app/forge_job_runner.py:231,341-345` |

**La prémisse « même avec 6 fichiers listés » est réfutée** : la liste à 6 fichiers n'a
pas été lue ; le mode a joué la suite entière. Le plafond de 6 Go n'est donc pas un
problème de mode ciblé, mais la conjonction (i) d'un chemin mal ancré et (ii) d'un repli
complet qui n'a pas été traité comme tel.
