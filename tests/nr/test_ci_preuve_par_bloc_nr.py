"""Un bloc de tests qui MEURT n'emporte pas la preuve des autres.

CE QUE CE FICHIER DEFEND. Le 2026-09-13, le gate « pytest (suite pure) » de la CI
GitHub (run 34784517659, sha b3ed1cc50) est sorti ROUGE sans qu'aucun test ne soit
casse. `pytest-timeout` a tue le processus PENDANT
`tests/nr/test_proprietes_generatives_nr.py` -- MainThread dans le scanner de
constantes locales d'Hypothesis -- et comme le rapport JUnit est ecrit A LA FIN de
la session, il n'a jamais existe. Resultat :

    9561 tests executes  ->  un seul JUnit  ->  processus tue  ->  AUCUNE preuve

Un defaut LOCAL (un fichier) s'est donc transforme en PERTE DE PREUVE GLOBALE. Le
gate n'avait pas tort de rester rouge -- on ne rachete pas un rc non nul sans
preuve ecrite -- mais il ne pouvait pas dire CE QUI s'etait passe, ni sauver le
verdict des 9560 autres tests.

LES CINQ ETATS, ET POURQUOI CINQ. `PASS` / `FAIL` ne suffisent pas :

    PASS     mesure, rien a signaler
    FAIL     mesure, des tests ont echoue
    ERROR    mesure, des tests ont leve hors assertion (collecte, fixture)
    TIMEOUT  le bloc a ete TUE : on sait POURQUOI on n'a pas de preuve
    UNKNOWN  pas de preuve, et on ne sait pas pourquoi

`TIMEOUT` n'est pas un sous-cas de `FAIL` : un bloc coupe n'a pas trouve de
probleme, il n'a pas fini de regarder. Les confondre envoie chercher un bug qui
n'existe pas -- c'est la meme famille que `UNKNOWN != NO` de la constitution
semantique, et que le troisieme etat de `_lire_junit`.

ET LA SYMETRIE, AUSSI IMPORTANTE : un rc nul SANS preuve n'est pas `PASS` non
plus. Sinon on rachete une absence de mesure par un code de retour, ce que le
certificateur faisait encore la veille (cf. test_generation_trois_etats_nr).
"""

from __future__ import annotations

import pathlib
import sys

import pytest

RACINE = pathlib.Path(__file__).resolve().parents[2]
if str(RACINE / "tools") not in sys.path:
    sys.path.insert(0, str(RACINE / "tools"))


@pytest.fixture()
def ci():
    try:
        import ci_local
    except Exception as exc:  # noqa: BLE001
        pytest.fail("ci_local ne s'importe pas : %s: %s" % (type(exc).__name__, exc))
    return ci_local


def _bilan(tests=0, failures=0, errors=0, skipped=0):
    """La forme REELLE que rend `_lire_junit`, pas une forme inventee.

    Un NR dont la fixture ne ressemble pas a la sortie de l'emetteur prouve la
    coherence du test avec lui-meme, pas celle du code (paye le 2026-09-12)."""
    total = {"tests": tests, "failures": failures, "errors": errors,
             "skipped": skipped}
    total["problemes"] = failures + errors
    total["rates"] = []
    return total


# Sortie REELLE du run 34784517659, reduite -- c'est ce que pytest-timeout imprime
# juste avant de tuer le processus.
SORTIE_TIMEOUT = (
    "tests\\nr\\test_proprietes_generatives_nr.py "
    "+++++++++++++++++++++++++++++++++++ Timeout +++++++++++++++++++++++++++++++++++\n"
    "~~~~~~~~~~~~~~~~~~~~ Stack of MainThread (8976) ~~~~~~~~~~~~~~~~~~~~\n"
    "  File \"...\\hypothesis\\internal\\conjecture\\providers.py\", line 790, in <genexpr>\n"
)


# --------------------------------------------------------------------------
# Les cinq etats d'un bloc
# --------------------------------------------------------------------------

