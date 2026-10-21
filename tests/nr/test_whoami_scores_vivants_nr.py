"""NR -- whoami ne classe plus « vivant » un modele mort (dette whoami_classe_vivant_un_modele_mort_20261017, R5).

Instruit par AGY (5b568366a) : _handle_whoami_sync lisait provider_scores WHERE status='ok' sans TTL et sans regarder
PROVIDERS[...]['perime'] -- groq/llama-3.3-70b « GOOD » sur une mesure du 2026-04-27 ; github_gpt41_mini « A » parce
que le watcher prend un /health 200 pour une inference. La logique vit dans le routeur (non critique) ; le registre
(CRITICAL, derogation owner du 17/10) n'appelle qu'elle. Un ecarte est DIT avec sa raison.
"""
from __future__ import annotations

import ast
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from nokido_agent.app import forge_llm_router as R  # noqa: E402

MAINTENANT = time.mktime(time.strptime("2026-10-17 12:00:00", "%Y-%m-%d %H:%M:%S"))


def _r(provider, quand, ttft=300, grade="A"):
    return {"provider": provider, "ttft_ms": ttft, "grade": grade, "measured_at": quand}


def test_une_mesure_de_plus_de_sept_jours_n_est_pas_un_vivant():
    vivants, ecartes = R.scores_vivants([_r("groq/llama-3.3-70b", "2026-04-27 07:36:49")], MAINTENANT,
                                        providers={}, morts=set())
    assert vivants == [] and "perimee" in ecartes["groq/llama-3.3-70b"]


def test_un_slot_marque_perime_par_le_routeur_n_est_pas_un_vivant():
    vivants, ecartes = R.scores_vivants([_r("github_gpt41_mini", "2026-10-16 23:20:56")], MAINTENANT,
                                        providers={"github_gpt41_mini": {"perime": "410 Gone"}}, morts=set())
    assert vivants == [] and "perime" in ecartes["github_gpt41_mini"]


def test_un_modele_prouve_mort_par_le_recensement_n_est_pas_un_vivant():
    vivants, ecartes = R.scores_vivants([_r("groq/llama-3.3-70b-versatile", "2026-10-17 11:00:00")], MAINTENANT,
                                        providers={}, morts={"groq:llama-3.3-70b-versatile"})
    assert vivants == [] and "mort" in ecartes["groq/llama-3.3-70b-versatile"]


def test_une_mesure_datee_du_futur_n_est_pas_un_vivant():
    """Revue adverse de Codex (17/10) : une date future passait la fenetre de fraicheur."""
    vivants, ecartes = R.scores_vivants([_r("x/y", "2026-10-19 12:00:00")], MAINTENANT, providers={}, morts=set())
    assert vivants == [] and "futur" in ecartes["x/y"]


def test_une_date_illisible_ne_prouve_pas_la_fraicheur():
    vivants, ecartes = R.scores_vivants([_r("x/y", "hier")], MAINTENANT, providers={}, morts=set())
    assert vivants == [] and "illisible" in ecartes["x/y"]


def test_une_mesure_fraiche_d_un_slot_sain_reste_vivante_et_triee():
    rows = [_r("b/m", "2026-10-17 10:00:00", ttft=500), _r("a/m", "2026-10-17 09:00:00", ttft=200)]
    vivants, ecartes = R.scores_vivants(rows, MAINTENANT, providers={}, morts=set())
    assert [v["provider"] for v in vivants] == ["a/m", "b/m"] and ecartes == {}


def test_whoami_passe_par_les_vivants_et_dit_les_ecartes():
    """Chemin reel : _handle_whoami_sync appelle scores_vivants et expose les ecartes (un filtre le DIT)."""
    src = (ROOT / "app" / "forge_mcp_registry.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    fn = next(n for n in ast.walk(arbre) if isinstance(n, ast.FunctionDef) and n.name == "_handle_whoami_sync")
    corps = ast.get_source_segment(src, fn)
    assert "scores_vivants" in corps and '"providers_ecartes"' in corps
