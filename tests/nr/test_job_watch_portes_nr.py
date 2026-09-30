"""Non-regression : le veilleur de job surveille la BONNE PORTE, et le dit.

DEFAUT MESURE le 2026-09-08. `forge_job_watch_notify` sort sur le temoin externe
`--rc`, absent tant que le job tourne. Mais le repertoire de travail d'un job
detache est `<depot>/sandbox/workspace`, PAS la racine du depot : un `--rc` donne en
chemin RELATIF -- exactement la forme que le garde de capacites imprime,
`--rc sandbox/jobs/<job>.rc` -- se resout ailleurs et ne trouve rien.

Mesure : `_lire_rc("sandbox/jobs/job_d4645c1e299f.rc")` rend None depuis le
repertoire de travail reel, `_lire_rc(<meme chemin absolu>)` rend "0". Le veilleur
lance a 21:53 tournait encore 35 minutes apres la fin de sa cible, son journal ne
contenant QUE sa ligne de demarrage, et il tenait sa lane -- donc aucun autre
veilleur ne pouvait etre poste.

DEUX DEFAUTS, PAS UN :
  1. un chemin relatif est resolu contre le mauvais repertoire ;
  2. et l'echec est MUET -- "fichier absent" se lit "le job tourne encore". C'est
     `UNKNOWN` rendu comme `NO`, dans l'outil meme que la doctrine impose pour ne
     pas poller. Le veilleur doit donc ANNONCER les chemins qu'il surveille, en
     absolu : une porte annoncee est une porte verifiable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE / "tools", RACINE / "app"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import forge_job_watch_notify as w  # noqa: E402


def test_un_chemin_RELATIF_est_ancre_sur_le_depot(tmp_path, monkeypatch):
    """Le repertoire de travail d'un job n'est PAS la racine du depot."""
    monkeypatch.chdir(tmp_path)
    resolu = w._resoudre("sandbox/jobs/exemple.rc")
    assert Path(resolu).is_absolute(), f"chemin non resolu : {resolu}"
    assert str(RACINE) in str(resolu), (
        f"ancre sur le repertoire courant ({tmp_path}) au lieu du depot : {resolu}")


def test_un_chemin_ABSOLU_est_laisse_INTACT(tmp_path):
    cible = tmp_path / "ailleurs.rc"
    assert Path(w._resoudre(str(cible))) == cible, (
        "un chemin absolu deplace serait pire que le defaut d'origine")


def test_le_rc_est_LU_meme_donne_en_relatif(tmp_path, monkeypatch):
    """Le coeur du defaut : la forme imposee par le garde de capacites doit MARCHER."""
    d = RACINE / "sandbox" / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    temoin = d / "test_nr_porte_veilleur.rc"
    temoin.write_text("0", encoding="utf-8")
    try:
        monkeypatch.chdir(tmp_path)
        assert w._lire_rc("sandbox/jobs/test_nr_porte_veilleur.rc") == "0", (
            "le veilleur ne trouve pas son temoin en chemin relatif : il attendra "
            "4 h (stall) ou 6 jours (max) en tenant sa lane")
    finally:
        temoin.unlink(missing_ok=True)


def test_le_veilleur_SORT_quand_le_rc_est_la(tmp_path, monkeypatch):
    """Chemin REEL : le point d'entree, avec la forme d'appel du garde."""
    appels = []
    monkeypatch.setattr(w, "notify_subscribers",
                        lambda *a, **k: appels.append((a, k)) or {"delivered": 1, "errors": 0})
    d = RACINE / "sandbox" / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    rc = d / "test_nr_sortie_veilleur.rc"
    prog = d / "test_nr_sortie_veilleur.progress.json"
    rc.write_text("0", encoding="utf-8")
    prog.write_text('{"phase": "en_cours"}', encoding="utf-8")
    try:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", [
            "forge_job_watch_notify",
            "--progress", "sandbox/jobs/test_nr_sortie_veilleur.progress.json",
            "--rc", "sandbox/jobs/test_nr_sortie_veilleur.rc",
            "--to", "CLAUDE", "--poll", "1"])
        w.main()
    finally:
        rc.unlink(missing_ok=True)
        prog.unlink(missing_ok=True)
    assert appels, "le veilleur n'a notifie personne alors que le rc etait la"


def test_le_veilleur_ANNONCE_les_portes_qu_il_surveille(capsys, tmp_path, monkeypatch):
    """Un echec muet ne se distingue pas d'une attente normale. Les chemins reellement
    surveilles doivent etre imprimes, en ABSOLU, des le demarrage."""
    monkeypatch.setattr(w, "notify_subscribers",
                        lambda *a, **k: {"delivered": 1, "errors": 0})
    d = RACINE / "sandbox" / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    rc = d / "test_nr_annonce_veilleur.rc"
    rc.write_text("0", encoding="utf-8")
    try:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", [
            "forge_job_watch_notify",
            "--progress", "sandbox/jobs/test_nr_annonce_veilleur.progress.json",
            "--rc", "sandbox/jobs/test_nr_annonce_veilleur.rc",
            "--to", "CLAUDE", "--poll", "1"])
        w.main()
    finally:
        rc.unlink(missing_ok=True)
    sortie = capsys.readouterr().out
    assert str(rc) in sortie or os.path.abspath(str(rc)) in sortie, (
        f"le veilleur n'annonce pas la porte qu'il surveille : {sortie!r}")