def test_un_bloc_mesure_et_propre_est_PASS(ci):
    assert ci.verdict_bloc(0, "7 passed in 2.07s", _bilan(tests=7)) == "PASS"


def test_un_bloc_avec_des_echecs_est_FAIL(ci):
    assert ci.verdict_bloc(1, "2 failed", _bilan(tests=9, failures=2)) == "FAIL"


def test_un_bloc_avec_des_erreurs_est_ERROR_et_non_FAIL(ci):
    """Une erreur de collecte ou de fixture n'est pas un test qui echoue."""
    assert ci.verdict_bloc(1, "2 errors", _bilan(tests=9, errors=2)) == "ERROR"


def test_un_bloc_tue_par_timeout_est_TIMEOUT_et_jamais_FAIL(ci):
    """LE test de ce fichier : le cas exact du run 34784517659."""
    v = ci.verdict_bloc(1, SORTIE_TIMEOUT, None)
    assert v == "TIMEOUT", "un bloc tue n'a pas mesure d'echec, il a ete coupe"
    assert v != "FAIL"


def test_junit_absent_sans_motif_connu_est_UNKNOWN(ci):
    """Pas de preuve et pas d'explication : on le DIT, on n'invente pas."""
    assert ci.verdict_bloc(1, "crash sans message", None) == "UNKNOWN"


def test_un_rc_nul_sans_preuve_n_est_PAS_un_PASS(ci):
    """La symetrie : un code de retour ne rachete pas une absence de mesure."""
    assert ci.verdict_bloc(0, "rien a lire", None) == "UNKNOWN"


def test_un_rapport_entierement_ignore_ne_rachete_rien(ci):
    """`tests` compte les cas EXECUTES ; tout skipper n'a rien prouve."""
    assert ci.verdict_bloc(0, "12 skipped", _bilan(tests=0, skipped=12)) == "UNKNOWN"


# --------------------------------------------------------------------------
# L'agregation : un bloc mort n'emporte pas les autres
# --------------------------------------------------------------------------

def test_un_bloc_TIMEOUT_laisse_aux_autres_leur_propre_verdict(ci):
    """Le coeur du mandat du 2026-09-14.

    Le bloc generatif meurt ; les 9560 autres tests gardent leur preuve."""
    res = ci.verdict_suite({"suite": "PASS", "generatif": "TIMEOUT"})
    assert res["blocs"]["suite"] == "PASS", "le verdict du bloc sain est perdu"
    assert res["blocs"]["generatif"] == "TIMEOUT"
    assert res["sans_preuve"] == ["generatif"]


def test_une_suite_incomplete_n_est_JAMAIS_verte(ci):
    """SUITE_INCOMPLETE != GREEN : on ne publie pas ce qu'on n'a pas mesure."""
    res = ci.verdict_suite({"suite": "PASS", "generatif": "TIMEOUT"})
    assert res["etat"] == "SUITE_INCOMPLETE"
    assert res["bloquant"] is True


def test_une_suite_entierement_mesuree_et_propre_est_complete(ci):
    res = ci.verdict_suite({"suite": "PASS", "generatif": "PASS"})
    assert res["etat"] == "SUITE_COMPLETE"
    assert res["bloquant"] is False
    assert res["sans_preuve"] == []


def test_un_echec_MESURE_ne_rend_pas_la_suite_incomplete(ci):
    """Un FAIL est une mesure : la suite est complete, et rouge. Deux choses."""
    res = ci.verdict_suite({"suite": "FAIL", "generatif": "PASS"})
    assert res["etat"] == "SUITE_COMPLETE"
    assert res["bloquant"] is True
    assert res["sans_preuve"] == []


def test_UNKNOWN_compte_aussi_comme_absence_de_preuve(ci):
    res = ci.verdict_suite({"suite": "PASS", "generatif": "UNKNOWN"})
    assert res["etat"] == "SUITE_INCOMPLETE"
    assert res["sans_preuve"] == ["generatif"]


