"""NR synthese du swarm pointeur : membre cloud, garde anti-repetition, post_flight agrege (jamais deduit)."""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import forge_cli_swarm as sw  # noqa: E402


def _membre(nom, ok=True, outils=()):
    return {"provider": nom, "ok": ok, "text": f"rep {nom}", "tours": 2, "outils_appeles": list(outils),
            "chars_envoyes": 1, "ms": 1, "post_flight": {"vus": 0}}


@pytest.fixture(autouse=True)
def _membres_factices_forts(monkeypatch):
    """ARBITRAGE 29/10 : les membres factices sont declares forts (regle REDACTEURS_FORTS) ; assertions inchangees."""
    monkeypatch.setattr(sw, "REDACTEURS_FORTS", ("a", "b", "c", "x"))
    monkeypatch.setattr(sw, "SYNTHESE_MIN_CAR", 0)  # 29/10 : syntheses factices courtes ; substance testee a part


@pytest.fixture
def monde(monkeypatch, tmp_path):
    monkeypatch.setattr(sw, "_membres_pointeur", lambda membres, sonde=None: (list(membres), []))
    monkeypatch.setattr(sw, "SORTIE_DIR", tmp_path)

    def installer(reponses, texte_synth):
        monkeypatch.setattr(sw, "_tourner_membre", lambda m, t, n: reponses[m])
        vus = {}

        def synth(membre, materiau, consigne, max_tours=1):
            vus.update(membre=membre, materiau=materiau, consigne=consigne)
            return {"text": texte_synth, "post_flight": {"vus": 1, "ok": 1, "alertes": 0, "illisibles": 0,
                                                         "motifs": []}}
        monkeypatch.setattr(sw, "_synthetiser", synth)
        return vus
    return installer


def test_garde_coupe_ligne_repetee(monde):
    texte = "a\nb\nc\n" + "\n".join(["  la   meme  ligne "] * 12)
    monde({"x": _membre("x", outils=["lire_tache"])}, texte)
    res = asyncio.run(sw.swarm_pointeur("q", ["p"], membres=["x"]))
    lignes = res["synthesis"].splitlines()
    assert sum(1 for line in lignes if "meme" in line and "garde" not in line) == 2
    assert res["synthese_garde"] == {"declenche": True, "lignes_ecartees": 10}
    assert lignes[-1] == "[garde anti-répétition : 10 ligne(s) répétée(s) écartée(s)]"


def test_separateurs_jamais_ecartes():
    texte = "\n".join(["|---|---|"] * 6 + ["", ""] + ["| a | b |"] * 2)
    sortie, n = sw._garde_repetition(texte)
    assert n == 0 and sortie == texte


def test_synthese_par_membre_le_plus_lu_et_motif_vide(monde):
    vus = monde({"a": _membre("a", outils=["lire_tache"]),
                 "b": _membre("b", outils=["lire_tache", "lire_fichier"]),
                 "c": _membre("c", ok=False)}, "fusion")
    res = asyncio.run(sw.swarm_pointeur("q", ["p"], membres=["a", "b", "c"]))
    assert res["synthese_par"] == "b" and vus["membre"] == "b"
    assert "rep a" in vus["materiau"] and "rep b" in vus["materiau"] and "rep c" not in vus["materiau"]
    assert "Fusionne sans répéter" in vus["consigne"]
    assert res["synthese_post_flight"]["vus"] == 1


def test_egalite_premier(monde):
    monde({"a": _membre("a", outils=["x"]), "b": _membre("b", outils=["x"])}, "f")
    res = asyncio.run(sw.swarm_pointeur("q", ["p"], membres=["a", "b"]))
    assert res["synthese_par"] == "a"


def test_aucun_ok_pas_de_synthese(monde):
    vus = monde({"a": _membre("a", ok=False)}, "jamais")
    res = asyncio.run(sw.swarm_pointeur("q", ["p"], membres=["a"]))
    assert res["synthesis"] is None and res["synthese_motif"] and not vus


def test_agreger_post_flight():
    metas = [{"ok": True, "motifs": []}, {"ok": True, "motifs": []},
             {"ok": False, "motifs": ["INJECTION"]}, {"ok": None, "motifs": ["ILLISIBLE"]}]
    agg = sw._agreger_post_flight(metas)
    assert (agg["vus"], agg["ok"], agg["alertes"], agg["illisibles"]) == (4, 2, 1, 1)
    assert sorted(agg["motifs"]) == ["ILLISIBLE", "INJECTION"]
    assert sw._agreger_post_flight([]) == {"vus": 0}


def test_membre_remonte_metas_sans_deduire(monkeypatch):
    from app import forge_handoff
    suite = iter([
        {"message": {"content": "", "tool_calls": []}, "tool_calls": [
            {"id": "1", "function": {"name": "lire_tache", "arguments": "{\"id\": \"zz\"}"}}],
         "_router_meta": {"post_flight": {"ok": False, "motifs": ["INJECTION"]}}},
        {"message": {"content": "fin"}, "tool_calls": [],
         "_router_meta": {"post_flight": {"ok": True, "motifs": []}}}])
    monkeypatch.setattr(forge_handoff, "_llm_round", lambda a, m, with_tools: next(suite))
    r = sw._tourner_membre("groq:m", "q", 4)
    assert r["post_flight"]["vus"] == 2 and r["post_flight"]["alertes"] == 1
    monkeypatch.setattr(forge_handoff, "_llm_round",
                        lambda a, m, with_tools: {"message": {"content": "x"}, "tool_calls": []})
    assert sw._tourner_membre("groq:m", "q", 2)["post_flight"] == {"vus": 0}
