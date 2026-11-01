"""NR : la retro-specification sort du CODE, et dit ce qu'elle n'a pas pu lire (owner 26/10).

Un collage externe a affirme le meme jour une dizaine de faits faux (verdict SURVIT_AVEC_GAIN, 28 outils, juge en
worktree...). L'extracteur lit les sources canoniques ; ces tests verrouillent : valeurs LUES avec leur ligne,
ILLISIBLE / ABSENTE dits au lieu d'omis, base ouverte en lecture seule (aucune ecriture possible), items owner isoles.
"""
import json
import sqlite3
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_spec_extractor as sx  # noqa: E402


def test_une_constante_est_lue_avec_sa_ligne(tmp_path):
    (tmp_path / "m.py").write_text("X = 1\nSEUIL = 85.0\nTUPLE = ('A', 'B')\nCALC = f(2)\n", encoding="utf-8")
    assert sx.lire_constante(tmp_path, "m.py", "SEUIL") == {"etat": "LU", "valeur": 85.0, "ligne": 2}
    assert sx.lire_constante(tmp_path, "m.py", "TUPLE")["valeur"] == ("A", "B")
    assert sx.lire_constante(tmp_path, "m.py", "CALC")["expression"] is True
    assert sx.lire_constante(tmp_path, "m.py", "NULLE")["etat"] == "ABSENTE"
    assert sx.lire_constante(tmp_path, "absent.py", "X")["etat"] == "ILLISIBLE"


def test_les_vraies_constantes_du_depot_sont_lisibles():
    """Chemin reel : chaque constante declaree existe encore la ou l'extracteur la cherche."""
    illisibles = [(rel, nom) for rel, nom, _ in sx.CONSTANTES if sx.lire_constante(_R, rel, nom)["etat"] != "LU"]
    assert illisibles == []


def test_les_verdicts_viennent_du_juge_et_pas_d_une_memoire():
    v = sx.verdicts_du_juge(_R)
    assert v and "AMELIORE" in v and "MEURT" in v
    assert "SURVIT_AVEC_GAIN" not in v  # le nom invente du collage du 26/10


def test_la_base_est_lue_en_lecture_seule(tmp_path):
    db = tmp_path / "b.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE forge_tools (tool_name TEXT PRIMARY KEY, min_ring INT, is_active INT)")
    con.execute("INSERT INTO forge_tools VALUES ('run', 1, 1), ('write', 0, 0)")
    con.commit()
    con.close()
    s = sx.schema_base(db)
    assert s["etat"] == "LU" and any(o["nom"] == "forge_tools" for o in s["objets"])
    assert sx.bareme_rings(db) == {"run": {"min_ring": 1, "actif": True}, "write": {"min_ring": 0, "actif": False}}
    ro = sx._ouvrir_ro(db)
    try:
        try:
            ro.execute("DELETE FROM forge_tools")
            ecrit = True
        except sqlite3.OperationalError:
            ecrit = False
    finally:
        ro.close()
    assert ecrit is False
    assert sx.schema_base(tmp_path / "absente.db")["etat"] == "ABSENTE"


def test_une_base_vue_sous_plusieurs_noms_n_est_decrite_qu_une_fois(tmp_path):
    """Mesure 26/10 : sans interrupteur, authority_path et le journal conversation_log rendent la base RAG -- son DDL
    (1 400 lignes) sortait trois fois, 170 000 caracteres pour un tiers d'information."""
    db = tmp_path / "b.db"
    sqlite3.connect(db).execute("CREATE TABLE t (x)").connection.close()
    groupes = sx.regrouper({"rag (db_path)": db, "bareme (authority_path)": db, "taches": tmp_path / "t.db"})
    assert sorted(len(noms) for noms in groupes.values()) == [1, 2]
    md = sx.rendre_schema({chemin: (noms, sx.schema_base(chemin)) for chemin, noms in groupes.items()},
                          [], {}, "abc", "now")
    assert md.count("CREATE TABLE t") == 1 and "rag (db_path) = bareme (authority_path)" in md


def test_le_plan_isole_les_items_owner_et_dit_l_illisible(tmp_path):
    assert "ILLISIBLE" in sx.rendre_plan(None, "abc", "now")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "roadmap_arbre.json").write_text(json.dumps({"items": [
        {"cle": "a", "etat": "CLOS"},
        {"cle": "b", "etat": "PARTIEL", "reste": "derogation owner sur le hub"},
        {"cle": "c", "etat": "PARTIEL", "reste": "ecrire le NR"},
        {"cle": "d", "etat": "DECISION_OWNER", "reste": ""}]}), encoding="utf-8")
    rm = sx.roadmap(tmp_path)
    assert rm["total"] == 4 and rm["comptes"]["CLOS"] == 1
    assert {r["cle"]: r["owner"] for r in rm["restants"]} == {"b": True, "c": False, "d": True}
    md = sx.rendre_plan(rm, "abc", "now")
    assert "1 / 4 CLOS (25.0 %)" in md and "Bloques par un geste ou une decision owner (2)" in md
    # 26/10 : le 04_PRD ne pouvait citer AUCUNE cle CLOS (roadmap_arbre.json non versionne) -> le plan les liste
    assert "## Clos (1)" in md and "`a`" in md


def test_l_instantane_mcp_est_lu_tel_quel():
    o = sx.outils_mcp(_R)
    assert o and all(set(x) == {"nom", "requis", "parametres"} for x in o)
    assert {"run", "governed_edit", "introspect"} <= {x["nom"] for x in o}


def test_le_point_d_entree_sans_ecrire_ne_touche_pas_docs_specs(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sx, "ROOT", tmp_path)
    monkeypatch.setattr(sx, "bases_canoniques", lambda: {})
    monkeypatch.setattr(sx, "_sha", lambda: "abc")
    assert sx.main([]) == 0
    assert not (tmp_path / "docs" / "specs").exists()
    assert "02_TRD.md" in capsys.readouterr().out
