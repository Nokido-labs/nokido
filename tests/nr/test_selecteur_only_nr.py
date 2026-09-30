"""NR 2026-09-09 — `--only <gate>` est EXCLUSIF : il n'execute que ce qu'on demande.

LE DEFAUT, MESURE SUR LA CI GITHUB. Le workflow lance `ci_local.py --ui-gate` dans le
job `ui-acceptance`. Or ce drapeau est ADDITIF -- son aide le dit : « + contrat
d'acceptation UI ». Le job rejoue donc TOUTE la CI avant d'entamer la campagne, alors
qu'il declare pourtant `needs: gates`, c'est-a-dire qu'il depend d'un job qui vient de
faire exactement ce travail.

Le compte tombe juste (run 34351716951, 2026-09-09) :

    job gates          ci_local.py           857 s (14m17, vert)
    job ui-acceptance  ci_local.py --ui-gate 929 s -> TUE a 15m00
                       = les 857 s rejouees, puis la campagne entamee

Les sept `cancelled` consecutifs des 8 derniers runs viennent de la : ce n'est ni le
runner, ni le code, ni la campagne qui serait lente -- c'est le meme travail fait deux
fois. Le timeout avait deja ete releve de 10 a 15 min le 2026-08-30 pour ce symptome,
et le probleme est revenu : on ne rallonge pas le tuyau avant d'avoir retire la boucle.

CE QUE `--only` DOIT GARANTIR, et c'est le seul point qui compte :

  1. EXCLUSIVITE — `--only X` n'execute JAMAIS implicitement un autre gate. Un
     selecteur qui laisserait passer les autres ne corrigerait rien.
  2. COMPATIBILITE — `--ui-gate` garde sa semantique HISTORIQUE (additive). On ne
     reinterprete pas silencieusement un drapeau existant : des appels s'en servent.
  3. NEUTRALITE — sans `--only`, le comportement est celui d'avant, a l'identique.

POURQUOI CE NR EST PUREMENT LOGIQUE. Il n'exerce pas un run de CI (20 min) : il teste
le PREDICAT de selection, qui est la seule chose que le correctif introduit. Le chemin
reel sera verifie par un run GitHub, une fois.

Zero service externe : aucune commande lancee, aucun gate execute.
"""

import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python (ci_local) (l.153)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE / "tools"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ci_local  # noqa: E402

# Echantillon de noms de gates REELS, releves dans main() le 2026-09-09.
GATES_REELS = (
    "secrets hors coffre (cliquet)",
    "flake8 critique (E9,F63,F7)",
    "pytest (suite pure)",
    "duplication (cliquet clones)",
    "anatomie (0 module non classe)",
    "pip-audit",
)
GATE_UI = "ui-acceptance (contrat web_hub :7400)"


def test_le_predicat_de_selection_existe():
    assert hasattr(ci_local, "_demande"), (
        "ci_local n'expose pas _demande : sans predicat de selection, `--only` ne "
        "peut pas etre exclusif, et le job ui-acceptance continuera de rejouer les "
        "857 s du job gates dont il depend deja")


def test_sans_only_tout_est_demande():
    """NEUTRALITE : le comportement par defaut ne change pas d'un iota."""
    ci_local._poser_only(None)
    for nom in GATES_REELS + (GATE_UI,):
        assert ci_local._demande(nom) is True, "%r refuse alors qu'aucun --only n'est pose" % nom


def test_only_ui_EXCLUT_tous_les_autres_gates():
    """EXCLUSIVITE — le coeur du correctif.

    Contre-epreuve incluse : on verifie a la fois que le gate demande passe ET que
    chacun des autres est refuse. Verifier seulement le premier laisserait passer un
    selecteur qui n'exclut rien, c'est-a-dire le bug qu'on corrige.
    """
    ci_local._poser_only(["ui-acceptance"])
    assert ci_local._demande(GATE_UI) is True, "le gate DEMANDE ne passe pas"
    for nom in GATES_REELS:
        assert ci_local._demande(nom) is False, (
            "%r s'executerait malgre `--only ui-acceptance` : le selecteur n'est pas "
            "exclusif, la duplication des 857 s subsiste" % nom)


def test_only_accepte_un_prefixe_du_nom_reel():
    """Les noms de gates portent leur contexte entre parentheses ; on ne l'exige pas."""
    ci_local._poser_only(["pip-audit"])
    assert ci_local._demande("pip-audit") is True
    ci_local._poser_only(["duplication"])
    assert ci_local._demande("duplication (cliquet clones)") is True
    assert ci_local._demande("anatomie (0 module non classe)") is False


