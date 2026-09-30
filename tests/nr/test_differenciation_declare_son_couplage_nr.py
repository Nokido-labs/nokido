"""NR — la differenciation d'une cellule souche DECLARE ce qu'elle lit et ce qu'elle fait.

MESURE DU 2026-09-20 (forge_signal_coupling, primitives existantes) :

    TSH_VECTORIZATION       EMIS 1 (n=4 181,  age 885 s)   LU 0   TRANSDUIT 0
    INSULIN_VECTORIZATION   EMIS 1 (n=33 273, age  66 s)   LU 1   TRANSDUIT 1

    valeurs lues :  TSH = 0.843   INSULIN = 0.833   (seuil du role : 0.1)

Le LU=1 d'INSULIN est un PIEGE : son unique lecture date de 4 544 211 s, soit
52,6 JOURS, et `forge_signal_coupling` lui attribue deja `trophisme = 0.0`.
Ce n'est donc pas une synapse fermee -- c'est une synapse qui a tire UNE FOIS.
Son lecteur `forge_rag_warmup.warmup_rag` n'est plus appele : le lien a ete
retire de `_action_rag_warmer` le 2026-07-05, et le motif inscrit sur place est
JUSTE (« il figeait le tick ~90s ET n'embarquait rien »).

Le vrai recepteur de TSH est aujourd'hui la DIFFERENCIATION elle-meme :

    perceive_environment()  ->  _read_hormone(role.trigger_hormone)   LECTURE
    differentiate(role)     ->  role.action()                         EFFET

Ces deux sites ne declarent rien. D'ou `LU 0` sur une hormone a 0.843 avec un
seuil a 0.1 : le corps emet 4 181 fois, quelqu'un lit peut-etre, et personne ne
peut le savoir. Etat exact : ni CONSUMER_ABSENT ni CONSUMER_DEAD, mais
LECTURE NON DECLAREE -- et c'est precisement ce qu'un instrument de couplage
existe pour distinguer.

CE NR EST GENERIQUE PAR CONSTRUCTION : le catalogue porte quatre hormones
(TSH_VECTORIZATION, LEPTIN_MAILBOX_FULL, DOPAMINE_SUCCESS, CORTISOL_QUOTA_CLOUD)
et un seul point de cablage les couvre toutes. C'est le patron reproductible,
pas un cas particulier de plus.

PORTEE DITE : ce NR ne demarre aucun worker, ne juge pas si le daemon tourne, et
ne touche pas aux seuils. Il verifie que LIRE et AGIR laissent une trace -- une
propriete du code.

⚠️ DIVERGENCE CONSTATEE, non corrigee ici : la docstring du module annonce
« TSH > 0.4 » alors que ROLE_CATALOG declare `trigger_threshold=0.1`. Nommee
pour ne pas se perdre.
"""
from __future__ import annotations

import pytest


