"""NR -- un pilier reclame mais non demarre se DIT, et le Knowledge Pack refuse AVANT de vectoriser (owner 1/11).

MESURE du 1/11 (promotion v0.20.15) : `embed.wanted` frais, RAM 76 % > seuil de reveil du keeper (70 %) ; la
contention « NokidoLlamaEmbed RECLAME mais NON DEMARRE » ne vivait que dans l'etat du keeper, et le pack a enchaine
1 280 echecs (lot 40/1400) avant son refus final. Deux reparations : contention au journal (une fois / 10 min), et
sonde de l'embedder avant le premier lot.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_knowledge_pack_export as K  # noqa: E402
import forge_llama_keeper as LK  # noqa: E402


def _horloge():
    t = [0.0]
    return t, (lambda: t[0]), (lambda s: t.__setitem__(0, t[0] + s))


def test_embedder_pret_des_que_la_sonde_vectorise():
    t, horloge, dormir = _horloge()
    pret, motif = K.embedder_pret(sonde=lambda: True, horloge=horloge, dormir=dormir)
    assert pret and "pret" in motif and t[0] == 0.0


def test_embedder_absent_refuse_vite_et_dit_pourquoi():
    t, horloge, dormir = _horloge()
    pret, motif = K.embedder_pret(sonde=lambda: False, attente_s=60, pas_s=15, horloge=horloge, dormir=dormir)
    assert not pret and t[0] == 60.0
    assert "reload_ok" in motif and "NokidoLlamaKeeper.log" in motif and "5 essai(s)" in motif


def test_une_sonde_qui_casse_vaut_pas_pret():
    def casse():
        raise ConnectionError("refuse")
    t, horloge, dormir = _horloge()
    assert K.embedder_pret(sonde=casse, attente_s=0, horloge=horloge, dormir=dormir)[0] is False


def test_le_pack_refuse_avant_le_premier_lot(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "embedder_pret", lambda: (False, "embedder :8099 injoignable"))
    monkeypatch.setattr(K, "Dist", lambda d: pytest.fail("aucun lot ne doit partir"))
    with pytest.raises(SystemExit, match="AVANT VECTORISATION"):
        K.export_pack_natif(dist=tmp_path, version="0.0.0")


def test_une_doublure_d_embed_ne_sonde_pas(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "embedder_pret", lambda: pytest.fail("pas de sonde avec embed_fn"))
    monkeypatch.setattr(K, "Dist", lambda d: (_ for _ in ()).throw(RuntimeError("Dist atteint")))
    with pytest.raises(RuntimeError, match="Dist atteint"):
        K.export_pack_natif(dist=tmp_path, version="0.0.0", embed_fn=lambda textes: [None] * len(textes))


def test_la_contention_va_au_journal_une_fois_par_fenetre(monkeypatch, capsys):
    monkeypatch.setattr(LK, "_CONTENTION_DITE", {})
    msg = "NokidoLlamaEmbed RECLAME mais NON DEMARRE : ram 76% > 70%"
    assert LK._dire_contention("NokidoLlamaEmbed", msg, maintenant=1000.0) is True
    assert LK._dire_contention("NokidoLlamaEmbed", msg, maintenant=1000.0 + LK.CONTENTION_LOG_S - 1) is False
    assert LK._dire_contention("NokidoLlamaEmbed", msg, maintenant=1000.0 + LK.CONTENTION_LOG_S) is True
    sortie = capsys.readouterr().out
    assert sortie.count("RECLAME mais NON DEMARRE") == 2


def test_la_branche_de_contention_appelle_le_journal():
    # Chemin REEL : la contention nommee dans `_bloc` passe aussi par `_dire_contention`.
    src = (RACINE / "tools" / "forge_llama_keeper.py").read_text(encoding="utf-8")
    bloc = src[src.find("def _piliers_on_demand"):src.find("if not actes:", src.find("def _piliers_on_demand"))]
    assert "_dire_contention(nom, _msg)" in bloc
