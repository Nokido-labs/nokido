# Veille Stratégique : Accélération de Suite de Tests & CI (2024-2026)
**Auteur :** Antigravity (Recherche & Synthèse)  
**Date :** 10 novembre 2026  
**Cible :** Nokido — Réduction drastique des temps de CI locale (Windows) et distante (GitHub Actions) sans dégradation de la couverture (21 030 tests, 2 209 fichiers).

---

## 1. Contexte & Problématique Mesurée
- **Suite locale :** 21 030 tests répartis sur 2 209 fichiers, 1 072 s mur (xdist 2 workers sous Windows), 3 028 s CPU cumulé.
- **Points de friction constatés :**
  - Collecte lente (`tests/nr` seul = 54 s de pure collecte).
  - Distribution asymétrique : 1 fichier prend 207 s, le top 15 représente 24 % du temps total.
  - Fragilité xdist sous Windows : worker tué, blocage à 99 % sur tests synchrones/bloquants.
  - Redondance triple : CI locale `ci_local.py` $\rightarrow$ CI GitHub privée (`suite-pure.yml` matrix OS, cap 90 min) $\rightarrow$ CI miroir publique (`workflow_run`).

---

## 2. Analyse Thématique des Meilleures Pratiques (2024–2026)

### a. Sélection de Tests par Impact & Prédictive (TIA / PTS)
* **Pratiques reconnues :**
  - **Déterministe (Test Impact Analysis / RTS) :** `pytest-testmon` instrumente l'exécution via `coverage.py`, stocke le graphe fichier/fonction $\leftrightarrow$ test dans SQLite (`.testmondata`) et ne réexécute que les tests couvrant les blocs modifiés.
  - **Statistique / ML (Predictive Test Selection - PTS) :** Meta (Machalica et al., ICSE-SEIP) et Google TAP entraînent des modèles (ex. GBDT/XGBoost) prédisant la probabilité d'échec par test selon le diff de code, la distance dans le graphe d'appel et l'historique de défaillances. Solutions SaaS : Launchable, Datadog Intelligent Test Runner.
* **Gains chiffrés mesurés :**
  - `pytest-testmon` : désélection de 85 % à 95 % des tests en développement itératif et CI de PR (feedback loop réduit de 15 min à < 1-2 min).
  - Meta PTS : réduction de 2× des coûts d'infrastructure de test, exécution de seulement 1/3 des tests dépendants tout en interceptant > 99,9 % des régressions.
* **Sources :**
  - *pytest-testmon* : https://testmon.org et https://github.com/tarpas/pytest-testmon
  - *Meta PTS* : Machalica et al., "Predictive Test Selection" (ICSE / arXiv:1810.05273) ; https://engineering.fb.com
  - *Launchable Predictive Test Selection* : https://www.launchableinc.com
* **Pièges majeurs :**
  - Métaprogrammation, imports dynamiques ou fixtures globales non tracées par AST/coverage pouvant mener à des faux négatifs (test omis alors que le code casse).
  - Coût d'initialisation (baseline complète obligatoire pour amorcer la base).
  - Concurrence sur `.testmondata` en environnement multi-workers si mal configuré.
* **Applicabilité à Nokido :**
  - **Excellente en local et PR :** Nokido dispose déjà d'un sélecteur statique `--impacte`. Compléter ou fiabiliser avec le traçage dynamique de `pytest-testmon` pour les commits locaux de dev. Le run complet (full suite) est alors réservé à la nuit ou avant release.

---

### b. « Build Once / Verify Once, Promote » (Cache de Verdict & Déduplication)
* **Pratiques reconnues :**
  - Éviter la triple exécution identique (Local $\rightarrow$ Dépôt privé $\rightarrow$ Dépôt public).
  - **Arbre immuable / Tree-hash :** Hachage cryptographique du code source et des dépendances (`git rev-parse HEAD^{tree}` + hash de lockfile). Si ce digest a déjà un statut vert validé et signé dans un cache partagé (ou commit status GitHub), la CI aval court-circuite l'exécution (`PASS cached`).
  - **Promotion d'artefacts / Workflow Run :** Le miroir public ne doit pas recalculer la suite pure si le commit SHA privé correspondant a déjà passé la validation de signature. Il lit l'attestation ou le statut GitHub.
  - **GitHub Merge Queue :** Regroupe les PR prêtes et teste la combinaison spéculative une seule fois en tête de branche plutôt que de retester chaque rebase individuellement.
* **Gains chiffrés mesurés :**
  - Élimination de 100 % des runs redondants sur le miroir public (gain immédiat de 30 à 60 minutes de runner GitHub par push).
  - Économie de 50 à 70 % des runs CI lors de modifications touchant uniquement la documentation, les assets ou des fichiers isolés.
* **Sources :**
  - *GitHub Merge Queue* : https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue
  - *Reproducible Builds & Verdict Caching* : Martin Fowler ("DeploymentPipeline") ; Google Bazel Remote Caching https://bazel.build
