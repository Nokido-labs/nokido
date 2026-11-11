"""NR -- P5 de la veille CI (choix owner 10/11 soir) : toute la suite tourne avec une borne socket native.

Veille AGY (docs/veille/ci_meilleures_pratiques_agy_20261110.md l.83-99, P5) : sous Windows, pytest-timeout est en
methode `thread` ; un appel natif bloque (socket synchrone, WaitForSingleObject) ne peut pas etre interrompu et
fige le worker xdist a 99 % (gw1 plante, run 42010880738). Contrats :
  1. pendant les tests, socket.getdefaulttimeout() est borne, STRICTEMENT sous --timeout=30 ;
  2. la borne vient du conftest racine (_armer_borne_socket), donc aussi des workers xdist.
"""
# pylint: disable=import-error,import-outside-toplevel,protected-access  # conftest racine charge par chemin
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))


def test_borne_socket_active_sous_le_timeout_pytest():
    """Borne native posee et strictement sous --timeout=30."""
    t = socket.getdefaulttimeout()
    assert t is not None and 0 < t < 30


def test_borne_posee_par_le_conftest_racine():
    """La borne vient du conftest racine (workers xdist compris).

    10/11 : `import conftest` attrapait en lot le conftest d'un SOUS-dossier deja dans sys.modules (rouge en lot,
    vert seul, job_0148a7c78f74). Le conftest racine se lit par son CHEMIN, en AST, sans le re-executer.
    """
    import ast
    from pathlib import Path

    racine = ROOT / "tests" / "conftest.py"   # le conftest « racine » de la suite (tests/nr/conftest.py est l'autre)
    arbre = ast.parse(racine.read_text(encoding="utf-8"))
    noms = {n.name for n in arbre.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_armer_borne_socket" in noms, "conftest racine sans _armer_borne_socket"
