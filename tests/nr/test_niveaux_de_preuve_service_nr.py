"""Une observation de TRANSPORT ne peut pas etre promue en STARTED / READY.

Ce garde formalise une semantique que le depot possede DEJA, ecrite le 2026-08-18 en
tete de `tools/forge_capability_contracts.py` :

    1. TRANSPORT  - le port accepte une connexion. Ne prouve RIEN sur le service :
                    un process fige tient son port.
    2. APPLICATIF - un endpoint HTTP repond (< 500). Un 401/403/404 compte comme
                    VIVANT : le service a compris la requete et l'a refusee.
    3. CAPACITE   - la FONCTION rend son service. ollama peut repondre tout en
                    n'ayant AUCUN modele charge.

Le contrat est juste, et il n'a que DEUX consommateurs — `forge_introspect` le range
meme parmi les organes « non consultes ». Pendant ce temps, d'autres sondes le violent
sans le savoir. Mesure du 2026-09-04 sur la famille LM Studio, trois definitions
concurrentes de « up » coexistaient :

    wait_for_port()  -> socket TCP ouvert            -> rend "status": "started"
    http_ok()        -> exige un 2xx                 -> lit un 401 comme MORT
    _up()            -> "401 in str(e)" -> True      -> conforme au contrat

Consequence mesuree : LM Studio protege par une cle d'API repond 401 ; le premier
module le voit vivant et se tait, le second le voit mort et relance `lms server start`
sur un serveur deja debout. Le troisieme declare `started` des l'ouverture du socket,
avant que l'API ne reponde quoi que ce soit.

CE QUE CE GARDE INTERDIT, et rien d'autre : qu'une sonde de niveau TRANSPORT decide
seule d'un statut de succes de service. Il n'interdit pas d'utiliser `wait_for_port`
(attendre un port est legitime), seulement d'en conclure « demarre ».
"""

import ast
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : parcours du depot : rglob app+tools + ast (l.98)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Sondes qui ne prouvent QUE le transport (socket ouvert).
_SONDES_TRANSPORT = {"wait_for_port", "port_is_listening", "_port_ouvert",
                     "_tcp_ouvert", "_port_ecoute"}

# Vocabulaire de succes de service. `up` seul est trop courant pour etre retenu.
_STATUTS_SUCCES = {"started", "ready", "serving", "running", "healthy", "operational"}


# Appels qui font MONTER la preuve au niveau applicatif. Si le bloc en contient un,
# il ne promeut pas le transport : il l'utilise comme premiere etape avant de
# verifier que le service repond. Mesure 2026-09-04 : sans cette exemption, le garde
# accusait `forge_services_launcher:409`, qui fait pourtant explicitement un
# « Double-check API OpenAI » sur /v1/models avant de conclure. Un garde qui accuse
# un site CONFORME se fait desarmer — et celui-la aurait ete le premier a l'etre.
_MONTEE_APPLICATIVE = {"urlopen", "http_ok", "_http", "get", "head", "request",
                       "_req", "health", "_up", "access_ok"}


def _monte_au_niveau_applicatif(noeud) -> bool:
    for sub in ast.walk(noeud):
        if isinstance(sub, ast.Call):
            nom = getattr(sub.func, "attr", None) or getattr(sub.func, "id", None)
            if nom in _MONTEE_APPLICATIVE:
                return True
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if sub.value.startswith(("http://", "https://", "/health", "/v1/", "/api/")):
                return True
    return False


def _declare_son_niveau_de_preuve(noeud) -> bool:
    """Le bloc annonce-t-il explicitement le niveau de preuve atteint ?"""
    for sub in ast.walk(noeud):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if sub.value.strip().lower() in ("preuve", "preuve_note", "proof", "evidence"):
                return True
    return False


def _statuts_dans(noeud) -> set:
    """Constantes de succes presentes dans un bloc."""
    out = set()
    for sub in ast.walk(noeud):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if sub.value.strip().lower() in _STATUTS_SUCCES:
                out.add(sub.value)
    return out


