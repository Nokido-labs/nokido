"""NR : forge_playwright_browser — infra navigateur + Oracle UI (défensive).

Le module a été restauré dans tools/ (séparation offensif/défensif 2026-08-22 :
c'est l'infra du gate d'acceptation UI, mal rangée auparavant dans tools/ctf).
On teste des EFFETS PURS — zéro lancement de navigateur, zéro service externe :
  - profil ISOLÉ du Firefox principal user (règle inviolable)
  - interface stable consommée par forge_ui_campaign / forge_ui_oracle
  - le JS d'introspection cible bien les éléments interactifs
  - LE CHOIX DU MOTEUR est explicite, borné, et DIT son motif (2026-09-14)

Le dernier volet répare un défaut payé : le gate `ui-acceptance` était UNKNOWN
depuis le 2026-09-11 parce que ce lanceur ouvrait `firefox.launch_persistent_context`
EN DUR. Sous un compte sans session graphique, ce firefox se lance puis GÈLE sur
`RenderCompositorSWGL failed mapping default framebuffer` ; l'appel pend 180 s,
puis rend un timeout qui ne nomme ni le moteur, ni le magasin, ni la cause. Le
verdict était donc illisible : impossible de distinguer « pas de navigateur » de
« pas de service ».

ANTI-DUP : la décision de moteur est déjà prise et mesurée dans le dépôt par
`tools/forge_ui_contrat_etats.py` (canal système + `launch` NU + timeout 25 s).
On ne fonde pas une politique concurrente — on la porte au seul endroit que les
trois consommateurs partagent (campaign, nervous_census, contrat_etats).

RÈGLE OWNER TENUE (`memory/feedback_firefox_main_isolated.md`) : un canal système
n'emprunte que le BINAIRE. `launch` NU ne touche AUCUN profil de l'utilisateur —
Playwright fabrique un répertoire jetable — et n'installe aucune extension. Ce que
la règle interdit, c'est le profil principal et les extensions, pas le binaire.
"""
import ast
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import forge_playwright_browser as pb

def test_profil_isole_du_firefox_principal():
    # Règle : jamais toucher au Firefox principal user -> profil dédié isolé.
    prof = str(pb.PROFILE_DIR).lower()
    assert "nokido" in prof and "browser-profiles" in prof
    assert "mozilla" not in prof and "appdata" not in prof

def test_interface_consommee_par_le_gate_ui():
    # forge_ui_campaign / forge_ui_oracle dépendent de CETTE surface.
    for meth in ("goto", "screenshot", "dom_text", "get_interactive_elements",
                 "set_of_mark", "click_index", "dom_hash", "accessibility_tree"):
        assert callable(getattr(pb.PlaywrightBrowser, meth)), f"méthode {meth} absente"
    assert inspect.iscoroutinefunction(pb.ui_observe)

def test_js_cible_les_interactifs():
    js = pb.PlaywrightBrowser._INTERACTIVE_JS
    for motif in ("button", "a[href]", "role=link", "getBoundingClientRect"):
        assert motif in js


# ---------------------------------------------------------------------------
# Choix du moteur — fonction pure : la décision ET son motif
# ---------------------------------------------------------------------------

def test_demande_absente_du_magasin_est_refusee_en_la_nommant():
    """Magasin LU sans chromium : refus NET. Le tenter, c'est pendre 180 s."""
    with pytest.raises(ValueError) as exc:
        pb.choisir_lancement("chromium", presents={"firefox"}, etat_magasin="LU")
    message = str(exc.value)
    assert "chromium" in message, "le refus doit nommer le moteur demandé"
    assert "magasin" in message.lower(), "le refus doit nommer où il a regardé"


def test_magasin_illisible_ne_vaut_pas_absent():
    """UNKNOWN != NO : on ne déclare pas chromium absent, on se replie en le disant."""
    moteur, canal, origine, motif = pb.choisir_lancement(
        None, presents=set(), etat_magasin="ILLISIBLE"
    )
    assert origine == "systeme", "magasin illisible -> canal système, aucun pari"
    assert "ILLISIBLE" in motif, f"le motif doit porter l'indétermination : {motif!r}"
    assert canal is not None, "un lancement système nomme son canal"
    assert moteur in pb.MOTEURS_CONNUS


def test_demande_inconnue_est_refusee_jamais_repliee():
    """Un repli muet ferait mesurer autre chose que ce qui a été demandé."""
    with pytest.raises(ValueError) as exc:
        pb.choisir_lancement("safari", presents={"firefox"}, etat_magasin="LU")
    message = str(exc.value)
    assert "safari" in message
    for connu in ("chromium", "chrome", "firefox"):
        assert connu in message, "le refus doit LISTER ce qui est acceptable"


