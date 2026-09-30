"""NR — le moteur natif des Golden Rules.

Le gate semgrep qu'il remplace rendait `scanned_files=0` suivi d'une coche verte
(run 31873587600) : un detecteur qui ne lit rien passe pour conforme. Les tests
ci-dessous visent donc la DISCRIMINATION, jamais l'import — separe-t-il encore
le vrai du faux ? Chaque valeur attendue vient d'un cas REEL du 2026-08-15,
cite en commentaire.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def _scan(tmp_path: Path, code: str) -> list[dict]:
    import forge_golden_rules_ast as G

    f = tmp_path / "cible.py"
    f.write_text(code, encoding="utf-8")
    return G.scan_file(str(f))


def _regles(findings: list[dict]) -> set[str]:
    return {f["rule"] for f in findings}


# ── discrimination : les trois familles ERROR ────────────────────────────────

def test_detecte_les_trois_familles_error(tmp_path):
    findings = _scan(tmp_path, (
        "import anthropic\n"
        "import sqlite3\n"
        "def f():\n"
        "    c = sqlite3.connect('C:/RAG/embeddings.db')\n"
        "    c.execute('INSERT INTO rag_chunks (text, source) VALUES (?,?)')\n"
    ))
    assert _regles(findings) >= {
        "laforge-no-anthropic-api-direct",
        "laforge-embeddings-db-literal-path",
        "laforge-insert-rag-chunks-no-id",
    }


def test_le_chemin_cache_dans_une_f_string_compte_aussi(tmp_path):
    """`f"{dossier}/embeddings.db"` viole l'invariant autant qu'une chaine nue ;
    ne regarder que ast.Constant laissait passer le cas le plus frequent."""
    findings = _scan(tmp_path, (
        "import sqlite3\n"
        "def f(d):\n"
        "    return sqlite3.connect(f'{d}/embeddings.db')\n"
    ))
    assert "laforge-embeddings-db-literal-path" in _regles(findings)


# ── anti-faux-positifs : cas payes a la main le 2026-08-15 ───────────────────

def test_colonnes_interpolees_ne_sont_pas_accusees(tmp_path):
    """forge_skill_curator.py:273 construit ses colonnes par f-string ET gere
    ON CONFLICT(id) : l'accuser etait un faux positif. Indecidable = silence."""
    findings = _scan(tmp_path, (
        "def f(keys, conn, payload):\n"
        "    sql = f\"INSERT INTO rag_chunks ({','.join(keys)}) VALUES (?)\"\n"
        "    conn.execute(sql, payload)\n"
    ))
    assert "laforge-insert-rag-chunks-no-id" not in _regles(findings)


def test_insert_avec_id_explicite_est_conforme(tmp_path):
    findings = _scan(tmp_path, (
        "def f(conn):\n"
        "    conn.execute('INSERT INTO rag_chunks (id, text) VALUES (?,?)')\n"
    ))
    assert "laforge-insert-rag-chunks-no-id" not in _regles(findings)


def test_db_path_ne_declenche_rien(tmp_path):
    """La forme CORRECTE — passer par db_path() — ne doit jamais etre denoncee,
    sinon le gate punit ceux qui respectent la regle."""
    findings = _scan(tmp_path, (
        "import sqlite3\n"
        "from forge_db_path import db_path\n"
        "def f():\n"
        "    return sqlite3.connect(db_path())\n"
    ))
    assert "laforge-embeddings-db-literal-path" not in _regles(findings)


def test_fichiers_jetables_hors_perimetre():
    """tools/_*.py et tools/tmp_* sont deja hors depot par .gitignore : ils
    fournissaient la moitie des chemins litteraux du premier passage."""
    import forge_golden_rules_ast as G

    assert G._scratch("tmp_progress_check.py")
    assert G._scratch("_check_batch8.py")
    assert not G._scratch("__init__.py")
    assert not G._scratch("forge_archi_lint.py")


# ── cliquet : la dette ne bloque pas, la nouveaute si ────────────────────────

def test_la_cle_ignore_le_numero_de_ligne():
    """Geler path:line ferait rompre le cliquet a chaque ligne inseree
    au-dessus — un garde qui hurle sur un commentaire finit desarme."""
    import forge_golden_rules_ast as G

    a = {"rule": "r", "path": "app/x.py", "line": 10, "severity": "ERROR"}
    b = {"rule": "r", "path": "app/x.py", "line": 512, "severity": "ERROR"}
    assert G._cle(a) == G._cle(b)


def test_le_compteur_ne_retient_que_les_error():
    import forge_golden_rules_ast as G

    findings = [
        {"rule": "r1", "path": "a.py", "line": 1, "severity": "ERROR"},
        {"rule": "r1", "path": "a.py", "line": 9, "severity": "ERROR"},
        {"rule": "r2", "path": "a.py", "line": 3, "severity": "WARNING"},
        {"rule": "r3", "path": "a.py", "line": 4, "severity": "INFO"},
    ]
    assert G._compter(findings) == {"r1|a.py": 2}


