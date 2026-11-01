"""NR : le self-patcher obtient une REPONSE du hub, et une panne en amont ne consomme pas la proposition.

Mesure 26/10 (journal logs/supervisor/NokidoSelfPatcher.log, 25/10 15:40) : `_hub_call` envoyait un JSON-RPC
SANS `id` -- une NOTIFICATION, acceptee par le serveur MCP avec un corps VIDE -- d'ou « Expecting value:
line 1 column 1 » ; puis run_once marquait quand meme les 3 propositions traitees. Une panne n'est pas
un « rien a faire » (UNKNOWN != NO).
"""
import json
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools"), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_self_patcher as sp  # noqa: E402


class _Rep:
    def __init__(self, corps: bytes):
        self._c = corps

    def read(self):
        return self._c

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_la_requete_est_une_requete_pas_une_notification(monkeypatch):
    vus = []

    def faux_urlopen(req, timeout=None):
        vus.append(json.loads(req.data))
        return _Rep(b'{"jsonrpc":"2.0","id":1,"result":{"content":[{"text":"ok"}]}}')

    monkeypatch.setattr("urllib.request.urlopen", faux_urlopen)
    out = sp._hub_call("ask", {"message": "x"})
    # les entetes peuvent d'abord demander un jeton court au hub : seul l'appel d'outil est juge ici
    appel = [v for v in vus if v.get("method") == "tools/call"][-1]
    assert appel["jsonrpc"] == "2.0" and "id" in appel
    assert out["result"]["content"][0]["text"] == "ok"


def test_corps_vide_dit_l_echec_au_lieu_d_un_json_illisible(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _Rep(b""))
    out = sp._hub_call("ask", {"message": "x"})
    assert "error" in out and "vide" in out["error"]


def test_une_panne_amont_ne_consomme_pas_la_proposition(monkeypatch, tmp_path):
    props = tmp_path / "props"
    faits = props / "patch_applied"
    props.mkdir()
    (props / "evolution_proposal_cible_bfcl_1.md").write_text("- **bfcl** : 94 < 95\n", encoding="utf-8")
    monkeypatch.setattr(sp, "PROPOSALS_DIR", props)
    monkeypatch.setattr(sp, "APPLIED_DIR", faits)
    monkeypatch.setattr(sp, "_rag_lookup", lambda pattern: "")
    monkeypatch.setattr(sp, "_hub_call", lambda tool, args, timeout=90: {"error": "corps vide"})
    sp.run_once(dry_run=False)
    assert list(faits.glob("*.md")) == []


def test_un_refus_du_hub_rendu_en_texte_ne_consomme_pas(monkeypatch, tmp_path):
    props = tmp_path / "props"
    faits = props / "patch_applied"
    props.mkdir()
    (props / "evolution_proposal_cible_bfcl_1.md").write_text("- **bfcl** : 94 < 95\n", encoding="utf-8")
    monkeypatch.setattr(sp, "PROPOSALS_DIR", props)
    monkeypatch.setattr(sp, "APPLIED_DIR", faits)
    monkeypatch.setattr(sp, "_rag_lookup", lambda pattern: "")
    monkeypatch.setattr(sp, "_hub_call", lambda tool, args, timeout=90: {
        "result": {"content": [{"text": "ERR: ring 4 <= requis 3 (ask)"}]}})
    sp.run_once(dry_run=False)
    assert list(faits.glob("*.md")) == []


def test_la_provenance_du_jeton_est_dite_sans_la_valeur(monkeypatch, caplog):
    """26/10 : le demon etait vu UNKNOWN par le hub et son journal ne disait pas d'ou venait son jeton."""
    import logging

    # Valeur FACTICE composee : un litteral « token = "..." » est pris pour un secret par le gate egress (26/10).
    factice = "-".join(("valeur", "jamais", "dite"))

    class _Client:
        token = factice

        def __init__(self, agent):
            self.agent = agent

        def _jeton_courant(self):
            return self.token, "coffre:FORGE_TOKEN_SELF_PATCHER+repli_statique"

    import types as _t
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_hub_client", _t.SimpleNamespace(HubClient=_Client))
    with caplog.at_level(logging.INFO, logger="Nokido.SelfPatcher"):
        sp._resolve_hub_token()  # tourne a l'import, journal pas encore configure : il RETIENT
        sp._dire_identite()      # main() le dit une fois le journal configure
    texte = caplog.text
    assert "coffre:FORGE_TOKEN_SELF_PATCHER+repli_statique" in texte and "SELF_PATCHER" in texte
    assert factice not in texte


def test_lance_comme_le_demon_nokido_agent_est_importable(tmp_path):
    """Chemin REEL (26/10) : `python tools/forge_self_patcher.py` ne met que tools/ dans sys.path ; sans la racine,
    `nokido_agent` etait introuvable -> ni HubClient ni coffre -> jeton maitre sans nom -> hub : UNKNOWN ring 4."""
    import subprocess

    code = ("import sys; sys.path[:] = [r'%s'] + [p for p in sys.path if p not in ('', '.')]\n"
            "import forge_self_patcher as sp; print(sp._PROVENANCE_JETON)") % (_R / "tools")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=25,
                       env=dict(__import__("os").environ, PYTHONNOUSERSITE="1"))
    assert r.returncode == 0, r.stderr[-400:]
    assert "ModuleNotFoundError" not in r.stdout and "HubClient SELF_PATCHER" in r.stdout


def test_une_reponse_sans_correctif_consomme_toujours(monkeypatch, tmp_path):
    props = tmp_path / "props"
    faits = props / "patch_applied"
    props.mkdir()
    (props / "evolution_proposal_cible_bfcl_1.md").write_text("- **bfcl** : 94 < 95\n", encoding="utf-8")
    monkeypatch.setattr(sp, "PROPOSALS_DIR", props)
    monkeypatch.setattr(sp, "APPLIED_DIR", faits)
    monkeypatch.setattr(sp, "_rag_lookup", lambda pattern: "")
    monkeypatch.setattr(sp, "_hub_call", lambda tool, args, timeout=90: {
        "result": {"content": [{"text": "aucun correctif sur sans risque"}]}})
    sp.run_once(dry_run=False)
    assert [f.name for f in faits.glob("*.md")] == ["evolution_proposal_cible_bfcl_1.md"]