# --------------------------------------------------------------------------
# Contre-epreuve et cablage
# --------------------------------------------------------------------------

def test_contre_epreuve_les_cinq_etats_sont_REELLEMENT_distingues(ci):
    """Sans elle, une fonction qui rendrait une constante passerait des tests.

    On exige cinq verdicts DIFFERENTS sur les cinq entrees canoniques."""
    rendus = {
        ci.verdict_bloc(0, "", _bilan(tests=3)),
        ci.verdict_bloc(1, "", _bilan(tests=3, failures=1)),
        ci.verdict_bloc(1, "", _bilan(tests=3, errors=1)),
        ci.verdict_bloc(1, SORTIE_TIMEOUT, None),
        ci.verdict_bloc(1, "", None),
    }
    assert rendus == {"PASS", "FAIL", "ERROR", "TIMEOUT", "UNKNOWN"}


def test_le_fichier_generatif_est_DECLARE_isole(ci):
    """Le cablage, pas seulement la mecanique.

    Un mecanisme d'isolation present mais non branche est une dette de cablage,
    jamais une securite. On verifie donc que le fichier en cause y EST."""
    isoles = getattr(ci, "BLOCS_ISOLES", None)
    assert isoles, "aucune declaration de blocs isoles"
    cibles = {chemin for chemin, _motif in isoles}
    assert "tests/nr/test_proprietes_generatives_nr.py" in cibles


def test_chaque_bloc_isole_porte_son_MOTIF(ci):
    """Une isolation sans motif se relit comme une exemption arbitraire."""
    for chemin, motif in ci.BLOCS_ISOLES:
        assert motif and len(motif) > 20, "isolation non motivee : %s" % chemin


# --------------------------------------------------------------------------
# Le bilan de preuve : ce que le verdict doit DIRE, chiffre par chiffre
# --------------------------------------------------------------------------

def test_le_bilan_chiffre_ce_qui_a_REELLEMENT_tourne(ci):
    bilan = ci.bilan_preuve(
        blocs={"suite pure": "PASS", "generatif": "PASS"},
        bilans={"suite pure": _bilan(tests=9560, skipped=15),
                "generatif": _bilan(tests=7)},
        absents=[], sha="65020e073")
    assert bilan["sha"] == "65020e073"
    assert bilan["executes"] == 9567
    assert bilan["skipped"] == 15
    assert bilan["echecs"] == 0 and bilan["erreurs"] == 0
    assert bilan["etat"] == "SUITE_COMPLETE"


def test_un_bloc_SANS_preuve_n_est_pas_compte_comme_zero_echec(ci):
    """Le piege central : `None` n'est pas « 0 probleme ».

    Le bloc tue disparaitrait des compteurs sans laisser de trace, et le bilan
    afficherait un vert parfaitement faux."""
    bilan = ci.bilan_preuve(
        blocs={"suite pure": "PASS", "generatif": "TIMEOUT"},
        bilans={"suite pure": _bilan(tests=9560), "generatif": None},
        absents=[], sha="deadbeef")
    assert bilan["timeouts"] == ["generatif"]
    assert bilan["sans_preuve"] == ["generatif"]
    assert bilan["etat"] == "SUITE_INCOMPLETE"
    assert bilan["executes"] == 9560, "on ne compte que ce qui a vraiment tourne"


def test_les_fichiers_DECLARES_mais_ABSENTS_sont_nommes(ci):
    """Un test declare et non versionne fait diverger CI locale et CI GitHub.

    Mesure du 2026-09-13 : deux NR ACP presents sur le disque, jamais ajoutes au
    depot -- la CI locale les jouait, le runner ne les voyait pas. Les taire,
    c'est laisser croire a une couverture qu'on n'a pas."""
    bilan = ci.bilan_preuve(
        blocs={"suite pure": "PASS"}, bilans={"suite pure": _bilan(tests=10)},
        absents=["tests/nr/test_acp_toolcallid_canonique_nr.py"], sha="abc1234")
    assert bilan["declares_absents"] == ["tests/nr/test_acp_toolcallid_canonique_nr.py"]


