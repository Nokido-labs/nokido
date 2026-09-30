"""Non-regression : le contexte arrive-t-il VRAIMENT au point de convergence ?

Les autres tests de ce chantier prouvent la structure (AST : chaque site d'appel
porte `context=`) et la lecture (chaque fichier importe `contexte_legacy`). C'est
plus faible qu'une preuve par EFFET : un `context=` present dans le source pourrait
etre ecrase, ignore, ou perdu par une couche intermediaire.

Ici on EXECUTE reellement chacun des chemins, avec le vrai `router_call`, et on
constate ce que le convergent a recu. Seul le fournisseur est double -- le contexte
traverse donc tout le code reel qui le transporte.

Discipline : aucun chemin n'est SAUTE en silence. Si l'un ne peut pas etre execute
hermetiquement, il est marque `skip` avec sa raison -- « je n'ai pas pu regarder »
ne doit jamais se lire comme « ca marche ».
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_llm_router as llm  # noqa: E402
import forge_share_policy as sp  # noqa: E402


class _FauxRouteur:
    """Remplace le FOURNISSEUR, pas le routeur : `router_call` s'execute pour de bon."""

    def __init__(self):
        self.appels = []

    def call(self, prompt, use_case, max_tokens, **kw):
        self.appels.append({"prompt": prompt, "use_case": use_case, "kw": kw})
        return {"ok": True, "text": "reponse de test", "provider": "faux"}


@pytest.fixture(autouse=True)
def _observation_isolee(tmp_path, monkeypatch):
    """AUCUN test n'ecrit dans l'agregat de PRODUCTION.

    Mesure 2026-09-02 : sans cette isolation, les tests qui appellent le vrai
    `router_call` incrementaient `sandbox/share_context_observation.json`. Le
    fichier affichait alors 16 observations dont ZERO trafic reel -- un compteur
    de production nourri par sa propre suite de tests fabrique une mesure, et la
    mesure fabriquee ressemble exactement a une vraie.
    """
    monkeypatch.setattr(sp, "_OBS", tmp_path / "observation_test.json")


@pytest.fixture()
def routeur(monkeypatch):
    faux = _FauxRouteur()
    monkeypatch.setattr(llm, "get_router", lambda: faux)
    return faux


def _contexte_vu(reponse) -> dict:
    """Ce que `router_call` a joint a la reponse. C'est la trace de l'EFFET."""
    assert isinstance(reponse, dict), reponse
    return reponse.get("contexte_partage") or {}


# --------------------------------------------------------------------------- #
# Le convergent lui-meme
# --------------------------------------------------------------------------- #

def test_sans_contexte_le_convergent_le_dit(routeur):
    """Un appel nu doit se voir : ABSENT, pas un silence."""
    rep = llm.router_call("bonjour", use_case="fast")
    assert _contexte_vu(rep) == {"contexte": "ABSENT"}


def test_avec_contexte_le_convergent_le_recoit(routeur):
    ctx = sp.SwarmRequestContext(identity="VIBE", data_class="INTERNAL",
                                 collaboration="SWARM", provenance="test")
    rep = llm.router_call("bonjour", use_case="fast", context=ctx)
    vu = _contexte_vu(rep)
    assert vu["data_class"] == "INTERNAL"
    assert vu["instrumente"] is True


def test_le_contexte_n_est_pas_transmis_au_fournisseur(routeur):
    """Le contexte sert a DECIDER, il n'a rien a faire dans la charge utile."""
    ctx = sp.SwarmRequestContext(identity="VIBE", data_class="SECRET",
                                 collaboration="PRIVATE")
    llm.router_call("bonjour", use_case="fast", context=ctx)
    assert routeur.appels, "le fournisseur n'a pas ete appele"
    kw = routeur.appels[-1]["kw"]
    assert "context" not in kw, kw
    for interdit in ("data_class", "collaboration", "audience"):
        assert interdit not in kw, (interdit, kw)


# --------------------------------------------------------------------------- #
# Les chemins reels, EXECUTES
# --------------------------------------------------------------------------- #

