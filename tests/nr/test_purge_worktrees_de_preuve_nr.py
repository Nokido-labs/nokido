"""NR -- purge quotidienne des worktrees de preuve de la CI (2026-09-24, question owner).

Mesure : 126 entrees dans sandbox/workspace/tmp/nokido_proof (11/09 -> 22/09) ; ci_local cree
un worktree PAR execution et ne le retire jamais. Ce NR fige :
  - garde : les PROOF_KEEP plus recents ET tout ce qui a moins de PROOF_DAYS ;
  - retrait PAR GIT (par chemin) avant toute suppression de dossier ;
  - si git echoue, le dossier n'est PAS supprime a la main (pas de reference orpheline) ;
  - `git worktree prune` en fin de passage ; simulation = aucune mutation.

REGRESSION DE MA MAIN, mesuree le soir meme en production : la purge resolvait sa racine par
`fw.PROOF_ROOT`, qui vaut le TEMP du compte qui l'evalue -- le service de retention lisait
`C:\\WINDOWS\\TEMP\\nokido_proof` (« zone absente ») et ne purgeait RIEN. La 1re version de ce NR
passait parce qu'elle FORCAIT `PROOF_ROOT` sur la zone de test : elle testait la fonction, pas
le chemin reel. D'ou `test_la_racine_de_la_ci_est_trouvee_quel_que_soit_le_compte`, sans double.
"""
from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path

