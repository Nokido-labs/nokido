# Fiche de sortie — Veille V6 « Infrastructure fonctionnelle : SQLite · WSL · Docker · cycle de vie · stockage · pannes » (2026-09-23)

Contrat : PATTERNS → NOKIDO_EXISTING → EVIDENCE → GAPS → MINIMAL_EXPERIMENT → NR → DECISION. Pipeline B.
Interroge V1–V5 et les incidents MESURÉS aujourd'hui (WAL 23 puis 48 Go, V: à 3,1 Gio, `database is locked`, RSS).

## 1. PATTERNS (`watch:infra_sqlite|infra_wsl|infra_docker|infra_lifecycle|infra_fault:%`)

| Pattern | Source |
|---|---|
| Un seul écrivain à la fois par base ; `BEGIN IMMEDIATE` pour prendre le verrou d'écriture tôt ; `busy_timeout` | SQLite FAQ, transactions, busy handler |
| Famine de checkpoint : un lecteur ouvert empêche la remise à zéro du WAL ; `journal_size_limit` rétrécit le fichier | SQLite wal.html (veille SQLite) |
| Bug WAL-reset (corruption rare, multi-processus) corrigé en **3.51.3** | SQLite, historique des versions |
| Causes de corruption : FS réseau/partagé, verrous POSIX, descripteurs réutilisés ; SQLite sur FS réseau déconseillé | howtocorrupt, useovernet |
| Sauvegarde À CHAUD : Online Backup API, `VACUUM INTO` ; une sauvegarde n'est valide qu'une fois RESTAURÉE et vérifiée | backup.html, lang_vacuum |
| WSL : ne pas travailler « à cheval » sur les FS ; données Linux dans ext4, pas `/mnt/c` ; `autoMemoryReclaim` | WSL filesystems, wsl-config |
| Docker : dépendance prête ≠ démarrée (`service_healthy` + healthcheck) ; données en volumes ; limites mémoire / OOM | Docker Compose startup order, Dockerfile HEALTHCHECK, resource constraints |
| Cycle de vie : Job Objects (arbre de processus Windows), SCM, systemd `Restart=`/`WatchdogSec=` ; logiciel « crash-only » | Microsoft, freedesktop, Candea (HotOS 2003) |
| Chaos engineering : hypothèse d'état stable, injection réelle, rayon d'explosion minimal | principlesofchaos.org ; Toxiproxy ; tests SQLite par injection |

## 2. NOKIDO_EXISTING + MESURES DU JOUR

- SQLite : **deux runtimes** — `laforge_py314` = 3.53.0 ; `miniforge3\python.exe` (LAFORGE_PYTHON) = **3.51.1**.
  `.githooks/post-commit` lance l'indexation RAG (`forge_post_commit.py`) **avec 3.51.1** → la version vulnérable EST
  dans le chemin d'écriture, en concurrence avec le hub (3.53). **MEASURED.**
- Pragmas d'écriture : WAL, `busy_timeout`, `synchronous=NORMAL`, `wal_autocheckpoint=500`, `mmap_size` 2 Go,
  **`journal_size_limit` 64 Mo depuis `97d552a90`** (VERIFIED par NR chemin réel + raffinage : WAL ≤ 738 Mo).
- Écrivains : `open_writer`/`write_retry` ; séparation M2M (`m2m.switch`), journaux (`journaux.switch`), campagne
  de veille = 1 écrivain + collecte parallèle.
- V: = volume virtuel de 100 Go (aucun disque physique ne le porte dans le mappage) — probablement un VHD sur le NVMe
  système (Disk #2) : **INCONNU** (fichier non localisé), cohérent avec « NVMe à 100 % » pendant l'ingestion.
- Docker = prothèse dynamique (`docker.wanted`, `forge_docker_keeper`) ; WSL présent (`vmmemWSL`).
- Services : NSSM + `supervisor.ts` ; relance du hub = lanceurs du bureau (owner).
- Sauvegarde de `%NOKIDO_DATA%\embeddings.db` (32 Go) : **non trouvée** dans ce qui a été lu → INCONNU (à chercher avant de conclure).

## 3. EVIDENCE

| Élément | Niveau |
|---|---|
| Version vulnérable dans le chemin d'écriture | **MEASURED** (post-commit → 3.51.1) |
| `journal_size_limit` efficace | **VERIFIED** |
| WAL bloqué par un lecteur long | **MEASURED** (48 Go, libéré par redémarrage manuel) |
| Placement V: sur le NVMe système | **OBSERVED** (volume absent du mappage physique), non vérifié |
| Sauvegarde restaurable de la base RAG | **absente de ce qui a été lu** (UNKNOWN) |
| Injection de pannes | **absente** : les pannes du jour ont été SUBIES, pas injectées |

## 4. GAPS

1. **Version SQLite hétérogène** entre écrivains (3.51.1 / 3.53) sur la même base WAL.
2. **Aucune sauvegarde restaurable prouvée** de la base de 32 Go (sous réserve de recherche).
3. **Placement du stockage non mesuré** (V: sur NVMe système ? contention avec l'OS et Windows Defender).
4. **Pas de banc de pannes** : les modes de défaillance du jour (RSS, verrou, disque plein, lecteur long) ne sont
   rejoués nulle part.
5. Healthchecks : la doctrine `TRANSPORT ≠ APPLICATIF ≠ CAPACITÉ` existe ; son application service par service
   (preuve fonctionnelle, pas un port ouvert) n'est pas mesurée ici.

## 5. MINIMAL_EXPERIMENTS

(a) **Mise à jour `libsqlite ≥ 3.51.3` dans `base`** (geste owner, commande fournie), versions capturées avant/après.
(b) Banc de contention reproductible (fixture, pas la vraie base) : 2 processus écrivains + 1 lecteur long → mesurer
    busy, taille WAL, durée des verrous, avec les DEUX versions de SQLite. La mise à jour n'est PAS la preuve.
(c) `VACUUM INTO` d'une copie + `PRAGMA integrity_check` + requêtes critiques sur la copie → sauvegarde RESTAURABLE.
(d) Localiser le fichier du volume V: (lecture seule).

## 6. NR

`test_contention_wal_banc_nr` (fixture : lecteur long ⇒ WAL borné grâce à `journal_size_limit`, 0 perte) ;
`test_runtime_ecrivain_sqlite_minimal_nr` (tout interpréteur lancé par un hook d'écriture a SQLite ≥ 3.51.3 —
échoue aujourd'hui sur `miniforge3`, c'est le rouge attendu).

## 7. DECISION

- **CORRIGER** la dépendance (a) — preuve par (b), pas par la mise à jour seule.
- **À TERME** : un seul environnement Python contractuel pour tous les écrivains (hooks inclus), au lieu de `base` implicite.
- **COMPLÉTER** : sauvegarde restaurable (c) ; banc de pannes à partir des incidents RÉELS du jour.
- UNKNOWN : emplacement de V: ; existence d'une sauvegarde.
- Contradiction : V1 supposait des « pannes partielles » à détecter ; V6 montre qu'elles sont d'abord **infrastructurelles**
  (disque, verrou, version) — la supervision agentique (V1) doit lire ces signaux d'infrastructure, pas seulement ceux des agents.
