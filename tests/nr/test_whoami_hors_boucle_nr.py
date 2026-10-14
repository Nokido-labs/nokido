"""NR -- whoami ne gele plus la boucle du hub (2026-10-13).

Mesure (logs/loop_lag.log, 13/10) : 6 gels de la boucle du hub dans la journee, 74 s cumules, max 17,9 s, tous
avec le thread principal dans handle_whoami, sur `SELECT domain, COUNT(*) FROM rag_chunks ... GROUP BY domain`
(~10 M lignes) execute SYNCHRONE dans un `async def`. Plus que les 42 autres gels du jour reunis.

Invariants :
- le corps synchrone de whoami tourne HORS du thread de la boucle (meme forme que `query`) ;
- les comptes par domaine sont caches : un second appel dans le TTL n'execute AUCUNE requete ;
- un comptage deja en cours ne se double pas : l'appel concurrent rend la valeur perimee, ou DIT qu'il n'y en a pas ;
- controle negatif : cache expire -> on recompte.
"""
# pylint: disable=protected-access
import asyncio
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app"), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app.forge_mcp_registry import ToolRegistry  # noqa: E402


class _Connexion:
    """Fausse connexion sqlite : compte les requetes, rend un domaine."""

    def __init__(self):
        self.requetes = 0

    def execute(self, _sql, *_args):
        """Compte la requete et rend une ligne `domain/n`."""
        self.requetes += 1
        return SimpleNamespace(fetchall=lambda: [{"domain": "ia", "n": 3}])


def _vider_cache():
    ToolRegistry._WHOAMI_DOMAINES.update(ts=0.0, val=None)


def test_le_corps_de_whoami_tourne_hors_de_la_boucle():
    """Chemin reel : handle_whoami delegue son corps synchrone a un thread du pool, jamais a la boucle."""
    vu = {}

    def _corps(_args, _agent, _ring):
        vu["corps"] = threading.current_thread()
        return "{}"

    async def _appel():
        vu["boucle"] = threading.current_thread()
        return await ToolRegistry.handle_whoami(SimpleNamespace(_handle_whoami_sync=_corps), {}, "NR", 3)

    assert asyncio.run(_appel()) == "{}"
    assert vu["corps"] is not vu["boucle"], "le corps synchrone de whoami tourne SUR la boucle du hub"


def test_les_comptes_par_domaine_ne_se_recalculent_pas_dans_le_ttl():
    """Deux appels rapproches : un seul scan de rag_chunks."""
    _vider_cache()
    cnx = _Connexion()
    premier = ToolRegistry._whoami_domaines(None, cnx)
    second = ToolRegistry._whoami_domaines(None, cnx)
    assert premier == second == [{"domain": "ia", "chunks": 3}]
    assert cnx.requetes == 1


def test_un_comptage_en_cours_ne_se_double_pas_et_l_absence_se_dit():
    """Verrou tenu par un autre appel : pas de second scan ; sans valeur, le dire ; avec, rendre la perimee."""
    _vider_cache()
    cnx = _Connexion()
    assert ToolRegistry._WHOAMI_DOMAINES_VERROU.acquire(blocking=False)
    try:
        sans_valeur = ToolRegistry._whoami_domaines(None, cnx)
        ToolRegistry._WHOAMI_DOMAINES.update(ts=1.0, val=[{"domain": "ancien", "chunks": 1}])
        perimee = ToolRegistry._whoami_domaines(None, cnx)
    finally:
        ToolRegistry._WHOAMI_DOMAINES_VERROU.release()
    assert cnx.requetes == 0
    assert isinstance(sans_valeur, str) and "EN_CALCUL" in sans_valeur
    assert perimee == [{"domain": "ancien", "chunks": 1}]
    _vider_cache()


def test_controle_negatif_un_cache_expire_recompte():
    """Au-dela du TTL, on recompte : le cache ne fige pas la valeur pour toujours."""
    _vider_cache()
    cnx = _Connexion()
    ToolRegistry._whoami_domaines(None, cnx)
    ToolRegistry._WHOAMI_DOMAINES["ts"] -= ToolRegistry._WHOAMI_DOMAINES_TTL_S + 1
    ToolRegistry._whoami_domaines(None, cnx)
    assert cnx.requetes == 2
    _vider_cache()
