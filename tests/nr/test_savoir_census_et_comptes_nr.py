"""NR — le census mesure vraiment, et la matrice des comptes ne ment pas.

Deux modules ecrits le 2026-09-03, restes sans test : le cliquet
`test_nr_coverage_ratchet_nr` les a designes, ces tests soldent la dette.

Hermetiques : la couverture se verifie sur une base SQLite construite ICI, pas
sur les 22,8 Go de production — une mesure qui exige la prod n'est pas rejouable
en CI, et un test non rejouable finit desarme.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _charger(nom):
    chemin = ROOT / "tools" / (nom + ".py")
    if not chemin.exists():
        pytest.skip("%s absent" % chemin)
    sys.path.insert(0, str(ROOT / "tools"))
    spec = importlib.util.spec_from_file_location(nom, chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _base_temoin():
    """4 chunks, un par quadrant — vectorise x indexe.

    Les textes depassent 20 caracteres : le census ecarte les chunks courts
    (`LENGTH(text) > 20`). Un temoin plus court sortait 0 partout, et ce zero se
    lisait comme « la fonction ne compte rien » au lieu de « mon temoin est hors
    perimetre » — le meme defaut que les tests sont censes attraper.
    """
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE rag_chunks (id TEXT PRIMARY KEY, text TEXT, "
                "source TEXT, embedding BLOB)")
    con.execute("CREATE VIRTUAL TABLE rag_fts USING fts5(chunk_id, text, "
                "source, domain)")
    _t = "texte temoin suffisamment long pour passer le filtre - %s"
    lignes = [("a", _t % "a", "rfc:rfc9110", b"vec"),  # vectorise + indexe
              ("b", _t % "b", "rfc:rfc6749", b"vec"),  # vectorise seul
              ("c", _t % "c", "src:c", None),          # indexe seul
              ("d", _t % "d", "src:d", None)]          # aucun des deux
    con.executemany("INSERT INTO rag_chunks VALUES (?,?,?,?)", lignes)
    for cid in ("a", "c"):
        con.execute("INSERT INTO rag_fts (chunk_id, text, source, domain) "
                    "VALUES (?,?,?,?)", (cid, "t", "s", "d"))
    con.commit()
    return con


def test_forge_savoir_census_ventile_les_quatre_quadrants():
    """L'angle mort reel est la case (pas de vecteur, pas d'index) — elle seule.

    Un chunk non vectorise reste servi par BM25 ; un chunk hors FTS reste
    trouvable par le sens. Annoncer « N % non vectorises donc aveugle » est faux.
    """
    census = _charger("forge_savoir_census")
    out = census.couverture_par_jointure(_base_temoin(), 100)
    assert out["quadrants"] == {"vec_et_fts": 1, "vec_seul": 1,
                                "fts_seul": 1, "aucun_des_deux": 1}
    assert out["chunks_vus"] == 4
    assert out["angle_mort_pct"] == 25.0


def test_forge_savoir_census_ne_joint_jamais_sur_la_table_virtuelle():
    """Non-regression du balayage a 2 195 Go : aucune jointure ACTIVE sur le FTS.

    Le motif est cite dans les commentaires (c'est la trace de l'incident) ; on
    verifie qu'il n'apparait dans AUCUNE ligne de code executable.
    """
    import ast as _ast
    src = (ROOT / "tools" / "forge_savoir_census.py").read_text(
        encoding="utf-8", errors="replace")
    arbre = _ast.parse(src)
    # Chercher « JOIN » dans le TEXTE du fichier attrapait le mot « jointure »
    # (nom de la fonction, commentaires expliquant l'incident) : un detecteur
    # qui accuse la trace de l'incident au lieu du defaut. On n'inspecte donc
    # que les chaines litterales qui ne sont pas des docstrings — c'est la que
    # vit le SQL reellement execute.
    docs = set()
    for n in _ast.walk(arbre):
        if isinstance(n, (_ast.Module, _ast.FunctionDef, _ast.AsyncFunctionDef,
                          _ast.ClassDef)):
            d = _ast.get_docstring(n, clean=False)
            if d:
                docs.add(d)
    litteraux = [n.value for n in _ast.walk(arbre)
                 if isinstance(n, _ast.Constant) and isinstance(n.value, str)
                 and n.value not in docs]
    # `"JOIN" in "JOINTURE"` est VRAI : la sous-chaine attrapait la clef
    # `couverture_jointure` et le titre du rapport. Sous-chaine != mot — meme
    # piege que `findstr` sans `/c:`. On exige donc une frontiere de mot.
    import re as _re
    fautives = [c for c in litteraux if _re.search(r"\bJOIN\b", c.upper())]
    assert not fautives, "SQL de jointure retrouve : %s" % fautives


def test_forge_savoir_census_un_dossier_refuse_est_illisible_pas_absent():
    """Le defaut le plus cher du depot : « pas vu » rendu comme « pas la »."""
    census = _charger("forge_savoir_census")
    out = census.supports_fichiers()
    for nom, fiche in out.items():
        if fiche["etat"] == "absent":
            assert "Default" not in fiche["chemin"], (
                "%s declare absent sur un chemin derive de HOME — c'est un "
                "acces refuse, pas une absence" % nom)


def test_forge_compte_capabilites_distingue_refus_et_succes(tmp_path):
    """La sonde d'ecriture doit rendre FAUX sur un chemin impossible.

    Une sonde qui rend vrai partout ne mesure que sa propre indulgence : c'est
    exactement ce qu'a fait `privileges_windows: oui` le 2026-09-03, qui
    mesurait que la commande repond, pas qu'elle aboutit.
    """
    comptes = _charger("forge_compte_capabilites")
    # L'API rend un couple (statut, raison) — jamais un booleen : « refuse » et
    # « pas pu regarder » doivent rester distinguables, c'est tout l'objet du
    # module. Un test qui attendait `is True` mesurait sa propre supposition.
    statut, _raison = comptes._ecriture(tmp_path)
    assert statut == "oui", "ecriture dans un tmp_path doit reussir"
    impossible = Path("Z:/inexistant") / "profond" / "encore"
    statut2, raison2 = comptes._ecriture(impossible)
    assert statut2 != "oui", "un chemin impossible ne peut pas rendre « oui »"
    assert raison2, "un refus sans raison ne se diagnostique pas"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
