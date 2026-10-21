"""NR 18/10 -- RSI action (4), decision owner (choix multiple) : declarer `embed.max_workers` comme reglage L1 officiel.

Etat : la mesure parametree existe (`mesurer_capacite_batch(max_workers=, taille=)`, debat tour 3 : AGY mesure +24 %
de 1 a 2 fils en lots de 16), mais le reglage n'etait ni dans la liste blanche `PARAMS_L1`, ni lu par le chemin reel
(`embed_batch_fast` gardait 4 fils en dur). Contrat :
  * `PARAMS_L1["embed.max_workers"]` : entier borne (1..16), defaut 4 (comportement inchange tant que rien n'agit),
    une mesure DECLAREE resolue a l'appel, un bruit declare sur les memes dimensions que embed.batch_size ;
  * `forge_embed_router._workers_l1()` lit la valeur L1 avec la MEME rigueur que `_batch_size_l1` : entier strict
    dans les bornes, sinon le defaut 4, DIT ;
  * `embed_batch_fast` prend `_workers_l1()` quand l'appelant n'impose pas de nombre de fils.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_embed_router as er  # noqa: E402
from nokido_agent.app import forge_proposal_applier as pa  # noqa: E402


def test_le_reglage_est_declare_dans_la_liste_blanche():
    d = pa.PARAMS_L1.get("embed.max_workers")
    assert d, "embed.max_workers absent de PARAMS_L1 (liste blanche des reglages L1)"
    assert d.get("type") == "int" and 1 <= d["min"] <= d["defaut"] <= d["max"] <= 16
    assert d["defaut"] == 4, "le defaut doit garder le comportement d'avant (4 fils)"
    assert set(d.get("bruit", {})) >= {"textes_par_seconde", "taux_succes"}, "bruit non declare"
    assert callable(pa._mesure_declaree("embed.max_workers")), "la mesure declaree ne se resout pas"


def test_le_lecteur_est_strict_et_dit_son_defaut(monkeypatch):
    monkeypatch.setattr(pa, "valeur_l1", lambda nom, defaut=None: 2 if nom == "embed.max_workers" else defaut)
    assert er._workers_l1() == 2
    for refuse in (99, 0, 2.5, True, "3", None):
        monkeypatch.setattr(pa, "valeur_l1", lambda nom, defaut=None, r=refuse: r)
        assert er._workers_l1() == 4, "valeur %r acceptee : le lecteur doit rendre le defaut 4" % (refuse,)


def test_le_chemin_reel_lit_le_reglage():
    src = inspect.getsource(er.embed_batch_fast)
    assert "_workers_l1()" in src, "embed_batch_fast garde un nombre de fils fixe : le reglage L1 ne sert a rien"