def test_sans_demande_le_bundled_prime_sur_le_systeme():
    """Le magasin ne dépend d'aucun binaire tiers : il passe en premier."""
    moteur, _canal, origine, _motif = pb.choisir_lancement(
        None, presents={"chromium", "firefox"}, etat_magasin="LU"
    )
    assert (moteur, origine) == ("chromium", "magasin")


def test_sans_demande_et_magasin_sans_chromium_replie_sur_le_systeme():
    """Mesure 2026-09-11 : le firefox du magasin GÈLE — il ne peut pas être le repli."""
    moteur, canal, origine, motif = pb.choisir_lancement(
        None, presents={"firefox"}, etat_magasin="LU"
    )
    assert origine == "systeme", f"firefox qui gèle ne doit pas être élu : {motif!r}"
    assert canal in ("chrome", "msedge")
    assert moteur == "chromium"


def test_chaque_verdict_nomme_son_origine_et_son_motif():
    """Un choix sans motif est un choix qu'on ne peut pas auditer après coup."""
    for presents, etat in (({"chromium"}, "LU"), (set(), "LU"), (set(), "ABSENT")):
        moteur, _canal, origine, motif = pb.choisir_lancement(None, presents, etat)
        assert origine in ("magasin", "systeme"), origine
        assert motif and motif.strip(), "le motif ne peut pas être vide"
        assert moteur in pb.MOTEURS_CONNUS


def test_demande_explicite_sur_canal_systeme_est_honoree():
    """`chrome` et `msedge` ne vivent pas dans le magasin : ne pas les y chercher."""
    moteur, canal, origine, _motif = pb.choisir_lancement(
        "msedge", presents=set(), etat_magasin="LU"
    )
    assert (moteur, canal, origine) == ("chromium", "msedge", "systeme")


def test_demande_firefox_explicite_reste_possible():
    """La mesure dit qu'il gèle SANS session graphique — pas qu'il est mort partout.

    L'owner doit pouvoir l'élire depuis une session graphique : on refuse de
    l'ÉLIRE par défaut, on ne l'interdit pas.
    """
    moteur, canal, origine, _motif = pb.choisir_lancement(
        "firefox", presents={"firefox"}, etat_magasin="LU"
    )
    assert (moteur, canal, origine) == ("firefox", None, "magasin")


# ---------------------------------------------------------------------------
# Cascade — la présence dans le magasin ne prouve pas que ça se lance
# ---------------------------------------------------------------------------

def test_la_presence_au_magasin_ne_suffit_pas_il_faut_un_repli():
    """Défaut payé le 2026-09-14, et il a coûté 172 Mo de téléchargement inutile.

    `playwright install chromium` (CLI de la lib 1.58.0) dépose `chromium-1208`
    pendant que l'API de la MÊME lib réclame `chromium-1228` : deux artefacts
    sous un seul nom (Chrome for Testing vs Chromium natif). Élire un candidat
    unique sur la foi du magasin donne donc un lanceur qui échoue en nommant un
    binaire qu'on vient d'installer. Mesure : chromium bundled REFUSÉ, canal
    `chrome` OK sur le même poste, à la même seconde.
    """
    candidats = pb.candidats_lancement(None, presents={"chromium"}, etat_magasin="LU")
    assert len(candidats) >= 2, "un seul candidat = aucun repli quand il refuse"
    origines = [c[2] for c in candidats]
    assert "systeme" in origines, "la cascade doit finir hors du magasin"


def test_une_demande_explicite_ne_donne_qu_un_candidat():
    """Sinon on mesure un autre navigateur que celui dont on parle."""
    assert len(pb.candidats_lancement("msedge", set(), "LU")) == 1
    assert len(pb.candidats_lancement("firefox", {"firefox"}, "LU")) == 1


def test_magasin_illisible_fait_passer_le_systeme_en_premier():
    """Un essai qui pend coûte tout le budget : commencer par ce qui ne dépend de rien."""
    candidats = pb.candidats_lancement(None, presents=set(), etat_magasin="ILLISIBLE")
    assert candidats[0][2] == "systeme"
    assert any(c[2] == "magasin" for c in candidats), (
        "ILLISIBLE != ABSENT : le magasin reste essayé, mais en dernier"
    )


def test_choisir_lancement_est_le_premier_candidat():
    """Une seule logique, deux vues — pas deux politiques qui divergeront."""
    for presents, etat in (({"chromium"}, "LU"), (set(), "LU"), (set(), "ILLISIBLE")):
        assert pb.choisir_lancement(None, presents, etat) == (
            pb.candidats_lancement(None, presents, etat)[0]
        )


