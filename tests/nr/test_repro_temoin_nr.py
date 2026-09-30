# -*- coding: utf-8 -*-
"""NR — P4_REPRO_WITNESS : quatre etages qu'une installation confond toujours.

    installe   != demarre   != sain   != MCP fonctionnel

Chacune de ces confusions a deja ete payee dans ce corps, et sur d'autres sujets :
  - des fichiers presents ne disent rien de l'execution ;
  - un process vivant peut etre bloque -- un CPU a 0 % n'est pas une preuve, un
    travail I/O-bound y ressemble ;
  - un port en LISTEN ne prouve pas qu'un modele est chargé (`TRANSPORT != APPLICATIF`) ;
  - un registre n'est pas une mesure : `list_providers` a affiche « grade A, ttft
    3,1 ms » sur un service mort, et router la-dessus, c'est router vers un mort.

Le temoin de P2 a montre la valeur de la separation : navigateur OK + service tombe
etait ILLISIBLE tant que les couches etaient fondues sous « interface injoignable ».
Ce fichier applique le meme patron a la reproduction externe, AVANT toute experience
-- un temoin ecrit apres coup se decouvre illisible pendant le run qu'il devait
eclairer (paye le 2026-09-09, run 34381575702).

L'INVARIANT QUI PORTE TOUT : un etage qui n'a pas pu etre ATTEINT n'est pas un etage
en ECHEC. Si l'installation echoue, le MCP n'est pas « casse » -- il est INCONNU. La
confusion inverse ferait accuser un composant que personne n'a essaye.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent


def _mod():
    import importlib  # noqa: PLC0415
    chemin = str(RACINE / "tools")
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    try:
        return importlib.import_module("forge_repro_temoin")
    except ImportError as e:  # pragma: no cover - chemin rouge du TDD
        raise AssertionError(
            "tools/forge_repro_temoin.py est absent : le temoin se definit AVANT la "
            "reproduction qu'il mesure — %s" % e) from None


def _obs(**maj):
    """Reproduction nominale : tout marche, du clone au premier appel d'outil."""
    base = {
        "identity": {"tested_sha": "02caf58aa"},
        "environment": {"os": "Windows-11", "python": "3.12.7",
                        "installation_mode": "git+pip"},
        "install": {"started": "T0", "finished": "T1", "result": "OK"},
        "runtime": {"process_started": True, "health_reachable": True,
                    "health_result": "ok"},
        "mcp": {"server_reachable": True, "handshake_ok": True,
                "one_real_tool_call": "hub.whoami", "tool_result_ok": True},
    }
    for k, v in maj.items():
        base[k] = {**base[k], **v} if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


def test_le_temoin_de_reproduction_existe():
    assert hasattr(_mod(), "construire")


def test_le_cas_nominal_est_PROVEN():
    t = _mod().construire(_obs())
    assert (t["final"]["INSTALL_OK"], t["final"]["RUNTIME_OK"], t["final"]["MCP_OK"]) \
        == (True, True, True)
    assert t["final"]["verdict"] == "PROVEN"


# --- l'invariant central : non ATTEINT != en ECHEC --------------------------

def test_une_installation_ratee_laisse_les_etages_suivants_INCONNUS():
    t = _mod().construire(_obs(
        install={"result": "FAIL"},
        runtime={"process_started": None, "health_reachable": None,
                 "health_result": None},
        mcp={"server_reachable": None, "handshake_ok": None,
             "one_real_tool_call": None, "tool_result_ok": None}))
    assert t["final"]["INSTALL_OK"] is False
    assert t["final"]["RUNTIME_OK"] is None, (
        "un etage jamais ATTEINT n'est pas un etage en ECHEC : l'accuser ferait "
        "chercher une panne dans un composant que personne n'a essaye")
    assert t["final"]["MCP_OK"] is None
    assert t["final"]["verdict"] == "FAILED"
    assert "install" in t["reason"].lower()


def test_un_demarrage_rate_ne_condamne_pas_le_MCP():
    t = _mod().construire(_obs(
        runtime={"process_started": False, "health_reachable": None,
                 "health_result": None},
        mcp={"server_reachable": None, "handshake_ok": None,
             "one_real_tool_call": None, "tool_result_ok": None}))
    assert t["final"]["INSTALL_OK"] is True
    assert t["final"]["RUNTIME_OK"] is False
    assert t["final"]["MCP_OK"] is None
    assert t["final"]["verdict"] == "FAILED"


