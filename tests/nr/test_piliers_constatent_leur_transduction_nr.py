"""NR — le site qui AGIT sur un pilier doit CONSTATER sa transduction.

MESURE DU 2026-09-20 (forge_signal_coupling, primitives existantes) :

    signal                 EMIS     LU  TRANSDUIT
    rerank.wanted             0      1          0     <- lu 36 799 fois, 0 effet
    embed.wanted              0      1          0
    lmstudio.wanted           0      1          0
    docker.wanted             2      1          0
    llama.wanted              1      1          1     <- la seule chaine .wanted fermee

    rerank.wanted -> LECTEUR forge_resource_manager.get_active_intents
                     n = 36 799, derniere lecture il y a 46,8 s

LE DIAGNOSTIC EXACT N EST PAS « personne ne lit ». Le signal est lu massivement
et en continu. Mais son unique lecteur lit pour EPARGNER le service, jamais pour
le RALLUMER : il fixe le ligand et n a pas de domaine de signalisation. C est le
RECEPTEUR LEURRE que `forge_rag_warmup` documente deja pour les hormones (OPG,
ACKR3) -- etat CONSUMER_NO_EFFECT, et surtout pas CONSUMER_DEAD.

Le site qui agit VRAIMENT sur les piliers est `_piliers_on_demand` : c est lui
qui appelle `forge_ensure_service.ensure`. Il ne constatait ni sa lecture ni son
effet. Consequence : meme une fois le keeper degele, `couplage()` continuerait de
rendre `TRANSDUIT 0` et rien ne distinguerait « le keeper est gele » de « le
keeper tourne et ne sert a rien ».

LE PATRON N EST PAS INVENTE ICI. Il est copie de `forge_rag_warmup.warmup_rag`,
eprouve sur TSH/INSULIN depuis le 2026-08-05 : `_observer` au site de la LECTURE,
`_transduire` au site de l EFFET. Sa docstring dit pourquoi les deux sont
necessaires -- « sans la lecture, l absence d effet ne distingue pas "lu sans
agir" de "ce code n a pas tourne", et accuser le second est le faux positif qui
fait desarmer un garde ».

PORTEE DITE : ce NR garde la DECLARATION au bon site. Il ne demarre aucun
service, ne juge pas l etat de la machine, et ne pretend pas que le keeper
tourne. Il verifie qu une abstention n est PAS comptee comme un effet --
`attempt != success`.
"""
from __future__ import annotations

import importlib

import pytest


def _keeper(monkeypatch):
    monkeypatch.setenv("LAFORGE_LLAMA_KEEPER_MONITOR_ONLY", "0")
    monkeypatch.setenv("LAFORGE_LLAMA_KEEPER_PILIERS_ONLY", "0")
    for nom in ("nokido_agent.tools.forge_llama_keeper", "tools.forge_llama_keeper",
                "forge_llama_keeper"):
        try:
            mod = importlib.import_module(nom)
        except Exception:  # noqa: BLE001
            continue
        return importlib.reload(mod)
    pytest.skip("forge_llama_keeper introuvable sous ses trois noms d'import")


def _capte(monkeypatch, mod):
    """Enregistre les declarations de couplage emises par le module."""
    vus = {"observe": [], "transduce": []}
    monkeypatch.setattr(mod, "_observer_signal",
                        lambda s: vus["observe"].append(s), raising=False)
    monkeypatch.setattr(mod, "_transduire_signal",
                        lambda s: vus["transduce"].append(s), raising=False)
    return vus


def _corps(monkeypatch, mod, *, accorde=True, up=False, ensure_ok=True):
    """Corps fictif : intention FRAICHE, pilier ABSENT, RAM basse -> acte attendu."""
    monkeypatch.setattr(mod, "_supervisor_claimed",
                        lambda: {8099: 1} if up else {}, raising=False)
    monkeypatch.setattr(mod, "_intention_voulue", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(mod, "_pilier_accorde", lambda d: accorde, raising=False)
    monkeypatch.setattr(mod, "_conns_port", lambda p: 0, raising=False)
    monkeypatch.setattr(mod, "_pilier_inutile", lambda *a, **k: False, raising=False)
    import sys as _s
    faux = type(_s)("nokido_agent.tools.forge_ensure_service")
    faux.ensure = lambda nom, etat: {"success": ensure_ok}
    monkeypatch.setitem(_s.modules, "nokido_agent.tools.forge_ensure_service", faux)


def test_les_helpers_de_declaration_existent(monkeypatch):
    """Garde l'instrument d'abord : sans eux, les autres tests ne prouvent rien."""
    mod = _keeper(monkeypatch)
    for nom in ("_observer_signal", "_transduire_signal"):
        assert hasattr(mod, nom), (
            f"{nom} absent : le site de l'effet ne peut RIEN constater, et "
            "`couplage()` rendra TRANSDUIT 0 meme quand le keeper agit")


def test_un_acte_REUSSI_sur_un_pilier_constate_sa_transduction(monkeypatch):
    """LE COEUR : c'est la seule preuve qu'une voie transduit vraiment."""
    mod = _keeper(monkeypatch)
    vus = _capte(monkeypatch, mod)
    _corps(monkeypatch, mod, accorde=True, up=False, ensure_ok=True)
    mod._piliers_on_demand(10.0)   # RAM tres basse -> rallumage attendu
    assert "rerank.wanted" in vus["transduce"] or "embed.wanted" in vus["transduce"], (
        "un pilier a ete rallume sans que l'effet soit constate -- le signal "
        f"restera 'LU SANS EFFET' pour toujours (transduits: {vus['transduce']})")


def test_la_LECTURE_est_constatee_meme_sans_acte(monkeypatch):
    """Sans elle, 'lu sans agir' et 'ce code n'a pas tourne' sont indistinguables."""
    mod = _keeper(monkeypatch)
    vus = _capte(monkeypatch, mod)
    # Intention REFUSEE par l'arbitre : le site LIT, mais n'agit pas.
    _corps(monkeypatch, mod, accorde=False, up=False)
    mod._piliers_on_demand(10.0)
    assert vus["observe"], (
        "le site n'a pas constate sa lecture alors qu'il a consulte les drapeaux")


def test_une_ABSTENTION_n_est_PAS_une_transduction(monkeypatch):
    """`attempt != success`, applique a la declaration d'effet.

    Un refus de l'arbitre ne doit jamais passer pour un effet : compter les
    abstentions ferait declarer COUPLE une voie qui n'agit jamais.
    """
    mod = _keeper(monkeypatch)
    vus = _capte(monkeypatch, mod)
    _corps(monkeypatch, mod, accorde=False, up=False)
    mod._piliers_on_demand(10.0)
    assert not vus["transduce"], (
        f"une abstention a ete comptee comme un effet : {vus['transduce']}")


def test_un_ensure_QUI_ECHOUE_n_est_PAS_une_transduction(monkeypatch):
    """Le keeper marque deja `ok=False` comme un besoin NON satisfait ; la
    declaration de couplage doit suivre la meme regle."""
    mod = _keeper(monkeypatch)
    vus = _capte(monkeypatch, mod)
    _corps(monkeypatch, mod, accorde=True, up=False, ensure_ok=False)
    mod._piliers_on_demand(10.0)
    assert not vus["transduce"], (
        f"un ensure() en echec a ete compte comme un effet : {vus['transduce']}")
