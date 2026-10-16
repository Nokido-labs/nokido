# -*- coding: utf-8 -*-
"""NR -- la boucle de preuve de Nokido (forge_lean_prove) : tout fournisseur via ask, Lean juge, preuve non fiable.

Decision owner du 15/10 : « pilotable par d'autres CLI de la surface (claude ou autre en local gratuit) ».
Contrat (sans Lean ni reseau : `ask` et juge factices, sur une copie de projet temporaire) :
  1. un fournisseur indisponible passe la main au suivant, et c'est DIT dans le journal ;
  2. une preuve portant un jeton interdit (#eval, IO, axiom, sorry, ...) est refusee SANS lancer le juge ;
  3. seul le PREMIER `sorry` est remplace, le reste du fichier est intact ;
  4. juge PROUVE -> PROUVE avec le fournisseur et la preuve ; juge INCONNU -> arret, jamais un succes ;
  5. budget epuise -> NON_PROUVE ; le projet d'origine n'est jamais modifie.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_lean_prove as lp  # noqa: E402

DEFI = "theorem t1 : 1 + 1 = 2 := by sorry\ntheorem t2 : True := by sorry\n"


def _projet(tmp_path):
    p = tmp_path / "formel"
    (p / "Formel").mkdir(parents=True)
    (p / "Formel" / "Defi.lean").write_text(DEFI, encoding="utf-8")
    return p


def test_jetons_interdits_et_substitution_du_premier_sorry():
    for mauvais in ("#eval IO.Process.spawn", "axiom triche", "sorry", "unsafe def f", "import Lean"):
        assert lp.preuve_interdite(mauvais)
    assert lp.preuve_interdite("decide") is None
    nouveau, n = lp.substituer(DEFI, "decide")
    assert n == 1 and nouveau.count("sorry") == 1 and "(by\n  decide)" in nouveau


def test_fournisseur_indisponible_puis_suivant_prouve(tmp_path):
    projet = _projet(tmp_path)
    vus = []

    def ask(p, m):
        vus.append(p)
        return {"error": "OAuth expire"} if p == "gemini_cli" else {"response": "```lean\ndecide\n```"}

    def juge(copie):
        assert "decide" in (copie / "Formel" / "Defi.lean").read_text(encoding="utf-8")
        return {"etat": "PROUVE", "theoremes": {}}

    r = lp.prouver(projet, "Formel/Defi.lean", ("gemini_cli", "groq"), essais=2, ask_fn=ask, juge=juge)
    assert r["etat"] == "PROUVE" and r["fournisseur"] == "groq" and r["preuve"] == "decide"
    assert r["journal"][0]["etat"] == "INDISPONIBLE" and vus == ["gemini_cli", "groq"]
    assert (projet / "Formel" / "Defi.lean").read_text(encoding="utf-8") == DEFI        # l'original intact


def test_jeton_interdit_refuse_sans_juge_et_budget_epuise(tmp_path):
    def juge(copie):
        raise AssertionError("le juge ne doit pas etre appele sur une preuve interdite")

    r = lp.prouver(_projet(tmp_path), "Formel/Defi.lean", ("groq",), essais=2,
                   ask_fn=lambda p, m: {"response": "#eval IO.println 1"}, juge=juge)
    assert r["etat"] == "NON_PROUVE" and all(j["etat"] == "REFUSE" for j in r["journal"]) and len(r["journal"]) == 2


def test_juge_inconnu_arrete_la_boucle(tmp_path):
    r = lp.prouver(_projet(tmp_path), "Formel/Defi.lean", ("groq", "ollama"), essais=3,
                   ask_fn=lambda p, m: {"response": "decide"},
                   juge=lambda copie: {"etat": "INCONNU", "raison": "lake introuvable"})
    assert r["etat"] == "INCONNU" and len(r["journal"]) == 1
