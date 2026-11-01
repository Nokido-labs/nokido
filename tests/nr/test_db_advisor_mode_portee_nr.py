"""NR -- `forge_db_index_advisor --portee` : parcours hors depot SEUL, sans SQL (owner 21/10).

Owner, 21/10 : ACL de lecture (RX, heritee) donnee a LaForgeTrusted sur E:/LaForge_tiede et E:/nokido_backups. Or les
passages complets du chasseur tournent en run_job sous LaForgeSbxOffline (que l'ACL ne couvre pas) et depassent la
borne de 110 s de `trusted_script`. Il faut un mode court : les racines hors depot et leurs etats, rien d'autre.

Contrats (chemin reel : main) :
  1. `--portee` n'appelle PAS auditer (aucune requete SQL, aucune base ouverte) ;
  2. il imprime une ligne JSON {"racines_hors_depot": [...], "bases": n} et rend 0 ;
  3. un etat ILLISIBLE reste ILLISIBLE dans la sortie (jamais converti en absent ni en 0).
"""
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_db_index_advisor as A  # noqa: E402


def test_portee_seule_sans_sql(monkeypatch, capsys):
    etats = [{"racine": "E:/LaForge_tiede", "etat": "LU", "bases": 2, "au_dela": 0, "temporaire": False},
             {"racine": "E:/nokido_backups", "etat": "ILLISIBLE (PermissionError)", "temporaire": False}]
    monkeypatch.setattr(A, "_hors_depot", lambda: (["E:/LaForge_tiede/a.db", "E:/LaForge_tiede/b.db"], etats))

    def interdit(*a, **kw):
        raise AssertionError("--portee ne doit pas auditer")
    monkeypatch.setattr(A, "auditer", interdit)
    assert A.main(["--portee"]) == 0
    sortie = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert sortie["bases"] == 2
    par = {e["racine"]: e["etat"] for e in sortie["racines_hors_depot"]}
    assert par["E:/nokido_backups"] == "ILLISIBLE (PermissionError)"
    assert par["E:/LaForge_tiede"] == "LU"
