# Protocole de mesure — profil « client + SSoT »

**Statut :** protocole (étape 1). Aucune mesure n'a été exécutée pour produire ce document.
**Date :** 2026-10-27
**Décision liée :** tableau noir `architecture_rules/P1_profil_client_ssot_mesure_20261026` (26/10).
**Portée :** définir *comment* mesurer le profil « client + SSoT » (hub MCP + mémoire partagée,
sans l'organisme) et le comparer au profil complet. **Ce document ne crée pas le profil, ne
modifie aucun fichier existant, ne supprime aucun service et ne lance rien.**

Le profil est **une option parmi d'autres**, jamais le point d'entrée par défaut : le défaut
reste `dev` (`app/forge_install_prerequis.py:919`), l'organisme complet reste le produit. Ce
protocole sert à produire le chiffre qui dira si l'option vaut la peine d'exister.

---

## 0. Ce que le protocole doit répondre

1. Combien de RAM **privée** le profil tient-il à l'arrêt, et sous charge ?
2. Combien de disque **installé** (binaires, modèles, socle) et combien de données ?
3. Combien de temps pour une installation **à froid**, et un démarrage à froid ?
4. Le tout comparé au profil complet, **à corpus et charge identiques**.

Trois choses sont dites d'avance, pour ne pas les découvrir après coup :

- **Le nom « client + SSoT » ne couvre pas la génération locale.** Sans Ollama/llama-server 7B
  (hors périmètre ci-dessous), le profil sait chercher dans la mémoire et exécuter des outils,
  pas produire un texte. S'il faut générer, c'est une **variante** à mesurer séparément.
- **Aucun installateur ne compose ce profil aujourd'hui.** `install.ps1` installe le socle
  commun ; `PROFILS` ne gate que ce qui *bloque* `dev`/`complet`
  (`app/forge_install_prerequis.py:913-922`). Donc le temps d'installation mesuré sera celui du
  **socle commun + démarrage réduit**, pas celui d'une installation réduite. Un pack de
  dépendances propre au profil n'existe pas : il est déclaré **NON MESURABLE AUJOURD'HUI**,
  jamais 0.
- **Le corpus de l'owner est interdit au balayage.** Les chiffres absolus à 1 152 197 vecteurs
  (`proxy_deno/core/services.toml:202-206`) sont une **référence déclarée**, pas une mesure de
  cette campagne. La campagne mesure à corpus borné, et extrapole explicitement.

### Critère de décision pré-enregistré (à ratifier par l'owner AVANT la campagne)

| gain RAM repos (1 − C1/C2) | lecture |
|---|---|
| ≥ 50 % **et** p95 `rag search` ≤ 2 × celle de C2 | le profil mérite d'exister |
| 30 – 50 % | l'owner arbitre, en regard du coût d'un second chemin d'installation |
| < 30 % | ne pas créer le profil ; l'écrire comme non rentable |

Le seuil est posé avant de voir le chiffre, pour que la conclusion ne soit pas choisie après.

---

## 1. Périmètre fonctionnel

### 1.1 Le cœur mesuré — C1 (3 services)

| service | `services.toml` | port | rôle | pourquoi lui |
|---|---|---|---|---|
| `NokidoMCP` | l.105 | 8766 | hub : MCP, RAG, outils, SSoT | sans lui il n'y a pas de client |
| `NokidoLlamaEmbed` | l.1136 | 8099 | embedder local `bge-m3` (GGUF) | écrire et relire la mémoire sans cloud ; `disabled=false` l.1155 |
| `NokidoSSoTMaintainer` | l.1317 | — | régénère roadmap/règles/mémoire/providers/system_state, cycle 300 s | c'est le « SSoT » du nom (~l.1336-1339) |

### 1.2 La façade mesurée à part — C1p (C1 + 1)

| service | `services.toml` | port | rôle |
|---|---|---|---|
| `NokidoDenoProxy` | l.747 | 8000 | façade OpenAI-compatible vers le hub, dépend de [8766] |

C1p est mesuré **n = 1**, déclaré comme tel : il ne sert qu'à chiffrer le coût marginal de la
seule surface « client » du dépôt. Son empreinte déclarée est 3,0 MB (`proxy_deno/main.ts:7`,
émis par le code, non mesuré).

### 1.3 Explicitement hors du profil (et pourquoi)

| exclu | où | raison |
|---|---|---|
| `NokidoMemoryConsolidator` | l.1946 | cycle de maintenance 12 h, lit la base 52 Go (~49,5 Mo/s, `docs/enquetes/consolidator_debit_disque_20261026.md:3`) ; confond disque et RAM. Mesurable en option séparée |
| `NokidoQdrantSidecar` / `NokidoQdrantServer` | l.465 / l.483 | alternative dense, pas un complément ; le hub garde son cache dense (l.207-210) |
| `NokidoCaddyTLS` | l.1023 | TLS optionnel. Aucun service d'auth dans `services.toml` : l'auth est le token du hub (`FORGE_MCP_TOKEN`, `proxy_deno/core/supervisor.ts:~95-101`) → coût 0 service |
| Ollama / llama-server 7B | — | la génération locale n'est pas dans le nom du profil (cf. §0) |
| boîte noire, watchdog, daemons, UI, netcfg | reste du registre | hors du besoin « client + SSoT » |

### 1.4 Le complément — 68 services

Le registre `proxy_deno/core/services.toml` compte **105 blocs `[[service]]`**, dont **33
`disabled = true`** ; **72 actifs** (105 − 33), dont 4 dans C1p.
Le complément est donc **68 services** (72 − 4). Cette arithmétique est vérifiée, pas supposée :
le snippet ci-dessous la recalcule et **échoue bruyamment** si le fichier a changé depuis.

```python
# .mesure/outils/inventaire_profil.py — script jetable, HORS dépôt, lecture seule
import tomllib, pathlib, sys
d = tomllib.loads(pathlib.Path("proxy_deno/core/services.toml").read_text(encoding="utf-8"))
s = d.get("service", [])
profil = {"NokidoMCP", "NokidoLlamaEmbed", "NokidoSSoTMaintainer", "NokidoDenoProxy"}
actifs = [x for x in s if not x.get("disabled")]
noms = {x["name"] for x in actifs}
print(f"blocs={len(s)} desactives={sum(1 for x in s if x.get('disabled'))} actifs={len(actifs)}")
print(f"profil_trouve={sorted(profil & noms)} manquants={sorted(profil - noms)}")
print(f"complement={len(noms - profil)}")
attendu = (105, 33, 72, 4, 68)
obtenu = (len(s), sum(1 for x in s if x.get("disabled")), len(actifs),
          len(profil & noms), len(noms - profil))
if obtenu != attendu:
    print(f"PERIMETRE_CHANGE attendu={attendu} obtenu={obtenu}", file=sys.stderr)
    sys.exit(3)
```

Sortie attendue le 2026-10-27 : `blocs=105 desactives=33 actifs=72 profil_trouve=[...4...]
manquants=[] complement=68`. Toute autre sortie invalide la campagne (I1).

---

## 2. Le banc

### 2.1 Machine, compte, horloge

- Une **VM propre** (snapshot), même classe que la référence : la machine citée dans
  `services.toml` fait 23,67 Go (~l.204, `app/forge_mcp_registry.py:7380`).
- Enregistrer avant tout processus Nokido : RAM physique, CPU, disque, GPU, **et la ligne de
  base privée/committed de l'OS** (I7). Si la ligne de base varie de plus de 1 Go entre C1 et
  C2, refaire le run.
- **Compte non privilégié** : `psutil.memory_maps()` y est refusé (commentaire
  `services.toml:191-196`) ; la boîte noire voit alors 310 process sur 314 avec une cmdline
  illisible (`services.toml:302-304`). Conséquence : O1 doit tourner **sous le même compte que
  le hub**, sinon `illisibles > 0` et la mesure est invalide (I4). Un droit admin n'est pas
  nécessaire au profil ; il l'est pour `netsh` (hors périmètre).
- Horloge : enregistrer l'offset NTP (`w32tm /query /status`) ; |offset| > 1 s → I9.

### 2.2 Isolation des données (à faire AVANT de démarrer le superviseur)

Le superviseur fusionne `{ ...Deno.env.toObject(), ...(def.env ?? {}) }` : **une clé du TOML
écrase l'environnement parent** (`proxy_deno/core/supervisor.ts:1486`). Vérifié : les 4 blocs
du profil ne définissent **aucune** clé `LAFORGE_DB`/`*_DATA_DIR` (grep sur le TOML) → poser
l'environnement avant le superviseur suffit. Le contrôle runtime reste obligatoire.

```powershell
$racine = Join-Path $PWD ".mesure"
$env:NOKIDO_DATA_DIR  = Join-Path $racine "data"
$env:LAFORGE_DATA_DIR = Join-Path $racine "data"
$env:LAFORGE_DB       = Join-Path $racine "data\embeddings.db"
$env:NOKIDO_RUNTIME   = Join-Path $racine "runtime"   # defaut sinon ~/nokido-runtime
$env:DENO_DIR         = Join-Path $racine "deno"      # sinon cache hors perimetre (LOCALAPPDATA)
$env:PIP_NO_CACHE_DIR = "1"                           # froid = pas de cache pip
$env:NO_PROXY         = "localhost,127.0.0.1"
```

Les deux racines (`NOKIDO_DATA_DIR`, `LAFORGE_DATA_DIR`) sont posées ensemble parce que le
module peut lire l'une ou l'autre (`app/forge_db_path.py:437-449`) ; `db_path()` fait un
`realpath` (`:548-554`) → **I2 juge le chemin résolu, pas le chemin écrit**.

Contrôle runtime, dans le Python du hub :

```powershell
& $env:LAFORGE_PYTHON -c "import json,os; from app.forge_db_path import db_path; p=os.path.realpath(db_path()); print(json.dumps({'db':p,'sous_mesure':p.startswith(os.path.realpath(os.path.join(os.getcwd(),'.mesure')))}, ensure_ascii=False))"
```

`sous_mesure` doit être `true`. Sinon **campagne annulée** : on aurait lu ou écrit la base de
l'owner (volume de données 52 Go).

### 2.3 Corpus

Deux jeux, jamais le corpus de l'owner :

- **D0 — vide.** Racine neuve, base créée par le hub au boot (ou absente). Exiger
  `chunks = 0` et base < 1 GiB. Mesure le coût *structurel* (schéma, index, WAL).
- **D1 — gelé, 100 000 chunks.** La base est **créée par le hub** au premier boot (schéma de
  production), puis remplie par la voie d'ingestion du dépôt, **jamais** par un `INSERT` écrit
  à la main. Le schéma doit exposer les colonnes lues par le cache dense —
  `id, source, domain, text, ext, folder, embedding` (`app/forge_mcp_registry.py:7429`) — et
  `embedding` doit être un BLOB `float32` de 4096 octets (`:7436`, `len(emb) == 4096`). Un
  schéma différent (celui, minimal, de `app/forge_rag_index_app.py:74-81`, n'a ni `id` ni
  `embedding`) rend **D1 invalide** au lieu de produire une RAM trompeuse. La construction
  peut se faire avec l'organisme complet : **elle n'est pas dans l'enveloppe mesurée**.
- **Gel** : `PRAGMA wal_checkpoint(TRUNCATE)`, suppression des `-wal`/`-shm`, puis empreinte
  `sha256`, `count(*)`, `page_count×page_size`, dimension 1024. Instrument candidat déjà
  présent : `tools/forge_rag_index_fingerprint.py` (à confirmer au premier run).
- **Pourquoi 100 000 et pas 1 152 197** : 100k × 1024 × 4 B = **0,39 GiB** de matrice, assez
  pour voir la réponse du profil ; le chiffre à l'échelle de l'owner est une **extrapolation
  linéaire** depuis `services.toml:202-206`, étiquetée comme telle, jamais un résultat.
- **Même base pour C1 et C2** : la comparaison ne dépend pas de la taille, seulement de
  l'identité (I3).

### 2.4 Environnement figé

Pas d'Ollama, pas de Docker, pas de réseau sortant. `PATH` contient `llama-server` et `deno`
du périmètre. Enregistrer : commit (`git rev-parse HEAD`), `sha256` du TOML **utilisé**, hash
du corpus, version Python/Deno, état antivirus. Variante assumée = variante déclarée.

---

## 3. Les mesures

Convention : **« privé » = mémoire privée/committed, pas RSS.** Le working set se rogne
(commentaire `app/forge_resource_manager.py:599`) ; le committé est ce que l'OS réserve. Le
working set est relevé mais **jamais fusionné** avec le privé.

Deux observateurs indépendants, mêmes définitions, même fermeture de PID :

- **O1, interne** : `attribuer_pression(force=True)`
  (`app/forge_resource_manager.py:599`) → `verdict, soi_gb, non_soi_gb, incertain_gb,
  illisibles, top_handles`. Son cache vaut 60 s (`:583`) : `force=True` obligatoire. Lancé
  dans **son propre process** (le module est importé, pas le hub) pour ne pas tenir le GIL du
  hub — un sampler à 3 s tenait déjà le GIL ~1,3 s (`services.toml:~993-999`).
- **O2, externe** : PowerShell/CIM, somme de `PrivatePageCount` sur l'arbre de PID, plus
  `\Memory\Committed Bytes` pour le système. Ne dépend d'aucun code Nokido.

```powershell
# O1 — a appeler a t=0, 60, 120, ... (le JSON est la ligne de mesure)
& $env:LAFORGE_PYTHON -c "import json,sys; sys.path.insert(0,'.'); from app.forge_resource_manager import attribuer_pression; print(json.dumps(attribuer_pression(force=True), ensure_ascii=False))"

# O2 — a appeler toutes les 20 s
$profil = @('NokidoMCP','NokidoLlamaEmbed','NokidoSSoTMaintainer','NokidoDenoProxy')
$svc = (Invoke-RestMethod 'http://127.0.0.1:8765/supervisor/status').services
$items = if ($svc -is [array]) { @($svc) }
         elseif ($svc -is [System.Collections.IDictionary]) { @($svc.Values) }
         else { @($svc.PSObject.Properties | ForEach-Object { $_.Value }) }
$racines = @($items | Where-Object { $_.status -eq 'running' -and $profil -contains $_.name } | ForEach-Object { [int]$_.pid })
$all = Get-CimInstance Win32_Process
$keep = [System.Collections.Generic.HashSet[int]]::new(); foreach ($p in $racines) { [void]$keep.Add($p) }
do { $a=$false; foreach ($p in $all) { if ($keep.Contains([int]$p.ParentProcessId) -and $keep.Add([int]$p.ProcessId)) { $a=$true } } } while ($a)
$sel = @($all | Where-Object { $keep.Contains([int]$_.ProcessId) })
[pscustomobject]@{
  n_pid      = $sel.Count
  private_go = [math]::Round((($sel | Measure-Object PrivatePageCount -Sum).Sum)/1GB, 3)
  working_go = [math]::Round((($sel | Measure-Object WorkingSetSize  -Sum).Sum)/1GB, 3)
  committed_go = [math]::Round((Get-Counter '\Memory\Committed Bytes').CounterSamples.CookedValue/1GB, 3)
} | ConvertTo-Json -Compress
```

### M1 — RAM au repos

- **Question** : privé du profil, base gelée, aucun trafic.
- **Protocole** : attendre **un cycle complet du mainteneur SSoT** (300 s) **puis** 300 s de
  silence (le premier cycle écrit et lit : ce n'est pas le repos). Fenêtre : 15 échantillons
  O1 à 60 s ; O2 toutes les 20 s (45 points).
- **Résultat** : médiane O1, médiane O2, max. Working set à part.
- **Accord** : |O1 − O2_privé| / max ≤ **15 %**, sinon I4.
- **Invalide si** : `illisibles > 0` sur un PID du profil, `incertain_gb > 10 %` du SOI, ou
  O1 = 0 alors que O2 > 0,5 Go (un registre muet rend 0 : c'est I10, pas une mesure).

### M2 — RAM sous charge

- **Charge W** : 150 appels `rag search` (sujet fixe, `limit=5`), un toutes les 2 s ± 0,2 s,
  plus 10 appels `run` triviaux (`python -c "raise SystemExit(0)"`), 300 s au total. Émise
  **par un agent à travers la surface MCP** : l'enveloppe est correcte par construction, rien
  n'est réinventé. Le process émetteur est **hors** de la fermeture mesurée, son coût est
  déclaré à part.
- **Échantillons** : O2 toutes les 20 s, O1 toutes les 60 s. Résultat : p50 et **pic** (max
  d'un échantillon) du privé ; p95 de la latence des 150 recherches.
- **Invalide si** : une recherche échoue, ou le hub redémarre (I6). Une p95 > 2 × celle de C2
  est un **résultat** (profil dégradé), pas une invalidation.

### M3 — Disque installé

Quatre postes, mesurés séparément (jamais un seul « total ») :

| poste | contenu | instrument |
|---|---|---|
| `D_code` | clone + `.venv` (socle Python commun) | octets logiques |
| `D_bin` | `deno`, `llama-server`, `DENO_DIR` redirigé | octets logiques |
| `D_models` | GGUF `bge-m3` | octets logiques |
| `D_data` | D0 seulement | octets logiques |

```powershell
foreach ($p in @('D_code','D_bin','D_models','D_data')) { $d = Join-Path $racine $p
  "{0} {1}" -f $p, ((Get-ChildItem -LiteralPath $d -Recurse -File -Force | Measure-Object Length -Sum).Sum) }
```

- Relever **aussi** la différence d'espace libre du volume avant/après installation : elle
  donne l'**allocation**, l'autre donne le **logique**. L'écart (overhead FS) est nommé, pas
  caché.
- **Exclure** : le corpus D1 (entrée, pas installation), le pagefile (l'OS peut committer
  au-delà de la RAM ; relever `pagefileusage`, ne pas l'additionner), `%TEMP%` de pip (nommé).
- **Contexte** : le README affirme « 8 Go RAM · ~2 Go disque » ; c'est réfuté à 11,7 Go privé
  (`docs/audit/readme_affirmations_20261019.md:38,57-62`). Ce protocole remplace une
  affirmation par une mesure, il n'ajoute pas une affirmation.

### M4 — Installation à froid

- **Périmètre** : snapshot propre, pas de `.venv`, pas de cache pip, pas de modèle, pas de
  Docker, pas de `DENO_DIR`.
- **Entrée** : `install.ps1` (paramètres l.13-21 ; l'invite Docker se refuse en répondant
  **N**, l.199-212). **Ne pas passer `-ML`** : torch n'est pas nécessaire au profil et
  gonflerait `D_code`/T_install — ce serait un autre profil.
- **4 étapes** : `T_dl` (clone + wheel), `T_deps` (pip), `T_bin` (deno + llama-server),
  `T_models` (téléchargement bge-m3). Instrument : `tools/forge_install_acceptance.py` donne
  `duree_s` par étape (l.58-74), la stabilisation (l.857) et le disque (l.155) ; un chronomètre
  mural encadre `install.ps1` entier.
- **Limite, dite d'avance** : aucun pack ne réduit l'installation (cf. §0). On publie donc
  **T_install(socle commun)** et **T_boot(profil)**, et on attribue au profil le démarrage,
  **pas** l'installation. Une installation réellement réduite reste NON MESURABLE.
- **Invalide si** I8 (cache, `.venv` préexistant, modèle déjà là, > 2 reprises réseau, une
  interaction hors l'invite documentée).

### M5 — Démarrage à froid et première mémoire

- `T_boot` : du lancement du superviseur à l'état `running` des 3 (ou 4) services ; sondage
  `/supervisor/status` toutes les 0,5 s, horloge monotone.
- `T_first_memory` : **séparé** — premier `rag search` réussi après le boot (le hub peut être
  « running » avant que la matrice dense ne soit chargée, pré-allocation
  `app/forge_mcp_registry.py:7390-7396`). Relever latence et RAM juste après.
- **Porte fonctionnelle** : un cycle du mainteneur SSoT doit **se terminer** (ligne de journal).
  S'il exige un LLM absent du profil, c'est un **résultat de périmètre** : C1 doit inclure le
  fournisseur, ou le mainteneur doit dégrader — à trancher, pas à contourner en silence.

### M6 — Profil complet (C2)

- **Même clone, même corpus gelé, même W, mêmes observateurs.** La seule différence est le jeu
  de services : TOML intact, **72 actifs**. Tout le reste identique (I3). 3 runs.
- Pour démarrer C1 sans toucher au dépôt : sur le **clone jetable de la VM**, passer
  `disabled = true` sur les 68 services hors profil, enregistrer le `sha256` du TOML ainsi
  produit. C'est un artefact de mesure, pas un commit ; C2 utilise le fichier d'origine.
- Référence historique : 11,7 Go privé sur le corpus de l'owner (audit) — **non comparable**
  à D1, citée comme contexte seulement.

### M7 — Coûts marginaux (optionnel, n = 1)

C1p (proxy) ; puis un service retiré à la fois. Sert à borner « et si on enlève X », pas à la
décision. Déclaré n = 1.

---

## 4. Critères d'invalidité

| # | test | conséquence |
|---|---|---|
| I1 | l'inventaire §1.4 ne rend pas 105/33/72/4/68, ou le `sha256` du TOML diffère entre runs | campagne annulée |
| I2 | `realpath(db_path())` hors `.mesure/`, ou D0 > 1 GiB, ou un chemin touche le volume de l'owner | campagne annulée |
| I3 | `sha256`/`count`/dim du corpus diffèrent entre C1 et C2 | comparaison annulée |
| I4 | \|O1 − O2_privé\|/max > 15 %, ou `incertain_gb` > 10 %, ou `illisibles > 0` sur un PID du profil | run annulé |
| I5 | dérive du repos : \|médiane(3 derniers) − médiane(3 précédents)\| > 2 % | fenêtre jetée |
| I6 | restart, sleep, ou changement de PID pendant la fenêtre | fenêtre jetée |
| I7 | bruit non-profil > 2 GiB ou > 10 % du total pendant > 60 s, ou CPU non-profil > 10 % (moyenne 1 min) | run annulé |
| I8 | installation non froide (cache, `.venv`, modèle, reprise réseau, interaction) | T_install re-étiqueté, sinon annulé |
| I9 | \|offset horloge\| > 1 s, ou sommeil/hibernation pendant la fenêtre | run annulé |
| I10 | instrument muet (exception, `None`, 0 sans source) | **UNKNOWN**, jamais 0 ; le run ne conclut pas |
| I11 | 3 runs, étendue du privé total > 10 % | publier la **plage**, pas la médiane seule |

Règle de doctrine, déjà payée : « mesure indisponible : DITE (None), jamais 0 »
(`tools/forge_install_acceptance.py:903`).

---

## 5. Livrables

```
.mesure/resultats/20261027_<C1|C1p|C2>_run<N>/
  manifest.json     # commit, sha256 toml/corpus, machine, compte, offset, N, AV
  ram_samples.csv   # t_s, obs, private_go, working_go, committed_go, incertain_go, illisibles
  phases.json       # T_dl, T_deps, T_bin, T_models, T_boot, T_first_memory
  disk.json         # D_code, D_bin, D_models, D_data, allocation, pagefile
  services.json     # name, pid, status, pid_tree
```

Table finale à remplir (une ligne par grandeur, jamais un total unique) :

| grandeur | C1 (n=3) | C1p (n=1) | C2 (n=3) | instrument |
|---|---|---|---|---|
| RAM repos privé (Go), médiane [min–max] | | | | O1 + O2 |
| RAM charge p50 / pic (Go) | | | | O1 + O2 |
| `D_code` / `D_bin` / `D_models` / `D_data` | | | | taille logique + allocation |
| `T_install` total + 4 étapes (s) | | | | acceptance + chrono |
| `T_boot` / `T_first_memory` (s) | | | | monotone + status |
| p95 `rag search` (ms) | | | | charge W |
| nombre de process | | | | status |

Chaque cellule porte sa **source** ; une cellule vide est UNKNOWN, pas 0.

---

## 6. Ce que ce protocole ne mesure pas

- La génération locale (Ollama / llama-server 7B), le consolidateur (l.1946), TLS, Qdrant,
  l'UI, le multi-utilisateur, netcfg.
- Le corpus réel de l'owner (52 Go) : interdit au balayage ; seulement extrapolé.
- L'installation réellement réduite (pas de pack) et le coût de maintenance d'un second chemin.
- L'effet antivirus/Windows Update : l'état AV est déclaré ; une exclusion n'est admise que
  comme **variante** documentée.

---

## 7. Ordre d'exécution

1. Ratifier le critère de décision §0.
2. Snapshot VM, relever machine/compte/horloge/AV, ligne de base OS.
3. Poser §2.2, vérifier `sous_mesure = true`.
4. Construire D1, geler, empreinte ; vérifier D0 vide.
5. Cloner le dépôt au commit ; lancer l'inventaire §1.4 (attendu 105/33/72/4/68).
6. Produire le clone de mesure C1 (68 `disabled=true`), hasher le TOML.
7. Installer à froid (M4), chronométrer les 4 étapes ; mesurer M3 sur D0.
8. Démarrer C1, mesurer T_boot/T_first_memory, attendre 1 cycle SSoT + 300 s.
9. M1, puis M2. Trois runs ; à chaque run, manifeste + CSV.
10. Rejouer 7-9 pour C2 (TOML d'origine), même corpus, même W.
11. C1p, n = 1.
12. Remplir §5, publier les plages et les UNKNOWN ; conclure **contre le seuil pré-enregistré**.