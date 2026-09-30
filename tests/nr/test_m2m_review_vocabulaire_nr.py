"""Non-regression : le vocabulaire de REVUE M2M, et ce qu'il garantit vraiment.

Le M2M sert desormais de couche de revue independante entre agents (Claude,
Antigravity/Gemini, autres fournisseurs). Pour que plusieurs intelligences se
contredisent utilement, il faut un vocabulaire qui distingue :

    REVIEW_OK       revue menee, RIEN D'OBSERVE dans le perimetre declare
    REVIEW_FINDING  defaut observe, a verifier -- pas un verdict d'activation
    REVIEW_UNKNOWN  revue NON MENEE ou partielle (acces refuse, outil absent)

L'invariant, le meme que partout ailleurs ici : **UNKNOWN n'est pas SAFE**, et
« aucun probleme observe » n'est pas « le sujet est sur ». Un agent qui ne trouve
rien n'a pas prouve l'absence de defaut : il a prouve qu'il n'a rien vu.

Ces tests portent aussi sur DEUX ecarts MESURES entre ce qui est declare et ce qui
est applique -- pour qu'ils ne se lisent jamais comme des garanties.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import forge_m2m_protocol as m2m  # noqa: E402

DICO = ROOT / "config" / "m2m_intents.json"
RULES = ROOT / "RULES_SHARED.md"
REVUE = ("REVIEW_OK", "REVIEW_FINDING", "REVIEW_UNKNOWN")


def _dico() -> dict:
    return json.loads(DICO.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Le vocabulaire existe et il est distinct
# --------------------------------------------------------------------------- #

def test_les_trois_etats_de_revue_existent():
    intents = _dico()["intents"]
    for nom in REVUE:
        assert nom in intents, "%s absent du dictionnaire" % nom
        assert intents[nom]["category"] == "review", intents[nom]["category"]


def test_les_trois_etats_sont_bien_TROIS_et_pas_deux():
    """Le coeur du sujet : sans REVIEW_UNKNOWN, une revue non menee se replierait
    sur REVIEW_OK et un silence deviendrait une absence de defaut."""
    assert len(set(REVUE)) == 3
    intents = _dico()["intents"]
    desc = intents["REVIEW_UNKNOWN"]["description"].lower()
    assert "ni review_ok" in desc or "non menee" in desc.replace("é", "e")


def test_review_ok_ne_pretend_pas_que_le_sujet_est_sur():
    """Garde de LECTURE : la description doit dire ce que l'intent ne prouve pas."""
    d = _dico()["intents"]["REVIEW_OK"]["description"].lower()
    assert "n'affirme pas" in d, d


def test_le_validateur_accepte_les_trois_intents():
    for nom in REVUE:
        v = m2m.validate("notify", {"intent": nom, "pointer_ref": "sandbox/x.json"})
        assert v["code"] == "M2M_OK", (nom, v)


def test_un_intent_hors_dictionnaire_est_refuse():
    """Le garde EXISTE et il MORD -- verifie, pas suppose."""
    v = m2m.validate("notify", {"intent": "REVIEW_TOTALEMENT_INVENTE",
                                "pointer_ref": "x"})
    assert v["code"] == "M2M_ERR_UNKNOWN_INTENT", v


def test_un_message_de_revue_sans_pointeur_est_refuse():
    """Une revue sans artefact n'est qu'une opinion : le pointer_ref est le canal
    par lequel la PREUVE circule, pas une formalite."""
    v = m2m.validate("notify", {"intent": "REVIEW_FINDING", "severite": "haute"})
    assert v["code"] == "M2M_ERR_MISSING_FIELD", v


def test_la_prose_longue_reste_signalee():
    charabia = " ".join("mot%d" % i for i in range(20))
    v = m2m.validate("notify", {"intent": "REVIEW_OK", "pointer_ref": "x",
                                "note": charabia})
    assert v["code"] == "M2M_WARN_PROSE", v


# --------------------------------------------------------------------------- #
# Deux ecarts MESURES entre le declare et l'applique
# --------------------------------------------------------------------------- #

def test_le_perimetre_est_declare_mais_N_EST_PAS_exige():
    """ECART MESURE le 2026-09-02, consigne pour qu'il ne trompe personne.

    `payload_schema` du dictionnaire est DECLARATIF : le validateur n'exige que
    `required_fields_by_channel`. Un REVIEW_OK sans `perimetre` passe donc, alors
    que sans perimetre un « rien observe » n'a pas de denominateur et se lit comme
    un OK global.

    Ce test ECHOUERA le jour ou le validateur exigera le champ -- et ce sera une
    bonne nouvelle : il faudra alors retirer ce test et le remplacer par son
    inverse. Il documente l'etat REEL, il ne benit pas le manque.
    """
    assert "perimetre" in _dico()["intents"]["REVIEW_OK"]["payload_schema"]
    v = m2m.validate("notify", {"intent": "REVIEW_OK", "pointer_ref": "x"})
    assert v["code"] == "M2M_OK", (
        "le validateur exige desormais le perimetre : mettre ce test a jour", v)


def test_le_mode_par_defaut_reste_observation():
    """`warn` = on mesure, on ne coupe pas. Armer `error` sans denominateur avait
    rendu 100 % des messages refuses le 2026-09-01 -- corps muet, recul immediat."""
    assert m2m.mode() in ("warn", "error", "off")


# --------------------------------------------------------------------------- #
# Le dictionnaire EMANE doit suivre le dictionnaire SOURCE
# --------------------------------------------------------------------------- #

def test_les_regles_partagees_portent_la_meme_version():
    """Sans reemanation, les agents lisent un vocabulaire perime : ils emettraient
    des intents que le validateur refuse, ou ignoreraient ceux qui existent."""
    txt = RULES.read_text(encoding="utf-8", errors="replace")
    version = _dico()["version"]
    assert "v%s" % version in txt or version in txt, (
        "RULES_SHARED.md ne porte pas la version %s : relancer "
        "tools/forge_m2m_emanate.py (en trusted_script -- le compte sandbox ne "
        "peut pas ecrire a la racine du depot)" % version)


def test_chaque_intent_du_dictionnaire_est_emane():
    txt = RULES.read_text(encoding="utf-8", errors="replace")
    manquants = [n for n in _dico()["intents"] if n not in txt]
    assert not manquants, "intents absents des regles partagees : %s" % manquants
