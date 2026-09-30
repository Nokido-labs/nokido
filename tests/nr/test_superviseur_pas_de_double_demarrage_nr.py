"""NR -- le superviseur ne demarre jamais un service DEJA en cours (2026-09-24).

Mesure apres la relance de 18:58 : 21 services demarres deux fois, 17 avec les DEUX
instances vivantes (meme parent deno). `auto-reconcile` et la boucle de vagues appelaient
`startService` sur le meme service ; le second spawn ecrasait `state.proc` et orphelinait le
premier process (double execution, purges concurrentes, RAM qui monte).
"""
from __future__ import annotations

from pathlib import Path

SUP = Path(__file__).resolve().parents[2] / "proxy_deno" / "core" / "supervisor.ts"


def _corps(nom: str) -> str:
    """Corps de la fonction jusqu'a la fonction suivante (pas une fenetre fixe : le 1er
    essai a 9 000 caracteres ne voyait pas le spawn, ~15 000 caracteres plus loin)."""
    src = SUP.read_text(encoding="utf-8", errors="replace")
    i = src.index("async function %s(" % nom)
    fin = src.find("\nasync function ", i + 10)
    fin2 = src.find("\nfunction ", i + 10)
    bornes = [b for b in (fin, fin2) if b != -1]
    return src[i:min(bornes) if bornes else len(src)]


def test_start_service_refuse_un_service_deja_en_cours():
    corps = _corps("startService")
    garde = corps.find('state.status === "running" && state.proc')
    spawn = corps.find(".spawn()")
    assert garde != -1, "startService ne verifie plus qu'un service tourne deja"
    assert spawn != -1 and garde < spawn, "le garde doit preceder le spawn"
    assert "deja en cours" in corps[garde:garde + 400], "un saut doit se DIRE au journal"


def test_chaque_ordre_mutant_est_journalise_avec_son_appelant():
    """Question owner 24/09 : QUI endort / reveille un service ? Le jeton est partage ; le
    journal dit le nom DECLARE, QUEL secret (jamais sa valeur) et la trace. Synchrone."""
    src = SUP.read_text(encoding="utf-8", errors="replace")
    corps = _corps("handleCtrl")
    assert "_journalOrdre(req, p, traceId)" in corps
    j = src[src.index("function _journalOrdre("):src.index("async function handleCtrl(")]
    assert "writeTextFileSync" in j and "append: true" in j, "le journal doit etre synchrone"
    assert "agent_declare" in j and "secret_presente" in j
    assert '"supervisor"' in j and '"maitre"' in j and '"aucun"' in j
    ecrit = j[j.index("JSON.stringify({"):j.index("}) +")]
    assert "tok" not in ecrit and "maitre," not in ecrit.replace(" ", ""), \
        "la valeur d'un jeton ne doit jamais etre ECRITE au journal"


def test_le_regulateur_se_nomme_aupres_du_superviseur():
    import sys
    sys.path.insert(0, str(SUP.parents[2]))
    from nokido_agent.app import forge_resource_manager as rm
    assert rm._supervisor_auth_headers().get("LaForge-Agent-Name") == "RESOURCE_MANAGER"


def test_les_deux_lanceurs_concurrents_existent_toujours():
    """Si l'un d'eux disparait, ce NR le dit : le garde reste utile, mais sa raison change."""
    src = SUP.read_text(encoding="utf-8", errors="replace")
    assert "auto-reconcile" in src and "for (const state of waveServices)" in src