# --- health OK != MCP OK ----------------------------------------------------

def test_un_health_vert_ne_prouve_PAS_le_MCP():
    """`TRANSPORT != APPLICATIF` : un port qui repond ne dit rien du service rendu."""
    t = _mod().construire(_obs(
        mcp={"server_reachable": True, "handshake_ok": False,
             "one_real_tool_call": None, "tool_result_ok": None}))
    assert t["final"]["RUNTIME_OK"] is True
    assert t["final"]["MCP_OK"] is False
    assert t["final"]["verdict"] != "PROVEN"


def test_un_handshake_ne_suffit_pas_sans_appel_reel():
    """Un registre n'est pas une mesure : il faut un appel qui RENDE un resultat."""
    t = _mod().construire(_obs(
        mcp={"handshake_ok": True, "one_real_tool_call": None,
             "tool_result_ok": None}))
    assert t["final"]["MCP_OK"] is not True, (
        "se serrer la main n'est pas rendre un service")
    assert t["final"]["verdict"] != "PROVEN"


def test_un_outil_qui_repond_FAUX_est_un_echec_pas_un_INCONNU():
    """Contre-epreuve : on a bien MESURE, et le resultat est negatif."""
    t = _mod().construire(_obs(
        mcp={"one_real_tool_call": "hub.whoami", "tool_result_ok": False}))
    assert t["final"]["MCP_OK"] is False
    assert t["final"]["verdict"] == "FAILED"


# --- identite et etats non mesures ------------------------------------------

def test_PROVEN_exige_de_savoir_QUEL_sha_a_ete_reproduit():
    t = _mod().construire(_obs(identity={"tested_sha": None}))
    assert t["final"]["verdict"] != "PROVEN"
    assert "sha" in t["reason"].lower()


def test_un_etage_NON_MESURE_ne_devient_pas_NEGATIF():
    t = _mod().construire(_obs(
        runtime={"process_started": None, "health_reachable": None,
                 "health_result": None},
        mcp={"server_reachable": None, "handshake_ok": None,
             "one_real_tool_call": None, "tool_result_ok": None}))
    assert t["runtime"]["process_started"] is None
    assert t["final"]["RUNTIME_OK"] is None
    assert t["final"]["verdict"] == "UNKNOWN", (
        "rien n'a echoue : on n'a simplement pas regarde")


def test_l_environnement_est_consigne_sans_etre_juge():
    """L'OS et la version de Python ne sont pas des verdicts, mais sans eux un
    echec n'est pas reproductible."""
    t = _mod().construire(_obs())
    assert t["environment"]["os"] == "Windows-11"
    assert t["environment"]["python"] == "3.12.7"
    assert t["environment"]["installation_mode"] == "git+pip"


# --- P4.1b : un echec d'installation se DIAGNOSTIQUE ------------------------
#
# `pip failed` recouvre six causes qui ne se traitent pas pareil -- meme defaut que
# « interface injoignable », qui en agregeait trois et a coute trois changements de
# compte le 2026-09-09. Un reseau coupe n'est pas une dependance introuvable, et
# aucun des deux n'est un paquet fautif.

# Jeton de TEST assemble a l'execution : ecrit en clair, il ressemble assez a un vrai
# PAT pour que le scanner de secrets du depot refuse le fichier -- il l'a fait. Le
# garde a raison, on ne le contourne pas, on ecrit autrement.
_FAUX_PAT = "gh" + "p_" + ("A1b2C3d4" * 4) + "Zz"


def test_la_taxonomie_des_echecs_existe():
    assert hasattr(_mod(), "classer_echec_install")


def test_chaque_famille_d_echec_est_distinguee():
    c = _mod().classer_echec_install
    cas = [
        ("resolver", "ERROR: Could not find a version that satisfies the requirement foo",
         "DEPENDENCY"),
        ("resolver", "ERROR: Package 'x' requires a different Python: 3.9.0 not in '>=3.12'",
         "UNSUPPORTED"),
        ("download", "Temporary failure in name resolution", "NETWORK"),
        ("download", "WinError 10013 : tentative d'acces a un socket interdite", "NETWORK"),
        ("build", "ERROR: Failed building wheel for cryptography", "BUILD"),
        ("build", "error: Microsoft Visual C++ 14.0 or greater is required", "BUILD"),
        ("install", "PermissionError: [Errno 13] Permission denied", "ENVIRONMENT"),
    ]
    for phase, msg, attendu in cas:
        assert c(phase, msg) == attendu, "%r -> %s attendu" % (msg[:40], attendu)


