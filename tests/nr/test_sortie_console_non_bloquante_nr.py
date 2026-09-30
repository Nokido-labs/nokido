"""NR — une decoration de console ne gele JAMAIS la boucle d'evenements.

Mesure du 2026-09-18, 18:25:17. Le hub `:8766` a ete tue par son propre garde :

    === 2026-09-18 18:25:17 WEDGE KILL : event-loop gele 60s >= 60s -> os._exit(1)

Le dump `faulthandler`, dans le thread qui porte `run_forever` :

    app/forge_byte_router.py:133 in process    <- frame la plus recente
    tools/nokido_hub.py:1199 in _tool_call
    tools/nokido_hub.py:2961 in mcp_post

La ligne 133 etait `print(..., flush=True)` : une decoration de TUI, ecrite
synchronement dans la boucle, a CHAQUE appel d'outil MCP. stdout est un tuyau
draine par le superviseur, mesure le MEME JOUR avec 7 minutes de retard. Tuyau
plein ⇒ `flush()` attend ⇒ boucle gelee ⇒ kill.

C'est le gel du webhub du meme jour (`logging:1144 self.stream.flush()`), sur un
autre service et par un autre chemin : `print` au lieu de `logging`.
`installer_logging_non_bloquant` ne couvrait que `logging`.

MORSURE (controle negatif) : le MEME flux lent, ecrit par un `print` ordinaire,
DOIT bloquer. Sans ce contre-exemple, le test ne prouverait rien sur le flux —
il passerait aussi avec un flux rapide.
"""

import sys
import threading
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from app.forge_logging import ecrire_sans_bloquer  # noqa: E402

LENTEUR_S = 0.4


class _FluxLent:
    """Imite un tuyau sature : chaque ecriture paie une attente."""

    def __init__(self):
        self.recu = []
        self._verrou = threading.Lock()

    def write(self, texte):
        time.sleep(LENTEUR_S)
        with self._verrou:
            self.recu.append(texte)
        return len(texte)

    def flush(self):
        time.sleep(LENTEUR_S)


def test_l_appelant_ne_paie_pas_l_attente_du_flux():
    flux = _FluxLent()
    debut = time.perf_counter()
    for i in range(5):
        ecrire_sans_bloquer(f"decoration {i}\n", flux=flux)
    ecoule = time.perf_counter() - debut
    # 5 ecritures x 0,4 s d'attente = 2 s si l'appelant paie. Il ne doit pas.
    assert ecoule < LENTEUR_S, (
        f"l'appelant a attendu {ecoule:.2f}s : la decoration bloque encore la boucle"
    )


def test_morsure_un_print_ordinaire_sur_le_meme_flux_BLOQUE():
    """CONTROLE NEGATIF — prouve que le flux de test est bien lent.

    Sans lui, le test precedent passerait au vert avec un flux rapide, sans
    rien demontrer.
    """
    flux = _FluxLent()
    debut = time.perf_counter()
    print("decoration\n", file=flux, end="", flush=True)
    ecoule = time.perf_counter() - debut
    assert ecoule >= LENTEUR_S, (
        f"le flux temoin n'est pas lent ({ecoule:.2f}s) — le NR ne prouverait rien"
    )


def test_le_texte_finit_par_arriver():
    """Non bloquant ne veut pas dire perdu : le fil separe ecrit pour de vrai."""
    flux = _FluxLent()
    ecrire_sans_bloquer("temoin-de-livraison\n", flux=flux)
    limite = time.time() + 10
    while time.time() < limite:
        if any("temoin-de-livraison" in t for t in list(flux.recu)):
            break
        time.sleep(0.05)
    assert any("temoin-de-livraison" in t for t in flux.recu), (
        "le texte n'est jamais parvenu au flux : on a echange un gel contre une cecite"
    )


def test_un_flux_casse_ne_leve_jamais():
    """Un canal d'affichage qui casse ne doit pas casser son appelant."""

    class _FluxCasse:
        def write(self, texte):
            raise OSError("tuyau ferme")

        def flush(self):
            raise OSError("tuyau ferme")

    # ne doit lever aucune exception
    ecrire_sans_bloquer("peu importe\n", flux=_FluxCasse())


def test_la_saturation_est_COMPTEE_pas_silencieuse():
    """Une perte muette echange un gel contre une cecite — le defaut du 27/07."""
    from app import forge_logging

    assert hasattr(forge_logging, "_signaler_perte"), "pas de compteur de pertes"
    src = (RACINE / "app" / "forge_logging.py").read_text(encoding="utf-8")
    bloc = src[src.index("def ecrire_sans_bloquer") :][:1500]
    assert "_signaler_perte" in bloc, (
        "la saturation de la file ne signale rien : les pertes seraient invisibles"
    )


def test_le_chemin_reel_du_hub_n_a_plus_de_print_bloquant():
    """Le NR emprunte le chemin REEL : plus aucun `print(flush=...)` dans le
    middleware qui tourne dans la boucle.

    Lecture par AST, PAS par texte. Une premiere version filtrait les lignes et
    s'est accusee elle-meme : la phrase de sa propre docstring qui DECRIT le
    defaut matchait le motif. C'est la cinquieme fois que ce piege mord dans ce
    depot — « un instrument ne lit jamais son propre vocabulaire ». L'AST ne voit
    que des appels, donc ni commentaires ni docstrings.
    """
    import ast

    chemin = RACINE / "app" / "forge_byte_router.py"
    arbre = ast.parse(chemin.read_text(encoding="utf-8"))
    fautifs = [
        f"ligne {n.lineno}"
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "print"
        and any(k.arg == "flush" for k in n.keywords)
    ]
    assert not fautifs, (
        "des print bloquants subsistent dans le middleware de la boucle : "
        + ", ".join(fautifs)
    )


def test_morsure_le_scanner_ast_voit_un_vrai_print(tmp_path):
    """CONTROLE NEGATIF du test precedent — sans lui, un scanner casse
    (mauvais chemin, AST vide) rendrait toujours zero et acquitterait."""
    import ast

    faux = tmp_path / "faux.py"
    faux.write_text(
        '"""docstring citant print(x, flush=True) sans en etre un."""\n'
        "def f():\n"
        "    print('vrai', flush=True)\n",
        encoding="utf-8",
    )
    arbre = ast.parse(faux.read_text(encoding="utf-8"))
    trouves = [
        n.lineno
        for n in ast.walk(arbre)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "print"
        and any(k.arg == "flush" for k in n.keywords)
    ]
    assert trouves == [3], (
        f"le scanner AST doit voir le print de la ligne 3 et IGNORER la docstring "
        f"de la ligne 1 — il a rendu {trouves}"
    )