* **Pièges majeurs :**
  - Invalidation de cache insuffisante si l'environnement externe change (ex. mise à jour d'un binaire système ou d'un paquet distant sans lockfile figé).
  - Clé de cache basée uniquement sur le SHA de commit plutôt que sur le Tree SHA (un rebase sans modification de code change le commit SHA mais garde le même arbre).
* **Applicabilité à Nokido :**
  - **Action immédiate :** Remplacer le re-jeu complet de la suite sur le miroir public par une vérification d'attestation (`gh api repos/.../commits/{sha}/check-runs` ou statut git signé).

---

### c. Sharding GitHub Actions & Caching Moderne (uv / pip)
* **Pratiques reconnues :**
  - **Sharding temporel équilibré (`pytest-split`) :** Plutôt que de diviser naïvement les tests par dossier ou par ordre alphabétique, `pytest-split` utilise le fichier historique `.test_durations` pour partitionner la suite en $N$ shards de durées strictement égales (algorithme glouton de bin-packing).
  - **Orchestration Matrix GitHub Actions :** Exécution de 4 à 8 shards en parallèle (`matrix: [1, 2, 3, 4]`).
  - **Gestionnaire ultra-rapide `astral-sh/setup-uv` :** Remplacement de `pip` par `uv` (`uv sync --locked`). `uv` exploite le multithreading Rust et le partage global de cache par hardlinks.
* **Gains chiffrés mesurés :**
  - `pytest-split` : passage d'un job monolithique de 60 min à 4 shards de 15 min ou 8 shards de ~8 min (division quasi-linéaire du temps mur).
  - `uv` vs `pip` : installation d'environnement passée de 45-90 s à 5-15 s (froid) et < 3 s (chaud), soit 30 à 40 % de gain sur le cycle de vie global du conteneur/runner.
* **Sources :**
  - *pytest-split* : https://github.com/jerry-git/pytest-split
  - *Astral uv CI Documentation* : https://docs.astral.sh/uv/guides/integration/github/
  - *GitHub Actions Matrix Strategy* : https://docs.github.com/en/actions/using-jobs/using-a-matrix-for-your-jobs
