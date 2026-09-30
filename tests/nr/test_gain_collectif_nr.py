"""Non-regression : mesurer ce que le collectif apporte, et ce qu'il retire.

Mesure du 2026-08-26. Nokido portait deja l'appareil complet d'une intelligence
collective -- `route_swarm` (politiques, fanout 1/2/3/5, angles, voix independantes,
porte deterministe), `arbitrer`, les roles de debat -- et ces trois organes n'avaient
AUCUN appelant hors de leur propre fichier. Ce qui manquait n'etait pas un framework
de plus : c'etait le DENOMINATEUR. On mesurait le collectif OU l'agent, jamais l'ECART,
et le cout produit par `router_call` (`elapsed_ms`, `tokens`) etait jete par son propre
appelant.

Ce fichier verrouille la mesure. Hermetique : aucune tentative n'appelle un LLM, tout
est construit en memoire.
"""

from __future__ import annotations

import sys
from pathlib import Path

_APP = Path(__file__).resolve().parents[2] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from forge_swarm_evidence import Tentative  # noqa: E402
from forge_swarm_router import cout_de, gain_collectif, score_de  # noqa: E402


def _t(sol, test_ok, modele="m1", angle="minimal", tokens=100, ms=500.0):
    return Tentative(modele=modele, provider=modele, strategie=angle, sortie="x",
                     solution_id=sol, test_ok=test_ok, format_ok=True,
                     tokens=tokens, latence_ms=ms)


# ------------------------------------------------------------------- score

def test_le_score_a_trois_etats_et_le_troisieme_nest_pas_zero():
    """Une tentative non verifiee n'est pas une tentative ratee : sans ce troisieme
    etat, un fanout jamais verifie rendrait « 0 % » au lieu de « je n'ai pas vu »."""
    assert score_de(_t("a", True)) == 1.0
    assert score_de(_t("a", False)) == 0.0
    assert score_de(_t("a", None)) is None


# -------------------------------------------------------------------- cout

def test_le_cout_porte_son_denominateur():
    """5 appels dont 2 sans usage rendu : le total ne doit pas se lire « gratuit »."""
    c = cout_de([_t("a", True, tokens=100), _t("b", False, tokens=200),
                 _t("c", None, tokens=0)])
    assert c["appels"] == 3 and c["tokens"] == 300
    assert c["tokens_mesures"] == 2 and c["tokens_inconnus"] == 1
    assert c["tokens_par_appel"] == 150.0


def test_un_cout_totalement_non_mesure_le_dit():
    c = cout_de([_t("a", True, tokens=0), _t("b", True, tokens=0)])
    assert c["tokens"] == 0 and c["tokens_mesures"] == 0
    assert c["tokens_par_appel"] is None, "0 tokens mesures ne vaut pas 0 token consomme"


# ------------------------------------------------------- les deux baselines

def test_le_collectif_qui_choisit_le_meilleur_ne_perd_rien_et_gagne_sur_le_hasard():
    """Le cas nominal : 3 agents, un seul a raison, l'arbitrage le retient."""
    ts = [_t("bonne", True, "m1"), _t("fausse", False, "m2"), _t("fausse", False, "m3")]
    g = gain_collectif(ts, "bonne")
    assert g["oracle"] == 1.0 and g["moyen"] == round(1 / 3, 4)
    assert g["collectif"] == 1.0
    assert g["gain_vs_oracle"] == 0.0, "il n'a pas fait moins bien que le meilleur"
    assert g["gain_vs_moyen"] > 0.6, "et bien mieux qu'un agent tire au hasard"
    assert g["degrade"] is False


def test_le_cas_NEGATIF_est_mesure_quand_larbitrage_choisit_moins_bien():
    """Le point que la litterature dit central et que personne ne mesure chez soi :
    la bonne reponse etait la, le collectif ne l'a pas prise."""
    ts = [_t("bonne", True, "m1"), _t("fausse", False, "m2"), _t("fausse", False, "m3")]
    g = gain_collectif(ts, "fausse")
    assert g["collectif"] == 0.0 and g["oracle"] == 1.0
    assert g["gain_vs_oracle"] == -1.0, "le regret doit etre NEGATIF, pas absent"
    assert g["degrade"] is True
    assert g["gain_vs_moyen"] < 0


