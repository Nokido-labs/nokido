"""Le barème d'autorite par origine ne doit pas se re-aplatir en silence.

Toute la chaine de confiance du RAG a deja tourne NEUTRE sans que rien ne le
signale : `apply_trust_weight` s'appliquait bien, mais sur un `trust_score` absent
de ~694k chunks, donc un facteur identique partout — et multiplier tous les scores
par la meme constante ne change aucun ordre. Ces tests fixent ce qui doit RESTER
discriminant.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from forge_rag_qualify import apply_trust_weight, trust_weight  # noqa: E402


@pytest.mark.parametrize(
    ("source", "attendu"),
    [
        # doctrine souveraine — fait foi sur « comment Nokido pense/agit »
        ("COGNITION.md#chunk4", 1.0),
        ("RULES_SHARED.md#chunk2", 1.0),
        # experience VALIDEE
        ("lessons_learned.md", 0.88),
        ("session:2026-07-24:solution", 0.85),
        # le corps : le code fait autorite sur ce qu'il fait, quel que soit le
        # separateur de chemin (4973 chunks retombaient au defaut a cause de « \ »)
        ("app/forge_rag_engine.py", 0.80),
        ("app\\forge_agent_proxy.py", 0.80),
        ("docs\\skills\\laforge\\SKILL.md", 0.75),
        # documentation TIERCE : utile, jamais prescriptive pour Nokido
        ("docset:Docker#Package attestations", 0.45),
        ("docset:Go#net/http", 0.45),
        # TRACE BRUTE : prouve qu'on a fait, jamais que c'etait juste
        ("session:auto_CLAUDE_495806", 0.30),
        ("conv_claude_desktop", 0.35),
        # ARTEFACTS d'ingestion : la « source » est en fait du contenu
        ("Directory structure:", 0.35),
        ("# SECTION: ctf/ (447 files)", 0.35),
        ("GO Phase 3 implementation immediate.", 0.35),
        ("", 0.35),
        # fichiers legitimes non rattaches : defaut, surtout PAS artefact
        ("debian-reference.fr.pdf", 0.60),
        ("ai_prompts_landscape/Amp/README.md", 0.60),
    ],
)
def test_autorite_par_origine(source: str, attendu: float) -> None:
    assert trust_weight(source) == pytest.approx(attendu)


def test_la_doctrine_prime_sur_le_docset_tiers() -> None:
    """Le classement doit pouvoir s'inverser a pertinence comparable."""
    assert trust_weight("COGNITION.md#chunk4") > trust_weight("docset:Docker#x")


def test_trace_brute_sous_le_docset() -> None:
    """L'echo de nos propres appels d'outils ne doit primer sur rien."""
    assert trust_weight("session:auto_CLAUDE_1") < trust_weight("docset:Docker#x")


def test_ponderation_reste_discriminante() -> None:
    """Le coeur du bug d'origine : un facteur CONSTANT ne trie rien.

    A pertinence egale, deux origines differentes doivent produire deux scores
    differents — sinon la ponderation est decorative.
    """
    base = 0.5
    doctrine, _ = apply_trust_weight(base, {"trust_score": trust_weight("COGNITION.md")})
    tiers, _ = apply_trust_weight(base, {"trust_score": trust_weight("docset:Go#x")})
    assert doctrine > tiers


def test_la_pertinence_garde_le_dernier_mot() -> None:
    """Le prior d'origine corrige, il n'ecrase pas : un tiers tres pertinent
    doit encore battre une doctrine hors-sujet."""
    tiers_pertinent, _ = apply_trust_weight(0.90, {"trust_score": trust_weight("docset:Go#x")})
    doctrine_hs, _ = apply_trust_weight(0.20, {"trust_score": trust_weight("COGNITION.md")})
    assert tiers_pertinent > doctrine_hs
