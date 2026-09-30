# Plan — suite de tests portable sous Linux (sessions cloud)

Rédigé le 2026-09-28 sur go owner. Branche de travail : `cloud-base` (jamais `alpha`).

## Pourquoi

Les sessions cloud Claude Code tournent sous Linux, loin du PC de l'owner : ni hub `:8766`,
ni coffre DPAPI, ni services Windows, ni runner self-hosted. Aujourd'hui la seule CI qui fait
foi (`.github/workflows/ci-selfhosted.yml`) tourne sur le runner Windows de l'owner ;
`.github/workflows/ci.yml` (matrice ubuntu/macos/windows, déclenchement manuel, liste de
fichiers écrite en dur) est rouge depuis le 2026-06-06.

But : un sous-ensemble **mesuré** de la suite passe sous Linux, **sans rien changer au
comportement sous Windows**.

## Mesures de départ (recon statique du 2026-09-28)

Repérage par motifs d'API Windows (`windll`, `winreg`, DPAPI, `nssm`, `schtasks`, `icacls`,
`powershell`, chemins `C:/`, `.exe`…).

| zone | fichiers de test | dépendants non gardés | déjà gardés |
|---|---|---|---|
| `tests/nr/` | 2150 | 116 | 3 |
| `tests/` (racine) | 188 | 19 | 2 |
| `app/tests/` | 8 | 1 | — |

Modules `app/` qui importent Windows **au niveau module** (donc cassent la collecte Linux de
tout test qui les importe) : `forge_env_crypt`, `forge_hub_worker`, `forge_machine_vault`,
`forge_memory`, `forge_persona_tpm`, `forge_phi3_npu`, `forge_provider_admin`,
`forge_settings`, `forge_skill_curator`, `forge_web_service`.

