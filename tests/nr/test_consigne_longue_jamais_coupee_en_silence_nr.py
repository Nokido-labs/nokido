# -*- coding: utf-8 -*-
"""NR -- Regle « une borne dit combien » sur les consignes longues (9/11).

Enquete AGY (docs/enquetes/consigne_coupee_30000_20261109.md, NR RED 03242062d) : `_extract_message` coupait toute
consigne a 30 000 car. pour TOUS les executeurs (OpenCode ACP par stdin compris : lot 6 05 recu 35/40) ; agy et
codex coupaient a 29 000 (`desc[:29000]`, lots 5 12/14 livres 29/40) ; toutes ces coupes etaient MUETTES pour l'agent.
Une consigne longue arrive ENTIERE, ou sa coupe de transport est DITE en tete (« N car. sur M servis »).
Test 3 adapte par Claude : il passe par le helper reellement appele par _delegate_to_agy / codex (chemin reel), au
lieu de rejouer `desc[:29000]` a la main.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from tools import forge_task_executor as T
except ImportError:
    import forge_task_executor as T  # type: ignore


def _generer_consigne_longue(n_blocs: int = 40, taille_bloc: int = 1050) -> str:
    blocs = [
        f"- branche tache/test/branche_{i:02d} | sha abcdef{i:04d} | ratio 1.00\n"
        f"  Directive detaillee pour le bloc {i:02d} : " + ("x" * taille_bloc) + "\n"
        for i in range(1, n_blocs + 1)
    ]
    consigne = "CONSIGNE GLOBALE :\n" + "\n".join(blocs)
    assert len(consigne) >= 40000
    return consigne


def test_extract_message_rend_la_consigne_entiere():
    consigne = _generer_consigne_longue(40, 1000)
    assert T._extract_message(consigne) == consigne


def test_opencode_consigne_longue_non_amputee_a_30000():
    consigne = _generer_consigne_longue(40, 1000)
    assert len(T._extract_message(consigne)) == len(consigne)


def test_borne_de_transport_dite_a_l_agent():
    consigne = _generer_consigne_longue(40, 1000)
    servi = T._borne_dite(consigne, 29000, "limite de ligne de commande Windows d'agy")
    assert len(servi) <= 29000
    tete = servi[:300].lower()
    assert "29000 car. sur %d servis" % len(consigne) in tete and "pas servi" in tete


def test_sous_la_borne_rien_n_est_ajoute():
    assert T._borne_dite("court", 29000, "x") == "court"


def test_agy_et_codex_passent_par_la_borne_dite():
    src_agy = inspect.getsource(T._delegate_to_agy)
    assert "_borne_dite(desc, 29000" in src_agy and "desc[:29000]" not in src_agy
    src_codex = inspect.getsource(T._delegate_to_codex)
    assert "_borne_dite(desc, 29000" in src_codex and "desc[:29000]" not in src_codex