def test_chemin_handoff_transporte_le_contexte(routeur):
    import forge_handoff as hf

    rep = hf._call_router("bonjour", use_case="fast", max_tokens=16)
    vu = (rep.get("_router_meta") or {}).get("contexte_partage") or {}
    assert vu, "forge_handoff n'a transmis AUCUN contexte"
    assert vu["provenance"] == "forge_handoff._call_router"
    assert vu["data_class"] == sp.INCONNU, "un chemin legacy ne doit rien inventer"


def test_chemin_internal_sampling_transporte_le_contexte(routeur, monkeypatch):
    import forge_internal_sampling as ins

    vu = {}
    vrai = llm.router_call

    def _espion(*a, **kw):
        vu["context"] = kw.get("context")
        return vrai(*a, **kw)

    monkeypatch.setattr(llm, "router_call", _espion)
    ins.sample("bonjour", purpose="test", max_tokens=16)
    ctx = vu.get("context")
    assert ctx is not None, "forge_internal_sampling n'a transmis AUCUN contexte"
    assert ctx.provenance == "forge_internal_sampling.sample"
    assert ctx.data_class == sp.INCONNU


def test_chemin_mcp_transporte_le_contexte(routeur, monkeypatch):
    """Le chemin le plus expose : un tool MCP, atteignable par tout agent connecte."""
    try:
        import mcp_server_tools as mst
    except Exception as e:  # noqa: BLE001
        pytest.skip("mcp_server_tools non importable ici : %s" % str(e)[:120])

    # On n'ESPIONNE PAS router_call : `mcp_server_tools` le reimporte DANS sa
    # fonction, donc un double pose sur le module peut ne pas etre celui qu'il
    # resout (mesure 2026-09-02 : le test passait dans le working tree et echouait
    # sur l'arbre detache -- il prouvait donc autre chose que ce qu'il annoncait).
    # On laisse le VRAI router_call s'executer et on lit ce qu'il a JOINT : c'est
    # l'effet final, et il ne depend d'aucun patch intermediaire.
    import json as _json

    fn = getattr(mst.llm_router_call, "fn", mst.llm_router_call)
    brut = asyncio.run(fn("bonjour", use_case="fast", max_tokens=16))
    rep = _json.loads(brut)

    # L'INVARIANT REEL, decouvert en EXECUTANT sur l'arbre detache : ce tool est
    # deja garde EN AMONT par une capability (scope=system) et refuse sans jeton --
    # il n'atteint alors jamais router_call. Ma cartographie comptait les APPELS,
    # pas les GARDES : deux des quatre chemins dits « non gardes » avaient en fait
    # leur propre controle (celui-ci, et le RBAC 403 de forge_router_gateway).
    #
    # Donc deux issues acceptables, et une seule interdite : passer SANS contexte.
    if rep.get("ok") is False and "CAPABILITY" in str(rep.get("error", "")).upper():
        return  # refuse en amont : la donnee n'est jamais sortie
    vu = rep.get("contexte_partage") or {}
    assert vu, "le tool a REPONDU sans contexte de partage : %s" % str(rep)[:200]
    assert vu.get("provenance") == "mcp_server_tools.llm_router_call", vu
    assert vu.get("data_class") == sp.INCONNU, "un chemin legacy ne doit rien inventer"


