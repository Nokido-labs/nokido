"""NR — un cycle d'entrainement DIT sur quelles donnees il s'est entraine.

MESURE DU 2026-09-20, dans `tools/forge_ami_train_cycle.run_cycle` :

    rows   = _load_traces(TRACES_DB, limit=2000)      # traces REELLES chargees
    n_real = len(rows)
    if n_real < 50:  traces = [rng.standard_normal(...) for _ in range(500)]
    else:            traces = rows                    # traces reelles retenues

    # 3. Train loop (synthetic data)                  <- le commentaire le DIT
    for epoch in range(epochs):
        for _ in range(20):
            s  = np_rng.standard_normal(JEPA_IN_DIM)
            a  = np_rng.standard_normal(JEPA_IN_DIM)
            sn = np_rng.standard_normal(JEPA_IN_DIM)
            loss = jepa.train_step(s, a, sn, lr=0.005)

LA VARIABLE `traces` N'EST JAMAIS UTILISEE DANS LA BOUCLE. Le modele s'entraine
donc TOUJOURS sur du bruit gaussien, que des traces reelles existent ou non. Le
chargement est decoratif.

Et le rapport rend `n_traces_real` A COTE de `jepa_loss_decreased`. Un lecteur --
humain ou agent -- en conclut que les traces ont servi et que le modele a appris.
Une loss qui decroit sur `np.random.standard_normal` ne prouve rien d'autre que
la capacite du reseau a memoriser du bruit.

Contexte qui rend ce defaut couteux : `experience_replay` contient 7 lignes,
toutes du 2026-04-28, et AUCUN ecrivain n'existe dans `app/` ni `tools/`
(sondes croisees sur le nom de table ET sur ses colonnes). Le corps croit donc
s'auto-ameliorer a partir d'une memoire vide, sur des donnees inventees.

CE QUE CE NR N EXIGE PAS : il ne demande PAS de brancher `traces` dans la boucle.
Cabler un entrainement sur des donnees qu'on n'a pas verifiees serait INVENTER un
apprentissage -- exactement le defaut qu'on corrige. Le brief l'interdit
explicitement : « ne ranime pas artificiellement ».

CE QU IL EXIGE : que le rapport soit HONNETE sur sa source. Un faux calme est
pire qu'une absence, parce qu'il empeche de chercher.

PORTEE DITE : ce NR ne juge ni la qualite du modele, ni la loss, ni le fait que
l'entrainement soit synthetique -- ce peut etre un choix legitime de smoke test.
Il juge uniquement ce que le rapport DECLARE.
"""
from __future__ import annotations

import sys
import types

import pytest


def _module():
    for nom in ("nokido_agent.tools.forge_ami_train_cycle",
                "tools.forge_ami_train_cycle", "forge_ami_train_cycle"):
        try:
            mod = __import__(nom, fromlist=["run_cycle"])
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, "run_cycle"):
            return mod
    pytest.skip("forge_ami_train_cycle introuvable sous ses trois noms d'import")


class _FauxJEPA:
    """Modele minimal : une loss qui decroit, comme sur du bruit."""

    def __init__(self, rng_seed=0):
        self._i = 0

    def train_step(self, s, a, sn, lr=0.0):
        self._i += 1
        return 1.0 / self._i          # decroit toujours

    def save(self, path):
        pass


class _FauxNMLP:
    def __init__(self, rng_seed=0):
        pass


def _faux_world_model(monkeypatch, n_traces: int):
    """Installe un `forge_world_model` factice avec N traces reelles."""
    m = types.ModuleType("nokido_agent.app.forge_world_model")
    m.JEPA = _FauxJEPA
    m.NMLP = _FauxNMLP
    m.JEPA_IN_DIM = 8
    m.OUTPUT_DIM = 8
    m.TRACES_DB = "::memoire::"
    import numpy as _np
    m._load_traces = lambda db, limit=2000: [
        (_np.zeros(8, dtype="float32"), "action", _np.ones(8, dtype="float32"))
        for _ in range(n_traces)
    ]
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_world_model", m)
    return m


def test_le_rapport_DIT_sur_quelles_donnees_il_s_est_entraine(monkeypatch):
    """LE COEUR DU CONTRAT."""
    _faux_world_model(monkeypatch, n_traces=0)
    mod = _module()
    r = mod.run_cycle(epochs=1, batch_size=4, persist=False)
    assert "error" not in r, f"le cycle a echoue : {r}"
    assert "entraine_sur" in r, (
        "le rapport rend `n_traces_real` et `jepa_loss_decreased` sans jamais "
        "dire sur QUOI l'entrainement a porte -- un lecteur en conclut que les "
        "traces ont servi")


def test_sans_trace_reelle_la_source_est_declaree_SYNTHETIQUE(monkeypatch):
    _faux_world_model(monkeypatch, n_traces=0)
    mod = _module()
    r = mod.run_cycle(epochs=1, batch_size=4, persist=False)
    assert r.get("n_traces_real") == 0
    assert "synth" in str(r.get("entraine_sur", "")).lower(), (
        f"0 trace reelle et la source n'est pas dite synthetique : {r.get('entraine_sur')!r}")


def test_AVEC_des_traces_reelles_la_source_reste_HONNETE(monkeypatch):
    """Le point delicat : la boucle n'utilise PAS `traces`, meme quand elles
    existent. Le rapport ne doit donc PAS se declarer entraine sur du reel."""
    _faux_world_model(monkeypatch, n_traces=500)
    mod = _module()
    r = mod.run_cycle(epochs=1, batch_size=4, persist=False)
    assert r.get("n_traces_real") == 500
    assert "synth" in str(r.get("entraine_sur", "")).lower(), (
        "500 traces reelles sont chargees mais la boucle s'entraine sur du bruit ; "
        f"le rapport annonce pourtant : {r.get('entraine_sur')!r}")


def test_la_baisse_de_loss_n_est_PAS_presentee_comme_une_preuve(monkeypatch):
    """Une loss qui decroit sur du bruit ne prouve aucun apprentissage.

    Le champ doit exister -- il est utile en smoke test -- mais le rapport doit
    porter de quoi ne PAS le lire comme un progres du corps.
    """
    _faux_world_model(monkeypatch, n_traces=0)
    mod = _module()
    r = mod.run_cycle(epochs=1, batch_size=4, persist=False)
    if r.get("jepa_loss_decreased"):
        assert r.get("apprentissage_prouve") is False, (
            "la loss decroit sur des donnees synthetiques et rien dans le rapport "
            "n'empeche de le lire comme un apprentissage reel")
