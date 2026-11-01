"""NR -- comptage de tokens Mistral EXACT (owner 24/10 « tu as repare tiktoken ? »).

Mesure du 24/10 : mistral_common 1.12 installe et importable, mais `MistralTokenizer.from_model("codestral-latest")`
puis le repli `from_model("mistral-large-latest")` echouaient (API depreciee) -> repli tiktoken a +/-15 % pour
mistral_free, et `openrouter_free` tombait en « provider inconnu ». Le comptage des tokens doit etre juste avant
d'orchestrer l'economie de tokens.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_tokenizer as T  # noqa: E402

TEXTE = "Nokido mesure ses tokens avant de les economiser."


def test_mistral_ne_retombe_pas_sur_tiktoken_quand_mistral_common_est_la(monkeypatch):
    pytest.importorskip("mistral_common")
    T._MISTRAL_CACHE.clear()

    def interdit(*a, **k):
        raise AssertionError("repli tiktoken alors que mistral_common est installe")

    monkeypatch.setattr(T, "_fallback_tiktoken", interdit)
    for modele in ("codestral-latest", "open-mistral-nemo", "mistral-large-latest"):
        assert T._count_mistral(TEXTE, modele) > 0


def test_un_fournisseur_gratuit_suffixe_free_garde_le_tokenizer_de_sa_famille(monkeypatch):
    vus = []
    monkeypatch.setitem(T._DISPATCHER, "openrouter", lambda t, m, o: vus.append(("openrouter", m)) or 7)
    assert T.count_tokens(TEXTE, provider="openrouter_free", model="free") == 7
    assert vus == [("openrouter", "free")]