def test_chemin_gateway_transporte_le_contexte(routeur, monkeypatch):
    try:
        import forge_router_gateway as gw
    except Exception as e:  # noqa: BLE001
        pytest.skip("forge_router_gateway non importable ici : %s" % str(e)[:120])

    vu = {}
    vrai = llm.router_call

    def _espion(*a, **kw):
        vu["context"] = kw.get("context")
        return vrai(*a, **kw)

    monkeypatch.setattr(llm, "router_call", _espion)
    try:
        req = gw.GenerateRequest(prompt="bonjour", use_case="fast", max_tokens=16)
    except Exception as e:  # noqa: BLE001
        pytest.skip("GenerateRequest non constructible hors FastAPI : %s" % str(e)[:120])
    # `generate` est une route FastAPI : hors du framework, `x_agent_id` vaut encore
    # l'objet `Header(...)` et non une chaine. On fournit donc la valeur, comme le
    # ferait l'injection de dependances -- un test doit imiter sa source.
    #
    # ET CE CHEMIN A DEJA SON PROPRE GATE : mesure 2026-09-02, `generate` refuse en
    # 403 tout agent READ_ONLY AVANT d'atteindre router_call. Ce n'etait donc pas une
    # porte ouverte, contrairement a ce que la seule cartographie des appels laissait
    # croire. On neutralise ce gate ICI parce qu'on teste le TRANSPORT du contexte,
    # pas le RBAC -- et surtout on ne le contourne pas en production.
    monkeypatch.setattr(gw, "_get_level", lambda agent_id: "MASTER_DEV")
    asyncio.run(gw.generate(req, x_agent_id="TEST"))
    ctx = vu.get("context")
    assert ctx is not None, "forge_router_gateway n'a transmis AUCUN contexte"
    assert ctx.provenance == "forge_router_gateway.generate"


# --------------------------------------------------------------------------- #
# Observation persistee : le denominateur doit exister HORS du process
# --------------------------------------------------------------------------- #

def test_l_observation_est_ecrite_sur_disque(routeur):
    """Une reponse n'est lue que par son appelant : sans agregat sur disque, le
    denominateur est invisible depuis l'exterieur du hub."""
    llm.router_call("a", use_case="fast")                       # ABSENT
    llm.router_call("b", use_case="fast", context=sp.contexte_legacy(provenance="x"))
    llm.router_call("c", use_case="fast",
                    context=sp.SwarmRequestContext(data_class="INTERNAL",
                                                   collaboration="SWARM",
                                                   provenance="y"))
    obs = sp.observation()
    assert obs["etat"] == "MESURE"
    assert obs["total"] == 3, obs
    assert obs["par_etat"] == {"ABSENT": 1, "PRESENT_MAIS_INCONNU": 1, "PRESENT": 1}, obs
    assert abs(obs["taux_classe"] - 1 / 3) < 1e-9, obs


def test_les_trois_etats_ne_sont_pas_fondus(routeur):
    """Fondre ABSENT et PRESENT_MAIS_INCONNU ferait passer un cablage a moitie
    fait pour une politique appliquee."""
    llm.router_call("a", use_case="fast")
    llm.router_call("b", use_case="fast", context=sp.contexte_legacy())
    pe = sp.observation()["par_etat"]
    assert pe["ABSENT"] == 1 and pe["PRESENT_MAIS_INCONNU"] == 1


def test_l_observation_ventile_par_provenance(routeur):
    """Savoir QUEL chemin n'est pas classe est ce qui rend la dette actionnable."""
    llm.router_call("a", use_case="fast",
                    context=sp.contexte_legacy(provenance="forge_handoff._call_router"))
    par_prov = sp.observation()["par_provenance"]
    assert par_prov["forge_handoff._call_router"]["PRESENT_MAIS_INCONNU"] == 1


def test_aucun_test_n_ecrit_dans_l_agregat_de_production():
    """Garde de l'isolation elle-meme.

    Un compteur de production nourri par sa propre suite de tests fabrique une
    mesure, et une mesure fabriquee ressemble exactement a une vraie -- c'est
    arrive le 2026-09-02 : 16 observations, zero trafic reel.
    """
    prod = (ROOT / "sandbox" / "share_context_observation.json").resolve()
    assert sp._OBS.resolve() != prod, (
        "les tests ecrivent dans l'agregat de PRODUCTION : la fixture d'isolation "
        "ne s'applique pas")


def test_absence_de_fichier_n_est_pas_un_zero_mesure():
    """« Jamais ecrit » et « zero appel » appellent des actions opposees."""
    obs = sp.observation()
    assert obs["etat"] == "JAMAIS_ECRIT"
    assert obs["total"] == 0
    assert obs["taux_classe"] is None, "un taux sur zero appel doit etre None, pas 0.0"


