"""NR -- le chasseur couvre C: hors depot et les dossiers TEMPORAIRES (owner 21/10).

Owner, 21/10 : « tu as bien capte les fichiers temporaires sur C et D aussi ? ». Reponse mesuree : NON pour C:. Le RED
8fca0ff2f disait « jamais C: » (pour ne pas re-parcourir le depot), ce qui excluait aussi C:/tmp : 658 bases, 555
entrees illisibles, 41 849 dossiers a 3 niveaux (CI ci_rt*/pytest_basetemp, lf-beta-sync/RAG, laforge_kp_v0.1.db 83 Mo).
Et le TEMP du compte (sandbox/workspace/tmp) gardait 1,1 Go de bases de recette. D:/Temp etait couvert (cite).

Contrats :
  1. racines_hors_depot(textes, depot=ROOT) : les racines C: citees sont retenues SAUF celles sous le depot ;
  2. racines_temporaires() : C:/tmp, D:/Temp et tempfile.gettempdir(), normalises, toujours proposes meme non cites
     (un temporaire n'est jamais cite par le code qui y ecrit) ;
  3. _bases() parcourt aussi les racines temporaires, chaque etat marque `temporaire: True` dans racines_hors_depot.
"""
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_db_index_advisor as A  # noqa: E402


def test_c_hors_depot_retenu_depot_exclu():
    depot = "C:/Users/moi/Projet"
    textes = {"a.py": 'x = "C:/tmp/nokido-dist" ; y = "C:/Users/moi/Projet/RAG/e.db" ; z = "%NOKIDO_DATA%\embeddings.db"'}
    r = A.racines_hors_depot(textes, depot=depot)
    assert "C:/tmp" in r and "%NOKIDO_DATA%\embeddings.db" in r
    assert not any(x.lower().startswith(depot.lower()) for x in r)


def test_racines_temporaires():
    r = A.racines_temporaires()
    assert "C:/tmp" in r and "D:/Temp" in r
    assert Path(tempfile.gettempdir()).as_posix() in r


def test_bases_parcourt_les_temporaires(tmp_path, monkeypatch):
    t = tmp_path / "TEMP_X"
    t.mkdir()
    (t / "copie.db").write_bytes(b"")
    monkeypatch.setattr(A, "_bases_du_depot", lambda: [])
    monkeypatch.setattr(A, "_textes_du_code", lambda: {})
    monkeypatch.setattr(A, "racines_temporaires", lambda: [str(t)])
    assert [Path(b).name for b in A._bases()] == ["copie.db"]
