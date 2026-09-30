# -*- coding: utf-8 -*-
"""NR — le gate ui-acceptance ne doit pas se taire sur un HOME qui n'est pas le sien.

MESURE 2026-09-09. `ci_local.py --only ui-acceptance` imprime
`[skip] forge_ui_campaign.py ou python py314 absent` et ne mesure RIEN, alors que
les DEUX fichiers existent et sont lisibles depuis le compte qui execute :

    tools/forge_ui_campaign.py                                     -> present
    %USERPROFILE%/miniforge3/envs/laforge_py314/python.exe       -> present

La resolution etait `Path.home() / "miniforge3" / "envs" / "laforge_py314"`. Sous le
compte de service, `HOME=C:/Users/Default` : le chemin teste est donc
`C:/Users/Default/miniforge3/...`, qui n'existe pour personne. Le gate se sautait
lui-meme en accusant une absence qui n'en etait pas une.

Deux defauts, deux gardes ici :

1. **La resolution ne doit pas dependre du HOME.** L'interpreteur qui fait tourner
   la CI (`sys.executable`) est present PAR CONSTRUCTION — c'est la source de verite
   du corps (`forge_python_bin.LAFORGE_PYTHON` vaut `sys.executable`). Un gate qui
   reconstruit un chemin depuis `Path.home()` fabrique un faux negatif silencieux.

2. **`A ou B absent` n'est pas un diagnostic.** Le message confondait trois causes
   (script absent · interpreteur absent · HOME faux) sous un seul mot, et ne nommait
   AUCUN chemin. C'est le motif `UNKNOWN != NO` : trois etats, jamais deux, et une
   absence NOMME ce qu'on n'a pas pu voir.
"""

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus git (code appele) (l.223)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "app"))

import ci_local  # noqa: E402


def test_la_resolution_de_l_interpreteur_existe_et_est_isolable():
    assert hasattr(ci_local, "_python_ui"), (
        "le gate UI doit resoudre son interpreteur par une fonction NOMMEE et testable, "
        "pas par une expression enfouie dans main()"
    )


def test_un_home_etranger_ne_fait_PAS_disparaitre_l_interpreteur():
    """Le coeur du defaut : HOME=C:/Users/Default sous le compte du job."""
    faux_home = Path(RACINE) / "sandbox" / "_home_qui_n_existe_pas_du_tout"
    chemin, motif = ci_local._python_ui(home=faux_home, executable=sys.executable, env={})
    assert chemin is not None, (
        "un HOME sans miniforge3 a fait conclure a l'absence d'interpreteur alors que "
        "sys.executable existe : %s" % motif
    )
    assert Path(chemin).exists(), "l'interpreteur rendu doit EXISTER, pas etre un chemin espere"


def test_l_override_explicite_prime_sur_tout():
    chemin, _ = ci_local._python_ui(
        home=Path(RACINE), executable=sys.executable,
        env={"LAFORGE_UI_PYTHON": sys.executable})
    assert chemin == sys.executable


def test_quand_rien_n_existe_le_motif_NOMME_les_chemins_essayes():
    absent = str(Path(RACINE) / "sandbox" / "_python_absent_xyz.exe")
    chemin, motif = ci_local._python_ui(
        home=Path(RACINE) / "sandbox" / "_home_absent_xyz",
        executable=absent, env={})
    assert chemin is None
    assert motif, "un refus muet est indiscernable d'un succes"
    assert "_python_absent_xyz" in motif or "_home_absent_xyz" in motif, (
        "le motif doit NOMMER au moins un chemin essaye, sinon il n'est pas diagnosticable : %r"
        % motif
    )


