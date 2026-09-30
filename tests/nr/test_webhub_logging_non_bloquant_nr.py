"""NR -- le webhub ne journalise JAMAIS depuis sa boucle d'evenements.

DEFAUT PHOTOGRAPHIE le 2026-09-17 a 22:47:31 par le veilleur de gel. La pile du
fil principal de :7400, prise SANS tuer le service :

    logging/__init__.py  1144  self.stream.flush()      <- LE BLOCAGE
    logging/__init__.py  1539  info
    uvicorn/protocols/http/httptools_impl.py  484  send  <- le log d'ACCES
    starlette/middleware/errors.py  161  _send
    app/web_hub/app.py  417  _envoyer
    starlette/responses.py  246  stream_response
    asyncio/base_events.py  645  run_forever

La ligne 1144 est `self.stream.flush()` ; `self.acquire()` est la 1141. Ce n'est
donc PAS une contention de verrou entre fils, c'est une ECRITURE d'entree-sortie
qui ne rend pas la main -- dans la boucle d'evenements, qui ne sert plus rien
pendant ce temps. `/health` devient muet, et un transport vivant passe pour une
application morte.

LE SECOND OBSERVATEUR, parce qu'une sonde unique ne decide pas. Les journaux par
service ecrits par le superviseur (`pipeToLog`), le 17/09 :

    service              21 h     22 h     23 h
    NokidoMCP             477        1      120
    NokidoSecretary       693       18      378
    NokidoWebHub         3343       38     1381

Une heure de quasi-silence pour TOUS les services, puis 1381 lignes deversees
d'un coup a 23:04:49, juste avant `Shutdown complete.` a 23:04:51 : le contenu
etait coince dans le tampon du pipe et n'en est sorti qu'a la fermeture. Et
`pipeToLog INTERROMPU` n'apparait nulle part ce jour-la (seulement les 27 et 28
juillet) : le drain n'etait pas MORT, il n'ecrivait plus assez vite.

CE QUE CE NR FIGE. Le webhub est le seul service a journaliser depuis une boucle
d'evenements ; il est donc le seul que la saturation du pipe puisse geler. La
propriete a tenir n'est pas << le drain doit etre rapide >> -- on ne controle pas
la latence du disque d'en face -- mais : AUCUNE ecriture de journal ne bloque
l'appelant, quelle que soit la lenteur du flux de sortie.

Ce fichier teste la PROPRIETE (le non-blocage, mesure au chronometre), pas la
forme du code. Et il porte sa propre morsure : sans un instrument dont on a
prouve qu'il sait echouer, un test de non-blocage est vert sur du vide.
"""
from __future__ import annotations

import ast
import logging
import threading
import time
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
SOURCE = RACINE / "tools" / "nokido_web_hub.py"

# Lenteur du flux temoin. Assez grande pour etre indiscutable face a la marge de
# mesure, assez petite pour ne pas alourdir la suite.
LENTEUR_S = 2.0
# Au-dela, on considere que l'appelant a ete BLOQUE. Un ordre de grandeur sous
# LENTEUR_S : entre les deux il n'y a pas de zone grise a interpreter.
TOLERANCE_S = 0.4


class FluxLent:
    """Flux dont le `flush()` dort -- le pipe sature du 2026-09-17, en petit.

    On imite `flush` ET `write` : sur un vrai pipe plein, c'est l'ecriture qui
    bloque d'abord et le flush ensuite. Les deux chemins doivent etre couverts,
    sinon l'instrument prouve moins que ce qu'on lui demande.
    """

    def __init__(self, lenteur: float = LENTEUR_S) -> None:
        self.lenteur = lenteur
        self.lignes: list[str] = []
        self.entrave = threading.Event()

    def write(self, texte: str) -> int:
        self.entrave.wait(self.lenteur)
        self.lignes.append(texte)
        return len(texte)

    def flush(self) -> None:
        self.entrave.wait(self.lenteur)

    def close(self) -> None:  # pragma: no cover - exige par certains handlers
        pass