import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (l.136)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
for p in (str(RACINE), str(RACINE / "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

import forge_log_retention as lr  # noqa: E402
import forge_worktree as fw  # noqa: E402

JOUR = 86400


@pytest.fixture()
def zone(tmp_path, monkeypatch):
    maintenant = time.time()
    ages = {"ci-reference-r1": 1, "ci-reference-r2": 2, "ci-reference-v1": 10,
            "ci-reference-v2": 11, "ci-reference-v3": 12, "ci-reference-casse": 13,
            "ci-reference-sansgit": 14, "ci-reference-sansgit-reference": 15}
    for nom, j in ages.items():
        e = tmp_path / nom
        (e / "worktree").mkdir(parents=True)
        (e / "artefacts").mkdir()
        if not nom.startswith("ci-reference-sansgit"):   # un vrai worktree git porte un FICHIER .git
            (e / "worktree" / ".git").write_text("gitdir: ailleurs\n", encoding="utf-8")
        if nom == "ci-reference-sansgit":
            # objet git de fixture pytest en LECTURE SEULE (mesure prod 24/09 : 137/137 restants)
            objet = e / "artefacts" / "depot" / ".git" / "objects" / "0b" / "b16635"
            objet.parent.mkdir(parents=True)
            objet.write_bytes(b"x")
            os.chmod(objet, stat.S_IREAD)
        os.utime(e, (maintenant - j * JOUR, maintenant - j * JOUR))
    # git connait ENCORE ce dossier sans .git : il ne doit PAS etre supprime a la main
    reference = str(tmp_path / "ci-reference-sansgit-reference" / "worktree")
    monkeypatch.setattr(fw, "list_wt", lambda: [{"path": str(RACINE)}, {"path": reference}])
    appels, git = [], []

    def _retirer(wt):
        nom = Path(wt).parent.name
        appels.append(nom)
        return {"status": "erreur", "msg": "verrou"} if nom == "ci-reference-casse" else {"status": "removed"}

    monkeypatch.setattr(lr, "_racines_de_preuve", lambda _fw: ([tmp_path, tmp_path / "absente"], []))
    monkeypatch.setattr(fw, "retirer_worktree", _retirer)
    monkeypatch.setattr(fw, "_git", lambda args, cwd: git.append(args))
    monkeypatch.setattr(lr, "PROOF_KEEP", 3)
    monkeypatch.setattr(lr, "PROOF_DAYS", 7.0)
    return tmp_path, appels, git


def test_garde_les_recents_retire_les_vieux_par_git(zone):
    base, appels, git = zone
    r = lr._purge_worktrees_de_preuve(dry=False)
    restants = sorted(p.name for p in base.iterdir())
    # 3 plus recents gardes (r1, r2, v1) ; v2 et v3 retires par git ; « casse » garde car git a echoue ;
    # « sansgit » supprime SANS git (plus un worktree) ; « sansgit-reference » GARDE : git le liste encore
    assert restants == ["ci-reference-casse", "ci-reference-r1", "ci-reference-r2",
                        "ci-reference-sansgit-reference", "ci-reference-v1"], restants
    assert set(appels) == {"ci-reference-v2", "ci-reference-v3", "ci-reference-casse"}
    principale = r["racines"][0]
    assert r["retirees"] == 3
    assert {x["entree"] for x in principale["erreurs"]} == {"ci-reference-casse", "ci-reference-sansgit-reference"}
    assert sorted(principale["noms_retires"]) == ["ci-reference-sansgit", "ci-reference-v2", "ci-reference-v3"]
    assert ["worktree", "prune"] in git


def test_une_racine_absente_est_dite_pas_confondue_avec_rien_a_purger(zone):
    r = lr._purge_worktrees_de_preuve(dry=True)
    assert r["racines"][1]["proof_zone"] == "absente"


def test_simulation_ne_touche_rien(zone):
    base, appels, git = zone
    r = lr._purge_worktrees_de_preuve(dry=True)
    # Echec intermittent en CI de reference (26/09, 584532375) : 9 entrees au lieu de 8, 8/8 vert
    # seul -- la simulation n'ecrit rien, l'intrus vient d'ailleurs. Nommer, pas compter.
    restants = sorted(p.name for p in base.iterdir())
    assert len(restants) == 8 and appels == [] and git == [], (restants, appels, git)
    assert r["racines"][0]["eligibles"] == 5 and r["retirees"] == 0


def test_la_racine_de_la_ci_est_trouvee_quel_que_soit_le_compte(tmp_path, monkeypatch):
    """Chemin REEL : `chemin_tmp_sandbox` n'est PAS remplace. Le compte de service a un
    PROOF_ROOT ailleurs (simule) ; la racine de la CI doit quand meme etre parcourue."""
    try:
        from app.forge_sandbox_exec import chemin_tmp_sandbox
    except ImportError:
        from nokido_agent.app.forge_sandbox_exec import chemin_tmp_sandbox
    monkeypatch.setattr(fw, "PROOF_ROOT", tmp_path / "TEMP_du_service" / "nokido_proof")
    racines, illisibles = lr._racines_de_preuve(fw)
    attendue = os.path.normcase(str(Path(chemin_tmp_sandbox()) / "nokido_proof"))
    assert not illisibles, illisibles
    assert attendue in [os.path.normcase(str(x)) for x in racines]
    assert len(racines) == 2


def test_dans_le_contexte_du_service_la_racine_de_la_ci_est_lisible():
    """CHEMIN REEL DU LANCEUR (relance du 24/09 21:15, mesure) : le service part de
    tools/forge_log_retention.py, sys.path[0] = tools/, racine ABSENTE -> `No module named 'app'`,
    la racine de la CI etait ILLISIBLE et 0 preuve retiree. Le test precedent passait parce que
    pytest met la racine dans sys.path : il faut le processus tel que le superviseur le lance."""
    import json
    import subprocess

    code = (
        "import sys, json\n"
        "racine = %r\n"
        "sys.path[:] = [p for p in sys.path if p.rstrip('\\\\/').lower() != racine.lower()]\n"
        "sys.path.insert(0, racine + '\\\\tools')\n"
        "import forge_log_retention as lr, forge_worktree as fw\n"
        "r, ill = lr._racines_de_preuve(fw)\n"
        "print(json.dumps({'racines': [str(x) for x in r], 'illisibles': ill}))\n" % str(RACINE))
    p = subprocess.run([sys.executable, "-c", code], cwd=str(RACINE / "tools"), capture_output=True,
                       text=True, errors="replace", timeout=120)
    assert p.returncode == 0, p.stderr[-800:]
    d = json.loads(p.stdout.strip().splitlines()[-1])
    assert d["illisibles"] == [], d
    attendue = os.path.normcase(str(RACINE / "sandbox" / "workspace" / "tmp" / "nokido_proof"))
    assert attendue in [os.path.normcase(x) for x in d["racines"]], d


def test_un_fichier_en_lecture_seule_n_empeche_plus_la_suppression(tmp_path):
    d = tmp_path / "entree" / "artefacts"
    d.mkdir(parents=True)
    f = d / "objet"
    f.write_bytes(b"x")
    os.chmod(f, stat.S_IREAD)
    lr._supprimer_arbre(tmp_path / "entree")
    assert not (tmp_path / "entree").exists()


def test_retirer_worktree_vise_le_chemin_donne(tmp_path, monkeypatch):
    vus = []
    monkeypatch.setattr(fw, "_git", lambda args, cwd: (vus.append(args), type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})())[1])
    wt = tmp_path / "ci-x" / "worktree"
    wt.mkdir(parents=True)
    assert fw.retirer_worktree(wt)["status"] == "removed"
    assert vus == [["worktree", "remove", "--force", str(wt)]]
    assert fw.retirer_worktree(tmp_path / "nulle_part")["status"] == "absent"


def test_elle_est_cablee_dans_le_passage_quotidien():
    src = (RACINE / "tools" / "forge_log_retention.py").read_text(encoding="utf-8")
    i = src.index("def run_retention(")
    assert '"worktrees_de_preuve": _purge_worktrees_de_preuve(dry)' in src[i:i + 900]