# ---------------------------------------------------------------------------
# Inventaire du magasin — trois états, jamais deux
# ---------------------------------------------------------------------------

def test_inventaire_lit_les_moteurs_du_magasin(tmp_path: Path):
    for nom in ("firefox-1532", "chromium-1194", "ffmpeg-1011", "winldd-1007"):
        (tmp_path / nom).mkdir()
    presents, etat = pb.inventaire_magasin(tmp_path)
    assert etat == "LU"
    assert presents == {"firefox", "chromium"}, "ffmpeg/winldd ne sont pas des moteurs"


def test_inventaire_ne_confond_pas_headless_shell_et_chromium(tmp_path: Path):
    """`chromium_headless_shell-1194` n'est PAS un chromium complet."""
    (tmp_path / "chromium_headless_shell-1194").mkdir()
    presents, etat = pb.inventaire_magasin(tmp_path)
    assert etat == "LU"
    assert "chromium" not in presents


def test_magasin_absent_se_distingue_d_un_magasin_illisible(tmp_path: Path):
    presents, etat = pb.inventaire_magasin(tmp_path / "nexistepas")
    assert (presents, etat) == (set(), "ABSENT")


def test_magasin_qui_leve_est_illisible_pas_vide(monkeypatch, tmp_path: Path):
    """Un refus d'ACL fait lever `iterdir` : c'est ILLISIBLE, pas vide.

    C'est le faux négatif indétectable de la constitution sémantique : un capteur
    qui rend la même chose pour « pas là » et pour « accès refusé ».
    """
    def _refuse(self):
        raise PermissionError("acces refuse")

    monkeypatch.setattr(Path, "iterdir", _refuse)
    presents, etat = pb.inventaire_magasin(tmp_path)
    assert (presents, etat) == (set(), "ILLISIBLE")


# ---------------------------------------------------------------------------
# Chemin RÉEL — un sélecteur que personne n'appelle est un faux vert
# ---------------------------------------------------------------------------

def _aenter_ast():
    source = (TOOLS / "forge_playwright_browser.py").read_text(encoding="utf-8")
    for noeud in ast.walk(ast.parse(source)):
        if isinstance(noeud, ast.AsyncFunctionDef) and noeud.name == "__aenter__":
            return noeud
    pytest.fail("__aenter__ introuvable — le lanceur a changé de forme")


def test_le_lanceur_reel_appelle_le_selecteur():
    """Lecture AST, sans import ni lancement de navigateur."""
    aenter = _aenter_ast()
    appels = {
        n.func.id
        for n in ast.walk(aenter)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "candidats_lancement" in appels, (
        "le lanceur réel n'appelle pas le sélecteur : les tests ci-dessus "
        "mesureraient une fonction morte"
    )
    for n in ast.walk(aenter):
        if isinstance(n, ast.Attribute) and n.attr == "launch_persistent_context":
            cible = n.value
            assert not (
                isinstance(cible, ast.Attribute) and cible.attr == "firefox"
            ), "firefox est de nouveau câblé en dur — c'est le défaut d'origine"


def test_le_lancement_est_borne_dans_le_temps():
    """180 s de pendaison muette : c'est ce qui a rendu le gate illisible.

    On exige un `timeout=` explicite, quelle que soit sa valeur. Ce qui est
    interdit, c'est le défaut implicite de Playwright.
    """
    aenter = _aenter_ast()
    bornes = [
        kw
        for appel in ast.walk(aenter)
        if isinstance(appel, ast.Call)
        for kw in appel.keywords
        if kw.arg == "timeout"
    ]
    assert bornes, "aucun timeout explicite : le lancement peut pendre 180 s"


def test_un_candidat_qui_refuse_est_nomme_pas_avale():
    """« le navigateur ne marche pas » ne dit ni lequel, ni pourquoi.

    Le lanceur doit consigner les refus. Sans cette liste, la cascade masque
    exactement ce qu'on a besoin de savoir pour réparer — et un gate qui sort
    INDISPONIBLE sans nommer l'essai est un gate illisible.
    """
    aenter = _aenter_ast()
    source_aenter = ast.dump(aenter)
    assert "refuses" in source_aenter, (
        "aucune collecte des refus : la cascade avalerait la cause réelle"
    )
    assert any(
        isinstance(n, ast.Try) for n in ast.walk(aenter)
    ), "sans try/except autour de l'essai, il n'y a pas de cascade du tout"