* **Pièges majeurs :**
  - Fichier `.test_durations` obsolète si non rafraîchi régulièrement (dérive de l'équilibrage).
  - Sous Windows GitHub Actions, la latence I/O disque est supérieure à Linux ; l'extraction de cache volumineux peut grignoter une partie du gain si le cache n'est pas ciblé.
* **Applicabilité à Nokido :**
  - Déployer `pytest-split` sur `suite-pure.yml` (ex. 4 runners Ubuntu/Windows en parallèle pour descendre sous les 15 minutes). Adopter `uv sync` dans les workflows GitHub.

---

### d. Quarantaine, Détection de Blocages & Spécificités Windows
* **Pratiques reconnues :**
  - **Quarantaine / Test Smells :** Marquer les tests instables ou les tests lourds d'intégration hors du chemin critique bloquant (`@pytest.mark.flaky`, `@pytest.mark.slow`, tag quarantine exécuté en nightly/asynchrone sans bloquer la fusion).
  - **Spécificité Windows pour `pytest-timeout` :**
    - Sous Unix, `pytest-timeout` utilise la méthode `signal` (`SIGALRM`).
    - **Sous Windows, `signal` n'existe pas :** `pytest-timeout` bascule obligatoirement sur la méthode `thread`.
    - **Le piège fatal du mode `thread` :** Si un test bloque dans un appel C natif ayant relâché le GIL (socket réseau Windows synchrone, subprocess Windows `WaitForSingleObject`, driver SQLite verrouillé), l'interruption logicielle du thread Python ne peut pas s'injecter. Le worker fige indéfiniment à 99 %.
  - **Gestion des crashs xdist :** Activer `--maxprocesses`, `--dist=loadfile` (groupe les tests d'un même fichier sur le même worker pour limiter les conflits de fixtures) et `--looponfail` en local.
* **Gains chiffrés mesurés :**
  - Élimination des gels de runners bloqués 90 min (perte sèche de quota GitHub Actions).
  - Isolation du top 15 des fichiers (24 % du temps total) et du fichier isolé à 207 s : gain immédiat de 25 à 30 % sur la boucle rapide locale.
* **Sources :**
  - *pytest-timeout documentation* : https://pytest-timeout.readthedocs.io
  - *pytest-xdist issue tracker (Windows worker hangs & GIL)* : https://github.com/pytest-dev/pytest-xdist
  - *Martin Fowler - Eradicating Non-Determinism in Tests* : https://martinfowler.com/articles/non-determinism.html
* **Pièges majeurs :**
  - Se reposer aveuglément sur `pytest-timeout` sous Windows en pensant qu'il tuera les boucles natives.
  - Risque d'accumuler des tests en quarantaine sans plan de remédiation technique.
* **Applicabilité à Nokido :**
  - Définir des timeouts stricts au niveau transport/socket (`socket.setdefaulttimeout(5.0)`) et requêtes SQLite au lieu d'attendre l'interruption de `pytest-timeout`.
  - Isoler le fichier à 207 s dans un bucket de test dédié (exécution séparée ou nightly).

---

### e. Coût de Démarrage Pytest (Collecte, Conftest & Imports)
* **Pratiques reconnues :**
  - **Diagnostic :** Mesurer précisément la phase de découverte via `pytest --collect-only` et profiler les imports avec `python -X importtime -m pytest --collect-only`.
  - **Lazy Imports dans les tests :** Déplacer les imports de modules massifs (IA, torch, pandas, drivers ou gros composants de `app/`) à l'intérieur des fonctions de test ou des fixtures plutôt qu'au niveau module (top-level).
  - **Nettoyage des `conftest.py` :** Supprimer toute exécution active (connexion DB, scan filesystem, lecture de registre) exécutée à l'import de `conftest.py`.
  - **Délimitation stricte du scope :** Forcer `testpaths = tests` et configurer `norecursedirs = .git venv .gemini build dist` dans `pytest.ini` / `pyproject.toml` pour éviter que pytest ne parcoure l'arborescence complète du worktree lors de la découverte AST.
* **Gains chiffrés mesurés :**
  - Réduction de la phase de collecte de 54 s à < 8-10 s sur des suites Python de 20 000+ tests (gain documenté de 70 à 85 % sur la seule découverte).
* **Sources :**
  - *Python Official Doc (-X importtime)* : https://docs.python.org/3/using/cmdline.html#cmdoption-X
  - *Pytest Performance Optimization Guide* : https://docs.pytest.org
* **Pièges majeurs :**
  - Fixtures `autouse=True` de portée session dans un `conftest.py` racine qui s'exécutent même sur un test unitaire isolé.
* **Applicabilité à Nokido :**
  - Audit immédiat avec `-X importtime` sur `tests/nr`. Transformer les imports de packages lourds situés en en-tête des fichiers `test_*.py` en imports locaux dans les fixtures/fonctions de test.

---

### f. Pyramide & Étagement Idéal des Tests
Pour maximiser la vélocité sans compromettre la sécurité, l'exécution doit suivre un entonnoir strict :

| Étage | Déclencheur | Périmètre & Outils | Budget Temps |
| :--- | :--- | :--- | :--- |
| **1. Pre-commit / Local instantané** | `git commit` ou dev itératif | Linters légers (Ruff), vérification statique AST, sélection d'impact ciblée (`--impacte` / `testmon`). Uniquement les tests du module modifié. | **< 15 secondes** |
| **2. Pre-push / CI locale complète** | `git push` ou appel `ci_local.py` | Lints complets, audits de sécurité, suite unitaire rapide sans tests lourds (sans le top 15 des fichiers lents). | **< 3 à 5 minutes** |
| **3. PR / CI GitHub Privée** | Ouverture / mise à jour de PR | Matrix GitHub Actions avec `pytest-split` (4 à 8 shards parallèles sous Linux/Windows) + runner self-hosted pour la suite pure complète. | **< 10 à 15 minutes** |
| **4. Promotion / Miroir Public** | Succès de la PR privée | Vérification de signature / Tree-hash. **Aucun re-calcul de test** si le code est identique. | **< 1 minute** |
| **5. Nightly / Cadence lente** | Quotidien (nuit) / Release | Suite complète non shardée, tests en quarantaine, tests de performance, simulations de pannes, tests d'intégration lents (le fichier de 207 s et le top 15). | **Libre (1 à 2 h)** |

---

## 3. Recommandations Classées par Ratio Gain / Effort

| Priorité | Action Recommandée | Cible | Effort | Gain Attendu |
| :---: | :--- | :--- | :---: | :--- |
| **P1** | **Court-circuiter le miroir public via Tree-hash / Commit Status** | CI Miroir | **Très Faible** | **100 % d'économie** sur la 3e CI (évite de rejouer 90 min de suite pure). |
| **P2** | **Sharder GitHub Actions avec `pytest-split` + `astral-sh/setup-uv`** | CI GitHub privée | **Faible** | Temps mur divisé par 4 à 6 sur GitHub Actions (de 60-90 min à ~12-15 min). |
| **P3** | **Optimiser la collecte pytest (Audit `-X importtime` & Lazy Imports)** | Local & CI | **Moyen** | Collecte ramenée de 54 s à < 10 s sur chaque invocation pytest. |
| **P4** | **Séparer le fichier de 207 s et le Top 15 lent en suite asynchrone / nightly** | Local `ci_local.py` | **Faible** | Gain immédiat de ~25 % (250 s CPU) sur la boucle locale de développement. |
| **P5** | **Durcir les timeouts I/O natifs (Sockets / DB) contre les hangs Windows** | Local Windows | **Moyen** | Suppression définitive du bug du worker xdist figé à 99 %. |
| **P6** | **Intégrer `pytest-testmon` dans la commande `--impacte` locale** | Dev local | **Moyen** | Feedback itératif TDD quasi-instantané (< 5 s) sur le poste de travail. |

---
*Fin du document de veille technique.*
