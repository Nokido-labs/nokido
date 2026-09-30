"""NR -- la TUI v13 interroge le RAG du HUB et ne charge plus la base au montage.

Mesure du 2026-09-25 (tools/forge_tui_sonde.py sous trusted_script, pile faulthandler a
l'echeance) : `on_mount` construisait `RAGEngine()` dans la boucle de l'interface, et
`_load_embeddings` parcourait TOUTES les lignes actives de rag_chunks -- ecran gele > 45 s,
plusieurs Go de RAM, lecteur long sur la base de 45 Go a chaque ouverture. Decision owner 1 :
la TUI passe par le RAG du hub (app/forge_rag_via_hub.py, adaptateur sur forge_hub_client).

Garde : le format reel du hub est converti ; un refus (ring, 401, hub muet) rend une liste vide
ET un etat NOMME (jamais « 0 chunks ») ; l'adaptateur ne touche pas la base ; le contexte de
session local est borne et compte ; et, sur le chemin reel (app/Nokido.py), `RAGEngine()` n'est
construit QUE sous l'opt-in LAFORGE_TUI_RAG_LOCAL.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from nokido_agent.app import forge_rag_via_hub as rvh  # noqa: E402

ECHANTILLON = (  # forme REELLE de `rag action=search` (releve le 25/09)
    "[coollabsio_coolify/public/js/nls.messages.fr.js] (sdk_gitingest, bm25=-37.2)\n"
    "raccourci clavier ...\n\n"
    "[mammouth_ai_code/docs/fr/keybinds.mdx] (sdk_gitingest, bm25=-35.2)\n"
    "Vous n'avez pas besoin d'utiliser une touche leader ...\n"
)


class _Client:
    def __init__(self, texte):
        self.texte, self.appels = texte, []

    def tool(self, name, args):
        self.appels.append((name, args))
        return self.texte


def test_le_format_reel_du_hub_est_converti():
    r = rvh.analyser_resultats(ECHANTILLON)
    assert [x["source"] for x in r] == ["coollabsio_coolify/public/js/nls.messages.fr.js",
                                        "mammouth_ai_code/docs/fr/keybinds.mdx"]
    assert r[0]["domain"] == "sdk_gitingest" and r[0]["score"] == -37.2
    assert r[1]["content"].startswith("Vous n'avez pas besoin")


def test_la_recherche_passe_par_l_outil_rag_du_hub():
    c = _Client(ECHANTILLON)
    rag = rvh.RAGViaHub(client=c)
    r = asyncio.run(rag.search("raccourci", k=1))
    assert c.appels == [("rag", {"action": "search", "topic": "raccourci", "limit": 1})]
    assert len(r) == 1 and rag.etat() == "joint"


def test_un_refus_rend_vide_et_le_nomme():
    for texte in ("GATE_DENIED: ring 4 <= requis 3", None):
        rag = rvh.RAGViaHub(client=_Client(texte))
        assert asyncio.run(rag.search("x")) == []
        assert rag.etat().startswith("refuse"), "un refus doit se DIRE, pas se lire « base vide »"


def test_l_adaptateur_ne_touche_pas_la_base():
    src = Path(rvh.__file__).read_text(encoding="utf-8")
    code = re.sub(r'"""[\s\S]*?"""', "", src)  # la doctrine peut NOMMER ce qu'on n'appelle pas
    assert "sqlite3" not in code and "RAGEngine(" not in code and "embeddings.db" not in code
    rag = rvh.RAGViaHub(client=_Client(""))
    assert rag._load_embeddings() is None and rag.chunks == []


def test_le_contexte_de_session_est_borne_et_compte():
    rag = rvh.RAGViaHub(client=_Client(""))
    rag.PLAFOND_SESSION = 3
    for i in range(5):
        asyncio.run(rag.add_session_message("s", "user", "m%d" % i))
    assert [m["content"] for m in rag.session_ctxs["s"]] == ["m2", "m3", "m4"]
    assert rag.sessions_ecartees == 2


def test_le_warmup_ne_declenche_pas_l_indexation_locale_via_hub(monkeypatch):
    """Sonde du 25/09 : le fil qui retenait la TUI v13 apres fermeture etait index_app_dir
    (parcours complet PAR FICHIER + DELETE/INSERT directs). Via le hub, le warmup le saute."""
    from nokido_agent.app import forge_context, forge_rag_warmup as rw

    appels = []

    async def _index():
        appels.append(1)

    async def _rien(*a, **k):
        return None

    class _Stop(Exception):
        pass

    def _arret(*a, **k):  # coupe la suite du warmup (llama, docs) : seul l'aiguillage est juge ici
        raise _Stop()

    monkeypatch.setattr(rw, "_warmup_app_index", _index)
    monkeypatch.setattr(rw.asyncio, "sleep", _rien)
    monkeypatch.setattr(forge_context, "get_rag_engine", lambda: rvh.RAGViaHub(client=_Client("")))
    monkeypatch.setattr(rw.logger, "info", _arret)
    try:
        asyncio.run(rw.rag_self_warmup(None))
    except _Stop:
        pass
    assert appels == [], "la TUI via hub a declenche l'indexation locale d'app/ et tools/"


def test_chemin_reel_la_tui_v13_ne_construit_ragengine_que_sous_opt_in():
    lignes = (RACINE / "app" / "Nokido.py").read_text(encoding="utf-8", errors="replace").splitlines()
    sites = [i for i, l in enumerate(lignes) if re.search(r"\brag_engine\s*=\s*RAGEngine\(\)", l)]
    assert sites, "construction de RAGEngine introuvable : le lecteur ne voit plus le montage"
    for i in sites:
        contexte = "\n".join(lignes[max(0, i - 4):i])
        assert "LAFORGE_TUI_RAG_LOCAL" in contexte, (
            "app/Nokido.py:%d construit RAGEngine() hors de l'opt-in LAFORGE_TUI_RAG_LOCAL" % (i + 1))
    assert any("RAGViaHub()" in l for l in lignes), "la TUI v13 n'utilise pas le RAG du hub"