def test_l_auto_detection_est_desarmable_quand_un_job_DEDIE_existe():
    """Sinon le job `gates` se fait tuer par le gate qu'un autre job porte deja.

    MESURE : sur le runner self-hosted, `gates` dure 857 s pour `timeout-minutes: 15`
    (900 s), et :7400 y repond — le workflow le dit en toutes lettres. L'auto-detection
    ajoutee le 2026-09-09 y declencherait donc la campagne UI, dont le budget INTERNE
    est de 480 s (`forge_ui_campaign._BUDGET_S`) : 857 + jusqu'a 480 depasse la borne,
    et le job sort en `cancelled` — indiscernable d'un echec au premier coup d'oeil.

    C'est le meme piege que le 2026-08-30 (job annule a 10 min 07 pour une borne a
    10 min), a ceci pres qu'on le voit AVANT de pousser cette fois.

    L'auto-detection reste le bon defaut en CI locale, ou aucun job dedie n'existe.
    Ce qu'il faut, ce n'est pas la retirer : c'est pouvoir la desarmer la ou le
    contrat UI est deja porte ailleurs. Le drapeau EXPLICITE, lui, reste souverain.
    """
    lancer, motif = ci_local._ui_doit_tourner(
        False, None, False, True, False, auto_permis=False)
    assert lancer is False, (
        "l'auto-detection n'est pas desarmable : le job `gates` rejouera la campagne "
        "UI que `ui-acceptance` porte deja (%s)" % motif)
    assert "auto" in motif.lower(), "le motif doit dire POURQUOI on ne lance pas"

    # Une demande EXPLICITE ne se laisse pas desarmer par ce reglage.
    assert ci_local._ui_doit_tourner(
        True, None, False, True, False, auto_permis=False)[0] is True
    assert ci_local._ui_doit_tourner(
        False, ["ui-acceptance"], True, False, False, auto_permis=False)[0] is True

    # Et le defaut ne change RIEN au comportement d'avant.
    assert ci_local._ui_doit_tourner(False, None, False, True, False)[0] is True


def test_une_inconclusion_NON_DEMANDEE_ne_compte_pas_comme_un_critique_non_mesure():
    """REQUESTED != ACHIEVED, applique dans le bon sens.

    MESURE 2026-09-09, CI de reference job_1dffb1d9eb38 : rc=1 avec
    << Tous les gates bloquants passent >> et ZERO test en echec. Le rouge venait du
    garde d'anergie : le gate UI, reveille par auto-detection, a rendu rc=2
    (<< interface injoignable, contrat NON JUGE >>) et comptait comme
    << 1 gate CRITIQUE non mesure >>.

    Or ce gate ne PEUT PAS juger sous le compte des jobs : Playwright pilote le
    navigateur par le loopback, que ce compte bloque. L'auto-detection fabriquerait
    donc un rouge PERMANENT sur toute CI locale -- et un garde qui crie a faux se
    fait desarmer, garde entier compris, pas seulement son bruit.

    La distinction qui tranche : ne pas obtenir un verdict qu'on a DEMANDE
    (`--ui-gate`, `--only ui-acceptance`) est un echec. Ne pas obtenir un verdict que
    PERSONNE n'a demande -- le gate s'est reveille seul -- est une information.

    Ce n'est PAS un vert par absence : l'inconclusion reste AFFICHEE et le gate reste
    dans `_INCONCLUS`. Seule sa GRAVITE change. Et sous `--only ui-acceptance`, rien
    ne bouge : `_verdict_sans_mesure` continue de refuser de conclure.
    """
    nom = "ui-acceptance (contrat web_hub :7400)"
    assert hasattr(ci_local, "_gravite_inconclusion"), (
        "la gravite d'une inconclusion doit etre une decision NOMMEE, pas un "
        "`_critique(name)` pose sans savoir qui a demande le verdict"
    )
    assert ci_local._gravite_inconclusion(nom, True) is True, (
        "un verdict DEMANDE et non obtenu reste un echec")
    assert ci_local._gravite_inconclusion(nom, False) is False, (
        "un gate reveille par auto-detection ne doit pas rendre la CI rouge en "
        "permanence sur une capacite absente de ce compte"
    )


def test_l_inconclusion_reste_ENREGISTREE_meme_non_bloquante():
    """Baisser la gravite ne doit pas faire disparaitre le fait."""
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    assert "_INCONCLUS.append" in src, (
        "l'inconclusion doit rester consignee : sinon on remplace un rouge permanent "
        "par un silence, ce qui est pire"
    )


def test_le_desarmement_est_atteignable_depuis_un_workflow():
    """Un reglage que seul un appel Python peut poser ne sert a aucun job CI."""
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    assert "LAFORGE_UI_AUTO" in src, (
        "le desarmement doit etre pilotable par l'environnement, sinon le workflow "
        "ne peut pas s'en servir"
    )