def test_un_sha_illisible_est_DIT_jamais_vide(ci):
    """Un champ vide se lit comme « pas de sha » ; INCONNU se lit comme un trou."""
    bilan = ci.bilan_preuve(blocs={}, bilans={}, absents=[], sha=None)
    assert bilan["sha"] == "INCONNU"


# --------------------------------------------------------------------------
# CONTROLE POSITIF DU PRODUCTEUR -- le chemin negatif, OBSERVE en production
# --------------------------------------------------------------------------
#
# Les tests ci-dessus prouvent que `verdict_bloc` sait rendre UNKNOWN sur un
# rapport absent. Ils ne prouvent PAS que la CHAINE REELLE l'emprunte : aucun run
# ne produit spontanement « rc=0 et pas de rapport », donc ce chemin est vrai par
# construction et par test, jamais par OBSERVATION.
#
#     SOURCE_CORRECT    code + NR purs
#     RUNTIME_ACTIVE    charge par le gate
#     RUNTIME_OBSERVED  <- ce qui manquait
#
# Le controle fabrique donc la condition A CHAQUE RUN, avec les fonctions de
# production elles-memes et dans le basetemp reel -- donc sous les memes ACL.
#
# TROIS ETATS, parce qu'un controle qui n'a pas pu s'executer n'est PAS un
# instrument casse : `OK` / `DEFAUT` (la chaine ne distingue plus) / `NON
# EXECUTABLE` (droits, disque -- on le dit, on n'accuse pas).


def test_le_controle_positif_passe_en_conditions_normales(ci, tmp_path):
    r = ci.auto_preuve(tmp_path)
    assert r["etat"] == "OK", r


def test_le_controle_couvre_absent_corrompu_ET_le_cas_nominal(ci, tmp_path):
    """La contre-epreuve fait partie du controle, pas a cote.

    Sans un cas qui doit rendre PASS, une chaine qui repondrait UNKNOWN a tout
    passerait le controle en ayant perdu toute capacite de distinguer."""
    noms = " ".join(c["cas"] for c in ci.auto_preuve(tmp_path)["cas"]).lower()
    assert "absent" in noms
    assert "corrompu" in noms
    assert "valide" in noms or "nominal" in noms, noms


def test_le_controle_DETECTE_une_chaine_qui_ne_distingue_plus(ci, tmp_path,
                                                              monkeypatch):
    """LA contre-epreuve du controle lui-meme.

    On casse `verdict_bloc` pour qu'il rende UNKNOWN partout -- ce qui est
    exactement le faux vert redoute : un instrument qui ne sait plus distinguer
    une preuve d'une absence de preuve. Le controle DOIT le voir."""
    monkeypatch.setattr(ci, "verdict_bloc", lambda rc, sortie, bilan: "UNKNOWN")
    r = ci.auto_preuve(tmp_path)
    assert r["etat"] == "DEFAUT", (
        "le controle n'a pas vu une chaine incapable de distinguer : %s" % r)


def test_un_controle_EMPECHE_n_accuse_pas_l_instrument(ci, tmp_path):
    """Trois etats : un repertoire ou l'on ne peut pas ecrire rend NON
    EXECUTABLE, jamais DEFAUT. Confondre les deux enverrait reparer un
    instrument sain (motif paye le 2026-09-03 : 30 929 refus d'acces lus comme
    7 731 echecs de tests)."""
    r = ci.auto_preuve(tmp_path / "sous" / "dossier" / "inexistant")
    assert r["etat"] == "NON EXECUTABLE", r
    assert r.get("motif"), "un refus non motive ne s'instruit pas"