def test_comparer_au_seul_oracle_ferait_toujours_perdre_le_collectif():
    """Garde de methode : meme quand tout le monde a raison, le gain vs oracle est
    nul — c'est pourquoi la seconde baseline existe."""
    ts = [_t("bonne", True, "m1"), _t("bonne", True, "m2")]
    g = gain_collectif(ts, "bonne")
    assert g["gain_vs_oracle"] == 0.0
    assert g["gain_vs_moyen"] == 0.0, "trois fois d'accord n'apporte rien de plus"
    assert g["degrade"] is False


# ------------------------------------------------------------- trois etats

def test_sans_verificateur_rien_nest_affirme():
    ts = [_t("a", None, "m1"), _t("b", None, "m2")]
    g = gain_collectif(ts, "a")
    assert g["mesurees"] == 0 and g["non_mesurees"] == 2
    assert g["gain_vs_oracle"] is None and g["degrade"] is None
    assert "rien n'est mesure" in g["raison"]


def test_une_seule_prouvee_non_livree_accuse_la_DIVERSITE_pas_la_reponse():
    """Cas mesure : une bonne reponse existe, l'arbitrage ne la retient pas faute de
    voix INDEPENDANTES. Le libelle doit pointer la diversite, sinon on ira corriger
    le prompt alors que le defaut est dans le cablage du fanout."""
    ts = [_t("a", True, "m1"), _t("b", None, "m1")]
    g = gain_collectif(ts, "inconnue")
    assert g["collectif"] is None and g["livre"] is False
    assert "NON LIVREE" in g["raison"] and "DIVERSITE" in g["raison"]


def test_sans_aucune_preuve_le_collectif_ne_se_compare_a_rien():
    ts = [_t("a", False, "m1"), _t("b", False, "m2")]
    g = gain_collectif(ts, "inconnue")
    assert g["mesurees"] == 2 and g["livre"] is False
    assert "ne se compare a rien" in g["raison"]


def test_une_tache_CONTESTEE_nest_pas_une_tache_non_mesuree():
    """Mesure du 2026-08-26 sur HumanEval/1 et /2 : les DEUX tentatives passent les
    tests unitaires, avec des solutions differentes ; l'arbitrage refuse de trancher
    (« 2 solutions differentes sont prouvees ») et ne livre rien. Le collectif a
    TROUVE, il n'a pas CHOISI — c'est un cout de prudence, pas une cecite."""
    ts = [_t("sol_a", True, "m1", angle="minimal"),
          _t("sol_b", True, "m1", angle="cause_racine")]
    g = gain_collectif(ts, "")           # aucune solution retenue
    assert g["mesurees"] == 2, "les deux tentatives ONT ete mesurees"
    assert g["livre"] is False
    assert g["score_si_livre"] == 1.0, "une bonne reponse existait bel et bien"
    assert g["collectif"] is None and g["gain_vs_moyen"] is None
    assert "CONTESTEE" in g["raison"] and "2 solutions prouvees" in g["raison"]


def test_une_tache_livree_est_marquee_livree():
    ts = [_t("bonne", True, "m1"), _t("fausse", False, "m2")]
    g = gain_collectif(ts, "bonne")
    assert g["livre"] is True and g["collectif"] == 1.0


def test_le_gain_ajuste_est_None_quand_le_cout_nest_pas_mesure():
    """Un backend local qui ne rend pas d'usage ne doit pas produire un ratio invente."""
    ts = [_t("bonne", True, "m1", tokens=0), _t("fausse", False, "m2", tokens=0)]
    g = gain_collectif(ts, "bonne")
    assert g["gain_vs_moyen"] == 0.5
    assert g["gain_ajuste_par_ktokens"] is None
    assert "non mesure" in g["raison"]


def test_le_gain_ajuste_rapporte_le_gain_au_SURCOUT_pas_au_total():
    """Le surcout est ce que le fanout ajoute a UN appel moyen : rapporter au total
    ferait baisser le ratio a mesure qu'on ajoute des agents, meme utiles."""
    ts = [_t("bonne", True, "m1", tokens=1000), _t("fausse", False, "m2", tokens=1000)]
    g = gain_collectif(ts, "bonne")
    # gain_vs_moyen = 0.5 ; surcout = 2000 - 1000 = 1000 tokens = 1 ktoken
    assert g["gain_ajuste_par_ktokens"] == 0.5


# ------------------------------------------------- le cout traverse la chaine

