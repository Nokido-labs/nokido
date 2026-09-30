"""NR — profilage des endpoints et attribution de roles.

Le routeur attribuait ses `use_case` par habitude : les chaines datent d'avril
et n'ont jamais ete confrontees a ce que les endpoints font reellement. Sept
chaines sur seize demarraient par un slot mort, et le seul critere disponible
etait l'ordre de la liste.

Ce qu'on protege ici : qu'un role soit toujours adosse a une MESURE, et que la
specialite se lise sur des faits (nom oriente code, fenetre annoncee, outils
publies, latence et debit constates) plutot que sur une impression. Un role
sans justification serait un avis deguise en mesure.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_endpoint_profiling as P  # noqa: E402

RAPIDE = {"modele": "x", "latence_s": 0.8, "debit_tok_s": 120.0}


def test_un_modele_de_code_est_reconnu_au_nom():
    for nom in ("qwen2.5-coder:1.5b", "codestral-2508", "devstral-latest", "starcoder2-15b"):
        role, pourquoi = P.role_propose({**RAPIDE, "modele": nom}, {})
        assert role == "code", nom
        assert pourquoi, "un role sans justification est un avis"


def test_un_modele_de_raisonnement_est_reconnu():
    """Ils laissent `content` vide sur un budget court : les router vers de la
    surveillance rapide serait une faute, ils sont faits pour planifier."""
    for nom in ("deepseek-r1-distill-qwen-14b", "qwq-32b", "nemotron-3-nano"):
        assert P.role_propose({**RAPIDE, "modele": nom}, {})[0] == "reasoning", nom


def test_une_grande_fenetre_devient_un_role_de_contexte():
    role, pourquoi = P.role_propose(RAPIDE, {"context_length": 400_000})
    assert role == "context" and "400000" in pourquoi


def test_les_outils_publies_donnent_le_role_d_orchestration():
    role, _ = P.role_propose(RAPIDE, {"supported_parameters": ["tools", "temperature"]})
    assert role == "tool_call"


def test_la_vitesse_mesuree_donne_le_role_de_sentinelle():
    role, pourquoi = P.role_propose(RAPIDE, {})
    assert role == "sentinel/speed"
    assert "0.8" in pourquoi and "120" in pourquoi, "la mesure doit figurer"


def test_un_modele_lent_sans_specialite_reste_generaliste():
    role, _ = P.role_propose({"modele": "m", "latence_s": 9.0, "debit_tok_s": 4.0}, {})
    assert role == "general"


def test_un_local_lent_devient_le_fallback():
    """Lent mais sans quota ni egress : c'est precisement ce qu'on veut en
    dernier recours."""
    fiche = {"modele": "gemma4:e4b", "latence_s": 12.0, "debit_tok_s": 5.0, "local": True}
    role, pourquoi = P.role_propose(fiche, {})
    assert role == "fallback_local" and "quota" in pourquoi


def test_la_specialite_prime_sur_la_vitesse():
    """Un petit modele de code rapide reste un modele de CODE : sinon tous les
    rapides finiraient sentinelles et le role de code resterait vide."""
    assert P.role_propose({**RAPIDE, "modele": "qwen2.5-coder:1.5b"}, {})[0] == "code"


def test_le_quota_n_est_rapporte_que_s_il_est_expose():
    assert P.quota({}) == "NON MESURE"
    assert P.quota({"x-ratelimit-remaining-requests": "14400"}) == \
        "x-ratelimit-remaining-requests=14400"


def test_la_taille_ordonne_les_candidats():
    assert P._taille("qwen-1.5b") < P._taille("qwen-70b") < P._taille("anonyme")


# ── appel d'outil : APPELLE, IGNORE, REFUSE — jamais un seul « supporte » ────

def _reponse(monkeypatch, charge_utile: dict):
    """Repond une reponse OpenAI arbitraire, sans reseau."""
    import forge_tool_call_probe as T

    class _Rep:
        def read(self, _n=None):
            import json as _j
            return _j.dumps(charge_utile).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(T.urllib.request, "urlopen", lambda req, timeout=None: _Rep())
    return T


def test_un_appel_conforme_est_reconnu(monkeypatch):
    T = _reponse(monkeypatch, {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "etat_commande", "arguments": '{"numero": "CMD-4711"}'}}]}}]})
    fiche = T.interroger("http://x/v1", "", "m")
    assert fiche["etat"] == "APPELLE" and "CMD-4711" in fiche["motif"]


def test_une_reponse_en_texte_est_IGNORE_pas_APPELLE(monkeypatch):
    """Le piege central : le modele accepte `tools` et repond une phrase. Cable
    en orchestration, il ferait echouer la chaine en silence."""
    T = _reponse(monkeypatch, {"choices": [{"message": {"content": "Je ne peux pas verifier."}}]})
    fiche = T.interroger("http://x/v1", "", "m")
    assert fiche["etat"] == "IGNORE" and "texte" in fiche["motif"]


def test_un_autre_nom_de_fonction_ne_compte_pas(monkeypatch):
    T = _reponse(monkeypatch, {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "autre_chose", "arguments": "{}"}}]}}]})
    assert T.interroger("http://x/v1", "", "m")["etat"] == "IGNORE"


def test_des_arguments_non_json_ne_comptent_pas(monkeypatch):
    T = _reponse(monkeypatch, {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "etat_commande", "arguments": "numero=CMD-4711"}}]}}]})
    fiche = T.interroger("http://x/v1", "", "m")
    assert fiche["etat"] == "IGNORE" and "non JSON" in fiche["motif"]


def test_l_argument_requis_manquant_ne_compte_pas(monkeypatch):
    T = _reponse(monkeypatch, {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "etat_commande", "arguments": '{"autre": 1}'}}]}}]})
    assert T.interroger("http://x/v1", "", "m")["etat"] == "IGNORE"


def test_un_refus_http_est_distingue_d_un_ignore(monkeypatch):
    import forge_tool_call_probe as T

    def _refus(req, timeout=None):
        raise T.urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, None)

    monkeypatch.setattr(T.urllib.request, "urlopen", _refus)
    fiche = T.interroger("http://x/v1", "", "m")
    assert fiche["etat"] == "REFUSE" and "400" in fiche["motif"]


def test_un_reseau_ferme_reste_NON_MESURE(monkeypatch):
    import forge_tool_call_probe as T

    def _boom(req, timeout=None):
        raise OSError("WinError 10061")

    monkeypatch.setattr(T.urllib.request, "urlopen", _boom)
    assert T.interroger("http://x/v1", "", "m")["etat"] == "NON_MESURE"
