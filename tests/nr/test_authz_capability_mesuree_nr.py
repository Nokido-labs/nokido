"""NR -- capability MESUREE vs capability DERIVEE (finding M2M #3).

Deriver la capability de la methode HTTP (`GET -> .read`, `POST -> .write`)
casse dans les deux sens : un GET peut declencher une action, un POST peut
n'etre qu'une lecture dont le corps ne tient pas dans une URL.

Verdict rendu apres lecture des deux handlers designes, et il est DOUBLE :

- `/api/rag/tokenize` : sur-privilege CONFIRME. Le handler compte des tokens
  avec tiktoken, sans la moindre I/O. `rag.write` -> `rag.read`.
- `/mpc/plan` : finding REFUTE, mais d'une facon qui renforce la conclusion.
  Son `execute_fn` ne joint aujourd'hui que `/health` et `/rag/query`, deux
  lectures -- pourtant la capability reste `.write`, parce que le CONTRAT de la
  route est d'executer des actions. Calibrer sur l'implementation du jour
  rendrait la capability fausse des qu'une branche mutante s'ajoute, et
  personne ne le remarquerait.

D'ou l'invariant que ces tests protegent : **une capability derivee est une
hypothese, une capability mesuree a un handler lu derriere elle** -- et les
afficher pareil ferait passer 79 hypotheses pour des verdicts.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from forge_authz_matrice import (  # noqa: E402
    _CAPABILITY_MESUREE, _capability, capability_preuve,
)

HUB = ROOT / "tools" / "nokido_hub.py"


def test_tokenize_est_une_lecture():
    assert _capability("/api/rag/tokenize", ["POST"]) == "rag.read"


def test_mpc_plan_reste_une_ecriture():
    """Le contrat prime sur l'implementation du jour."""
    assert _capability("/mpc/plan", ["POST"]) == "plan.write"


def test_le_mapping_par_defaut_reste_inchange():
    """Les exceptions ne doivent pas deregler le cas general."""
    assert _capability("/api/services/list", ["GET"]) == "service.read"
    assert _capability("/api/watch/create", ["POST"]) == "watch.write"


def test_chaque_exception_porte_sa_preuve():
    """Sans exigence de preuve, cette table deviendrait l'endroit ou l'on
    corrige les classements qui derangent."""
    for route, (cap, preuve) in _CAPABILITY_MESUREE.items():
        assert cap and "." in cap, route
        assert len(preuve) > 120, (
            "%s : preuve trop courte pour etre une mesure" % route)
        assert "handler lu" in preuve, route


def test_une_capability_derivee_se_distingue_d_une_mesuree():
    assert capability_preuve("/api/rag/tokenize")
    assert capability_preuve("/api/services/list") == ""


def test_les_routes_exceptees_existent_dans_le_hub():
    """Une exception qui survit a sa route est une table qui derive du reel."""
    src = HUB.read_text(encoding="utf-8", errors="replace")
    for route in _CAPABILITY_MESUREE:
        assert '"%s"' % route in src, (
            "%s n'existe plus dans le hub : exception orpheline" % route)


def test_tokenize_ne_fait_toujours_aucune_ecriture():
    """Contre-epreuve de la mesure : si le handler gagne une I/O, la capability
    `rag.read` devient fausse et ce test doit tomber AVANT qu'on s'en serve
    pour autoriser quoi que ce soit."""
    src = HUB.read_text(encoding="utf-8", errors="replace")
    i = src.find("async def rag_tokenize")
    assert i > 0, "handler introuvable : la mesure n'est plus verifiable"
    corps = src[i:i + 1200]
    for interdit in ("open(", "urlopen", "execute(", "INSERT", "UPDATE",
                     "DELETE", "subprocess", "write_text"):
        assert interdit not in corps, (
            "rag_tokenize contient %r : ce n'est plus une lecture pure" % interdit)


def test_mpc_plan_porte_toujours_un_execute_fn():
    """Si `execute_fn` disparaissait, la justification de `.write` tomberait et
    la capability devrait etre re-mesuree, pas heritee."""
    src = HUB.read_text(encoding="utf-8", errors="replace")
    i = src.find("async def mpc_plan")
    assert i > 0
    assert "execute_fn" in src[i:i + 3000]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
