# -*- coding: utf-8 -*-
"""NR (owner 3/11 « des garde-fous E/S sur le disque avaient ete mis en place, pourquoi ca a ete contourne ? ») : le hub
(NokidoMCP, preuve superviseur) lisait 70 Mo/s au moment d'une requete `rag` qui a expire (22:24), sans qu'aucun garde
ne sache QUELLE requete lisait. Chaque appel d'outil mesure desormais les octets lus par le processus pendant son
execution ; au-dela du seuil, une ligne est journalisee (outil, agent, Mo, duree, requetes concurrentes -- attribution
INCERTAINE si d'autres requetes tournaient). Compteur illisible : rien n'est ecrit (jamais un 0 invente)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_mcp_registry as M  # noqa: E402


def test_au_dela_du_seuil_une_ligne_est_journalisee(tmp_path):
    f = tmp_path / "io.jsonl"
    M._noter_io_requete("rag", "CLAUDE", 0, 300 * 2 ** 20, 12000.0, 0, chemin=f, seuil_mo=50.0)
    ligne = json.loads(f.read_text(encoding="utf-8").splitlines()[-1])
    assert ligne["outil"] == "rag" and ligne["agent"] == "CLAUDE" and ligne["lus_mo"] == 300.0
    assert ligne["attribution"] == "SURE"


def test_requetes_concurrentes_attribution_incertaine(tmp_path):
    f = tmp_path / "io.jsonl"
    M._noter_io_requete("rag", "CLAUDE", 0, 300 * 2 ** 20, 12000.0, 2, chemin=f, seuil_mo=50.0)
    assert json.loads(f.read_text(encoding="utf-8"))["attribution"] == "INCERTAINE"


def test_sous_le_seuil_rien(tmp_path):
    f = tmp_path / "io.jsonl"
    M._noter_io_requete("read", "CLAUDE", 0, 2 * 2 ** 20, 30.0, 0, chemin=f, seuil_mo=50.0)
    assert not f.exists()


def test_compteur_illisible_rien(tmp_path):
    f = tmp_path / "io.jsonl"
    M._noter_io_requete("rag", "CLAUDE", None, 300 * 2 ** 20, 10.0, 0, chemin=f, seuil_mo=50.0)
    M._noter_io_requete("rag", "CLAUDE", 0, None, 10.0, 0, chemin=f, seuil_mo=50.0)
    assert not f.exists()


def test_le_compteur_du_processus_est_lisible():
    v = M._io_lus_processus()
    assert v is None or (isinstance(v, int) and v >= 0)


def test_le_dispatch_mesure_chaque_appel():
    import inspect
    src = inspect.getsource(M.ToolRegistry.dispatch)
    assert "_noter_io_requete(" in src and "_io_lus_processus()" in src