def _module():
    for nom in ("nokido_agent.app.forge_pluripotent_workers",
                "app.forge_pluripotent_workers", "forge_pluripotent_workers"):
        try:
            mod = __import__(nom, fromlist=["PluripotentWorker"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "PluripotentWorker"):
            return mod
    pytest.skip("forge_pluripotent_workers introuvable sous ses trois noms d'import")


def _capte(monkeypatch, mod):
    vus = {"observe": [], "transduce": []}
    monkeypatch.setattr(mod, "_observer_signal",
                        lambda s: vus["observe"].append(s), raising=False)
    monkeypatch.setattr(mod, "_transduire_signal",
                        lambda s: vus["transduce"].append(s), raising=False)
    return vus


def test_les_helpers_de_declaration_existent():
    """Garde l'instrument d'abord : sans eux, les autres tests ne prouvent rien."""
    mod = _module()
    for nom in ("_observer_signal", "_transduire_signal"):
        assert hasattr(mod, nom), (
            f"{nom} absent : la differenciation lit des hormones et agit sans "
            "laisser aucune trace, d'ou `LU 0` sur une hormone a 0.843")


def test_la_LECTURE_des_hormones_est_declaree(monkeypatch):
    """`perceive_environment` lit CHAQUE hormone du catalogue : elle doit le dire.

    On declare la lecture pour TOUTES les hormones consultees, pas seulement
    pour celle qui gagne : une hormone lue et ecartee a bien ete LUE.
    """
    mod = _module()
    vus = _capte(monkeypatch, mod)
    monkeypatch.setattr(mod, "_read_hormone", lambda nom: 0.0, raising=False)

    w = mod.PluripotentWorker(name="nr_stem")
    assert w.perceive_environment() is None       # aucun seuil franchi
    attendues = {r.trigger_hormone for r in mod.ROLE_CATALOG}
    assert set(vus["observe"]) >= attendues, (
        f"hormones lues mais NON declarees : {attendues - set(vus['observe'])}")


def test_une_differenciation_REUSSIE_constate_sa_transduction(monkeypatch):
    """LE COEUR : la seule preuve qu'une hormone a produit un effet."""
    mod = _module()
    vus = _capte(monkeypatch, mod)
    cible = mod.ROLE_CATALOG[0]
    monkeypatch.setattr(mod, "_read_hormone",
                        lambda nom: 0.9 if nom == cible.trigger_hormone else 0.0,
                        raising=False)
    monkeypatch.setattr(cible, "action", lambda: {"role": cible.name, "ok": True},
                        raising=False)

    w = mod.PluripotentWorker(name="nr_stem")
    w.cycle()
    assert cible.trigger_hormone in vus["transduce"], (
        f"la cellule s'est differenciee en {cible.name} et a agi sans constater "
        f"la transduction (transduits: {vus['transduce']})")


def test_une_action_EN_ECHEC_n_est_PAS_une_transduction(monkeypatch):
    """`attempt != success`. Une action qui echoue n'a produit aucun effet."""
    mod = _module()
    vus = _capte(monkeypatch, mod)
    cible = mod.ROLE_CATALOG[0]
    monkeypatch.setattr(mod, "_read_hormone",
                        lambda nom: 0.9 if nom == cible.trigger_hormone else 0.0,
                        raising=False)
    monkeypatch.setattr(cible, "action",
                        lambda: {"role": cible.name, "ok": False, "err": "NR"},
                        raising=False)

    w = mod.PluripotentWorker(name="nr_stem")
    w.cycle()
    assert not vus["transduce"], (
        f"une action en echec a ete comptee comme un effet : {vus['transduce']}")


def test_G0_idle_ne_transduit_RIEN(monkeypatch):
    """Rester en G0 est une abstention, pas un effet."""
    mod = _module()
    vus = _capte(monkeypatch, mod)
    monkeypatch.setattr(mod, "_read_hormone", lambda nom: 0.0, raising=False)

    w = mod.PluripotentWorker(name="nr_stem")
    out = w.cycle()
    assert out.get("role") == "G0_idle"
    assert not vus["transduce"], (
        f"G0_idle a declare un effet : {vus['transduce']}")


def test_l_instrumentation_ne_CASSE_JAMAIS_la_differenciation(monkeypatch):
    """Un capteur de couplage ne doit jamais casser la regulation qu'il observe."""
    mod = _module()
    monkeypatch.setattr(mod, "_observer_signal",
                        lambda s: (_ for _ in ()).throw(RuntimeError("NR boom")),
                        raising=False)
    monkeypatch.setattr(mod, "_transduire_signal",
                        lambda s: (_ for _ in ()).throw(RuntimeError("NR boom")),
                        raising=False)
    monkeypatch.setattr(mod, "_read_hormone", lambda nom: 0.0, raising=False)

    w = mod.PluripotentWorker(name="nr_stem")
    out = w.cycle()          # ne doit PAS lever
    assert out.get("role") == "G0_idle"
