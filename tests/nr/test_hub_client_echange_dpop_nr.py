"""NR -- option B, etape client (owner 30/10) : un job porteur d'un jeton de job ne lit PLUS le coffre a la construction
de HubClient ; chaque appel d'outil echange (RFC 8693) pour la portee EXACTE de l'appel et part en DPoP (RFC 9449).
Portee refusee par la politique : repli TARDIF sur le chemin actuel, journalise (observer avant d'enforcer).
Sans jeton de job : comportement d'avant. Faux reseau, aucun secret reel.
"""
import json
import logging
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE)]
from nokido_agent.app import forge_hub_client as HC  # noqa: E402


class _Rep:
    def __init__(self, corps):
        self._c = json.dumps(corps).encode()

    def read(self):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def reseau(monkeypatch):
    vues = []

    def urlopen(req, timeout=None):
        vues.append(req)
        return _Rep({"result": {"content": [{"type": "text", "text": "ok"}]}})
    monkeypatch.setattr(HC.urllib.request, "urlopen", urlopen)
    return vues


@pytest.fixture
def job(monkeypatch):
    monkeypatch.setenv("NOKIDO_JOB_SUBJECT_TOKEN", "sujet-factice")
    monkeypatch.setenv("NOKIDO_JOB_ID", "job_factice")
    monkeypatch.setattr(HC, "_echange_arme", lambda: True)


def test_interrupteur_desarme_comportement_d_avant_meme_avec_jeton_de_job(monkeypatch, reseau):
    monkeypatch.setenv("NOKIDO_JOB_SUBJECT_TOKEN", "sujet-factice")
    monkeypatch.setenv("NOKIDO_JOB_ID", "job_factice")
    monkeypatch.setattr(HC, "_echange_arme", lambda: False)
    lus = []
    monkeypatch.setattr(HC, "_resoudre_jeton", lambda agent: lus.append(agent) or ("STATIQUE", "coffre:FORGE_TOKEN_X"))
    monkeypatch.setenv("LAFORGE_HUB_CLIENT_JETON_COURT", "0")
    c = HC.HubClient(agent="SELF_PATCHER")
    assert lus == ["SELF_PATCHER"]
    c.tool("task", {"action": "status"})
    assert reseau[-1].get_header("Authorization") == "Bearer STATIQUE"


def _coffre_interdit(*a, **k):
    raise AssertionError("coffre lu alors qu'un jeton de job permet l'echange")


def test_avec_jeton_de_job_le_coffre_n_est_pas_lu_et_l_appel_part_en_dpop(monkeypatch, job, reseau):
    monkeypatch.setattr(HC, "_resoudre_jeton", _coffre_interdit)
    demandes = []

    def echanger(self, portee):
        demandes.append(portee)
        from cryptography.hazmat.primitives.asymmetric import ec
        return "ACCES_FACTICE", ec.generate_private_key(ec.SECP256R1()), 300
    monkeypatch.setattr(HC.HubClient, "_echanger_portee", echanger)
    c = HC.HubClient(agent="SELF_PATCHER")
    assert c.tool("ask", {"prompt": "x"}) == "ok"
    assert demandes == ["ask:appel"]
    req = reseau[-1]
    assert req.get_header("Authorization") == "DPoP ACCES_FACTICE"
    assert req.get_header("Dpop")  # urllib capitalise les noms d'en-tete
    c.tool("ask", {"prompt": "y"})
    assert demandes == ["ask:appel"]  # jeton de la portee en cache jusqu'a expiration


def test_portee_refusee_repli_tardif_journalise(monkeypatch, job, reseau, caplog):
    lus = []
    monkeypatch.setattr(HC, "_resoudre_jeton", lambda agent: lus.append(agent) or ("STATIQUE", "coffre:FORGE_TOKEN_X"))
    monkeypatch.setattr(HC.HubClient, "_echanger_portee", lambda self, portee: None)
    monkeypatch.setenv("LAFORGE_HUB_CLIENT_JETON_COURT", "0")
    c = HC.HubClient(agent="SELF_PATCHER")
    assert lus == []  # rien lu a la construction
    with caplog.at_level(logging.WARNING):
        c.tool("rag", {"action": "search"})
    assert lus == ["SELF_PATCHER"]
    assert reseau[-1].get_header("Authorization") == "Bearer STATIQUE"
    assert any("rag:search" in r.getMessage() for r in caplog.records)


