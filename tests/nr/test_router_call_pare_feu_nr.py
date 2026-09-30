"""NR 2026-09-26 : `router_call` -> `LLMRouter.call()` envoyait au cloud SANS pare-feu.

Mesure (session a8bcd050, en preparant un envoi cloud autorise par l'owner) : les gardes de
sortie -- `pre_flight` du pare-feu semantique, redaction `redact_text`, `SecretGuard.scan_outbound`
-- ne vivaient que dans `call_cascade`. `call()`, appele par `router_call`, passait directement a
`litellm.completion`. Et sa relance vers le slot suivant pouvait partir au cloud apres un premier
slot LOCAL, sans garde non plus.

Ces tests empruntent le VRAI `call()` ; seuls les bords sont simules (fournisseur litellm, slot,
verdict du pare-feu). `redact_text` est le vrai redacteur. Rappel L4 : `pre_flight` est BINAIRE
(safe_task VIDE des que le DLP mord) -- l'effet attendu est une REDACTION, pas un prompt vide.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
for _d in (RACINE, RACINE / "app"):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

import nokido_agent.app.forge_llm_router as R  # noqa: E402
import nokido_agent.app.forge_secret_guard as SG  # noqa: E402
import nokido_agent.app.forge_semantic_firewall as FW  # noqa: E402

IP = "localhost"
PROMPT = f"Diagnostique le service qui ecoute sur {IP} port 8766."


class _Slot:
    def __init__(self, name):
        self.name = name
        self.config = {"models": ["modele-test"]}
        self.api_key = None
        self.is_available = True

    def record_call(self):
        pass

    def record_failure(self):
        pass


def _routeur(slot, autres=None):
    r = R.LLMRouter.__new__(R.LLMRouter)
    r._slots = dict(autres or {})
    r._select_slot = lambda use_case, exclure=(): slot
    return r


def _litellm(monkeypatch, envoyes, lever_sur=()):
    def _completion(**kw):
        envoyes.append(kw)
        if kw["model"] in lever_sur:
            raise RuntimeError("backend local hors service")
        msg = types.SimpleNamespace(content="reponse")
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)],
                                     usage=types.SimpleNamespace(total_tokens=1))

    fake = types.SimpleNamespace(completion=_completion)
    # Le `except` de call() teste `isinstance(exc, litellm.RateLimitError)` : le faux module
    # doit porter les classes d'exception que la detection de rate-limit interroge, sinon
    # AttributeError. Une RuntimeError generique est ainsi classee non-RL -> record_failure -> relance.
    for _n in ("RateLimitError", "APIError", "APIConnectionError", "Timeout",
               "ServiceUnavailableError", "InternalServerError", "BadRequestError",
               "AuthenticationError", "APIStatusError"):
        setattr(fake, _n, type(_n, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "litellm", fake)


def _dlp_mord(monkeypatch, vus=None):
    pf = types.SimpleNamespace(ok=False, dlp_triggered=True, injection=False, reason="dlp")

    def _pre_flight(prompt, **kw):
        if vus is not None:
            vus.append(kw.get("provider"))
        return pf

    monkeypatch.setattr(FW, "get_firewall", lambda: types.SimpleNamespace(pre_flight=_pre_flight))


def _contenu_user(kw):
    return [m["content"] for m in kw["messages"] if m["role"] == "user"][0]


def test_cloud_le_prompt_est_redige_quand_le_dlp_mord(monkeypatch):
    envoyes = []
    _litellm(monkeypatch, envoyes)
    _dlp_mord(monkeypatch)
    rep = _routeur(_Slot("groq")).call(PROMPT, "general")
    assert rep["ok"], rep
    assert len(envoyes) == 1
    envoye = _contenu_user(envoyes[0])
    assert IP not in envoye, envoye
    assert envoye.strip(), "prompt VIDE envoye : pre_flight pris pour un redacteur"


def test_local_recoit_le_prompt_tel_quel(monkeypatch):
    envoyes = []
    _litellm(monkeypatch, envoyes)

    def _interdit(*a, **k):
        raise AssertionError("le pare-feu cloud n'a pas a juger un slot local")

    monkeypatch.setattr(FW, "get_firewall", lambda: types.SimpleNamespace(pre_flight=_interdit))
    rep = _routeur(_Slot("ollama_local")).call(PROMPT, "general")
    assert rep["ok"], rep
    assert IP in _contenu_user(envoyes[0])


def test_secretguard_refuse_et_rien_ne_part(monkeypatch):
    envoyes = []
    _litellm(monkeypatch, envoyes)
    _dlp_mord(monkeypatch)

    def _refus(prompt, provider=None, local_only=False):
        raise ValueError("secret detecte")

    monkeypatch.setattr(SG, "scan_outbound", _refus)
    rep = _routeur(_Slot("groq")).call(PROMPT, "general")
    assert not rep["ok"], rep
    assert "SecretGuard" in rep["error"], rep
    assert envoyes == [], "le fournisseur a ete appele malgre le refus du SecretGuard"


def test_pare_feu_qui_leve_bloque_le_cloud(monkeypatch):
    envoyes = []
    _litellm(monkeypatch, envoyes)

    def _casse(*a, **k):
        raise RuntimeError("pare-feu en panne")

    monkeypatch.setattr(FW, "get_firewall", lambda: types.SimpleNamespace(pre_flight=_casse))
    rep = _routeur(_Slot("groq")).call(PROMPT, "general")
    assert not rep["ok"] and "pare-feu" in rep["error"], rep
    assert envoyes == []


def test_la_relance_vers_le_cloud_repasse_la_garde(monkeypatch):
    envoyes, vus, relances = [], [], []
    _litellm(monkeypatch, envoyes, lever_sur=("modele-test",))
    _dlp_mord(monkeypatch, vus)
    groq = _Slot("groq")
    r = _routeur(_Slot("ollama_local"), {"groq": groq})
    monkeypatch.setattr(R, "chaine_active", lambda uc: ["ollama_local", "groq"])
    r._call_slot = lambda slot, prompt, *a: relances.append((slot.name, prompt)) or {"ok": True}
    r.call(PROMPT, "general")
    assert IP in _contenu_user(envoyes[0]), "le premier slot est local : prompt intact attendu"
    assert relances and relances[0][0] == "groq", relances
    assert IP not in relances[0][1], "la relance est partie au cloud EN CLAIR"
    assert vus == ["groq"], vus
