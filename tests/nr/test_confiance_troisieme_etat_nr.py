# -*- coding: utf-8 -*-
"""Non-regression — la confiance de l'intuition GOAP a TROIS etats, jamais deux.

Constitution semantique (RULES_SHARED, 2026-09-05) : UNKNOWN != NO. Et la symetrie
compte autant : UNKNOWN != YES — « ne pas remplacer une sur-deduction par une autre ».

Mesure du 2026-09-08, sur le chemin reel, apres lecture directe des deux sites :

  app/forge_goap_intuition._confidence
    aucun score positif -> 0.0   absence de signal rendue identique a un signal PLAT
    un seul candidat    -> 1.0   marge NON mesurable rendue comme certitude MAXIMALE

  tools/forge_goap_hub_bridge.GOAPPlanner.plan
    conf = 1.0 en valeur par defaut (L146), et le `except` qui protege le planner
    (L160) remet `allowed` a None sans jamais remettre `conf` : une intuition qui
    LEVE laisse donc la confiance a 1.0.

Effet MESURE, et c'est lui qui rend le defaut couteux : conf >= conf_threshold (0.25)
elague aux top_k ET rend faux le test du reflexe doute->oracle (L167), c'est-a-dire
desarme « dans le doute, teste avant d'agir » devant une action a effet RISQUE. Un
echec silencieux de l'intuition produit donc la confiance maximale et supprime la
verification. La branche `0.0` tombait du cote prudent par accident ; la branche
`1.0` desarme un garde.

Source de l'enseignement : depot de veille yale-nlp/RLMF, entree A1 de
docs/roadmap_ameliorations_veille.md — « le troisieme etat est deja code ailleurs ».

Contrat pose ici : une marge non mesurable rend None (UNKNOWN), et UNKNOWN tombe du
cote PRUDENT — il n'elague pas, et il arme l'oracle.

Hermetique : aucun reseau, aucun service, aucune ecriture.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from forge_goap_intuition import _confidence  # noqa: E402


# --- niveau 1 : fonction pure ------------------------------------------------

def test_aucun_score_positif_rend_unknown_et_non_zero():
    """Aucun signal n'est pas un signal plat. Rendre 0.0 confond les deux."""
    assert _confidence([]) is None
    assert _confidence([0.0, 0.0, 0.0]) is None
    assert _confidence([-1.0, -2.0]) is None


def test_candidat_unique_rend_unknown_et_non_un():
    """Un seul point n'a pas de second : la marge n'est PAS mesurable.

    C'est la branche couteuse : 1.0 signifie « intuition nette », donc elagage dur
    et reflexe de doute desarme, sur la foi d'un seul candidat.
    """
    assert _confidence([0.7]) is None
    assert _confidence([0.7, 0.0, -3.0]) is None  # un seul POSITIF


def test_distribution_plate_mesuree_rend_zero():
    """Deux candidats positifs et egaux : le signal EST plat. NO mesure, pas UNKNOWN."""
    assert _confidence([0.5, 0.5]) == 0.0


def test_top_detache_rend_une_marge_haute():
    v = _confidence([1.0, 0.1])
    assert v is not None
    assert 0.85 <= v <= 0.95


# --- niveau 3 : chemin reel, via GOAPPlanner.plan ----------------------------

def _bridge_et_planner():
    """Planner portant une action a effet RISQUE et l'oracle qui la garde."""
    import forge_goap_hub_bridge as B

    p = B.GOAPPlanner()
    p.add_action(B.Action("ecrire_module", 1, {}, {"file_written": True}, "run", {}))
    p.add_action(B.Action("tester_hypothese", 1, {}, {"hypothesis_tested": True},
                          "oracle_python_repl", {}))
    return B, p


