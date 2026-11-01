"""NR mode POINTEUR du swarm : outils lecture seule, sonde, caviardage, garde de taille, CLI."""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import forge_cli_swarm as sw  # noqa: E402

FAUX_SECRET = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "note.txt").write_text("x" * 100, encoding="utf-8")
    (ws / "secret.txt").write_text("ip localhost cle " + FAUX_SECRET, encoding="utf-8")
    dehors = tmp_path / "dehors"
    dehors.mkdir()
    (dehors / "a.txt").write_text("interdit", encoding="utf-8")
    db = tmp_path / "tasks.db"
    c = sqlite3.connect(db)
    c.execute("create table tasks (id text, description text, result text)")
    c.execute("insert into tasks values ('t1','desc un','res un')")
    c.commit()
    c.close()
    monkeypatch.setattr(sw, "RACINES_LECTURE", [ws])
    monkeypatch.setattr(sw, "TASKS_DB", db)
    monkeypatch.setattr(sw, "RAG_DB", tmp_path / "absent.db")
    monkeypatch.setattr(sw, "SORTIE_DIR", tmp_path / "out")
    return {"ws": ws, "dehors": dehors, "tmp": tmp_path}


def _sonde(tmp_path, resultats):
    p = tmp_path / "probe.json"
    p.write_text(json.dumps({"resultats": resultats}), encoding="utf-8")
    return p


def test_lire_fichier_refus(monde):
    lf = sw._outils_lecture()["lire_fichier"]
    assert "refus" in lf("../dehors/a.txt").lower()
    assert "refus" in lf(str(monde["dehors"] / "a.txt")).lower()
    assert "refus" in lf("app/forge_handoff.py").lower()
    assert "refus" in lf(str(monde["ws"] / ".." / "dehors" / "a.txt")).lower()


def test_lire_fichier_fenetre_dit_le_reste(monde):
    lf = sw._outils_lecture()["lire_fichier"]
    out = lf(str(monde["ws"] / "note.txt"), 0, 40)
    assert "40/100" in out and "debut=40" in out


def test_lire_tache(monde):
    lt = sw._outils_lecture()["lire_tache"]
    assert "desc un" in lt("t1")
    assert "inconnue" in lt("zzz")


def test_sonde_ecarte(monde):
    p = _sonde(monde["tmp"], [
        {"fournisseur": "groq", "modele": "m", "etat": "APPELLE", "motif": ""},
        {"fournisseur": "mistral", "modele": "m", "etat": "IGNORE", "motif": "texte"},
    ])
    ret, ecartes = sw._membres_pointeur(["groq", "mistral", "cerebras"], p)
    assert ret == ["groq"]
    raisons = {e["provider"]: e["raison"] for e in ecartes}
    assert set(raisons) == {"mistral", "cerebras"} and all(raisons.values())
    ret, ecartes = sw._membres_pointeur(["groq"], monde["tmp"] / "nulle.json")
    assert ret == [] and ecartes[0]["raison"]


def _fake_round(monde, vus):
    etat = {"n": 0}

    def fake(agent, messages, with_tools):
        etat["n"] += 1
        vus.append(json.dumps(messages))
        if etat["n"] == 1:
            assert with_tools and agent.tools
            return {"message": {"content": ""}, "tool_calls": [
                {"function": {"name": "lire_fichier",
                              "arguments": json.dumps({"chemin": str(monde["ws"] / "secret.txt")})}}]}
        return {"message": {"content": "reponse finale"}, "tool_calls": []}
    return fake


def test_boucle_outil_et_caviardage(monde, monkeypatch):
    from app import forge_handoff
    vus = []
    monkeypatch.setattr(forge_handoff, "_llm_round", _fake_round(monde, vus))
    p = _sonde(monde["tmp"], [{"fournisseur": "groq", "modele": "m", "etat": "APPELLE", "motif": ""}])
    monkeypatch.setattr(sw, "SONDE", p)

    async def fake_ask(*a, **k):
        return {"ok": True, "text": ""}
    monkeypatch.setattr(sw, "ask", fake_ask)
    res = asyncio.run(sw.swarm_pointeur("question ?", ["tasks.db:t1"], membres=["groq"]))
    a = res["answers"][0]
    assert a["ok"] and a["text"] == "reponse finale"
    assert "lire_fichier" in a["outils_appeles"] and a["tours"] == 2 and a["chars_envoyes"] > 0
    second = vus[1]
    assert "ip " in second  # le contenu est revenu au modele
    assert "localhost" not in second and FAUX_SECRET not in second
    assert "tasks.db:t1" in vus[0]


