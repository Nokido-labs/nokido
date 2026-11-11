"""NR -- le repli cloud du rerank passe par la membrane, et par provenance ; la vectorisation vers Modal n'est pas bloquee.

Mesure du 6/11 : reranker local eteint, la requete et 1 000 caracteres de chaque candidat partaient chez Cohere, sans filtre,
conversations et memoires comprises. Choix owner : garder le repli sous membrane, « qu elle ne rate rien ». Un motif ne reconnait
pas une conversation privee : la provenance se juge en liste blanche, un domaine inconnu ne sort pas.
« a l inverse une vectoristion vers modal ne doit psa etre bloque ». Sujets et valeurs fictifs : ce fichier part dans le depot public.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
for _p in (str(RACINE), str(RACINE / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_embed_router as EMB  # noqa: E402
from nokido_agent.app import forge_rag_engine as RE  # noqa: E402
from nokido_agent.app import forge_sovereign_membrane as M  # noqa: E402

pytestmark = pytest.mark.timeout(60)
SUJETS = {"chemins": [], "mots": ["projet\\s*fictif"], "caviarder": [], "retirer": [], "erreurs": []}


@pytest.fixture
def banc(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "_lire_sujets", lambda: SUJETS)
    monkeypatch.setattr(M, "_cle_sujets", lambda: object())
    vraie = M.SovereignMembrane
    monkeypatch.setattr(M.SovereignMembrane, "for_mission", classmethod(
        lambda cls, mission_id, **k: vraie(mission_id=mission_id, db_path=str(tmp_path / "m.db"), hmac_secret=b"n" * 32)))
    monkeypatch.setenv("COHERE_API_KEY", "fictive")
    envois = []

    class Rep(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def faux_urlopen(req, timeout=None):
        url = getattr(req, "full_url", str(req))
        if "cohere" not in url:
            raise OSError("reranker local eteint")
        corps = json.loads(req.data)
        envois.append(corps)
        return Rep(json.dumps({"results": [{"index": i, "relevance_score": 1.0 - i / 10} for i in range(len(corps["documents"]))]}).encode())
    monkeypatch.setattr("urllib.request.urlopen", faux_urlopen)
    return envois


def _doc(domaine, texte="contenu de documentation"):
    return {"content": texte, "score": 0.5, "domain": domaine, "source": "rag:x"}


def test_documents_publics_partent_sous_membrane(banc):
    r = RE.RAGEngine._rerank("ou en est le projet fictif", [_doc("ext_repo", "le projet fictif est cite"), _doc("sdk_gitingest")], top_n=2)
    assert len(banc) == 1 and len(r) == 2
    envoye = json.dumps(banc[0], ensure_ascii=False)
    assert "projet fictif" not in envoye and "contenu de documentation" in envoye


@pytest.mark.parametrize("domaine", ["conv", "memory", "mcp_result", "nokido_doc", "reference", "domaine_inconnu", None])
def test_un_seul_document_non_public_garde_tout_en_local(banc, domaine):
    r = RE.RAGEngine._rerank("question", [_doc("ext_repo"), _doc(domaine, "souvenir prive de session")], top_n=2)
    assert banc == [] and len(r) == 2 and all("rerank_score" in d for d in r)


def test_session_sans_domaine_ne_sort_pas(banc):
    d = {"source": "session:x", "content": "souvenir", "score": 0.4, "type": "session"}
    assert RE.RAGEngine._rerank("question", [d], top_n=1) and banc == []


def test_membrane_en_panne_ne_sort_rien(banc, monkeypatch):
    def casse(*_a, **_k):
        raise RuntimeError("membrane illisible")
    monkeypatch.setattr(M.SovereignMembrane, "for_mission", classmethod(casse))
    assert RE.RAGEngine._rerank("question", [_doc("ext_repo")], top_n=1) and banc == []


def test_la_vectorisation_modal_n_est_pas_bloquee():
    """Le chemin de `_modal_call` : le texte part, le secret seul est masque, un sujet ou un souvenir n'arrete rien."""
    mot = "PW" + "D = " + chr(34) + "fictif" + "!" + "2099" + chr(34)
    sortie = EMB.masquer_pour_cloud(["souvenir de session sur le projet fictif", mot], "modal_embed")
    assert sortie is not None and len(sortie) == 2
    assert sortie[0] == "souvenir de session sur le projet fictif"
    assert "fictif!2099" not in sortie[1]