def test_l_observation_ne_casse_jamais_l_appel(routeur, monkeypatch):
    """Si le disque refuse, l'appel doit passer quand meme."""
    def _boum(*a, **kw):
        raise OSError("disque plein")

    monkeypatch.setattr(sp, "noter_appel", _boum)
    rep = llm.router_call("a", use_case="fast")
    assert rep["ok"] is True


# --------------------------------------------------------------------------- #
# Etape 6 : le canal M2M porte les metadonnees, JAMAIS le contenu
# --------------------------------------------------------------------------- #

def test_l_enveloppe_m2m_est_acceptee_par_le_validateur():
    """Elle doit passer le validateur REEL, pas un schema suppose."""
    import forge_m2m_protocol as m2m

    ctx = sp.SwarmRequestContext(identity="CLAUDE", audience=("ANTIGRAVITY",),
                                 data_class="INTERNAL", collaboration="SELECTED_AGENTS",
                                 provenance="sandbox/security_reviews/x.json")
    env = sp.enveloppe_m2m(ctx, "REVIEW_FINDING")
    v = m2m.validate("notify", env)
    assert v["code"] == "M2M_OK", v


def test_l_enveloppe_porte_le_pointeur_et_pas_la_charge():
    ctx = sp.SwarmRequestContext(identity="CLAUDE", provenance="bb:zone/cle",
                                 data_class="CONFIDENTIAL", collaboration="SWARM")
    env = sp.enveloppe_m2m(ctx, "REVIEW_OK")
    assert env["pointer_ref"] == "bb:zone/cle"
    assert env["data_class"] == "CONFIDENTIAL"
    assert env["sender"] == "CLAUDE"
    # Aucun champ ne doit contenir de charge utile : le canal reste maigre.
    for cle, val in env.items():
        assert not (isinstance(val, str) and len(val) > 300), cle


def test_une_enveloppe_sans_pointeur_ne_peut_pas_etre_EMISE():
    """Refus VOULU : une revue sans artefact n'est qu'une opinion."""
    with pytest.raises(ValueError) as e:
        sp.enveloppe_m2m(None, "REVIEW_UNKNOWN")
    assert "pointer_ref" in str(e.value)


def test_le_validateur_LUI_accepte_un_pointeur_vide():
    """ECART MESURE, consigne pour qu'il ne trompe personne.

    Le validateur verifie la PRESENCE du champ, pas qu'il soit renseigne : une
    enveloppe `pointer_ref: ""` sort en M2M_OK. Present n'est pas renseigne. C'est
    pourquoi le garde est pose cote PRODUCTEUR (enveloppe_m2m leve) et non ici.

    Ce test ECHOUERA le jour ou le validateur exigera un pointeur non vide -- et ce
    sera une bonne nouvelle : il faudra alors le remplacer par son inverse.
    """
    import forge_m2m_protocol as m2m

    v = m2m.validate("notify", {"intent": "REVIEW_UNKNOWN", "pointer_ref": ""})
    assert v["code"] == "M2M_OK", (
        "le validateur exige desormais un pointeur non vide : mettre ce test a jour", v)


def test_l_enveloppe_d_un_contexte_absent_declare_UNKNOWN():
    env = sp.enveloppe_m2m(None, "REVIEW_UNKNOWN", pointer_ref="p")
    assert env["data_class"] == sp.INCONNU
    assert env["collaboration"] == sp.INCONNU
    assert env["audience"] == []


def test_chemin_swarm_router_transporte_le_contexte(routeur, monkeypatch):
    import forge_swarm_router as sr

    monkeypatch.setattr(sr, "authorize",
                        lambda **kw: {"allow": True, "ring": 2, "via": "test"})
    rep = sr.route_subtask("VIBE", "tache", token="t", data_class="INTERNAL",
                           collaboration="SWARM", audience=["ANTIGRAVITY"])
    assert rep["status"] == "ok", rep
    assert rep["partage"]["contexte"] == "PRESENT"
    assert rep["partage"]["decision"] == sp.ALLOW
