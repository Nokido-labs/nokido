# -*- coding: utf-8 -*-
"""NR -- utilitaires partages de forge_utils nes du cliquet clones (31/10).

valeur_option remplace claude_session_start._opt et forge_acp_router._val ; mapper_chaines remplace
acp_harness._caviarder_valeur et forge_db_sanitize._sanitize_dict_str_recursive. Le contrat est fige ici pour que
les quatre appelants ne divergent plus en silence.
"""
import io
import sqlite3
import sys
from pathlib import Path

import pytest
from forge_utils import charger_module_par_chemin, lire_json_dict, mapper_chaines, repondre_json, valeur_option

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE / "tools"), str(RACINE / "tools" / "bancs")]


def test_valeur_option_suit_l_option_ou_rend_none():
    argv = ["--racine", "C:/x", "--seul"]
    assert valeur_option(argv, "--racine") == "C:/x"
    assert valeur_option(argv, "--seul") is None      # option sans valeur
    assert valeur_option(argv, "--absente") is None


def test_lire_json_dict_rend_un_dict_ou_vide(tmp_path):
    """Remplace lire_etat_nuit et _lire_indispo (cliquet clones, 4/11)."""
    p = tmp_path / "e.json"
    assert lire_json_dict(p) == {}, "absent"
    p.write_text("{cassé", encoding="utf-8")
    assert lire_json_dict(p) == {}, "illisible"
    p.write_text("[1, 2]", encoding="utf-8")
    assert lire_json_dict(p) == {}, "pas un dict"
    p.write_text('{"a": "é"}', encoding="utf-8")
    assert lire_json_dict(p) == {"a": "é"}


def test_repondre_json_ecrit_entetes_et_corps():
    """Remplace _repondre du relais AGY et _send_json du sidecar Qdrant."""
    class Faux:
        def __init__(self):
            self.statut, self.entetes, self.fin, self.wfile = None, {}, False, io.BytesIO()

        def send_response(self, code):
            self.statut = code

        def send_header(self, k, v):
            self.entetes[k] = v

        def end_headers(self):
            self.fin = True
    f = Faux()
    repondre_json(f, 200, {"a": "é"}, "application/json; charset=utf-8")
    assert f.statut == 200 and f.fin and f.wfile.getvalue() == '{"a": "é"}'.encode("utf-8")
    assert f.entetes["Content-Type"] == "application/json; charset=utf-8"
    assert f.entetes["Content-Length"] == str(len('{"a": "é"}'.encode("utf-8")))


def test_charger_module_par_chemin_isole_le_nom_et_refuse_l_illisible(tmp_path):
    """Remplace _charger_mecanique des deux passerelles : un module charge sous un nom propre, jamais un homonyme."""
    p = tmp_path / "m.py"
    p.write_text("VALEUR = 7\n", encoding="utf-8")
    m = charger_module_par_chemin("module_de_test_unique", p)
    assert m.VALEUR == 7 and m.__name__ == "module_de_test_unique"
    with pytest.raises(SystemExit):
        charger_module_par_chemin("x", tmp_path / "pas_python.xyz")


def test_jeton_du_hook_coffre_illisible_retombe_sur_la_variable(monkeypatch, tmp_path):
    """Le coffre illisible ne leve pas ; l'ordre complet reste garde par test_hooks_claude_jeton_coffre_seul_nr."""
    import forge_jeton_hook as J
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_secrets", None)   # import impossible
    monkeypatch.setenv("FORGE_TOKEN_CLAUDE_HOOK", "de-la-variable")
    assert J.jeton_du_hook(tmp_path) == "de-la-variable"
    monkeypatch.delenv("FORGE_TOKEN_CLAUDE_HOOK")
    assert J.jeton_du_hook(tmp_path) == ""


def test_fabriquer_chercher_rend_les_lignes_et_consigne_l_erreur():
    """Remplace les deux `chercher` des bancs ; une table hors liste est refusee, le nom entre dans le SQL."""
    import pytest
    B = pytest.importorskip("banc_rappel_lexical")  # banc prive : absent de la distribution publique
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE mini USING fts5(id, source, texte)")
    con.execute("INSERT INTO mini VALUES ('i1', 's1', 'bonjour monde')")
    erreurs = []
    chercher = B.fabriquer_chercher(con, "mini", lambda q: q, 5, erreurs)
    assert chercher("bonjour") == [{"id": "i1", "source": "s1"}]
    assert chercher("") == []
    assert chercher('"') == [] and erreurs, "une requete refusee par FTS5 compte RATEE et se dit"
    with pytest.raises(ValueError):
        B.fabriquer_chercher(con, "mini; DROP", lambda q: q, 5, [])
    con.close()


def test_mapper_chaines_ne_touche_que_les_chaines_imbriquees():
    v = {"a": "x", "b": ["y", 3, {"c": "z"}], "d": None}
    assert mapper_chaines(v, str.upper) == {"a": "X", "b": ["Y", 3, {"c": "Z"}], "d": None}
    assert mapper_chaines(7, str.upper) == 7
