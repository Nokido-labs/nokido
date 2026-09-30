"""NR -- un compte de jetons fait PAR NOUS ne s'enregistre plus comme rapporte par le fournisseur.

Mesure du 2026-09-24 (veille « cache de prompt », fiches lot_B_22/24/30, verifiee localement avant
toute correction) : sur 7 jours, ~730 appels fournisseurs dans `token_usage` (607 chez groq
gpt-oss-120b), TOUS etiquetes `measurement_kind = REPORTED`, et AUCUN ne porte de compteur de
cache. Or `_record_provider_call` (forge_agent_proxy) ne lit jamais l'usage rendu par l'API : il
compte lui-meme le texte (`count_text_tokens`, sur systeme + message seulement -- l'historique du
fil n'y est pas) puis appelle `log_call` sans dire ce qu'il a mesure, et `log_call` range par
defaut toute valeur chiffree en REPORTED.

Le contrat canonique existait deja (`forge_llm_usage_event.creer`) : il REFUSE `REPORTED` adosse
a une source d'estimation. Ce chemin-la le contournait. Ce qui est garde ici :

  1. le chemin reel (`_record_provider_call` -> `log_call`) declare ESTIMATED avec un instrument
     nomme ;
  2. cet instrument est reconnu comme une estimation par le contrat, qui refuserait donc qu'on
     le re-etiquette REPORTED ;
  3. quand l'API REND son usage (Groq, 83 % des appels fournisseurs sur 7 j), c'est lui qui est
     enregistre -- REPORTED, avec `cached_tokens` : c'est le seul compteur qui dise si
     l'alignement de prefixe (`forge_cache_aligner`) produit des hits ;
  4. CHAMP ABSENT != ZERO : une reponse sans `prompt_tokens_details` laisse le cache INCONNU
     (None), jamais 0.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from nokido_agent.app import forge_agent_proxy as ap  # noqa: E402
from nokido_agent.app import forge_llm_usage_event as ev  # noqa: E402
from nokido_agent.app import forge_token_monitor as tm  # noqa: E402


class _Fournisseur:
    name = "groq"
    model = "openai/gpt-oss-120b"


def _capturer(monkeypatch):
    vus: list[dict] = []
    monkeypatch.setattr(tm, "log_call", lambda **k: vus.append(k))
    monkeypatch.setattr(tm, "count_text_tokens", lambda texte, *a, **k: len(texte.split()))
    return vus


def test_le_chemin_reel_declare_une_estimation(monkeypatch):
    vus = _capturer(monkeypatch)
    ap._record_provider_call(_Fournisseur(), "bonjour le monde", "une reponse", "systeme", 12.0)
    assert len(vus) == 1, "log_call n'a pas ete atteint (%d appels)" % len(vus)
    k = vus[0]
    assert k.get("measurement_kind") == "ESTIMATED", (
        "un compte fait par tokenizer local est enregistre %r" % k.get("measurement_kind"))
    assert k.get("measurement_source"), "une estimation sans instrument nomme n'est pas verifiable"


def test_l_instrument_nomme_est_reconnu_comme_estimation_par_le_contrat(monkeypatch):
    vus = _capturer(monkeypatch)
    ap._record_provider_call(_Fournisseur(), "a b c", "d e", "", 1.0)
    source = vus[0]["measurement_source"]
    ok = ev.creer("exec-nr", "groq", "m", "ESTIMATED", measurement_source=source,
                  input_tokens=3, output_tokens=2)
    assert ok["measurement_kind"] == "ESTIMATED"
    with pytest.raises(ev.ErreurContrat):
        ev.creer("exec-nr", "groq", "m", "REPORTED", measurement_source=source,
                 input_tokens=3, output_tokens=2)


def _client_factice(usage):
    class _Completions:
        async def create(self, **kw):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                                   usage=usage)

    class _Client:
        def __init__(self, *a, **k):
            self.chat = SimpleNamespace(completions=_Completions())

    return _Client


def _groq_par_ask_tracked(monkeypatch, usage):
    """Chemin REEL : ask_tracked -> ask garde (firewall neutralise) -> Groq.ask -> log_call.

    `Groq.ask` fait `from openai import AsyncOpenAI` a l'appel : un faux module suffit, et le
    vrai (des centaines de modules, > 30 s a froid sur le runner) n'est jamais charge."""
    faux_openai = ModuleType("openai")
    faux_openai.AsyncOpenAI = _client_factice(usage)
    monkeypatch.setitem(sys.modules, "openai", faux_openai)

    vus = _capturer(monkeypatch)
    monkeypatch.setattr(ap, "_load_api_key", lambda *a, **k: "cle-factice")
    monkeypatch.setattr(ap, "_firewall_pre", lambda prov, m, s: (None, m, None))
    monkeypatch.setattr(ap, "_firewall_post", lambda r, fw: r)
    assert asyncio.run(ap.Groq().ask_tracked("bonjour", [], "systeme", 32, 10)) == "ok"
    assert len(vus) == 1, "log_call atteint %d fois" % len(vus)
    return vus[0]


def test_groq_enregistre_l_usage_rendu_par_l_api_avec_le_cache(monkeypatch):
    usage = SimpleNamespace(prompt_tokens=1200, completion_tokens=40,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=1024))
    k = _groq_par_ask_tracked(monkeypatch, usage)
    assert k.get("measurement_kind") == "REPORTED", k.get("measurement_kind")
    assert (k.get("prompt_tokens"), k.get("completion_tokens")) == (1200, 40)
    assert k.get("cache_read_tokens") == 1024
    src = k.get("measurement_source") or ""
    assert src and "estim" not in src.lower()
    ev.creer("exec-nr", "groq", "m", "REPORTED", measurement_source=src,
             input_tokens=1200, output_tokens=40, cache_read_tokens=1024)


def test_cache_non_rapporte_reste_inconnu(monkeypatch):
    k = _groq_par_ask_tracked(monkeypatch, SimpleNamespace(prompt_tokens=10, completion_tokens=2))
    assert k.get("measurement_kind") == "REPORTED"
    assert k.get("cache_read_tokens") is None, "un cache non rapporte a ete ecrit %r" % k.get("cache_read_tokens")


def test_sans_usage_rendu_on_retombe_sur_l_estimation(monkeypatch):
    k = _groq_par_ask_tracked(monkeypatch, None)
    assert k.get("measurement_kind") == "ESTIMATED"


class _ImportOpenaiRefuse:
    """Chercheur qui refuse l'import REEL d'openai.

    Run GitHub 36211634261 (26/09) : `import openai` a froid (des centaines de modules de types)
    a depasse les 30 s de pytest-timeout sur le runner -- pile arretee dans `get_data`, une
    lecture disque, ni reseau ni interblocage -- et la methode thread de pytest-timeout tue
    TOUTE la suite pure, pas ce seul test."""

    def find_spec(self, nom, *a, **k):
        if nom == "openai" or nom.startswith("openai."):
            raise ImportError("import reel d'openai refuse par le NR (cout a froid > borne du test)")
        return None


def test_le_chemin_groq_ne_charge_pas_le_vrai_openai(monkeypatch):
    monkeypatch.delitem(sys.modules, "openai", raising=False)
    monkeypatch.setattr(sys, "meta_path", [_ImportOpenaiRefuse(), *sys.meta_path])
    k = _groq_par_ask_tracked(monkeypatch, SimpleNamespace(prompt_tokens=3, completion_tokens=1))
    assert k.get("measurement_kind") == "REPORTED"
