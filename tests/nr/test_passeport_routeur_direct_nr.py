"""NR 30/10 -- tranche 3 du passeport d'appel : les appels du routeur en HTTP DIRECT (hors proxy) laissent aussi leur
ligne, sans doublon pour ceux qui passent par le proxy (qui ecrit deja la sienne).

Marque partagee dans le contexte (forge_trace_context) : router_call l'ouvre, le proxy la coche en ecrivant ; si
personne ne l'a cochee, le routeur ecrit lui-meme (fournisseur et modele de la reponse, endpoint INCONNU -- jamais
devine).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app"), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_agent_proxy as AP  # noqa: E402
import forge_llm_router as R  # noqa: E402
import forge_trace_context as trace  # noqa: E402


def _routeur(passe_par_le_proxy: bool):
    class _R:
        def call(self, prompt, use_case, max_tokens, **kw):
            if passe_par_le_proxy:
                trace.marquer_passeport_ecrit()
            return {"ok": True, "text": "x", "provider": "groq_direct", "model": "modele-direct"}
    return _R()


def test_appel_direct_ecrit_sa_ligne_de_passeport(monkeypatch, tmp_path):
    journal = tmp_path / "passeport.jsonl"
    monkeypatch.setattr(AP, "_PASSEPORT_JOURNAL_PATH", str(journal))
    monkeypatch.setattr(R, "get_router", lambda: _routeur(False))
    R.router_call("bonjour", use_case="code", max_tokens=10, timeout=5)
    ligne = json.loads(journal.read_text(encoding="utf-8").strip())
    assert ligne["provider"] == "groq_direct" and ligne["modele"] == "modele-direct"
    assert ligne["use_case"] == "code" and ligne["endpoint"] == "INCONNU"


def test_appel_par_le_proxy_pas_de_doublon(monkeypatch, tmp_path):
    journal = tmp_path / "passeport.jsonl"
    monkeypatch.setattr(AP, "_PASSEPORT_JOURNAL_PATH", str(journal))
    monkeypatch.setattr(R, "get_router", lambda: _routeur(True))
    R.router_call("bonjour", use_case="code", max_tokens=10, timeout=5)
    assert not journal.exists() or journal.read_text(encoding="utf-8").strip() == ""
    assert trace.passeport_deja_ecrit() is False, "la marque ne fuit pas apres l'appel"
