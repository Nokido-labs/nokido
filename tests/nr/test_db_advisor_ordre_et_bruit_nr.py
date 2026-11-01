"""NR -- le budget du parcours hors depot va aux DONNEES d'abord ; extraction sans doublons de casse ni bruit (21/10).

Passage reel `--portee` sous LaForgeTrusted (21/10, apres l'ACL owner sur E:) : apres les temporaires, l'ordre etait
ALPHABETIQUE -> C:/WINDOWS (tronque a 8 s) a mange le budget de 30 s, et E:/LaForge_tiede, E:/nokido_backups, %NOKIDO_DATA%\...
sont restes NON_EXAMINE -- precisement les disques de donnees. Le meme rapport montrait des doublons de casse
(C:/WINDOWS, C:/Windows, C:/windows : Windows ignore la casse) et du bruit tire de chaines du code (A:/n{text_a[,
S:/%s, %NOKIDO_DATA%\RAG={).

Contrats :
  1. racines_hors_depot dedoublonne sans tenir compte de la casse (premiere graphie gardee) ;
  2. un segment contenant { } [ ] % = est du bruit : ignore ;
  3. ordre_parcours(racines, temporaires) : temporaires, puis racines HORS C: (disques de donnees), puis C: ;
     l'ordre interne de chaque groupe est alphabetique (deterministe).
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_db_index_advisor as A  # noqa: E402


def test_doublons_de_casse_et_bruit():
    textes = {"a.py": 'p = "C:/NOKIDO/x" ; q = "C:/Nokido/y" ; r = "c:/nokido/z"',
              "b.py": 's = "A:/n{text_a[0]}" ; t = "S:/%s" % u ; v = "%NOKIDO_DATA%\RAG={x}" ; w = "%NOKIDO_DATA%\embeddings.db"'}
    r = A.racines_hors_depot(textes, depot="C:/Users/moi/Projet")
    assert [x for x in r if x.lower() == "c:/nokido"] == ["C:/NOKIDO"]
    assert "%NOKIDO_DATA%\embeddings.db" in r
    assert not any(c in x for x in r for c in "{}[]%=")


def test_point_final_de_phrase_ne_cree_pas_de_doublon():
    textes = {"c.py": '# voir D:/Temp. puis "D:/Temp" et E:/nokido_backups.'}
    r = A.racines_hors_depot(textes, depot="C:/Users/moi/Projet")
    assert [x for x in r if x.lower().startswith("d:/temp")] == ["D:/Temp"]
    assert "E:/nokido_backups" in r and "E:/nokido_backups." not in r


def test_dossiers_systeme_ecartes_et_dits():
    textes = {"s.py": 'w = "C:/WINDOWS/System32" ; p = "C:/Program Files/X" ; q = "C:/Program Files (x86)/Y" ; '
                      'k = "C:/ProgramData/Z" ; n = "C:/nokido/data"'}
    r = A.racines_hors_depot(textes, depot="C:/Users/moi/Projet")
    assert not any(x.lower().startswith(("c:/windows", "c:/program files")) for x in r)
    assert "C:/Program" not in r            # forme reellement extraite : la regex coupe a l'espace
    assert "C:/nokido" in r and "C:/ProgramData" in r
    assert A.est_racine_systeme("C:/WINDOWS") and A.est_racine_systeme("c:/program files (x86)")
    assert not A.est_racine_systeme("C:/ProgramData")


def test_ordre_parcours_donnees_avant_c():
    racines = ["C:/WINDOWS", "E:/nokido_backups", "C:/tmp", "%NOKIDO_DATA%\", "D:/Temp", "C:/ProgramData", "E:/LaForge_tiede"]
    temporaires = ["C:/tmp", "D:/Temp"]
    assert A.ordre_parcours(racines, temporaires) == [
        "C:/tmp", "D:/Temp",
        "E:/LaForge_tiede", "E:/nokido_backups", "%NOKIDO_DATA%\",
        "C:/ProgramData", "C:/WINDOWS"]