**Ces chiffres sont un plancher, pas un compte.** Le motif ne voit pas les dépendances
indirectes (un test sans motif qui importe l'un des 10 modules). La mesure qui fait foi est
la collecte réelle sous Linux, faite en phase 1.

## Règles communes à toutes les sessions

1. **Départ** : `git fetch origin cloud-base` puis `git switch -c <ta-branche> origin/cloud-base`.
   Ce plan n'existe que sur `cloud-base`.
2. **PR vers `cloud-base`, jamais vers `alpha`.** Une PR vers `alpha` déclenche
   `ci-selfhosted.yml` sur le runner self-hosted du PC de l'owner : du code non relu
   s'exécuterait sur sa machine.
3. **Ne toucher que les fichiers de ton lot** (listes ci-dessous). Jamais
   `ci-selfhosted.yml`, `gitleaks.yml`, `tools/ci_local.py`, ni `git add -A` : ajouter les
   fichiers un par un.
3 bis. **`.github/` est fermé.** Pour un `push`, GitHub exécute le workflow tel qu'il est
   DANS la branche poussée : un workflow modifié sur une branche de travail tournerait avant
   toute PR. Donc : seule la session A crée un fichier dans `.github/`, et c'est
   `.github/workflows/ci-linux.yml`, rien d'autre. Ce fichier : `runs-on: ubuntu-latest`
   uniquement (le mot `self-hosted` n'apparaît nulle part), déclencheurs `pull_request` vers
   `cloud-base` et `workflow_dispatch` seulement, `permissions: contents: read`, aucune
   référence à `secrets.`, `timeout-minutes` sur chaque job, `concurrency` avec
   `cancel-in-progress: true` (les minutes Actions d'un dépôt privé sont comptées). Si GitHub
   refuse le push de ce fichier faute de droit `workflows`, pousser le reste et mettre le
   contenu du fichier dans la description de la PR : l'owner l'ajoutera.
4. **Windows inchangé.** Une garde de plateforme AJOUTE un chemin Linux ; elle ne réécrit
   pas le chemin Windows (le code Windows est seulement placé sous la garde).
5. **Marquer, jamais supprimer.** Un test qui exige Windows reçoit le marqueur `windows`
   (`pytestmark` si tout le fichier, sinon par test). Aucun test supprimé, aucune assertion
   affaiblie, aucun `xfail` pour masquer un échec.
6. **Un échec Linux qui n'est PAS une dépendance Windows** (séparateur `\\`, encodage,
   ordre, bug réel) ne se corrige pas dans `app/` en phase 2 : le lister dans la
   description de PR (fichier:ligne + sortie pytest). Il fera l'objet d'une session dédiée.
7. **Sauté n'est pas vert.** Tout rapport compte séparément passés / sautés / échoués /
   erreurs de collecte. Un test sauté sous Linux reste non vérifié sous Linux.
8. **Aucun secret** : aucun jeton, clé, contenu de `.env` ou du coffre, ni dans le code, ni
   dans les tests, ni dans la PR. Un test qui exige un secret ou un service local est marqué,
   jamais alimenté.
9. **Le hub n'existe pas dans le cloud.** `CLAUDE.md` et `RULES_SHARED.md` décrivent le PC
   de l'owner (outils `mcp__laforge-sovereign-hub__*`, `governed_edit`, `run_job`) : en
   session cloud, utiliser les outils natifs. Les invariants de fond restent (règles 5 à 8,
   `UNKNOWN` ≠ `NO`, commits petits et nommés).
10. **Réseau** : PyPI est nécessaire pour installer les dépendances (`requires-python >= 3.12`,
    extras dans `pyproject.toml`). À vérifier dans l'environnement cloud ; si PyPI est
    bloqué, le dire dans la PR et s'arrêter. Rien d'autre n'est requis : pas d'Ollama, pas
    de Docker, pas de modèle.

## Phase 1 — session A, seule, avant les autres

**Fichiers du lot A** : `pyproject.toml` (section des marqueurs pytest uniquement),
`tests/conftest.py`, les 10 modules `app/` listés plus haut,
`.github/workflows/ci-linux.yml` (nouveau), `tests/linux_baseline/A-socle.txt` (nouveau).

1. **Marqueurs** : lire d'abord `[tool.pytest.ini_options] markers` et réutiliser un
   marqueur existant s'il a déjà ce sens. Sinon déclarer `windows` (exige Windows) et
   `local_stack` (exige le hub, le coffre ou un service du PC de l'owner).
2. **`tests/conftest.py`** : hors `win32`, sauter les tests `windows` et `local_stack` avec
   une raison explicite. Sous `win32`, aucun changement de comportement.
3. **Les 10 modules** : imports Windows conditionnels. Une fonction Windows appelée sous
   Linux lève une erreur explicite qui nomme l'indisponibilité ; jamais un faux succès
   silencieux ni une valeur par défaut qui passerait pour un résultat.
4. **`ci-linux.yml`** : conforme à la règle 3 bis, Python 3.12.
   Étapes : installation, import des 10 modules, puis
   `pytest -m "not windows and not local_stack"` sur la concaténation des fichiers de
   `tests/linux_baseline/*.txt`.
5. **Mesure** : collecte complète sous Linux (`pytest --collect-only -q tests app/tests`),
   erreurs de collecte comptées par fichier ; `A-socle.txt` = les fichiers verts sous Linux
   à ce stade.

**Critère de fin A** : les 10 modules s'importent sous Linux par le chemin qu'utilisent les
tests ; `ci-linux` vert sur la PR ; le diff des 10 modules ne modifie aucune branche
`win32` ; la PR donne les chiffres (collectés, passés, sautés, échoués, erreurs de collecte).

## Phase 2 — sessions B, C, D, E en parallèle, après fusion de A dans `cloud-base`

Lots disjoints. Chaque session n'écrit que dans ses fichiers de test et dans SON fichier de
baseline : aucun conflit possible entre sessions.

| session | fichiers de test | dépendants repérés | fichier de baseline |
|---|---|---|---|
| B | `tests/nr/test_a*` à `tests/nr/test_c*` | 32 | `tests/linux_baseline/B-nr-a-c.txt` |
| C | `tests/nr/test_d*` à `tests/nr/test_o*` | 39 | `tests/linux_baseline/C-nr-d-o.txt` |
| D | `tests/nr/test_p*` à `tests/nr/test_z*` | 45 | `tests/linux_baseline/D-nr-p-z.txt` |
| E | `tests/test_*.py` (racine), `tests/unit/`, `tests/biblio/`, `app/tests/` | 20 | `tests/linux_baseline/E-racine-unit-app.txt` |

Pour chaque fichier du lot, sous Linux : vert → ajouté à la baseline du lot ; dépendance
Windows ou pile locale → marqué (règle 5) ; autre échec → listé dans la PR (règle 6).

**Critère de fin (par session)** : chaque fichier du lot est soit dans la baseline du lot,
soit marqué, soit listé dans la PR avec sa raison ; `ci-linux` vert sur la PR ;
`git diff --name-only origin/cloud-base` ne contient que des fichiers du lot et sa baseline.

## Phase 3 — locale, owner (hors cloud)

Avant chaque fusion dans `cloud-base` : l'owner relit le diff complet de `.github/`
(règle 3 bis). Le runner self-hosted reste ARRÊTÉ pendant toute la phase cloud et ne repart
qu'après cette relecture.

CI de référence Windows sur `cloud-base` fusionnée : les marqueurs ne doivent changer AUCUN
résultat sous Windows. Seulement ensuite, fusion vers `alpha`.

## Hors périmètre

Coffre et secrets (chantier local owner), hub, services, `tools/ci_local.py` et sa liste
`PURE_TESTS`, workflows existants.