def test_le_socle_du_depot_couvre_l_etat_courant():
    """Le socle versionne doit rester le reflet du depot : s'il vieillit, le
    cliquet devient soit muet, soit hurlant."""
    import json

    import forge_golden_rules_ast as G

    gele = json.loads(Path(G.SOCLE).read_text(encoding="utf-8"))
    assert gele["par_regle_et_fichier"], "socle vide = cliquet sans reference"
    assert all("|" in k for k in gele["par_regle_et_fichier"])


# ── robustesse : le defaut trouve en ecrivant ce test ────────────────────────

def test_une_cible_hors_du_volume_ne_plante_pas(tmp_path, monkeypatch):
    """relpath leve ValueError des que la cible est sur un autre montage — et
    le RAG vit sur V:. Le scan doit rendre un verdict, pas un traceback."""
    import os

    import forge_golden_rules_ast as G

    f = tmp_path / "ailleurs.py"
    f.write_text("import anthropic\n", encoding="utf-8")

    vrai = os.path.relpath

    def _relpath_hostile(path, start=None):
        raise ValueError("path is on mount 'V:', start on mount 'C:'")

    monkeypatch.setattr(os.path, "relpath", _relpath_hostile)
    try:
        findings = G.scan_file(str(f))
    finally:
        monkeypatch.setattr(os.path, "relpath", vrai)
    assert "laforge-no-anthropic-api-direct" in _regles(findings)


def test_un_fichier_impossible_a_parser_est_signale_non_vu(tmp_path):
    """« 0 finding » sur un fichier illisible est le faux-vert d'origine."""
    findings = _scan(tmp_path, "def f(:\n    pass\n")
    assert any(f["rule"] == "parse" for f in findings)


# ---------------------------------------------------------------------------
# UN IMPORT NE RECLAME PAS DE PRIVILEGE (mesure 2026-09-16)
#
# `tools/forge_trace_replay.py` ouvrait son journal AU NIVEAU MODULE. Le fichier
# est lisible mais non inscriptible par les comptes de service (verifie sous
# LaForgeSbxOffline ET LaForgeSbxOnline) : le module etait donc INIMPORTABLE, et
# son propre test de chargement mesurait les ACL au lieu du code. Un defaut reel
# que la CI ne voyait pas, faute de l'exercer sous cette contrainte.
#
# PORTEE MESUREE : 28 modules dans tools/ et 6 dans app/ ouvrent un handler
# fichier. La regle est donc WARNING et non ERROR -- on observe avant
# d'enforcer, sinon le gate rougit sur 34 cas des son premier passage et se
# fait desarmer.
#
# CRITERE : ce qui S'EXECUTE au chargement, jamais ce qui est seulement DEFINI.
# Le moteur porte deja cette distinction (`_flux_module`), et c'est exactement
# celle que j'avais ratee dans mon premier NR, lequel condamnait le correctif.
# ---------------------------------------------------------------------------

_REGLE_IMPORT = "laforge-effet-de-bord-import"


def test_un_handler_fichier_au_niveau_module_est_signale(tmp_path):
    code = ("import logging\n"
            "from logging.handlers import RotatingFileHandler\n"
            "logging.basicConfig(handlers=[RotatingFileHandler('x.log')])\n")
    assert _REGLE_IMPORT in _regles(_scan(tmp_path, code))


def test_le_MEME_handler_dans_une_fonction_n_est_PAS_signale(tmp_path):
    """Une DEFINITION n'est pas une EXECUTION : c'est la forme CORRIGEE."""
    code = ("import logging\n"
            "from logging.handlers import RotatingFileHandler\n"
            "def configurer_journal():\n"
            "    logging.basicConfig(handlers=[RotatingFileHandler('x.log')])\n")
    assert _REGLE_IMPORT not in _regles(_scan(tmp_path, code)), (
        "le correctif lui-meme est condamne : la regle ne distingue pas ce qui "
        "s'execute a l'import de ce qui est seulement defini"
    )


def test_un_basicConfig_SANS_fichier_ne_declenche_pas(tmp_path):
    """Console seule : aucun privilege filesystem reclame."""
    code = "import logging\nlogging.basicConfig(level=logging.INFO)\n"
    assert _REGLE_IMPORT not in _regles(_scan(tmp_path, code))


def test_un_basicConfig_AVEC_filename_declenche(tmp_path):
    code = "import logging\nlogging.basicConfig(filename='x.log')\n"
    assert _REGLE_IMPORT in _regles(_scan(tmp_path, code))


def test_un_handler_sous_un_if_de_niveau_module_declenche(tmp_path):
    """Un `if` de niveau module S'EXECUTE au chargement."""
    code = ("import logging, os\n"
            "if os.environ.get('X'):\n"
            "    logging.FileHandler('x.log')\n")
    assert _REGLE_IMPORT in _regles(_scan(tmp_path, code))


def test_la_regle_OBSERVE_avant_d_enforcer(tmp_path):
    code = "import logging\nlogging.basicConfig(filename='x.log')\n"
    trouves = [f for f in _scan(tmp_path, code) if f["rule"] == _REGLE_IMPORT]
    assert trouves and trouves[0]["severity"] == "WARNING", (
        "34 modules sont concernes : une regle ERROR des son premier passage "
        "rougirait tout et se ferait desarmer"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