def test_un_only_inconnu_ne_selectionne_RIEN_et_ne_plante_pas():
    """Un nom qui ne matche aucun gate ne doit pas tout laisser passer par defaut.

    C'est la degenerescence classique : un filtre qui ne reconnait rien et qui, faute
    de correspondance, retombe sur « tout autoriser ». Elle transformerait une faute
    de frappe en run complet -- exactement ce qu'on cherche a eviter.
    """
    ci_local._poser_only(["gate-qui-n-existe-pas-2026"])
    for nom in GATES_REELS + (GATE_UI,):
        assert ci_local._demande(nom) is False


def test_le_drapeau_historique_reste_additif():
    """COMPATIBILITE : on ne reinterprete pas `--ui-gate`.

    Sa semantique documentee est « + contrat d'acceptation UI » : CI complete PUIS
    campagne. Des appels existants en dependent ; les casser en silence serait une
    regression invisible jusqu'au prochain run.
    """
    src = (RACINE / "tools" / "ci_local.py").read_text(encoding="utf-8", errors="replace")
    i = src.find('"--ui-gate"')
    assert i > 0, "le drapeau --ui-gate a disparu : semantique historique cassee"
    assert "+ contrat" in src[i:i + 240], (
        "l'aide de --ui-gate ne dit plus qu'il est ADDITIF")


def test_le_point_d_entree_traverse_vraiment(tmp_path):
    """LE test qui manquait, et qui a coute un NameError commite.

    Le predicat etait vert (7/7) pendant que `main()` levait
    `NameError: name 'partiel' is not defined` des qu'on l'executait : `partiel` est
    le parametre de `_summary`, pas une variable de `main`. Invisible au parse,
    invisible a tout NR qui n'emprunte pas le point d'entree -- et masque parce que
    la CI de reference qui avait « valide » ce code tournait sur un sha ANTERIEUR a
    son commit.

    On lance donc le vrai binaire sur le gate le plus court (ruff, 0,2 s mesure).
    Le seuil de duree est genereux : ce test ne mesure pas la performance, il mesure
    que le chemin va au bout. Un `--only` qui rejouerait toute la CI le ferait
    exploser, ce qui est aussi ce qu'on veut savoir.
    """
    import subprocess  # noqa: PLC0415

    # EFFET DE BORD MESURE le 2026-09-09, par la CI de reference elle-meme.
    # Ce run ECRIT `tests/nr/vitalite_gardes.json`. Sur l'arbre partage l'ecriture
    # est REFUSEE par l'ACL (les comptes sandbox n'ecrivent pas dans tests/nr), donc
    # l'effet de bord etait invisible. Dans un worktree de reference il reussit, et
    # coute deux fois :
    #   - il salit l'arbre de reference, ce qui suffit a interdire la capture de
    #     generation (« le sha ne representerait pas l'etat teste ») ;
    #   - il fait basculer le garde d'anergie de NON BLOQUANT a BLOQUANT pour tous
    #     les tests suivants, d'ou `test_summary_traverse_la_fermeture_sans_exploser`
    #     rouge a 8653 tests -- un echec a distance, sans rapport apparent.
    # Un NR qui emprunte le chemin REEL doit rendre l'arbre comme il l'a trouve.
    _registre = RACINE / "tests" / "nr" / "vitalite_gardes.json"
    _avant = _registre.read_bytes() if _registre.exists() else None

    try:
        r = subprocess.run(
            [sys.executable, str(RACINE / "tools" / "ci_local.py"), "--only", "ruff critique"],
            cwd=str(RACINE), capture_output=True, text=True, errors="replace", timeout=180,
            env={**__import__("os").environ, "PYTHONNOUSERSITE": "1", "PYTHONIOENCODING": "utf-8"},
        )
    finally:
        # Restauration inconditionnelle : si l'ecriture avait ete refusee, le contenu
        # est deja identique et rien n'est reecrit.
        if _avant is None:
            _registre.unlink(missing_ok=True)
        elif _registre.read_bytes() != _avant:
            _registre.write_bytes(_avant)
    sortie = (r.stdout or "") + (r.stderr or "")
    assert "Traceback" not in sortie, (
        "le point d'entree leve une exception :\n%s" % sortie[-900:])
    assert "NameError" not in sortie
    assert "selection EXCLUSIVE" in sortie, (
        "le drapeau --only n'a pas ete pris en compte par le binaire reel")
    assert "ruff critique" in sortie