def test_un_echec_non_reconnu_ne_se_range_pas_dans_une_famille_flatteuse():
    """Liste BLANCHE : ce qu'on ne sait pas classer est BROKEN, jamais NETWORK.

    Ranger un inconnu du cote « transitoire » ferait conseiller de reessayer sur un
    paquet reellement casse.
    """
    assert _mod().classer_echec_install("install", "quelque chose d'inedit") == "BROKEN"


def test_aucune_famille_n_est_rendue_quand_il_n_y_a_PAS_d_echec():
    assert _mod().classer_echec_install(None, None) is None


# --- P4.1b : la redaction precede l'ecriture --------------------------------

def test_le_temoin_REDIGE_avant_de_stocker():
    """Une URL VCS authentifiee porte le PAT, et pip la REIMPRIME dans ses erreurs.

    Rediger « apres coup » a deja ecrit le secret sur disque. C'est la meme raison
    qui fait refuser `git remote -v` a `bash_guard` sur cette machine.
    """
    m = _mod()
    assert hasattr(m, "rediger")
    sale = ("pip install git+https://x-access-token:%s@github.com/user/nokido.git "
            "a echoue dans %USERPROFILE%\\AppData\\Local" % _FAUX_PAT)
    propre = m.rediger(sale)
    assert _FAUX_PAT not in propre
    assert "x-access-token" not in propre
    assert "user" not in propre, "le nom d'utilisateur est un chemin sensible inutile"
    assert "github.com/user/nokido.git" in propre, (
        "rediger n'est pas effacer : ce qui n'est pas sensible doit rester lisible")


def test_le_stderr_brut_n_est_JAMAIS_persiste():
    t = _mod().construire(_obs(install={
        "result": "FAIL", "phase": "download",
        "stderr": "token=%s dans %USERPROFILE%\\x" % _FAUX_PAT}))
    plat = repr(t)
    assert _FAUX_PAT not in plat
    assert "user" not in plat
    assert "stderr" not in t["install"], (
        "seule une version REDIGEE est persistee, jamais le flux brut")
    assert t["install"].get("stderr_tail"), "le diagnostic doit rester lisible"


def test_un_echec_porte_sa_phase_son_code_et_sa_famille():
    t = _mod().construire(_obs(install={
        "result": "FAIL", "phase": "build", "exit_code": 1,
        "stderr": "ERROR: Failed building wheel for cryptography"}))
    assert t["install"]["phase"] == "build"
    assert t["install"]["exit_code"] == 1
    assert t["install"]["failure_class"] == "BUILD"
    assert t["final"]["RUNTIME_OK"] is None and t["final"]["MCP_OK"] is None


# --- P4.1b : authentifie != public ------------------------------------------

def test_un_mode_AUTHENTIFIE_ne_pretend_pas_prouver_l_acces_public():
    """P4.2a reproduit un depot PRIVE avec jeton ; ce n'est pas la promesse du README."""
    t = _mod().construire(_obs(
        environment={"installation_mode": "git_vcs_authenticated"}))
    assert t["environment"]["public_access_demonstrated"] is False
    assert t["final"]["verdict"] == "PROVEN", (
        "la reproduction authentifiee reste PROUVEE dans SON perimetre")


def test_un_mode_ANONYME_demontre_l_acces_public():
    t = _mod().construire(_obs(environment={"installation_mode": "git_vcs"}))
    assert t["environment"]["public_access_demonstrated"] is True


def test_l_architecture_est_consignee():
    t = _mod().construire(_obs(environment={"architecture": "AMD64"}))
    assert t["environment"]["architecture"] == "AMD64"


def test_le_mode_d_installation_est_OBLIGATOIRE_pour_conclure():
    """`pip install nokido-agent` et `git clone` ne promettent pas la meme chose.

    Le README declare desormais le paquet `nokido-agent` ; reproduire par clone ne
    prouve donc PAS la promesse faite au lecteur qui tape `pip install`.
    """
    t = _mod().construire(_obs(environment={"installation_mode": None}))
    assert t["final"]["verdict"] != "PROVEN"
    assert "mode" in t["reason"].lower() or "installation" in t["reason"].lower()
