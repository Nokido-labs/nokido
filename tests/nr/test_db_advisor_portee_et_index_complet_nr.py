"""NR -- le chasseur de lectures massives voit TOUT : autres disques, index lus en entier, chaque site (owner 21/10).

Owner, 21/10 : « update_readme_stats fait un COUNT sur 46 Go = il faut que tu chasses toutes ces lectures massives de
la base, si l'indexation est bien faite c'est totalement inutile » ; puis « n'oublie pas qu'il existe de la matiere
hors RAG, sur d'autres disques ». Le chasseur EXISTE (tools/forge_db_index_advisor.py, EXPLAIN QUERY PLAN sans lire de
donnee) ; lance le 21/10, il n'a PAS vu update_readme_stats. Trois angles morts mesures :
  a. portee : `forge_savoir_census.bases()` = ROOT.rglob seul ; le code reference pourtant V: (14 racines), E: (7,
     dont E:/LaForge_tiede), D: (9), F: (1) -- invisibles ;
  b. jugement : `SCAN t USING [COVERING] INDEX` n'est jamais compte, or `SELECT COUNT(*) FROM rag_chunks` lit l'index
     ENTIER (10,5 M d'entrees) a chaque appel ;
  c. sites : deduplication par (table, colonne) -> tous les balayages « a predicat compose » d'une table se replient
     sur UNE origine ; et les 195 requetes non analysables ne sont qu'un nombre, sans leurs sites.

Contrats :
  1. racines_hors_depot(textes) : {file: texte} -> racines `X:/premier_segment` citees, lettre D a Z (jamais C:),
     triees ; une racine `X:/` nue reste `X:/` ;
  2. bases_hors_depot(racines, profondeur=2) -> (bases, etats) : *.db / *.sqlite / *.sqlite3 sous chaque racine
     jusqu'a `profondeur` niveaux ; racine absente -> ABSENT (disque non monte), refus -> ILLISIBLE, jamais confondus ;
     ce qui depasse la profondeur est COMPTE (`au_dela`) -- une borne dit combien ;
  3. _bases() = bases du depot + bases_hors_depot(racines_hors_depot(_textes_du_code())) sans doublon ;
  4. auditer : chaque base `fiche["index_complets"]` = parcours d'un index ENTIER sur une grosse table (plan
     `SCAN t USING ... INDEX` et requete sans LIMIT), avec leur origine ;
  5. auditer : aucun site perdu -- chaque entree de `scans` porte `origines` (tous les fichier:ligne du meme
     (table, colonne)) ; `rapport["non_analysables_sites"]` liste les fichier:ligne des requetes non analysables.
"""
import sqlite3
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools"), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_db_index_advisor as A  # noqa: E402


def _base(chemin, n=50):
    with sqlite3.connect(str(chemin)) as c:
        c.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, active INT, text TEXT, embedding BLOB)")
        c.execute("CREATE INDEX idx_active ON rag_chunks(active)")
        c.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?)", [("k%d" % i, 1, "t", b"x") for i in range(n)])
    return chemin


def test_racines_hors_depot():
    textes = {"a.py": 'DB = "%NOKIDO_DATA%\embeddings.db" ; tiede = r"E:\\LaForge_tiede\\x"',
              "b.py": 'p = "C:/Users/moi" ; q = "D:/" ; r = "F:/Grodata/z"'}
    # Depot EXPLICITE : `C:/Users` n'est ecarte que s'il CONTIENT le depot. Le defaut (ROOT) rendait le test
    # dependant de l'emplacement du checkout -- rouge sur le runner GitHub (25/10, run 40191424899).
    sous_profil = A.racines_hors_depot(textes, depot="%NOKIDO_ROOT%")
    assert sous_profil == ["D:/", "E:/LaForge_tiede", "F:/Grodata", "%NOKIDO_DATA%\embeddings.db"]
    ailleurs = A.racines_hors_depot(textes, depot="D:/runner/_work/nokido")
    assert ailleurs == ["C:/Users", "E:/LaForge_tiede", "F:/Grodata", "%NOKIDO_DATA%\embeddings.db"], (
        "depot hors du profil : C:/Users est une racine a parcourir, D:/ contient le depot")


def test_bases_hors_depot_bornees_et_etats_distincts(tmp_path):
    r = tmp_path / "disque"
    (r / "a" / "c" / "d").mkdir(parents=True)
    _base(r / "racine.db")
    _base(r / "a" / "b.sqlite")
    _base(r / "a" / "c" / "d" / "profond.db")
    bases, etats = A.bases_hors_depot([str(r), str(tmp_path / "absent")], profondeur=2)
    noms = sorted(Path(b).name for b in bases)
    assert noms == ["b.sqlite", "racine.db"]
    par = {e["racine"]: e for e in etats}
    assert par[str(r)]["etat"] == "LU" and par[str(r)]["au_dela"] == 1
    assert par[str(tmp_path / "absent")]["etat"] == "ABSENT"


def test_bases_inclut_le_hors_depot(tmp_path, monkeypatch):
    r = tmp_path / "E_tiede"
    r.mkdir()
    _base(r / "tiede.db")
    monkeypatch.setattr(A, "_bases_du_depot", lambda: [])
    monkeypatch.setattr(A, "_textes_du_code", lambda: {"x.py": "racine"})
    monkeypatch.setattr(A, "racines_hors_depot", lambda textes: [str(r)])
    monkeypatch.setattr(A, "racines_temporaires", lambda: [])
    assert [Path(b).name for b in A._bases()] == ["tiede.db"]


def test_index_complet_et_aucun_site_perdu(tmp_path, monkeypatch):
    db = _base(tmp_path / "rag.db")
    requetes = [("SELECT COUNT(*) FROM rag_chunks", "stats.py", 10, True),
                ("SELECT id FROM rag_chunks WHERE active=1 LIMIT 5", "borne.py", 4, True),
                ("SELECT embedding FROM rag_chunks WHERE embedding IS NOT NULL", "b.py", 3, True),
                ("SELECT text FROM rag_chunks WHERE length(text) > 3", "c.py", 9, True),
                ("<dynamique>", "dyn.py", 77, False)]
    monkeypatch.setattr(A, "_requetes_du_code", lambda: requetes)
    monkeypatch.setattr(A, "_bases", lambda: [db])
    monkeypatch.setattr(A, "_hors_depot", lambda: ([], []))  # le parcours reel des disques est teste a part
    rap = A.auditer(seuil=1)
    fiche = rap["bases"][0]
    complets = {o for e in fiche["index_complets"] for o in [e["origine"]]}
    assert "stats.py:10" in complets and "borne.py:4" not in complets
    origines = {o for s in fiche["scans"] for o in s["origines"]}
    assert {"b.py:3", "c.py:9"} <= origines
    assert rap["non_analysables_sites"] == ["dyn.py:77"]