def _promotions():
    """Rend (violations, fichiers_lus, illisibles) — le denominateur est RENDU."""
    violations, illisibles = [], []
    lus = 0
    for dossier in ("app", "tools"):
        base = ROOT / dossier
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.py")):
            if "_attic" in f.parts:
                continue
            try:
                arbre = ast.parse(f.read_text(encoding="utf-8", errors="strict"),
                                  filename=str(f))
            except Exception as exc:
                illisibles.append("%s (%s)" % (f.relative_to(ROOT), type(exc).__name__))
                continue
            lus += 1
            for noeud in ast.walk(arbre):
                if not isinstance(noeud, ast.If):
                    continue
                # Le test appelle-t-il une sonde de transport ?
                sondes = {getattr(c.func, "attr", None) or getattr(c.func, "id", None)
                          for c in ast.walk(noeud.test) if isinstance(c, ast.Call)}
                if not (sondes & _SONDES_TRANSPORT):
                    continue
                bloc = ast.Module(body=noeud.body, type_ignores=[])
                # Le bloc monte-t-il lui-meme au niveau applicatif ? Alors le
                # transport n'est qu'une premiere etape, et c'est conforme.
                if _monte_au_niveau_applicatif(bloc):
                    continue
                # DEUXIEME forme de conformite : declarer le niveau atteint. Tous
                # les services n'ont pas d'endpoint HTTP — brain_worker parle ZMQ, le
                # cervelet WSL n'expose aucune sante declaree. Pour eux, le transport
                # EST le maximum atteignable, et exiger une montee impossible ferait
                # crier ce garde sur des sites irreprochables. Ce qu'on exige alors,
                # c'est l'HONNETETE : un champ `preuve` qui dit ce qui a ete prouve,
                # au lieu d'un `started` qui laisse croire davantage. Meme regle que
                # « une capacite absente reste declaree absente, jamais False ».
                if _declare_son_niveau_de_preuve(bloc):
                    continue
                # Le corps conclut-il a un succes de SERVICE ?
                trouves = _statuts_dans(bloc)
                if trouves:
                    violations.append(
                        "%s:%d — `if %s(...)` conclut %s"
                        % (f.relative_to(ROOT), noeud.lineno,
                           sorted(sondes & _SONDES_TRANSPORT)[0], sorted(trouves)))
    return violations, lus, illisibles


def test_le_balayage_est_representatif():
    """Sans denominateur, « 0 violation » ne se distingue pas de « je n'ai pas lu »."""
    _, lus, illisibles = _promotions()
    assert lus > 500, "balayage non representatif : %d fichiers" % lus
    assert not illisibles, "fichiers non parsables : %r" % (illisibles[:5],)


def test_aucune_promotion_du_transport_en_statut_de_service():
    """Le garde. Un socket ouvert ne demarre rien."""
    violations, _, _ = _promotions()
    assert not violations, (
        "%d endroit(s) concluent a un succes de SERVICE depuis une sonde de niveau "
        "TRANSPORT. Le contrat de `forge_capability_contracts` (2026-08-18) l'enonce : "
        "« le port accepte une connexion — ne prouve RIEN sur le service : un process "
        "fige tient son port ». Constater le port est legitime ; en conclure "
        "« demarre » ne l'est pas.\n  %s" % (len(violations), "\n  ".join(violations)))


def test_le_contrat_de_reference_traite_un_401_comme_vivant():
    """La regle de niveau APPLICATIF, verifiee sur la source de verite elle-meme.

    Si un jour ce contrat cessait de compter 401/403/404 comme vivant, tout le
    raisonnement ci-dessus perdrait son fondement — et les sondes qui le respectent
    deviendraient les fautives. On le fige donc explicitement.
    """
    src = (ROOT / "tools" / "forge_capability_contracts.py").read_text(
        encoding="utf-8", errors="replace")
    assert "code < 500" in src, (
        "le contrat de reference n'exprime plus le niveau APPLICATIF par `code < 500` : "
        "verifier qu'un 401/403/404 compte toujours comme VIVANT avant de s'appuyer "
        "dessus")


def test_le_garde_reconnait_une_vraie_promotion(tmp_path):
    """Contre-epreuve : un garde qui ne detecte rien passerait pour vert."""
    piege = tmp_path / "faux.py"
    piege.write_text(
        'def f(port):\n'
        '    if wait_for_port(port, max_s=10):\n'
        '        return {"status": "started"}\n'
        '    return {"status": "failed"}\n'
        'def g(port):\n'
        '    if wait_for_port(port):\n'
        '        log("port ouvert")   # ne conclut a AUCUN statut -> tolere\n'
        '    return None\n',
        encoding="utf-8")
    arbre = ast.parse(piege.read_text(encoding="utf-8"))
    vus = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.If):
            sondes = {getattr(c.func, "attr", None) or getattr(c.func, "id", None)
                      for c in ast.walk(noeud.test) if isinstance(c, ast.Call)}
            if sondes & _SONDES_TRANSPORT:
                t = _statuts_dans(ast.Module(body=noeud.body, type_ignores=[]))
                if t:
                    vus.append(sorted(t))
    assert vus == [["started"]], (
        "la detection ne rend pas exactement la promotion reelle : %r — soit elle "
        "rate le vrai cas, soit elle accuse un simple `wait_for_port` sans verdict"
        % (vus,))
