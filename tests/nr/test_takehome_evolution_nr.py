"""NR du 27/10 : boucle d'evolution dirigee du take-home (decision owner : boucle DEDIEE, thymus intact).

Le juge est le banc (cycles + exactitude), jamais un modele. Ces tests jugent la logique pure : lecture du
meilleur au registre chaine, extraction des blocs SEARCH/REPLACE, et classement d'un verdict de banc.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

N = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(N / "tools"))
import forge_takehome_evolution as E  # noqa: E402


def _ligne(cycles, correct=True, statut="VALEUR"):
    return json.dumps({"statut": statut, "correct": correct, "cycles": cycles, "candidat": "c%d" % cycles})


def test_le_meilleur_est_le_minimum_exact_du_registre(tmp_path):
    reg = tmp_path / "r.jsonl"
    reg.write_text("\n".join([_ligne(1041), _ligne(1017), _ligne(900, correct=False, statut="ECHEC_METIER"),
                              _ligne(1030)]) + "\n", encoding="utf-8")
    assert E.meilleur_prouve(reg)["cycles"] == 1017  # un 900 FAUX ne compte jamais


def test_registre_absent_rend_none(tmp_path):
    assert E.meilleur_prouve(tmp_path / "absent.jsonl") is None


def test_blocs_search_replace_extraits_dans_l_ordre():
    txt = ("bla\n<<<<<<< SEARCH\na = 1\n=======\na = 2\n>>>>>>> REPLACE\n"
           "<<<<<<< SEARCH\nb = 1\n=======\nb = 3\n>>>>>>> REPLACE\nfin")
    assert E.extraire_blocs(txt) == [("a = 1", "a = 2"), ("b = 1", "b = 3")]


def test_le_texte_utile_sort_de_l_enveloppe_json_de_ask():
    # mesure 27/10 : 4 iterations SANS_BLOC, les blocs etaient cherches dans l'enveloppe {"ok":..,"text":..}
    env = json.dumps({"ok": True, "text": "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE", "provider": "groq"})
    assert E.extraire_blocs(E.texte_utile(env)) == [("a", "b")]
    assert E.texte_utile("texte brut") == "texte brut"
    assert E.texte_utile(json.dumps({"ok": False, "text": "", "error": "vide"})) == ""


def test_verdict_classe_par_le_banc_seul():
    assert E.classer({"statut": "VALEUR", "correct": True, "cycles": 1010}, 1017) == "AMELIORE"
    assert E.classer({"statut": "VALEUR", "correct": True, "cycles": 1017}, 1017) == "SANS_GAIN"
    assert E.classer({"statut": "ECHEC_METIER", "correct": False, "cycles": 800}, 1017) == "FAUX"
    assert E.classer({"statut": "REFUS"}, 1017) == "REFUS"
