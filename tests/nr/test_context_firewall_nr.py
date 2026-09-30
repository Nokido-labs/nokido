"""NR -- context firewall : reduire ce que Claude RECOIT, sans perdre la preuve.

ARBITRAGE OWNER 2026-09-11, qui corrige la direction precedente :

    outil produit 30k -> PostToolUse -> Claude recoit 300

vaut mieux que :

    outil produit 30k -> interdire l'appel

parce que la premiere PRESERVE LA CAPACITE en reduisant le contexte. Le `deny`
economise des tokens en detruisant le moyen de travailler ; il reste reserve
aux vraies boucles et aux appels absurdes.

Le mecanisme existe dans ce runtime -- MESURE, pas suppose :
`updatedToolOutput` est present dans le binaire (claude.exe, sonde findstr avec
4 temoins negatifs muets), et la reference donne la forme
`{"hookSpecificOutput": {"hookEventName": "PostToolUse",
  "updatedToolOutput": {"text": ..., "isError": ...}}}`, valable pour TOUS les
outils.

LE DANGER EST LE MECANISME LUI-MEME. Un firewall qui coupe la ligne qui
comptait est pire que pas de firewall : il fabrique du faux calme, et le faux
calme ne se detecte pas. D'ou la regle de securite du brief, que ce NR
transforme en tests -- un garde anti-token ne doit JAMAIS :

    cacher une erreur
    inventer un succes
    transformer UNKNOWN en PASS
    supprimer une preuve

C'est pourquoi l'original est ECRIT SUR DISQUE avant toute reduction, et que
son chemin est cite dans le texte rendu. Reduire n'est acceptable que si rien
n'est PERDU : la sortie complete reste joignable, elle cesse seulement d'etre
re-facturee a chaque tour.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "tools" / "hook_context_firewall.py"


def _charger(scratch):
    if not SRC.exists():
        pytest.fail("%s absent -- le firewall n'existe pas encore" % SRC.name)
    spec = importlib.util.spec_from_file_location("hook_context_firewall", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DOSSIER_ARCHIVE = Path(scratch)
    return mod


def _pytest_volumineux(n_failed=3):
    lignes = ["============================= test session starts ============================="]
    lignes += ["tests/test_%03d.py %s" % (i, "." * 60) for i in range(300)]
    for i in range(n_failed):
        lignes.append("FAILED tests/test_casse_%d.py::test_important_%d - AssertionError: x != y" % (i, i))
    lignes.append("=========================== short test summary info ===========================")
    for i in range(n_failed):
        lignes.append("FAILED tests/test_casse_%d.py::test_important_%d" % (i, i))
    lignes.append("================== %d failed, 2997 passed in 412.55s ==================" % n_failed)
    return "\n".join(lignes)


# --------------------------------------------------------------------------
# 1. NE RIEN CASSER : sous le seuil, la sortie est INTACTE
# --------------------------------------------------------------------------

def test_une_sortie_courte_n_est_PAS_touchee(tmp_path):
    """Le firewall ne doit pas se declencher sur le cas normal.

    Un hook qui reecrit toutes les sorties ajoute un risque permanent pour un
    gain nul : la depense vient des sorties ENORMES, pas des petites."""
    F = _charger(tmp_path)
    court = "3 passed in 0.42s"
    assert F.reduire("Bash", court, True) is None, (
        "une sortie courte a ete reecrite : risque sans benefice")


def test_le_seuil_est_explicite_et_lisible(tmp_path):
    F = _charger(tmp_path)
    assert isinstance(F.SEUIL_OCTETS, int)
    assert F.SEUIL_OCTETS >= 4000, (
        "un seuil trop bas fait passer le firewall sur des sorties normales")


# --------------------------------------------------------------------------
# 2. NE JAMAIS PERDRE UNE ERREUR -- le coeur du contrat
# --------------------------------------------------------------------------

def test_tous_les_FAILED_survivent_a_la_reduction(tmp_path):
    """Le cas cible : 3000 lignes de pytest dont 3 qui comptent."""
    F = _charger(tmp_path)
    brut = _pytest_volumineux(3)
    reduit = F.reduire("Bash", brut, False)
    assert reduit is not None, "une sortie de 3000 lignes doit etre reduite"
    for i in range(3):
        assert "test_important_%d" % i in reduit, (
            "le test en echec n%d a DISPARU de la sortie reduite. Un firewall "
            "qui coupe la ligne qui comptait fabrique du faux calme." % i)
    assert "failed" in reduit, "le compte final des echecs a disparu"


def test_une_trace_python_survit(tmp_path):
    F = _charger(tmp_path)
    brut = ("bruit\n" * 2000) + (
        "Traceback (most recent call last):\n"
        "  File \"app/x.py\", line 42, in charger\n"
        "    raise ValueError('vecteur absent')\n"
        "ValueError: vecteur absent\n")
    reduit = F.reduire("Bash", brut, False)
    assert reduit is not None
    assert "Traceback" in reduit
    assert "ValueError: vecteur absent" in reduit, (
        "la cause de l'echec a ete coupee : c'est exactement ce qu'il ne faut "
        "jamais faire")


def test_les_lignes_d_erreur_d_un_log_survivent(tmp_path):
    F = _charger(tmp_path)
    lignes = ["INFO tick %d ok" % i for i in range(3000)]
    lignes.insert(1500, "ERROR NokidoWebHub /health timeout apres 6.05s")
    lignes.insert(2200, "FATAL supervisor: port 7400 LISTENING mais app muette")
    reduit = F.reduire("Bash", "\n".join(lignes), True)
    assert reduit is not None
    assert "timeout apres 6.05s" in reduit
    assert "app muette" in reduit


# --------------------------------------------------------------------------
# 3. NE RIEN PERDRE TOUT COURT : l'original reste joignable
# --------------------------------------------------------------------------

def test_l_original_est_ecrit_sur_disque_et_son_chemin_est_cite(tmp_path):
    """Reduire n'est acceptable que si rien n'est PERDU.

    La sortie complete cesse d'etre re-facturee a chaque tour ; elle ne cesse
    pas d'exister. Sans cela le firewall supprime une preuve, ce que la regle
    de securite interdit."""
    F = _charger(tmp_path)
    brut = _pytest_volumineux(2)
    reduit = F.reduire("Bash", brut, False)
    archives = list(Path(tmp_path).glob("*.txt"))
    assert archives, "l'original n'a ete archive NULLE PART : preuve supprimee"
    assert archives[0].read_text(encoding="utf-8") == brut, (
        "l'archive ne contient pas la sortie integrale")
    assert archives[0].name in reduit, (
        "le chemin de l'original n'est pas cite : la preuve existe mais "
        "personne ne peut la retrouver")


def test_la_reduction_est_ANNONCEE_avec_son_ampleur(tmp_path):
    """Un contexte ampute en silence se lit comme un contexte complet."""
    F = _charger(tmp_path)
    reduit = F.reduire("Bash", _pytest_volumineux(1), False)
    assert any(mot in reduit.lower() for mot in ("reduit", "retire", "tronqu")), (
        "la reduction n'est pas annoncee : la sortie amputee se lira comme "
        "une sortie complete")
    assert any(c.isdigit() for c in reduit), (
        "l'ampleur du retrait n'est pas chiffree")


# --------------------------------------------------------------------------
# 3bis. UN PLAFOND DUR -- mesure du 2026-09-11
#
# Premiere version : 88,8 % de reduction sur le log de CI reel (2,7 Mo), zero
# signal decisif perdu. Ratio flatteur, resultat ABSURDE : 305 Ko residuels,
# soit ~76 000 tokens -- encore catastrophique a chaque tour.
#
# Un taux de reduction n'est pas un verdict. Ce qui compte est ce qui ARRIVE
# dans le contexte, pas le pourcentage evite. D'ou un plafond dur, qui borne
# le pire cas au lieu d'esperer que le motif soit assez selectif.
# --------------------------------------------------------------------------

def test_une_sortie_pathologique_reste_sous_le_plafond(tmp_path):
    F = _charger(tmp_path)
    # 60 000 lignes qui portent TOUTES un signal : le pire cas pour un
    # firewall fonde sur un motif.
    brut = "\n".join("ERROR tentative %d refusee" % i for i in range(60000))
    reduit = F.reduire("Bash", brut, False)
    assert reduit is not None
    assert len(reduit.splitlines()) <= F.PLAFOND_LIGNES + 10, (
        "%d lignes rendues : sans plafond dur, un log ou tout matche passe "
        "quasi entier et le firewall ne sert a rien"
        % len(reduit.splitlines()))


def test_le_plafond_garde_les_signaux_les_plus_FORTS(tmp_path):
    """Quand il faut choisir, on garde ce qui decide.

    Un plafond qui tranche au hasard perdrait l'unique FAILED noye dans
    60 000 lignes de bruit -- le faux calme, encore."""
    F = _charger(tmp_path)
    lignes = ["INFO tick %d" % i for i in range(40000)]
    lignes[20000] = "FAILED tests/test_decisif.py::test_qui_compte - AssertionError"
    lignes[30000] = "Traceback (most recent call last):"
    reduit = F.reduire("Bash", "\n".join(lignes), False)
    assert reduit is not None
    assert "test_qui_compte" in reduit, (
        "le plafond a coupe le seul FAILED : c'est exactement le faux calme "
        "que ce garde doit empecher")
    assert "Traceback" in reduit
    assert len(reduit.splitlines()) <= F.PLAFOND_LIGNES + 10


def test_le_VERDICT_FINAL_survit_meme_quand_les_forts_saturent(tmp_path):
    """DEFAUT MESURE le 2026-09-11 sur le log de CI reel, NR au vert.

    Premiere version du plafond : remplir avec les lignes << fortes >> puis,
    s'il reste de la place, les bords. Sur un vrai log de CI, des milliers de
    lignes portent ERROR / refus / Permission (flake8, scan de secrets) : elles
    saturaient les 300 lignes, et le VERDICT -- qui est a la FIN -- disparaissait.
    Mesure : 99 % evites, et 5 signaux decisifs perdus. REGRESSION.

    Aucun des 15 tests synthetiques ne l'avait vu. C'est la mesure sur cas reel
    qui l'a trouve : une fixture fabriquee ressemble a ce qu'on imagine, pas a
    ce qui arrive.
    """
    F = _charger(tmp_path)
    bruit_fort = ["ERROR ligne %d hors coffre" % i for i in range(20000)]
    lignes = bruit_fort + [
        "=== RESUME ===",
        "Tous les gates bloquants passent (1 non mesure, tous supplees)",
    ]
    reduit = F.reduire("Bash", "\n".join(lignes), True)
    assert reduit is not None
    assert "Tous les gates bloquants passent" in reduit, (
        "le VERDICT FINAL a ete noye par 20 000 lignes qui matchent aussi. "
        "Les bords doivent etre GARANTIS avant tout remplissage.")


def test_le_plafond_est_declare_et_raisonnable(tmp_path):
    F = _charger(tmp_path)
    assert isinstance(F.PLAFOND_LIGNES, int)
    assert 50 <= F.PLAFOND_LIGNES <= 1000, (
        "plafond=%d : trop bas on perd le contexte, trop haut il ne borne rien"
        % F.PLAFOND_LIGNES)


# --------------------------------------------------------------------------
# 4. FAIL-OPEN : un firewall casse ne doit PAS tronquer
# --------------------------------------------------------------------------

def test_une_panne_interne_laisse_la_sortie_INTACTE(tmp_path, monkeypatch):
    """Silence = sortie d'origine preservee.

    Le sens de l'echec est l'inverse de celui du garde bloquant : ici, en cas
    de doute, on ne touche a RIEN. Une sortie tronquee par un bug serait
    indetectable et mensongere."""
    F = _charger(tmp_path)

    def _casse(*a, **k):
        raise RuntimeError("archive impossible")

    monkeypatch.setattr(F, "_archiver", _casse)
    assert F.reduire("Bash", _pytest_volumineux(2), False) is None, (
        "le firewall a reecrit la sortie alors que l'archivage a echoue : la "
        "preuve serait perdue ET la sortie amputee")


def test_une_entree_non_texte_ne_casse_rien(tmp_path):
    F = _charger(tmp_path)
    for valeur in (None, "", 12345, {"a": 1}, []):
        assert F.reduire("Bash", valeur, True) is None


# --------------------------------------------------------------------------
# 5. FORME DE SORTIE attendue par le runtime
# --------------------------------------------------------------------------

def test_rien_a_reduire_ne_produit_AUCUNE_sortie(tmp_path, capsys):
    F = _charger(tmp_path)
    rc = F.traiter({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                    "tool_output": "3 passed", "tool_succeeded": True})
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_la_reecriture_a_la_forme_updatedToolOutput(tmp_path, capsys):
    import json
    F = _charger(tmp_path)
    F.traiter({"hook_event_name": "PostToolUse", "tool_name": "Bash",
               "tool_output": _pytest_volumineux(2), "tool_succeeded": False})
    paye = json.loads(capsys.readouterr().out)
    hso = paye["hookSpecificOutput"]
    assert hso["hookEventName"] == "PostToolUse"
    assert "text" in hso["updatedToolOutput"]
    assert hso["updatedToolOutput"]["isError"] is True, (
        "`isError` doit refleter tool_succeeded : un firewall ne transforme "
        "jamais un echec en succes")


def test_le_succes_reste_un_succes(tmp_path, capsys):
    import json
    F = _charger(tmp_path)
    F.traiter({"hook_event_name": "PostToolUse", "tool_name": "Bash",
               "tool_output": "ok\n" * 5000, "tool_succeeded": True})
    hso = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert hso["updatedToolOutput"]["isError"] is False
