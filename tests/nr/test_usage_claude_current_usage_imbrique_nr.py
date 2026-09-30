"""NR : `depuis_claude` lit `current_usage` LA OU Claude Code le place.

Mesure du 2026-09-12 -- payload REEL capture par le traceur de
`tools/nokido_statusline.py` : `current_usage` n'est PAS a la racine du
payload, il vit sous `context_window`. L'adaptateur le cherchait a la
racine, rendait None, et la ligne d'etat affichait `usage non rapporte`.
Un UNKNOWN presente comme un NO -- dans le garde meme cense mesurer la
depense.

Le NR verrouille les trois cas, dont le temoin NEGATIF : un payload sans
`current_usage` nulle part doit TOUJOURS rendre None. Sinon on fabrique
une depense nulle la ou il n'y a pas de mesure, ce qui est le defaut
symetrique et non moins couteux.
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "app"))

from forge_llm_usage_adapters import depuis_claude  # noqa: E402

USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "cache_read_input_tokens": 7,
    "cache_creation_input_tokens": 3,
}


def _payload_reel(usage):
    """Forme MESUREE le 2026-09-12, reduite aux champs que le test lit."""
    return {
        "model": {"id": "claude-opus-5", "display_name": "Opus 5"},
        "session_id": "sess-1",
        "context_window": {
            "context_window_size": 1000000,
            "total_input_tokens": 4242,
            "current_usage": dict(usage),
        },
    }


def test_current_usage_imbrique_sous_context_window():
    ev = depuis_claude(_payload_reel(USAGE))
    assert ev is not None, "payload reel : l'usage doit etre LU, pas ignore"
    assert ev["input_tokens"] == 100
    assert ev["output_tokens"] == 20
    assert ev["cache_read_tokens"] == 7
    assert ev["cache_write_tokens"] == 3
    assert ev["total_tokens"] == 120
    assert ev["context_window"] == 4242
    assert ev["model"] == "claude-opus-5"


def test_current_usage_a_la_racine_reste_lu():
    charge = _payload_reel(USAGE)
    charge["current_usage"] = charge["context_window"].pop("current_usage")
    ev = depuis_claude(charge)
    assert ev is not None, "forme racine : retrocompat, ne pas la casser"
    assert ev["input_tokens"] == 100


def test_sans_current_usage_rend_none_pas_un_zero():
    charge = _payload_reel(USAGE)
    charge["context_window"].pop("current_usage")
    assert depuis_claude(charge) is None