def test_un_run_sans_AUCUNE_mesure_ne_rend_PAS_un_succes():
    """LE defaut trouve par le chemin reel, et le plus grave de ce chantier.

    MESURE 2026-09-09 (job_9b956666182d) : `ci_local.py --only ui-acceptance` a rendu
    rc=0 avec un RESUME VIDE et la ligne « Tous les gates bloquants passent ». Zero
    gate execute, zero mesure, verdict de SUCCES -- le gate UI n'avait pas pu demarrer
    (`forge_ui_campaign.py ou python py314 absent`, le compte du job ayant
    HOME=C:/Users/Default). Une generation STABLE a meme ete produite sur ce vide.

    C'est le « vert par absence » que le depot combat partout, fabrique par le
    selecteur lui-meme. Branche dans le workflow, le job ui-acceptance serait passe
    au vert SANS JAMAIS tester l'interface -- exactement l'anergie qu'on venait de
    corriger, retournee en faux succes.

    L'invariant : ne rien avoir mesure n'est pas un succes. `--only` sur un nom
    inconnu, ou sur un gate qui ne peut pas demarrer, doit se DIRE et sortir non nul.
    """
    assert hasattr(ci_local, "_verdict_sans_mesure"), (
        "ci_local n'expose pas _verdict_sans_mesure : rien n'empeche un run qui "
        "n'execute AUCUN gate de rendre « tous les gates passent »")
    # aucune mesure alors qu'une selection etait demandee -> refus
    rc, motif = ci_local._verdict_sans_mesure(n_resultats=0, only=["ui-acceptance"])
    assert rc != 0, "zero gate execute doit sortir NON NUL"
    assert motif and "aucun" in motif.lower()
    # selection qui a produit quelque chose -> pas de refus
    rc2, _ = ci_local._verdict_sans_mesure(n_resultats=1, only=["ui-acceptance"])
    assert rc2 == 0
    # sans --only, un resume vide releve d'un autre probleme : on ne s'en mele pas
    rc3, _ = ci_local._verdict_sans_mesure(n_resultats=0, only=None)
    assert rc3 == 0


def test_la_decision_de_lancer_l_UI_est_isolable():
    assert hasattr(ci_local, "_ui_doit_tourner"), (
        "la decision de lancer la campagne UI doit etre une fonction NOMMEE : enfouie "
        "dans une chaine if/elif de main(), son garde d'exclusivite etait MORT sans "
        "que rien ne le signale"
    )


def test_only_sur_un_AUTRE_gate_ne_lance_JAMAIS_la_campagne_UI():
    """LE defaut, mesure le 2026-09-09 par la DUREE d'un NR.

    L'auto-detection etait ecrite ainsi :

        if not a.ui_gate and not _ui_demande and not a.fast:
            _ui_ok, _ui_motif = _webhub_repond()
            _ui_auto = _ui_ok
        elif _ONLY and not _ui_demande:
            _ui_auto = False          # <-- BRANCHE MORTE

    Sous `--only "ruff critique"` les TROIS conditions du `if` sont vraies : la
    premiere branche est prise, `_ui_auto` recoit le resultat de la sonde, et le
    `elif` n'est jamais atteint. Des que :7400 repondait, `--only X` lancait donc la
    campagne UI complete — exactement ce que `--only` promet d'empecher, et ce que
    l'invariant d'EXCLUSIVITE de ce fichier affirme.

    Pourquoi personne ne l'a vu : un SECOND defaut le masquait. L'interpreteur du
    gate etait resolu par `Path.home()`, faux sous le compte de service, donc le gate
    se sautait avant de demarrer. Corriger ce second defaut a fait passer
    `test_le_point_d_entree_traverse_vraiment` de 5 s a plus de 100 s — Playwright
    demarrait pour de bon. La duree du NR voisin est le temoin de ce bug.
    """
    lancer, motif = ci_local._ui_doit_tourner(
        False, ["ruff critique"], False, True, False)
    assert lancer is False, (
        "`--only ruff critique` lance la campagne UI alors que :7400 repond — le "
        "selecteur n'est pas exclusif (%s)" % motif
    )


def test_only_sur_le_gate_UI_le_lance_bien():
    lancer, _ = ci_local._ui_doit_tourner(False, ["ui-acceptance"], True, False, False)
    assert lancer is True, "`--only ui-acceptance` doit lancer le gate, sonde ou pas"


def test_le_drapeau_explicite_prime_sur_la_selection():
    lancer, _ = ci_local._ui_doit_tourner(True, ["ruff critique"], False, False, False)
    assert lancer is True, "--ui-gate est une demande EXPLICITE, elle prime"


def test_sans_only_le_comportement_d_avant_est_intact():
    """NEUTRALITE — invariant 3 de ce fichier : `--only` absent ne change RIEN."""
    assert ci_local._ui_doit_tourner(False, None, False, True, False)[0] is True
    assert ci_local._ui_doit_tourner(False, None, False, False, False)[0] is False
    assert ci_local._ui_doit_tourner(False, None, False, True, True)[0] is False


def test_poser_only_est_reversible():
    """Un etat global doit pouvoir revenir a neutre, sinon les tests se contaminent."""
    ci_local._poser_only(["pip-audit"])
    assert ci_local._demande("bandit") is False
    ci_local._poser_only(None)
    assert ci_local._demande("bandit") is True