def test_appel_outil_rend_le_dict_brut_par_l_echange(monkeypatch, job, reseau):
    """Mesure reelle 30/10 (journal du coffre, job_eb088676d2b6) : forge_self_patcher._hub_call construisait ses propres
    en-tetes Bearer (entetes_repli_env) -> repli tardif -> lecture de FORGE_TOKEN_SELF_PATCHER. appel_outil passe par
    _req, donc par l'echange, et rend la reponse JSON-RPC brute que l'appelant lisait."""
    monkeypatch.setattr(HC, "_resoudre_jeton", _coffre_interdit)

    def echanger(self, portee):
        from cryptography.hazmat.primitives.asymmetric import ec
        return "ACCES_FACTICE", ec.generate_private_key(ec.SECP256R1()), 300
    monkeypatch.setattr(HC.HubClient, "_echanger_portee", echanger)
    c = HC.HubClient(agent="SELF_PATCHER")
    r = c.appel_outil("ask", {"prompt": "x"}, timeout=90)
    assert r == {"result": {"content": [{"type": "text", "text": "ok"}]}}
    assert reseau[-1].get_header("Authorization") == "DPoP ACCES_FACTICE"


def test_le_self_patcher_passe_par_appel_outil_quand_l_echange_est_arme(monkeypatch, job):
    sys.path.insert(0, str(RACINE / "tools"))
    import forge_self_patcher as SP
    vus = []

    class _Client:
        _echange_job = True

        def appel_outil(self, name, args, timeout=None):
            vus.append((name, timeout))
            return {"result": {"content": [{"type": "text", "text": "ok"}]}}

        def entetes_repli_env(self):
            raise AssertionError("en-tetes Bearer construits alors que l'echange est arme")
    monkeypatch.setattr(SP, "_HUB_CLIENT", _Client())
    assert SP._hub_call("ask", {"prompt": "x"}, timeout=90)["result"]["content"][0]["text"] == "ok"
    assert vus == [("ask", 90)]


def test_la_provenance_du_self_patcher_ne_lit_pas_le_coffre_en_voie_d_echange(monkeypatch, job):
    """Mesure reelle 30/10 (journal du coffre, job_fce6a9f71bd4) : forge_self_patcher calculait au chargement
    `_PROVENANCE_JETON = ... + _HUB_CLIENT._jeton_courant()[1]`, pour une simple etiquette -- ce qui declenchait le repli
    tardif et lisait FORGE_TOKEN_SELF_PATCHER."""
    sys.path.insert(0, str(RACINE / "tools"))
    import forge_self_patcher as SP
    monkeypatch.setattr(HC, "_resoudre_jeton", _coffre_interdit)
    from nokido_agent.app import forge_agent_credential as AC
    monkeypatch.setattr(AC, "jeton_pour", _coffre_interdit)
    monkeypatch.setattr(SP, "_HUB_CLIENT", None)
    SP._resolve_hub_token()
    assert "echange" in SP._PROVENANCE_JETON


def test_le_chargement_du_module_ne_lit_pas_le_coffre_en_voie_d_echange():
    """Mesure reelle 30/10 : `_TOKEN, _TOKEN_SRC = _resoudre_jeton(_AGENT)` au CHARGEMENT faisait lire
    FORGE_TOKEN_SERVICES a tout job qui importe ce client (aucun consommateur de _TOKEN hors du module)."""
    import ast
    src = (RACINE / "app" / "forge_hub_client.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    nus = [n for n in arbre.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
           and getattr(n.value.func, "id", "") == "_resoudre_jeton"]
    assert not nus, "lecture du coffre inconditionnelle au chargement du module"
    # 31/10 (COF-1) : la condition vit dans _resolution_au_chargement (voie d'echange ET jeton injecte par le lanceur) ;
    # le comportement est eprouve par tests/nr/test_service_jeton_injecte_sans_coffre_nr.py.
    fonc = [n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "_resolution_au_chargement"]
    assert fonc, "resolution au chargement introuvable"
    corps = ast.unparse(fonc[0])
    assert "NOKIDO_JOB_SUBJECT_TOKEN" in corps and "_resoudre_jeton" in corps
    assert corps.index("NOKIDO_JOB_SUBJECT_TOKEN") < corps.index("_resoudre_jeton")  # la voie d'echange passe AVANT
    appels = [n for n in arbre.body if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
              and getattr(n.value.func, "id", "") == "_resolution_au_chargement"]
    assert appels, "_TOKEN n'est plus resolu par la fonction conditionnelle"


def test_sans_jeton_de_job_comportement_d_avant(monkeypatch, reseau):
    monkeypatch.delenv("NOKIDO_JOB_SUBJECT_TOKEN", raising=False)
    monkeypatch.delenv("NOKIDO_JOB_ID", raising=False)
    lus = []
    monkeypatch.setattr(HC, "_resoudre_jeton", lambda agent: lus.append(agent) or ("STATIQUE", "coffre:FORGE_TOKEN_X"))
    monkeypatch.setattr(HC.HubClient, "_echanger_portee", _coffre_interdit)
    monkeypatch.setenv("LAFORGE_HUB_CLIENT_JETON_COURT", "0")
    c = HC.HubClient(agent="SERVICES")
    assert lus == ["SERVICES"]
    c.tool("task", {"action": "status"})
    assert reseau[-1].get_header("Authorization") == "Bearer STATIQUE"
