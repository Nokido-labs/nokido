"""NR 18/10 -- le routeur LLM EMET l'effort (token_events) a chaque appel reussi.

Mesure du 18/10 (p1_coeur_suit_effort_llm_20261013) : `sandbox/token_usage.db` table `token_events`
EXISTE mais 0 ligne ; `forge_token_watchdog.record_tokens` n'a AUCUN appelant -- un recepteur sans
emetteur (doctrine « un garde branche sur un signal que personne n'emet »). Le capteur d'effort LLM
du coeur ne peut rien lire tant que le routeur n'emet pas.

Contrat :
- chaque appel REUSSI (chemin `call` ET relance `_call_slot`) emet (provider, jetons d'entree, de sortie) ;
- usage ILLISIBLE -> rien d'emis : UNKNOWN n'est pas 0 jeton (on n'invente pas un effort nul) ;
- une panne de l'emetteur ne fait JAMAIS echouer l'appel LLM.
Chemin reel : `LLMRouter.call` traverse, seuls litellm et l'enregistreur sont doubles.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

import forge_llm_router as R  # noqa: E402


class _Usage:
    def __init__(self, entree, sortie):
        self.prompt_tokens, self.completion_tokens = entree, sortie
        self.total_tokens = (entree or 0) + (sortie or 0)


class _Resp:
    def __init__(self, usage):
        self.usage = usage
        self.model = "modele-test"
        msg = types.SimpleNamespace(content="ok")
        self.choices = [types.SimpleNamespace(message=msg)]


class _Slot:
    name = "slot_test"
    api_key = "local"
    is_available = True
    config = {"models": ["modele-test"]}

    def record_call(self):
        pass

    def record_failure(self):
        pass


def _routeur(monkeypatch, resp, emis, panne=False):
    faux = types.ModuleType("litellm")
    faux.completion = lambda **kw: resp
    monkeypatch.setitem(sys.modules, "litellm", faux)
    monkeypatch.setattr(R, "_capter_capacite", lambda *a, **k: None)

    def enregistrer(provider, entree, sortie):
        if panne:
            raise OSError("base des jetons injoignable")
        emis.append((provider, entree, sortie))

    monkeypatch.setattr(R, "_enregistrer_jetons", enregistrer)
    r = R.LLMRouter.__new__(R.LLMRouter)
    r._select_slot = lambda *a, **k: _Slot()
    r._garde_sortante = lambda prompt, system, nom: (prompt, None)
    return r


def test_un_appel_reussi_emet_ses_jetons(monkeypatch):
    emis = []
    out = _routeur(monkeypatch, _Resp(_Usage(120, 30)), emis).call("bonjour")
    assert out["ok"] is True
    assert emis == [("slot_test", 120, 30)]


def test_la_relance_par_call_slot_emet_aussi(monkeypatch):
    emis = []
    r = _routeur(monkeypatch, _Resp(_Usage(7, 3)), emis)
    out = r._call_slot(_Slot(), "p", "", 50, 0.1, 5, "general")
    assert out["ok"] is True
    assert emis == [("slot_test", 7, 3)]


def test_usage_illisible_n_emet_pas_zero(monkeypatch):
    emis = []
    out = _routeur(monkeypatch, _Resp(None), emis).call("bonjour")
    assert out["ok"] is True
    assert emis == [], "usage illisible : rien d'emis (UNKNOWN n'est pas 0 jeton)"


def test_chaque_site_litellm_du_routeur_emet_l_effort():
    """Temoin REEL du 18/10 apres relance : `ask provider=router` passe par call_cascade, dont le site
    litellm.completion n'emettait pas -> 0 ligne. Chaque site d'appel du module doit etre suivi de l'emetteur."""
    import ast

    src = (ROOT / "app" / "forge_llm_router.py").read_text(encoding="utf-8")
    manquants = []
    for noeud in ast.walk(ast.parse(src)):
        corps = getattr(noeud, "body", None)
        if not isinstance(corps, list):
            continue
        for i, stmt in enumerate(corps):
            seg = ast.get_source_segment(src, stmt) or ""
            if isinstance(stmt, ast.Assign) and "litellm.completion(" in seg:
                suite = " ".join(ast.get_source_segment(src, s) or "" for s in corps[i + 1:i + 4])
                if "_emettre_effort(" not in suite:
                    manquants.append(stmt.lineno)
    assert not manquants, "site(s) litellm.completion sans _emettre_effort aux lignes %s" % manquants


def test_une_panne_de_l_emetteur_ne_casse_pas_l_appel(monkeypatch):
    emis = []
    out = _routeur(monkeypatch, _Resp(_Usage(5, 5)), emis, panne=True).call("bonjour")
    assert out["ok"] is True and out["text"] == "ok"