def test_intuition_qui_leve_n_arme_pas_une_confiance_maximale(monkeypatch):
    """Une intuition qui ECHOUE laisse la confiance INCONNUE, donc arme l'oracle.

    Etat mesure avant correctif : conf reste a 1.0 (valeur par defaut jamais
    reinitialisee dans le `except`), le test L167 est faux, le reflexe ne tire pas.
    """
    B, planner = _bridge_et_planner()
    import forge_goap_intuition as GI

    def _leve(*a, **k):
        raise RuntimeError("intuition indisponible")

    monkeypatch.setattr(GI, "intuition_rank", _leve)

    arme = []
    monkeypatch.setattr(B, "_log_doubt_reflex", lambda goal, conf: arme.append(conf))

    goal = B.Goal("ecrire un module", 1, {}, {"file_written": True})
    planner.plan({}, goal)

    assert arme, (
        "l'intuition a LEVE : la confiance est INCONNUE, le reflexe doute->oracle "
        "doit etre arme avant une action a effet risque"
    )


def test_candidat_unique_n_elague_pas_le_planner(monkeypatch):
    """UNKNOWN ne doit pas restreindre l'espace de recherche aux top_k."""
    B, planner = _bridge_et_planner()
    import forge_goap_intuition as GI

    monkeypatch.setattr(
        GI, "intuition_rank",
        lambda state, actions, **k: ([(actions[0], 0.9, {})], GI._confidence([0.9])),
    )

    vus = []
    monkeypatch.setattr(B, "_log_intuition",
                        lambda g, s, c, a: vus.append((c, a)))

    goal = B.Goal("ecrire un module", 1, {}, {"file_written": True})
    planner.plan({}, goal)

    assert vus, "la decision d'intuition doit etre journalisee, meme incertaine"
    conf, allowed = vus[0]
    assert conf is None, "un candidat unique = marge non mesurable = UNKNOWN"
    assert allowed is None, "UNKNOWN ne doit PAS elaguer aux top_k"


# --- second site : le juge de la cascade frugale ----------------------------
#
# Entree A4 de la veille (« la cascade penalise l'aveu d'incertitude ») : MESUREE
# et ECARTEE le 2026-09-08. Sur ce chemin, une confiance basse declenche l'ESCALADE
# vers le tier superieur (forge_frugal_cascade L310/L320) : penaliser « je ne sais
# pas » fait passer la main a un modele plus fort, ce qui est le comportement voulu
# d'une cascade FrugalGPT. Retirer les marqueurs de doute serait une regression.
#
# Le defaut REEL du fichier est ailleurs, et c'est la meme famille que A1 :
# _ask_self_confidence rend 0.5 dans TROIS cas d'echec de mesure — juge muet, parse
# casse, aucun nombre trouve. 0.5 est une valeur MOYENNE, pas UNKNOWN, et elle est
# moyennee dans la confiance retenue : un echec de mesure DECIDE.

def test_juge_muet_ne_rend_pas_une_confiance_moyenne(monkeypatch):
    """Un juge qui n'a pas repondu n'a pas mesure 0.5 : il n'a rien mesure."""
    import forge_frugal_cascade as FC

    monkeypatch.setattr(FC, "_call_llm", lambda *a, **k: "")
    assert FC._ask_self_confidence({"name": "t"}, "p", "r") is None


def test_juge_illisible_ne_rend_pas_une_confiance_moyenne(monkeypatch):
    """Une reponse sans nombre est ILLISIBLE, pas moyenne."""
    import forge_frugal_cascade as FC

    monkeypatch.setattr(FC, "_call_llm", lambda *a, **k: "je prefere ne pas noter")
    assert FC._ask_self_confidence({"name": "t"}, "p", "r") is None


def test_juge_lisible_rend_sa_note(monkeypatch):
    """Le chemin nominal reste intact : un nombre lu est une mesure."""
    import forge_frugal_cascade as FC

    monkeypatch.setattr(FC, "_call_llm", lambda *a, **k: "0.82")
    assert FC._ask_self_confidence({"name": "t"}, "p", "r") == 0.82