def test_le_fanout_demande_un_AUTRE_modele_a_chaque_angle(monkeypatch):
    """Le correctif du plafond de voix. Sans exclusion, les N tentatives partaient au
    MEME modele et `voix_independantes` restait a 1 : 5 reponses justes sur 6 et zero
    acceptee (mesure du 2026-08-26)."""
    import forge_swarm_router as R

    monkeypatch.setattr(R, "authorize", lambda **k: {"allow": True}, raising=False)
    vus = []
    dispo = ["p1", "p2", "p3"]

    def _faux(prompt, use_case="general", **k):
        exclus = list(k.get("exclure") or ())
        vus.append(exclus)
        restants = [p for p in dispo if p not in exclus]
        if not restants:
            return {"ok": False, "error": "plus de provider", "provider": None,
                    "diversite_epuisee": True}
        return {"ok": True, "text": "R-" + restants[0], "provider": restants[0],
                "model": restants[0], "elapsed_ms": 10.0, "tokens": 5}

    monkeypatch.setattr(R, "router_call", _faux, raising=False)
    res = R.route_swarm("CLAUDE", "t", politique="critique",   # fanout 5
                        verificateur=lambda t: (True, ["p"]))
    assert res["modeles_entendus"] == ["p1", "p2", "p3"], "chaque tour change de modele"
    assert vus[0] == [] and vus[1] == ["p1"] and vus[2] == ["p1", "p2"]
    # 4e tour : plus rien a interroger -> on s'arrete au lieu de re-signer une voix
    assert any("diversite epuisee" in (t.get("erreur") or "") for t in res["tentatives"])
    assert len(res["modeles_entendus"]) == 3


def test_le_mode_single_ne_cherche_pas_de_second_avis(monkeypatch):
    import forge_swarm_router as R

    monkeypatch.setattr(R, "authorize", lambda **k: {"allow": True}, raising=False)
    vus = []

    def _faux(prompt, use_case="general", **k):
        vus.append(k.get("exclure"))
        return {"ok": True, "text": "R", "provider": "p1", "model": "p1",
                "elapsed_ms": 5.0, "tokens": 3}

    monkeypatch.setattr(R, "router_call", _faux, raising=False)
    R.route_swarm("CLAUDE", "t", politique="simple", verificateur=lambda t: (True, []))
    assert vus == [None], "un appel unique n'exclut personne"


def test_un_echec_du_routeur_nest_plus_lu_comme_une_reponse(monkeypatch):
    """route_subtask renvoyait status ok avec un texte vide quand router_call rendait
    ok=False : l'aval comptait un ECHEC comme une tentative valide."""
    import forge_swarm_router as R

    monkeypatch.setattr(R, "authorize", lambda **k: {"allow": True}, raising=False)
    monkeypatch.setattr(R, "router_call",
                        lambda prompt, use_case="general", **k: {
                            "ok": False, "error": "tous les slots sont muets"},
                        raising=False)
    rep = R.route_subtask("CLAUDE", "t")
    assert rep["status"] == "error" and "muets" in rep["reason"]


def test_route_swarm_expose_cout_et_gain(monkeypatch):
    """Test d'effet : le coût rendu par le routeur LLM traverse `route_subtask` puis
    `route_swarm` au lieu d'etre jete -- c'etait le defaut d'origine."""
    import forge_swarm_router as R

    monkeypatch.setattr(R, "authorize", lambda **k: {"allow": True}, raising=False)

    def _faux_router_call(prompt, use_case="general", **k):
        juste = "[ANGLE IMPOSE] Corrige au plus juste" in prompt
        return {"text": "REPONSE-A" if juste else "REPONSE-B", "provider": "p1",
                "model": "modele-x", "elapsed_ms": 250.0, "tokens": 700}

    monkeypatch.setattr(R, "router_call", _faux_router_call, raising=False)
    res = R.route_swarm("CLAUDE", "tache", politique="incertain",
                        verificateur=lambda t: (t == "REPONSE-A", ["preuve"]))
    assert res["cout"]["appels"] == 2
    assert res["cout"]["tokens"] == 1400, "le cout ne doit plus etre jete"
    assert res["cout"]["latence_ms"] == 500.0
    assert res["gain"]["oracle"] == 1.0 and res["gain"]["moyen"] == 0.5
    assert res["tentatives"][0]["tokens"] == 700
    assert res["tentatives"][0]["modele"] == "modele-x", "le modele, pas le provider"
