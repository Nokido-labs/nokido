# -*- coding: utf-8 -*-
"""Non-regression — le hub doit dire POURQUOI il s'arrete.

Signalement owner du 2026-08-26 : « hub instable ». Il est effectivement tombe deux fois
dans la journee. Le diagnostic a bute sur un mur : `logs/hub.log` n'est plus alimente
depuis MAI, et `logs/hub_boot.log` trace le demarrage phase par phase jusqu'a
« pre-serve — uvicorn bind :8766 »... puis PLUS RIEN. 9 945 lignes, uniquement des boots.

Le hub disait sa naissance et jamais sa mort. On lisait « aucune erreur dans le log » et
on en concluait « il ne crashe pas, il est arrete » — alors qu'on ne pouvait rien savoir
du tout. C'est le pire etat d'un capteur : muet, mais lu comme rassurant.

PORTEE ASSUMEE, et c'est le point le plus important de ce fichier : un `taskkill /F` ne
laissera RIEN, aucun code utilisateur ne s'execute. Le SILENCE de la sonde apres un arret
devient donc lui-meme une information — mort brutale ou eviction par un tiers — au lieu
d'etre indistinguable de « pas de probleme ». On ne pretend pas tout couvrir, on rend les
cas distinguables.

Hermetique : AST du module, aucun hub demarre.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HUB = ROOT / "tools" / "nokido_hub.py"


@pytest.fixture(scope="module")
def source():
    if not HUB.exists():
        pytest.skip("tools/nokido_hub.py absent de cette copie")
    return HUB.read_text(encoding="utf-8", errors="replace")


def _fonctions(source: str) -> set:
    return {n.name for n in ast.walk(ast.parse(source))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_le_module_reste_valide(source):
    ast.parse(source)          # un hub qui ne parse pas ne demarre pas du tout


def test_une_sonde_de_fin_existe(source):
    assert "_fin_probe" in _fonctions(source), (
        "le hub trace son boot mais rien de sa fin : sa chute serait muette")


def test_la_sortie_normale_est_tracee(source):
    assert "atexit.register" in source.replace("_atexit", "atexit"), (
        "aucun atexit : une sortie propre ne laisserait pas de trace")


@pytest.mark.parametrize("sig", ["SIGTERM", "SIGINT", "SIGBREAK"])
def test_les_signaux_sont_traces(source, sig):
    """Un arret demande de l'exterieur est le cas le PLUS frequent, et il etait muet."""
    assert sig in source, "signal %s non gere" % sig


def test_les_exceptions_fatales_sont_tracees(source):
    assert "sys.excepthook" in source
    assert "_ancien_hook" in source, (
        "le hook precedent doit etre chaine, sinon on masque le comportement d'origine")


def test_les_threads_morts_sont_signales(source):
    """Un thread non-daemon qui meurt peut emporter le process a la sortie."""
    assert "threading.excepthook" in source


def test_la_fin_est_idempotente(source):
    """Un signal SUIVI de l'atexit ne doit pas ecrire deux verdicts contradictoires :
    le premier, le plus proche de la cause, gagne."""
    assert "_FIN_ECRITE" in source


def test_la_fin_ecrit_dans_le_journal_du_boot(source):
    """Meme fichier = ordre chronologique lisible : on voit le demarrage PUIS la fin.
    Deux fichiers separes obligeraient a les recoller a la main."""
    i = source.find("def _fin_probe")
    assert i > 0
    corps = source[i:i + 900]
    assert "_boot_probe(" in corps


def test_la_portee_limitee_est_ecrite(source):
    """Un garde qui laisse croire qu'il couvre tout est pire qu'un garde absent :
    la limite doit etre ECRITE la ou on la lira.

    Elle a ete CORRIGEE par la mesure : ma premiere note affirmait que SIGTERM serait
    capture. Deux redemarrages plus tard, zero ligne de fin — le superviseur appelle
    `proc.kill("SIGTERM")` cote Deno, et Windows n'ayant pas de SIGTERM, Deno le
    traduit en `TerminateProcess`. Le chemin d'arret le PLUS FREQUENT n'est donc pas
    couvert, et le code doit le dire."""
    i = source.find("PORTEE REELLE")
    assert i > 0, "la portee reelle n'est pas documentee"
    entete = source[i:i + 1500]
    assert "TerminateProcess" in entete, (
        "la cause mesuree (Windows n'a pas de SIGTERM) doit etre nommee")
    assert "battement" in entete.lower(), (
        "la limite doit renvoyer vers ce qui, LUI, survit a un arret brutal")


# ------------------------------------------------- le battement periodique

def test_un_battement_periodique_existe(source):
    """LE remede reel : la seule trace qui survive a une destruction du processus."""
    assert "_battement_de_service" in _fonctions(source), (
        "sans pouls periodique, un arret brutal ne laisse RIEN — et c'est le cas le "
        "plus frequent")


def test_le_battement_est_une_tache_asyncio(source):
    """En thread, il battrait au-dessus d'une boucle gelee : faux temoin de sante.
    En tache asyncio, il gele AVEC la boucle — ce qui est le signal recherche."""
    arbre = ast.parse(source)
    trouve = [n for n in ast.walk(arbre)
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_battement_de_service"]
    assert trouve, "_battement_de_service doit etre une coroutine, pas un thread"
    assert "create_task(_battement_de_service" in source, (
        "le battement doit etre lance dans la boucle d'evenements")


def test_le_battement_utilise_la_primitive_partagee(source):
    """39 modules avaient reimplemente ce geste : on cable sur UN seul chemin."""
    i = source.find("async def _battement_de_service")
    corps = source[i:i + 2600]
    assert "beat_daemon" in corps, (
        "utiliser forge_heartbeat.beat_daemon, pas une enieme reimplementation")


def test_le_battement_ne_tue_pas_son_porteur(source):
    """« Un pouls qui casse son porteur serait pire que pas de pouls. »"""
    i = source.find("async def _battement_de_service")
    corps = source[i:i + 2600]
    assert "except Exception" in corps and "CancelledError" in corps, (
        "le battement doit absorber ses erreurs et relayer l'annulation")


def test_les_signaux_nont_pas_casse_le_boot(source):
    """`signal.signal` leve hors du thread principal : sans garde, un hub importe
    depuis un thread ne demarrerait plus du tout."""
    i = source.find("for _nom_sig")
    assert i > 0
    bloc = source[i:i + 400]
    assert "except" in bloc and ("ValueError" in bloc or "OSError" in bloc)