def _chronometrer(fn) -> float:
    debut = time.perf_counter()
    fn()
    return time.perf_counter() - debut


@pytest.fixture
def journal_isole():
    """Un logger a soi, detruit apres usage : ce NR ne doit pas deteindre."""
    nom = "nr.webhub.non.bloquant.%d" % time.monotonic_ns()
    lg = logging.getLogger(nom)
    lg.setLevel(logging.INFO)
    lg.propagate = False
    yield nom, lg
    for h in list(lg.handlers):
        lg.removeHandler(h)
        try:
            h.close()
        except Exception:  # pragma: no cover - fermeture best effort
            pass


# --------------------------------------------------------------------------
# 0. L'INSTRUMENT AVANT LA MESURE
# --------------------------------------------------------------------------

def test_l_instrument_mord_un_handler_ordinaire_bloque_bel_et_bien(journal_isole):
    """Sans ceci, le test suivant serait vert meme si rien n'avait ete corrige.

    C'est la reproduction FIDELE du defaut du 2026-09-17 : un `StreamHandler`
    pose sur un flux lent fait attendre son appelant.
    """
    _, lg = journal_isole
    flux = FluxLent()
    lg.addHandler(logging.StreamHandler(flux))

    duree = _chronometrer(lambda: lg.info("une ligne d'acces"))

    assert duree >= LENTEUR_S * 0.8, (
        "le flux temoin n'a PAS retenu l'appelant (%.3f s) : l'instrument ne "
        "mord pas, donc le test de non-blocage ne prouverait rien" % duree)


# --------------------------------------------------------------------------
# 1. LA PROPRIETE : journaliser ne bloque JAMAIS l'appelant
# --------------------------------------------------------------------------

def test_un_flux_lent_ne_retient_plus_l_appelant(journal_isole):
    from app.forge_logging import installer_logging_non_bloquant

    nom, lg = journal_isole
    flux = FluxLent()
    pose = installer_logging_non_bloquant([nom], flux=flux)
    try:
        duree = _chronometrer(lambda: lg.info("une ligne d'acces"))
    finally:
        pose.arreter()

    assert duree < TOLERANCE_S, (
        "journaliser a retenu l'appelant %.3f s alors que le flux de sortie est "
        "lent : c'est exactement le gel de :7400 du 2026-09-17, ou la boucle "
        "d'evenements attendait `self.stream.flush()` pendant que /health se "
        "taisait" % duree)


def test_la_sortie_finit_par_etre_ECRITE_le_report_n_est_pas_une_perte(journal_isole):
    """Ne pas bloquer ne doit pas vouloir dire ne pas journaliser.

    Un correctif qui rendrait la main en JETANT la ligne echangerait un gel
    contre une cecite -- le defaut du 2026-07-27, ou 5 h de journaux ont disparu
    sans un mot.
    """
    from app.forge_logging import installer_logging_non_bloquant

    nom, lg = journal_isole
    flux = FluxLent(lenteur=0.05)
    pose = installer_logging_non_bloquant([nom], flux=flux)
    try:
        lg.info("ligne temoin 42")
        pose.arreter()  # l'arret VIDE la file avant de rendre la main
    finally:
        pass

    assert any("ligne temoin 42" in l for l in flux.lignes), (
        "la ligne n'a jamais atteint le flux : le report est devenu une perte")


def test_la_file_pleine_PERD_en_le_comptant_et_sans_bloquer(journal_isole):
    """Une file non bornee echange un gel contre une fuite memoire.

    Bornee, elle finit par perdre -- et une perte muette est un capteur qui ment.
    On exige donc : ne pas bloquer, ET tenir le compte de ce qui est tombe.
    """
    from app.forge_logging import installer_logging_non_bloquant

    nom, lg = journal_isole
    flux = FluxLent()
    pose = installer_logging_non_bloquant([nom], flux=flux, taille_file=4)
    try:
        duree = _chronometrer(lambda: [lg.info("saturation %d" % i) for i in range(200)])
    finally:
        pose.arreter()

    assert duree < TOLERANCE_S, (
        "200 lignes sur une file de 4 ont retenu l'appelant %.3f s : la file "
        "pleine bloque au lieu de perdre" % duree)
    assert pose.perdus > 0, (
        "aucune perte comptee alors que la file etait bornee a 4 pour 200 "
        "lignes : le compteur ne compte pas, donc la perte serait MUETTE")


