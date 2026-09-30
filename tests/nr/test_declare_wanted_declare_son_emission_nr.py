"""NR — le poseur d'intention doit DECLARER ce qu'il emet.

Mesure du 2026-09-20 par `forge_signal_coupling` (job_6178a2110524, rc=0) :

    signal            verdict                em cons troph
    llama.wanted      COUPLE                  1   3   0.50
    rerank.wanted     DECOY_LECTEUR_PASSIF    0   1   0.00
    lmstudio.wanted   DECOY_LECTEUR_PASSIF    0   1   0.00
    docker.wanted     DECOY_LECTEUR_PASSIF    0   1   0.00   DEGENERESCENCE

Or `rerank.wanted` N'EST PAS sans emetteur : le fichier `sandbox/rerank.wanted`
existe, les journaux en portent 326 lignes, et AUCUNE ligne « NON posee ». Le
`em=0` ne mesure donc pas l'emission mais la DECLARATION -- `forge_signal_coupling`
exige un appel explicite a `emit_signal`, precisement parce qu'un grep mentait :
« un grep sur llama.wanted a rendu 14 lectures et 0 ecriture, et c'etait FAUX ».

C'est un DECLARANT MANQUANT, pas un emetteur absent -- la regle du depot :
« quand N chemins produisent un etat et qu'UN SEUL le declare, l'asymetrie est
invisible en lecture de code et visible dans le journal ».

Le raccord tient en un point : `forge_embed_router.declare_wanted`, poseur COMMUN
importe sous l'alias `_dw` par exactement trois modules (forge_mcp_registry,
forge_rag_engine, forge_resource_manager). Sa propre docstring nomme deja le
defaut : « Un lecteur sans declarant ne vaut rien -- c'est l'asymetrie payee sur
llama.wanted : quatre organes lisaient l'intention, un seul reveilleur sur six la
posait. »

CE QUI EST GARDE ICI, et rien de plus : on declare ce qu'on a REELLEMENT ecrit.
Un cooldown, un refus de l'arbitre ou une ecriture refusee ne sont PAS des
emissions -- les declarer gonflerait le compteur et ferait passer pour couple un
signal qui ne sort jamais. `attempt != success`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

er = pytest.importorskip("app.forge_embed_router")


def _les_deux_formes(nom: str):
    """Les DEUX chemins d'import du meme module, resolus a l'appel.

    `declare_wanted` importe `nokido_agent.app.forge_pillar_arbiter` alors qu'un
    test ecrit naturellement `app.forge_pillar_arbiter`. Ce sont DEUX objets
    distincts (`is` -> False) : patcher l'un laisse l'autre intact, et le test
    passe ou echoue pour une raison qui n'a rien a voir avec ce qu'il mesure.
    Defaut paye le 2026-09-10, re-paye ici meme a la premiere ecriture de ce NR.
    """
    mods = []
    for chemin in ("app.%s" % nom, "nokido_agent.app.%s" % nom):
        try:
            __import__(chemin)
            mods.append(sys.modules[chemin])
        except Exception:
            continue
    assert mods, "aucun des deux chemins d'import de %s n'est resolvable" % nom
    return mods


@pytest.fixture()
def emissions(monkeypatch):
    """Capture les declarations et neutralise l'arbitre — sur LES DEUX formes."""
    vues = []
    for sc in _les_deux_formes("forge_signal_coupling"):
        monkeypatch.setattr(sc, "emit_signal",
                            lambda signal, emitter=None: vues.append((signal, emitter)) or True,
                            raising=True)
    # l'arbitre est un organe VIVANT : on ne le laisse pas decider du verdict du test
    for pa in _les_deux_formes("forge_pillar_arbiter"):
        monkeypatch.setattr(pa, "reclamer",
                            lambda flag, motif="": {"accorde": True}, raising=True)
    monkeypatch.setattr(er, "_WANT_TS", {}, raising=False)
    return vues


def test_une_pose_REUSSIE_est_declaree(emissions, monkeypatch, tmp_path):
    """Le cas nominal : l'ecriture aboutit, donc l'emission doit etre constatee."""
    ok = er.declare_wanted("nr_temoin.wanted", cooldown=0.0, motif="nr")
    assert ok is True, "la pose devait reussir (arbitre neutralise, cooldown nul)"
    assert any(s == "nr_temoin.wanted" for s, _ in emissions), (
        "l'intention a ete ECRITE mais jamais DECLAREE : c'est exactement ce qui "
        "fait sortir rerank/lmstudio/docker en DECOY_LECTEUR_PASSIF avec em=0."
    )


def test_un_COOLDOWN_n_est_PAS_une_emission(emissions):
    """`attempt != success` : un appel bloque par le cooldown n'ecrit rien."""
    er.declare_wanted("nr_cd.wanted", cooldown=0.0, motif="nr")
    emissions.clear()
    r = er.declare_wanted("nr_cd.wanted", cooldown=9999.0, motif="nr")
    assert r is False, "le second appel devait etre bloque par le cooldown"
    assert not emissions, (
        "un cooldown a ete declare comme une emission : le compteur gonflerait et "
        "un signal qui ne sort jamais passerait pour COUPLE."
    )


def test_un_REFUS_DE_L_ARBITRE_n_est_PAS_une_emission(emissions, monkeypatch):
    """Le corps peut REFUSER l'intention. Un refus n'est pas une emission."""
    for pa in _les_deux_formes("forge_pillar_arbiter"):
        monkeypatch.setattr(pa, "reclamer",
                            lambda flag, motif="": {"accorde": False, "motif": "nr refus"},
                            raising=True)
    emissions.clear()
    r = er.declare_wanted("nr_refus.wanted", cooldown=0.0, motif="nr")
    assert r is False, "l'arbitre refusait : la pose ne devait pas avoir lieu"
    assert not emissions, "un refus du corps a ete compte comme une emission"


def test_l_instrumentation_ne_CASSE_JAMAIS_la_pose(emissions, monkeypatch):
    """Un capteur qui casse l'emission qu'il observe est pire que le defaut.

    `emit_signal` est deja fail-safe, mais le RACCORD doit l'etre aussi : si le
    module de couplage est absent ou leve, la pose doit aboutir quand meme.
    """
    def _explose(*a, **k):
        raise RuntimeError("capteur casse")

    for sc in _les_deux_formes("forge_signal_coupling"):
        monkeypatch.setattr(sc, "emit_signal", _explose, raising=True)
    r = er.declare_wanted("nr_failsafe.wanted", cooldown=0.0, motif="nr")
    assert r is True, (
        "l'instrumentation a casse la pose : un capteur ne doit jamais empecher "
        "l'acte qu'il mesure."
    )
