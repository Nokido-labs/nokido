"""NR — un drapeau CORROMPU doit pouvoir etre repare, meme sous cooldown.

MESURE RUNTIME DU 2026-09-20 (chemin reel, pas un test) :

    sandbox/rerank.wanted   0 octet, mtime 69,6 min
    _intention_voulue('rerank.wanted')  -> False
    forge_signal_coupling               -> EMIS 0  LU 2  TRANSDUIT 0

    declare_wanted('rerank.wanted', cooldown=0.0)  -> True
    sandbox/rerank.wanted   18 octets  b'1789931884.8181345'
    _intention_voulue('rerank.wanted')  -> True
    forge_signal_coupling               -> EMIS 1  LU 2  TRANSDUIT 0

Le producteur repare donc le drapeau -- MAIS seulement parce que le cooldown a
ete force a zero pour la mesure. En exploitation il vaut 300 s, et le test du
cooldown se fait AVANT toute lecture du fichier :

    if now - _WANT_TS.get(flag, 0.0) < cooldown:
        return False

Consequence : un drapeau ecrit VIDE (ou tronque) reste vide pendant toute la
duree du cooldown, `_intention_voulue` rend False, et le corps se croit sans
demande alors qu'un organe vient d'en exprimer une. C'est le meme motif que
« attempt != success », applique cette fois a la REPARATION : le cooldown
protege l'ECRITURE sans jamais regarder le CONTENU.

Le cooldown reste NECESSAIRE -- il evite de repiler une intention identique a
chaque appel. Ce NR ne le supprime pas : il exige qu'un drapeau ILLISIBLE soit
traite comme une ABSENCE d'intention, donc reecrit, et non comme une intention
deja posee.

PORTEE DITE : ce NR garde la reparation du drapeau. Il ne juge ni le keeper, ni
la RAM, ni l'etat de :8100 -- ce serait des sondes sur la MACHINE. La contention
ressource mesuree le meme jour (`ram 77% > 55%`) est un resultat physiologique
VALIDE et n'a rien a faire ici.
"""
from __future__ import annotations

import pathlib

import pytest

FLAG = "nr_drapeau_corrompu.wanted"


def _module():
    for nom in ("nokido_agent.app.forge_embed_router", "app.forge_embed_router",
                "forge_embed_router"):
        try:
            mod = __import__(nom, fromlist=["declare_wanted"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "declare_wanted"):
            return mod
    pytest.skip("forge_embed_router introuvable sous ses trois noms d'import")


@pytest.fixture(autouse=True)
def cible(monkeypatch):
    mod = _module()
    for nom in ("nokido_agent.app.forge_pillar_arbiter", "app.forge_pillar_arbiter",
                "forge_pillar_arbiter"):
        try:
            arb = __import__(nom, fromlist=["reclamer"])
        except Exception:  # noqa: BLE001
            continue
        monkeypatch.setattr(arb, "reclamer",
                            lambda flag, motif="": {"accorde": True}, raising=False)
    monkeypatch.setattr(mod, "_WANT_TS", {}, raising=False)
    chemin = pathlib.Path(mod.__file__).resolve().parent.parent / "sandbox" / FLAG
    yield chemin
    try:
        chemin.unlink()
    except OSError:
        pass


def test_un_drapeau_VIDE_est_reecrit_malgre_le_cooldown(cible):
    """LE COEUR DU CONTRAT.

    Scenario mesure sur rerank.wanted : une pose reussit, puis le fichier se
    retrouve vide (ecriture concurrente, troncature, producteur d'avant le
    correctif). Sous cooldown, le producteur refusait de le reecrire et le corps
    restait aveugle a une demande pourtant exprimee.
    """
    mod = _module()
    assert mod.declare_wanted(FLAG, cooldown=0.0, motif="NR pose initiale") is True
    assert cible.read_bytes(), "pre-condition cassee : la pose initiale a rendu du vide"

    cible.write_text("", encoding="utf-8")          # corruption, cooldown TOUJOURS actif
    assert not cible.read_bytes().strip()

    repose = mod.declare_wanted(FLAG, cooldown=9999.0, motif="NR reparation")
    assert repose is True, (
        "le cooldown a bloque la reparation d'un drapeau VIDE -- le corps reste "
        "aveugle a une demande exprimee pendant toute la duree du cooldown")
    assert cible.read_bytes().strip(), "le drapeau est toujours vide apres reparation"


def test_un_drapeau_VALIDE_reste_protege_par_le_cooldown(cible):
    """Le symetrique : on repare l'illisible, on ne desarme pas le cooldown.

    Sans ce test, supprimer purement le cooldown ferait passer le premier.
    """
    mod = _module()
    assert mod.declare_wanted(FLAG, cooldown=0.0, motif="NR premiere") is True
    avant = cible.read_bytes()
    assert mod.declare_wanted(FLAG, cooldown=9999.0, motif="NR seconde") is False, (
        "le cooldown ne protege plus une intention DEJA valide -- le correctif "
        "a desarme le frein au lieu de traiter le cas illisible")
    assert cible.read_bytes() == avant, "le drapeau valide a ete reecrit inutilement"


def test_un_drapeau_ABSENT_est_pose_malgre_le_cooldown(cible):
    """Absence et corruption appellent la meme reponse : il n'y a pas d'intention.

    `UNKNOWN != NO` -- mais ici les deux etats disent la meme chose au lecteur
    (`_intention_voulue` rend False), donc le producteur doit reagir pareil.
    """
    mod = _module()
    assert mod.declare_wanted(FLAG, cooldown=0.0, motif="NR pose") is True
    cible.unlink()
    assert mod.declare_wanted(FLAG, cooldown=9999.0, motif="NR re-pose") is True, (
        "un drapeau EFFACE n'a pas ete repose : le cooldown raisonne sur sa "
        "memoire de processus et jamais sur l'etat reel du disque")
    assert cible.exists() and cible.read_bytes().strip()