def test_le_magasin_de_navigateurs_ne_se_deduit_pas_du_HOME():
    """Meme defaut que `_python_ui`, un etage plus bas -- et il a coute 180 s de silence.

    MESURE 2026-09-09, en lancant Playwright NU (sans profil persistant) :

        BrowserType.launch: Executable doesn't exist at
          C:/Users/Default/AppData/Local/ms-playwright/firefox-1532/firefox/firefox.exe

    Or `firefox-1532` -- la version EXACTE reclamee -- est present dans
    `C:/nokido/ms-playwright`. Rien ne manquait : Playwright derive son magasin de
    `HOME`, qui vaut `C:/Users/Default` pour les comptes de service.

    Pourquoi personne ne l'avait vu : la campagne utilise
    `launch_persistent_context`, qui sur ce cas PEND puis expire a 180 s
    (<< harnais mort au lancement >>) au lieu de dire que l'executable manque. Un
    timeout ne nomme rien ; c'est le lancement NU qui a rendu la cause en 2 s.
    Reflexe : devant un timeout muet, retirer les options avant de changer de compte.
    """
    assert hasattr(ci_local, "_magasin_playwright"), (
        "le magasin de navigateurs doit etre resolu explicitement, pas laisse a "
        "une deduction depuis HOME"
    )
    faux_home = Path(RACINE) / "sandbox" / "_home_sans_playwright_xyz"
    reel = Path(RACINE) / "sandbox"          # existe a coup sur, sert de magasin bidon
    chemin, motif = ci_local._magasin_playwright(home=faux_home, magasins=[reel])
    assert chemin == str(reel), (
        "un magasin existant hors du HOME doit etre retenu (%s)" % motif)

    chemin2, motif2 = ci_local._magasin_playwright(
        home=faux_home, magasins=[Path(RACINE) / "sandbox" / "_magasin_absent_xyz"])
    assert chemin2 is None
    assert "_magasin_absent_xyz" in motif2, (
        "une absence NOMME ce qu'elle n'a pas pu voir : %r" % motif2)


def test_le_gate_UI_transmet_le_magasin_a_la_campagne():
    """Resoudre sans transmettre ne sert a rien : c'est le SOUS-PROCESSUS qui lance."""
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    assert "PLAYWRIGHT_BROWSERS_PATH" in src, (
        "le magasin doit etre pose dans l'environnement du subprocess de la campagne, "
        "a cote de LAFORGE_UI_HEADED et LAFORGE_UI_CLICKS"
    )


def test_le_sha_du_temoin_prefere_l_environnement_de_CI():
    """MESURE 2026-09-09, run 34390571371 : le temoin est sorti `tested_sha: null`.

    `_sha_courant()` n'interrogeait que `git rev-parse` et avalait son echec. Or en
    CI GitHub la source fiable est `GITHUB_SHA` -- elle etait disponible, posee par
    le runner, et ignoree. Resultat : un temoin qui certifie sans dire sur quoi.

    L'ordre compte : `GITHUB_SHA` designe le commit que le workflow a CHECKOUT, ce
    qui est exactement l'objet de la mesure ; `git rev-parse` reste le repli local.
    """
    assert hasattr(ci_local, "_sha_courant")
    assert ci_local._sha_courant(env={"GITHUB_SHA": "abc123def"}) == "abc123def"


def test_sans_environnement_de_CI_le_sha_reste_cherche_localement():
    """Contre-epreuve : l'ajout ne doit pas casser le chemin local."""
    sha = ci_local._sha_courant(env={})
    assert sha is None or len(sha) >= 7, (
        "hors CI, le sha vient de git ou vaut None — jamais une valeur fantaisiste")


def test_le_message_de_skip_ne_confond_plus_deux_causes_sous_un_ou():
    """Cliquet textuel : `A ou B absent` etait indiscernable de `je n'ai pas regarde`."""
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    # On tolere la mention dans une docstring d'explication (le post-mortem la cite),
    # on interdit qu'elle reste la SORTIE du gate.
    assert 'print("\\n\\033[90m[skip] forge_ui_campaign.py ou python py314 absent' not in src, (
        "le skip du gate UI doit nommer LAQUELLE des conditions manque, et son chemin"
    )