# --------------------------------------------------------------------------
# 2. LE CHEMIN REEL -- la fonction peut etre juste et n'etre appelee nulle part
# --------------------------------------------------------------------------

def _appels(arbre: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(arbre) if isinstance(n, ast.Call)]


def _nom_appele(appel: ast.Call) -> str:
    cible = appel.func
    if isinstance(cible, ast.Attribute):
        return cible.attr
    if isinstance(cible, ast.Name):
        return cible.id
    return ""


@pytest.fixture(scope="module")
def arbre_webhub() -> ast.AST:
    assert SOURCE.exists(), (
        "%s introuvable : sans lui ce test passerait sur du vide" % SOURCE)
    return ast.parse(SOURCE.read_text(encoding="utf-8", errors="replace"))


def test_le_lanceur_installe_la_file_avant_de_servir(arbre_webhub):
    """Un mecanisme present mais non cable est une dette, jamais une securite."""
    assert any(_nom_appele(a) == "installer_logging_non_bloquant"
               for a in _appels(arbre_webhub)), (
        "tools/nokido_web_hub.py n'appelle jamais `installer_logging_non_bloquant` : "
        "le correctif existe mais le service continue de journaliser depuis sa "
        "boucle d'evenements")


def test_le_journal_racine_est_detache_aussi(arbre_webhub):
    """Gel du 2026-09-29 08:55:30 : la boucle s'est arretee dans `stream.write`,
    atteinte par `httpx` (INFO par requete) via le journal RACINE, que la liste
    uvicorn/uvicorn.error/uvicorn.access ne couvrait pas. La racine couvre tout
    journal qui y remonte ; l'enumeration laisserait la prochaine porte ouverte."""
    appels = [a for a in _appels(arbre_webhub) if _nom_appele(a) == "installer_logging_non_bloquant"]
    assert appels, "installer_logging_non_bloquant n'est pas appele"
    premier = appels[0].args[0] if appels[0].args else None
    noms = ({e.value for e in premier.elts if isinstance(e, ast.Constant)}
            if isinstance(premier, (ast.Tuple, ast.List)) else None)
    assert noms is not None, "liste des journaux detaches ILLISIBLE (pas un litteral) : ni vrai ni faux"
    assert "" in noms, (
        "le journal racine n'est pas detache : httpx (et tout journal qui y remonte) "
        "ecrit encore en synchrone depuis la boucle -- %s" % sorted(noms))


def test_uvicorn_ne_repose_plus_sa_propre_configuration_de_journal(arbre_webhub):
    """uvicorn REMPLACE les handlers de `uvicorn.access` quand il configure.

    Installer la file puis laisser uvicorn poser sa configuration par defaut
    reviendrait a la desinstaller juste apres -- un garde branche puis debranche
    dans la meme fonction, et rigoureusement invisible a la relecture.
    """
    runs = [a for a in _appels(arbre_webhub) if _nom_appele(a) == "run"]
    assert runs, "aucun appel `.run(...)` dans le lanceur"
    for appel in runs:
        cles = {k.arg for k in appel.keywords if k.arg}
        if "host" in cles and "port" in cles:
            assert "log_config" in cles, (
                "uvicorn.run est appele SANS `log_config` : il pose alors sa "
                "configuration par defaut, qui reinstalle un StreamHandler "
                "synchrone sur uvicorn.access et annule la file")
            return
    pytest.fail("appel uvicorn.run(host=..., port=...) introuvable : chemin reel "
                "non verifiable, donc ILLISIBLE -- ni vrai ni faux")
