"""NR -- secours de la synthese par les EXECUTEURS (CLAUDE_HEADLESS puis ANTIGRAVITY), par POINTEUR.

Faux depot, faux statut, temps simule : aucun vrai executeur, aucune ecriture dans tasks.db."""
# pylint: disable=protected-access,wrong-import-position
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "app")]

import pytest  # noqa: E402
import forge_cli_swarm as S  # noqa: E402

FORT = "ollama_cloud_gptoss:gpt-oss:120b"


def _m(texte="reponse 12 ms"):
    return {"provider": FORT, "ok": True, "text": texte, "outils_appeles": [], "extraits": ["extrait 12 ms"],
            "ancrage": {"sans_source": []}}


@pytest.fixture
def monde(monkeypatch, tmp_path):
    monkeypatch.setenv("LAFORGE_SECOURS_EXECUTEURS", "1")
    monkeypatch.setattr(S, "_membres_pointeur", lambda membres, sonde=None: (list(membres), []))
    monkeypatch.setattr(S, "SORTIE_DIR", tmp_path)
    monkeypatch.setattr(S, "_tourner_membre", lambda m, t, n: _m())
    monkeypatch.setattr(S, "_synthetiser", lambda *a, **k: {"text": "", "error": "vide"})
    monkeypatch.setattr(S, "_pre_flight_envoi", lambda t, v: (True, None))
    monkeypatch.setattr(S, "_appeler_voie", lambda v, p, timeout=180: {"text": "", "error": "backend non prêt"})
    horloge = {"t": 0.0}
    monkeypatch.setattr(S, "_horloge", lambda: horloge["t"])
    monkeypatch.setattr(S, "_dormir", lambda s: horloge.__setitem__("t", horloge["t"] + s))

    def installer(resultats):
        """resultats : executeur -> texte (termine), None (reste en cours), 'ECHEC'."""
        d = {"depots": [], "ids": {}}

        def depot(executeur, titre, consigne):
            d["depots"].append((executeur, consigne))
            tid = "t%d" % len(d["depots"])
            d["ids"][tid] = executeur
            return tid

        def statut(tid):
            r = resultats.get(d["ids"][tid])
            if r is None:
                return {"status": "in_progress", "results": "[]"}
            if r == "ECHEC":
                return {"status": "failed", "results": "[]"}
            return {"status": "review", "results": json.dumps([{"text": r}])}
        monkeypatch.setattr(S, "_deposer_tache", depot)
        monkeypatch.setattr(S, "_statut_tache", statut)
        return d
    return installer


def _run():
    return asyncio.run(S.swarm_pointeur("q", ["p"], membres=[FORT]))


def test_depot_par_pointeur_et_resultat_retenu(monde):
    # REMPLACEE (decision owner 29/10) : ancienne = depot par le job puis resultat retenu ; nouvelle = aucun depot,
    # la demande porte le pointeur (entre guillemets) et la consigne courte.
    d = monde({"CLAUDE_HEADLESS": "ligne ancree 12 ms"})
    res = _run()
    assert d["depots"] == []
    consigne = res["demande_synthese"]["consigne"]
    # extraction par GUILLEMETS (29/10) : le decoupage aux blancs cassait un chemin contenant des espaces
    chemin = re.search(r'"([^"]*swarm_synthese_[^"]*)"', consigne).group(1)
    assert Path(chemin).is_file() and "reponse 12 ms" not in consigne and len(consigne) < 600
    assert chemin == res["demande_synthese"]["pointeur"]
    assert json.loads(Path(chemin).read_text(encoding="utf-8"))["answers"]
    assert res["synthese_par"] is None and res["synthesis"] is None


def test_delai_depasse_passe_a_antigravity(monde):
    # REMPLACEE : ancienne = delai CLAUDE puis ANTIGRAVITY depose par le job ; nouvelle = les deux executeurs
    # sont nommes dans la demande, aucun depot, aucune attente dans le job.
    d = monde({"CLAUDE_HEADLESS": None, "ANTIGRAVITY": "par agy 12 ms"})
    res = _run()
    assert d["depots"] == []
    assert res["demande_synthese"]["executeurs"] == ["CLAUDE_HEADLESS", "ANTIGRAVITY"]
    assert res["synthese_par"] is None


def test_les_deux_echouent_reponses_publiees(monde):
    monde({"CLAUDE_HEADLESS": "ECHEC", "ANTIGRAVITY": None})
    res = _run()
    assert res["synthesis"] is None and res["synthese_motif"] and res["answers"]


def test_chiffre_invente_ligne_retiree(monde):
    # REMPLACEE : ancienne = jugement dans le job apres depot ; nouvelle = le meme jugement a l'integration
    # (--integrer-secours), couvert en detail par test_swarm_secours_par_lanceur_nr ; ici : le job ne juge rien.
    d = monde({"CLAUDE_HEADLESS": "ancree 12 ms\ninventee 77 %"})
    res = _run()
    assert d["depots"] == [] and res["synthesis"] is None and "demande_synthese" in res
