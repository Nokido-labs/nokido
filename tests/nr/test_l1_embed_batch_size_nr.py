"""NR — reglage L1 `embed.batch_size` : consommateur REEL et mesure LOCALE stricte (debat RSI 15/10).

Debat M2M (AGY, Codex, Claude), decision owner Q3. Defauts payes dans le debat lui-meme :
  - Codex, tour 2 : `embed_batch` imposait `batch_size=32` en dur -> la valeur L1 n'aurait
    jamais atteint ce chemin ;
  - AGY, tour 2 : un float ou None dans `range(...)` paralyserait le RAG ; une mesure qui
    rendrait la PERTE (plus haut = pire) ferait CONSERVER un reglage destructeur ; :8099 arrete
    + repli cloud = mesure qui fuit vers un backend payant.
Aucun appel reseau ici : backends, lecteur L1 et appel :8099 sont simules.
"""
import sys
import types

import threading

import pytest

from nokido_agent.app import forge_embed_router as er


def _l1(monkeypatch, valeur=None, leve=False):
    mod = types.ModuleType("nokido_agent.app.forge_proposal_applier")

    def valeur_l1(nom, defaut=None):
        if leve:
            raise RuntimeError("magasin illisible")
        return defaut if valeur is None else valeur

    mod.valeur_l1 = valeur_l1
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_proposal_applier", mod)


@pytest.fixture
def lots(monkeypatch):
    tailles = []

    def essais(batch):
        return [("llama8099", lambda b=batch: (tailles.append(len(b)) or [[1.0]] * len(b)))]

    monkeypatch.setattr(er, "_essais_batch", essais)
    monkeypatch.setattr(er, "_politique_embed", lambda: None)
    monkeypatch.setattr(er, "_essais_selon_politique", lambda e, a: e)
    return tailles


def test_sans_reglage_le_lot_reste_32(monkeypatch):
    _l1(monkeypatch)
    assert er._batch_size_l1() == 32


def test_le_reglage_l1_atteint_le_chemin_reel(monkeypatch, lots):
    _l1(monkeypatch, valeur=40)
    out = er.embed_batch_fast(["t"] * 100)
    assert len(out) == 100 and sorted(lots) == [20, 40, 40]


def test_un_appelant_explicite_garde_sa_valeur(monkeypatch, lots):
    _l1(monkeypatch, valeur=40)
    er.embed_batch_fast(["t"] * 30, batch_size=10)
    assert lots == [10, 10, 10]


@pytest.mark.parametrize("valeur", [40.0, "40", True, 0, 5000])
def test_une_valeur_l1_invalide_rend_32(monkeypatch, valeur):
    _l1(monkeypatch, valeur=valeur)
    assert er._batch_size_l1() == 32


def test_un_lecteur_illisible_rend_32(monkeypatch):
    _l1(monkeypatch, leve=True)
    assert er._batch_size_l1() == 32


def test_embed_batch_n_impose_plus_32(monkeypatch):
    vus = {}
    monkeypatch.setattr(er, "_role_embed_local_autorise", lambda: False)
    monkeypatch.setattr(er, "embed_batch_fast", lambda texts, **kw: vus.update(kw) or [[1.0]] * len(texts))
    er.embed_batch(["a", "b"])
    assert vus.get("batch_size") is None


def test_la_mesure_est_plus_haut_mieux(monkeypatch):
    # Un lot trop gros echoue : la mesure doit le voir comme une BAISSE de taux_succes.
    def appel(lot):
        return None if len(lot) > 48 else [[1.0]] * len(lot)

    _l1(monkeypatch, valeur=64)
    gros = er.mesurer_capacite_batch(repetitions=2, appel=appel)
    _l1(monkeypatch, valeur=32)
    sain = er.mesurer_capacite_batch(repetitions=2, appel=appel)
    assert gros["taux_succes"] == 0.0 and sain["taux_succes"] == 1.0
    assert sain["textes_par_seconde"] > 0


def test_mesure_indisponible_si_le_local_est_interdit(monkeypatch):
    monkeypatch.setattr(er, "_role_embed_local_autorise", lambda: False)
    assert er.mesurer_capacite_batch() == {}


def test_mesure_indisponible_si_8099_injoignable_sans_repli_cloud(monkeypatch):
    def injoignable(lot, timeout=60.0):
        raise ConnectionError(":8099 arrete")

    monkeypatch.setattr(er, "_role_embed_local_autorise", lambda: True)
    monkeypatch.setattr(er, "_llama8099_call", injoignable)
    monkeypatch.setattr(er, "embed", lambda *a, **k: pytest.fail("repli cloud texte par texte appele"))
    assert er.mesurer_capacite_batch() == {}


def test_le_corpus_de_mesure_est_fixe():
    assert len(er._CORPUS_MESURE_L1) == 64 and len(set(er._CORPUS_MESURE_L1)) == 64


def test_la_mesure_se_parametre_par_workers_et_taille_sans_changer_le_defaut(monkeypatch):
    """Debat tour 3 (Q1) : mesurer `embed.max_workers` AVANT de le declarer. Codex : la mesure
    FIXAIT 4 fils ; AGY : il faut au moins autant de lots que de fils (lots de 16)."""
    tailles, pic, en_cours, verrou = [], [0], [0], threading.Lock()

    def appel(lot):
        with verrou:
            en_cours[0] += 1
            pic[0] = max(pic[0], en_cours[0])
            tailles.append(len(lot))
        import time as _t
        _t.sleep(0.01)
        with verrou:
            en_cours[0] -= 1
        return [[1.0]] * len(lot)

    _l1(monkeypatch, valeur=32)
    r = er.mesurer_capacite_batch(repetitions=1, appel=appel, max_workers=1, taille=16)
    assert r["taux_succes"] == 1.0 and set(tailles) == {16} and len(tailles) == 4 and pic[0] == 1
    tailles.clear()
    pic[0] = 0
    er.mesurer_capacite_batch(repetitions=1, appel=appel)          # defaut : taille L1, 4 fils
    assert set(tailles) == {32} and len(tailles) == 2 and pic[0] <= 4
