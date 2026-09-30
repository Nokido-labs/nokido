# -*- coding: utf-8 -*-
"""NR — les trois outils du chantier retrieval, par leur EFFET.

Le cliquet de couverture (`test_nr_coverage_ratchet_nr`) a fait ROUGIR la CI du
checkpoint 35c992a4b : `forge_router_replay`, `forge_retrieval_baseline` et
`forge_patch_run_network_contract` avaient ete livres sans qu'aucun test ne les
nomme. Le cliquet avait raison -- un module que rien ne cite n'a aucune chance
d'echouer le jour ou il regresse.

Ces tests portent sur ce que chaque module FAIT, pas sur son import :
  - le replay COMPTE ce qu'il ecarte, et ne recalcule que la decision ;
  - la baseline distingue « canal muet » de « canal absent », et son marqueur
    d'inobservable n'est jamais un zero ;
  - le patcheur garde son invariant d'ancre unique / deja-patche.

Zero service externe : journal jetable en tmp_path, routeur d'embedding remplace,
lecture seule sur le depot.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_retrieval_router as rr  # noqa: E402
import forge_router_replay as replay  # noqa: E402


# ─────────────────────────── forge_router_replay ────────────────────────────

def _observation(query: str, ctx: dict | None = None) -> dict:
    """Fabrique une observation REELLE coherente avec le routeur courant."""
    d = rr.decider(query, ctx or {})
    return {
        "query": query,
        "query_id": "q_test",
        "kind": rr.OBSERVATION_REELLE,
        "schema": rr.SCHEMA_OBSERVATION,
        "decision": {
            "lexical_weight": d.lexical_weight,
            "vector_weight": d.vector_weight,
            "structure_weight": d.structure_weight,
            "profil": d.profil,
            "reason": d.reason,
            "availability_context": ctx or {},
        },
    }


def _journal(tmp_path: Path, lignes: list) -> Path:
    p = tmp_path / "observations.jsonl"
    p.write_text("\n".join(lignes), encoding="utf-8")
    return p


def test_journal_absent_ne_plante_pas(tmp_path):
    r = replay.rejouer(tmp_path / "jamais_ecrit.jsonl")
    assert r["compte"]["lues"] == 0
    assert r["compte"]["rejouees"] == 0


def test_une_ligne_illisible_est_comptee_jamais_ignoree(tmp_path):
    """« Pas lisible » doit se voir. Une ligne avalee surestime la couverture."""
    p = _journal(tmp_path, [json.dumps(_observation("test bm25")), "{ceci n'est pas du json"])
    r = replay.rejouer(p)
    assert r["compte"]["illisibles"] == 1, r
    assert r["compte"]["lues"] == 1, r


def test_une_ligne_incomplete_est_ecartee_ET_motivee(tmp_path):
    p = _journal(tmp_path, [json.dumps({"query": "sans le reste"})])
    r = replay.rejouer(p)
    assert r["compte"]["rejouees"] == 0
    assert r["ecartees"].get("champs_manquants") == 1, r


def test_une_fixture_ne_se_melange_pas_aux_observations_reelles(tmp_path):
    """Un rejeu qui compte les fixtures rendrait des chiffres sur du synthetique."""
    faux = _observation("requete de fixture")
    faux["kind"] = rr.FIXTURE_TEST
    p = _journal(tmp_path, [json.dumps(faux), json.dumps(_observation("requete reelle"))])
    r = replay.rejouer(p)
    assert r["compte"]["rejouees"] == 1, r
    assert any(k.startswith("kind=") for k in r["ecartees"]), r


def test_rejouer_une_decision_stable_ne_diverge_pas(tmp_path):
    """En SHADOW, rejouer la meme entree doit redonner la meme decision.

    Si ce test devient rouge, c'est que le routeur a DERIVE -- ce que le module
    dit lui-meme : une divergence est une derive a instruire, pas un progres.
    """
    p = _journal(tmp_path, [json.dumps(_observation("comment fonctionne le cache RRF ?"))])
    r = replay.rejouer(p)
    assert r["compte"]["rejouees"] == 1, r
    assert r["compte"]["divergentes"] == 0, r["divergences"]
    assert r["compte"]["identiques"] == 1, r


# ────────────────────────── forge_retrieval_baseline ─────────────────────────

def _baseline():
    import forge_retrieval_baseline as b
    return b


def test_marqueur_inobservable_n_est_jamais_un_zero():
    """`NOT_OBSERVABLE` doit rester un marqueur EXPLICITE.

    Le jour ou il vaudrait 0, None ou "", un signal non mesure se lirait comme
    un signal nul -- et on conclurait a la non-pertinence de ce qu'on n'a pas vu.
    """
    b = _baseline()
    assert isinstance(b.NOT_OBSERVABLE, str)
    assert b.NOT_OBSERVABLE not in ("", "0", "null", "None")
    assert b.NOT_OBSERVABLE  # ni vide, ni falsy


@pytest.mark.parametrize("vecteur,attendu", [
    ([0.1] * 1024, True),    # backend qui repond vraiment
    ([0.1] * 8, False),      # repond, mais pas un embedding utilisable
    ([], False),             # repond vide
    (None, False),           # ne repond pas
])
def test_dense_vivant_ne_confond_pas_muet_et_vivant(monkeypatch, vecteur, attendu):
    import types
    b = _baseline()
    faux = types.ModuleType("forge_embed_router")
    faux.embed = lambda *a, **k: vecteur
    monkeypatch.setitem(sys.modules, "forge_embed_router", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_embed_router", faux)
    ok, motif = b._dense_vivant()
    assert ok is attendu, motif
    assert motif, "un verdict sans motif ne s'instruit pas"


def test_dense_indisponible_se_dit_au_lieu_de_passer_pour_faux(monkeypatch):
    """Canal ABSENT et canal MUET sont deux etats, pas un seul."""
    import types
    b = _baseline()
    faux = types.ModuleType("forge_embed_router")

    def _casse(*a, **k):
        raise RuntimeError("backend injoignable")

    faux.embed = _casse
    monkeypatch.setitem(sys.modules, "forge_embed_router", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_embed_router", faux)
    ok, motif = b._dense_vivant()
    assert ok is False
    assert "RuntimeError" in motif and "backend injoignable" in motif, motif


# ─────────────────── forge_patch_run_network_contract ────────────────────────

def test_le_patcheur_garde_son_invariant_ancre_unique():
    """Deja patche OU ancre STRICTEMENT unique -- jamais ni l'un ni l'autre.

    Un patcheur one-shot dont l'ancre a disparu sans marqueur reecrirait au
    mauvais endroit ou echouerait en silence a la prochaine execution.
    """
    import forge_patch_run_network_contract as pc
    texte = Path(pc.CIBLE).read_text(encoding="utf-8", errors="replace")
    deja = pc.MARQUEUR in texte
    occurrences = texte.count(pc.ANCIEN)
    assert deja or occurrences == 1, (
        f"ni marqueur present ({deja}) ni ancre unique (occurrences={occurrences}) : "
        "le patcheur ne sait plus ou ecrire"
    )
