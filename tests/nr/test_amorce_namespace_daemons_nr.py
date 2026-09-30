"""NR — un daemon lance PAR CHEMIN doit pouvoir ecrire son pouls.

Defaut mesure le 2026-09-20. `NokidoOrganPulse` et `NokidoCardiacNode` etaient
morts depuis le 2026-09-10 06:45 (pid 20408 et 16396 : `aucune tache`), et leur
`.heartbeat` fige a 10,4 jours. Trois diagnostics successifs ont ete faux avant
que l'execution ne tranche :

    {"verdict": "embolie", ...}          <- le tour SE FAIT
    Traceback (most recent call last):
    ModuleNotFoundError: No module named 'nokido_agent'

Le daemon faisait son cycle, puis CRASHAIT en important
`nokido_agent.app.forge_heartbeat` pour ecrire son pouls. Donc : un log qui
grossit (le tour a lieu), un pouls fige (l'ecriture n'a jamais lieu), et un
service qui meurt a chaque tour.

CAUSE : lance par chemin, `sys.path[0]` vaut le dossier du SCRIPT, pas la racine
du depot. `forge_organ_pulse` ajoutait `ROOT/app` et `ROOT/tools` — mais PAS
`ROOT`, ou vit le package `nokido_agent`. `forge_service_crash_watcher` porte
l'amorce correcte et, lui, demarre.

⚠️ CE QUE CE TEST VERROUILLE : l'amorce, pas le texte. On charge le module PAR
SON FICHIER, comme le superviseur, et on exige que l'import canonique du pouls
passe ensuite. Verifier la presence d'une ligne dans la source ne prouverait
rien — un correctif peut se relire juste et ne rien changer (2026-09-20).

Pur : aucun service, aucun reseau. On charge des modules et on restaure `sys.path`.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent

# Les daemons qui ecrivent leur pouls par le chemin canonique et sont lances par
# chemin depuis services.toml. En ajouter un ici est GRATUIT ; l'oublier coute
# dix jours de mort silencieuse.
DAEMONS = [
    ("forge_organ_pulse", RACINE / "tools" / "forge_organ_pulse.py"),
    ("forge_cardiac_node", RACINE / "app" / "forge_cardiac_node.py"),
    ("forge_service_crash_watcher", RACINE / "tools" / "forge_service_crash_watcher.py"),
]


def _charge_par_chemin(nom: str, chemin: Path):
    """Charge comme le superviseur : par FICHIER, sans preparer le path."""
    spec = importlib.util.spec_from_file_location("nr_" + nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_chaque_daemon_amorce_la_racine_du_depot(monkeypatch):
    """Apres chargement, la RACINE doit etre dans `sys.path` — c'est la seule
    condition pour que `from nokido_agent...` ne leve pas."""
    manquants = []
    for nom, chemin in DAEMONS:
        assert chemin.exists(), "daemon introuvable : %s" % chemin
        sauvegarde = list(sys.path)
        try:
            # On RETIRE la racine avant, sinon le test passerait grace a
            # l'environnement de pytest et ne prouverait rien.
            sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != RACINE]
            try:
                _charge_par_chemin(nom, chemin)
            except Exception as e:  # noqa: BLE001
                manquants.append("%s : %s au chargement" % (nom, type(e).__name__))
                continue
            if not any(Path(p or ".").resolve() == RACINE for p in sys.path):
                manquants.append("%s : la racine n'est pas amorcee" % nom)
        finally:
            sys.path[:] = sauvegarde
    assert not manquants, (
        "lance PAR CHEMIN, ce daemon ne peut pas importer `nokido_agent`, donc "
        "pas ecrire son pouls : il mourra a chaque tour, apres avoir travaille, "
        "et son heartbeat fige se lira comme une mort sans cause. %s" % manquants
    )


def test_l_import_canonique_du_pouls_passe_apres_amorce():
    """Le point precis qui tuait : `nokido_agent.app.forge_heartbeat`."""
    sauvegarde = list(sys.path)
    try:
        sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != RACINE]
        _charge_par_chemin("forge_organ_pulse", RACINE / "tools" / "forge_organ_pulse.py")
        from nokido_agent.app.forge_heartbeat import beat_daemon  # noqa: F401
    finally:
        sys.path[:] = sauvegarde
