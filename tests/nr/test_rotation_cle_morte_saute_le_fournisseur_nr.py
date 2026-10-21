"""NR -- une cle SOUS ROTATION dont toutes les valeurs sont mortes fait SAUTER le fournisseur (jamais un repli env).

Revue Claude du lot 1 livre par AGY (3003cb6ec, 16/10) : forge_key_rotation.resolve rend (managed=True, None) quand
le pool est gere mais toutes ses cles sont mortes ou REVOQUEES -- contrat : « => skip provider », et le modele maison
est `if _managed: return _rk` (forge_agent_proxy). Le code livre retombait alors sur os.environ, qui peut encore
porter la valeur revoquee. Sites : claude_precompact._load_env (GROQ), multi_llm_daemon._groq_key (GROQ),
forge_swarm_team (MISTRAL).
"""
import importlib
import os
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

from nokido_agent.app import forge_key_rotation as KR  # noqa: E402


def test_precompact_saute_groq_quand_toutes_ses_cles_sont_mortes(monkeypatch):
    pc = importlib.import_module("claude_precompact")
    monkeypatch.setattr(KR, "resolve", lambda nom: (True, None))
    monkeypatch.setenv("GROQ_API_KEY", "cle-revoquee-encore-dans-l-env")
    monkeypatch.setattr(pc, "GROQ_KEY", "", raising=False)
    pc._load_env()
    assert pc.GROQ_KEY in ("", None)


def test_le_demon_multi_llm_saute_groq_quand_toutes_ses_cles_sont_mortes(monkeypatch):
    import logging
    import logging.handlers

    # le demon ouvre logs/multi_llm_daemon.log au chargement : sans droit d'ecriture (compte sandbox), l'import casse
    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())
    monkeypatch.setattr(logging.handlers, "RotatingFileHandler", lambda *a, **k: logging.NullHandler())
    md = importlib.import_module("multi_llm_daemon")
    monkeypatch.setattr(KR, "resolve", lambda nom: (True, None))
    monkeypatch.setenv("GROQ_API_KEY", "cle-revoquee-encore-dans-l-env")
    assert md._groq_key() in ("", None)


def test_call_groq_n_envoie_pas_la_cle_revoquee_de_l_env(monkeypatch):
    """Le chemin REEL : call_groq ne doit pas re-servir l'env par un second lecteur apres _groq_key()."""
    import logging
    import logging.handlers

    monkeypatch.setattr(logging, "FileHandler", lambda *a, **k: logging.NullHandler())
    monkeypatch.setattr(logging.handlers, "RotatingFileHandler", lambda *a, **k: logging.NullHandler())
    md = importlib.import_module("multi_llm_daemon")
    monkeypatch.setattr(KR, "resolve", lambda nom: (True, None))
    monkeypatch.setenv("GROQ_API_KEY", "cle-revoquee-encore-dans-l-env")
    envois = []
    monkeypatch.setattr(md, "_http_post", lambda *a, **k: envois.append(k.get("headers") or a[2:]) or {})
    md.call_groq("ping")
    assert envois == [], "requete Groq partie avec une cle que la rotation declare morte"


def test_mistral_saute_quand_toutes_ses_cles_sont_mortes(monkeypatch):
    import urllib.request

    from nokido_agent.app import forge_swarm_team as ST

    monkeypatch.setattr(KR, "resolve", lambda nom: (True, None))
    monkeypatch.setenv("MISTRAL_API_KEY", "cle-revoquee-encore-dans-l-env")
    envois = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: envois.append(a) or (_ for _ in ()).throw(OSError("x")))
    rep = ST.LeadOrchestrator._mistral_call(None, "ping", "", {})
    assert envois == [] and "manquant" in rep, rep