def test_swarm_refuse_gros(monkeypatch):
    called = []

    async def fake_one(*a, **k):
        called.append(1)
        return {}
    monkeypatch.setattr(sw, "_one", fake_one)
    res = asyncio.run(sw.swarm("x" * (sw.SEUIL_CONSIGNE + 1), ["groq"]))
    assert not called and "swarm_pointeur" in res["refus"] and res["answers"] == []


def test_cli_pointeur(monde, monkeypatch, capsys):
    f = monde["tmp"] / "consigne.txt"
    f.write_text("longue consigne", encoding="utf-8")
    recu = {}

    async def fake(consigne, pointeurs, membres=None, max_tours=4):
        recu.update(c=consigne, p=pointeurs)
        return {"answers": [], "ecartes": [], "synthesis": None}
    monkeypatch.setattr(sw, "swarm_pointeur", fake)
    rc = sw.main(["--pointeur", str(f), "--ptr", "tasks.db:t1", "--ptr", "docs/x.md"])
    assert rc == 0 and recu == {"c": "longue consigne", "p": ["tasks.db:t1", "docs/x.md"]}


# --- tour final garanti + reprise 5xx ---
def _appel_lire(monde):
    return {"message": {"content": ""}, "tool_calls": [
        {"id": "c1", "function": {"name": "lire_fichier",
                                  "arguments": json.dumps({"chemin": str(monde["ws"] / "note.txt")})}}]}


def _echec(code):
    meta = {"ok": False, "provider": "groq", "tools": True, "error": f"groq: HTTP {code}", "http": code}
    return {"message": {"content": ""}, "tool_calls": [], "_router_meta": meta}


def test_defaut_max_tours_six():
    import inspect
    assert inspect.signature(sw.swarm_pointeur).parameters["max_tours"].default == 6


def test_plafond_tour_final_sans_outils(monde, monkeypatch):
    from app import forge_handoff
    avant = forge_handoff.REGLE_D_OR_INERTES
    vus = []

    # Contrat du 28/10 23 h 25 : le tour final reste sur la voie UNIQUE (outils declares, tool_choice="none") ;
    # la voie aplatie sans outils rendait un contenu vide en reel (Ollama Cloud).
    def fake(agent, messages, with_tools):
        choix = getattr(agent, "tool_choice", "auto")
        vus.append((with_tools, bool(agent.tools), json.dumps(messages), choix))
        if choix != "none":
            return _appel_lire(monde)
        return {"message": {"content": "synthese lue"}, "tool_calls": []}
    monkeypatch.setattr(forge_handoff, "_llm_round", fake)
    r = sw._tourner_membre("groq:m", "q", 4)
    assert r["ok"] is True and r["text"] == "synthese lue" and r["tours"] == 4
    assert [v[3] for v in vus] == ["auto", "auto", "auto", "none"]  # appel interdit au seul dernier tour
    assert vus[-1][1] and vus[-1][0] and "ne cite que les extraits lus" in vus[-1][2]
    assert forge_handoff.REGLE_D_OR_INERTES == avant


def test_plafond_sans_rien_lu_reste_ok_false(monde, monkeypatch):
    from app import forge_handoff
    monkeypatch.setattr(forge_handoff, "_llm_round",
                        lambda a, m, with_tools: {"message": {"content": "invente"}, "tool_calls": []})
    r = sw._tourner_membre("groq:m", "q", 3)
    assert r["ok"] is False and "aucun pointeur lu" in r["error"]


def _rejeu(monkeypatch, sequence):
    from app import forge_handoff
    it = iter(sequence)
    appels, pauses = [], []
    monkeypatch.setattr(sw.time, "sleep", lambda s: pauses.append(s))

    def fake(agent, messages, with_tools):
        appels.append(1)
        return next(it)
    monkeypatch.setattr(forge_handoff, "_llm_round", fake)
    return appels, pauses


def test_500_puis_succes(monde, monkeypatch):
    appels, pauses = _rejeu(monkeypatch, [
        _appel_lire(monde), _echec(500), {"message": {"content": "ok fini"}, "tool_calls": []}])
    r = sw._tourner_membre("groq:m", "q", 6)
    assert r["ok"] is True and r["text"] == "ok fini" and pauses == [3] and len(appels) == 3


def test_500_deux_fois(monde, monkeypatch):
    appels, pauses = _rejeu(monkeypatch, [_appel_lire(monde), _echec(500), _echec(500)])
    r = sw._tourner_membre("groq:m", "q", 6)
    assert r["ok"] is False and "HTTP 500" in r["text"] and "groq" in r["text"]
    assert len(appels) == 3 and pauses == [3]


def test_403_aucune_reprise(monde, monkeypatch):
    appels, pauses = _rejeu(monkeypatch, [_echec(403)])
    r = sw._tourner_membre("groq:m", "q", 6)
    assert r["ok"] is False and "403" in r["text"] and len(appels) == 1 and pauses == []
