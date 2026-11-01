"""NR 24/10 : moelle d'usage des LLM (phase B) -- tools/forge_moelle_llm.py.

Contrats : requete FTS indexee (mots quotes, filtre par colonne source), plafond par page
(sur-fragmentation : ~300 morceaux/page claude_docs), jamais Claude dans la cascade d'un
travail de masse, et un theme sans sources ou sans reponse est ecrit INDISPONIBLE --
jamais un texte invente.
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import forge_moelle_llm as M  # noqa: E402


def _base(tmp_path):
    db = tmp_path / "e.db"
    cx = sqlite3.connect(db)
    cx.execute("CREATE TABLE rag_chunks(rowid INTEGER PRIMARY KEY, text TEXT, source TEXT, domain TEXT)")
    cx.execute("CREATE VIRTUAL TABLE rag_chunks_fts USING fts5(text, source, domain, content='rag_chunks', content_rowid='rowid')")
    lignes = [("prompt caching saves cost %d" % i, "claude_docs:platform/prompt-caching.md", "d") for i in range(6)]
    lignes += [("prompt caching on openai", "openai_docs:platform/caching.md", "d")]
    lignes += [("unrelated text", "claude_docs:platform/other.md", "d")]
    for i, (t, s, d) in enumerate(lignes, 1):
        cx.execute("INSERT INTO rag_chunks(rowid,text,source,domain) VALUES(?,?,?,?)", (i, t, s, d))
        cx.execute("INSERT INTO rag_chunks_fts(rowid,text,source,domain) VALUES(?,?,?,?)", (i, t, s, d))
    cx.commit()
    return cx


def test_requete_quote_les_mots_et_filtre_la_source():
    q = M.requete_fts(["prompt", 'ca"ching'], ["claude docs", "anthropic"])
    assert q == '("prompt" "ca""ching") AND (source:"claude docs" OR source:"anthropic")'


def test_extraits_plafonnes_par_page_et_filtres_par_surface(tmp_path):
    cx = _base(tmp_path)
    ex = M.extraits(cx, M.requete_fts(["prompt", "caching"], ["claude docs"]), par_page=2)
    assert [s for s, _ in ex] == ["claude_docs:platform/prompt-caching.md"] * 2
    assert all("openai" not in s for s, _ in ex)


def test_cascade_de_masse_sans_claude():
    chaine = ["ollama_cloud_ultra", "ollama_cloud_gptoss", "groq_free", "repli_oauth"]
    assert M.slots_gratuits(chaine) == 3
    assert M.slots_gratuits(["claude_oauth", "groq_free"]) == 0


def test_theme_sans_source_ou_sans_reponse_ecrit_indisponible(tmp_path):
    cx = _base(tmp_path)
    appels = []

    def appel(prompt):
        appels.append(prompt)
        return {"ok": False, "error": "quota"}

    r = M.traiter_theme(cx, "cache", ["prompt", "caching"], {"claude": ["claude docs"]}, appel, tmp_path)
    assert r["etat"] == "INDISPONIBLE"
    texte = (tmp_path / "cache.md").read_text(encoding="utf-8")
    assert "INDISPONIBLE" in texte and "claude_docs:platform/prompt-caching.md" in texte
    r2 = M.traiter_theme(cx, "vide", ["zzzz"], {"claude": ["claude docs"]}, appel, tmp_path)
    assert r2["etat"] == "INDISPONIBLE" and r2["sources"] == []


def test_drapeau_plan_traverse_le_point_d_entree(tmp_path, monkeypatch, capsys):
    """Chemin REEL : `--plan` passe par main() et exige un plan sur l'index FTS (jamais un SCAN de table)."""
    _base(tmp_path).close()
    monkeypatch.setattr(M, "BASE", str(tmp_path / "e.db").replace("\\", "/"))
    assert M.main(["--plan", "--themes", "cache"]) == 0
    assert "VIRTUAL TABLE INDEX" in capsys.readouterr().out


def test_theme_redige_cite_ses_sources_et_le_fournisseur(tmp_path):
    cx = _base(tmp_path)
    reponses = iter([{"ok": True, "text": "brouillon", "provider": "ollama_cloud_gptoss"},
                     {"ok": True, "text": "avis", "provider": "ollama_cloud_ultra"},
                     {"ok": True, "text": "version finale", "provider": "ollama_cloud_gptoss"}])
    r = M.traiter_theme(cx, "cache", ["prompt", "caching"], {"claude": ["claude docs"], "openai": ["openai docs"]},
                        lambda p: next(reponses), tmp_path)
    assert r["etat"] == "FAIT" and r["fournisseurs"] == ["ollama_cloud_gptoss", "ollama_cloud_ultra", "ollama_cloud_gptoss"]
    texte = (tmp_path / "cache.md").read_text(encoding="utf-8")
    assert "version finale" in texte and "openai_docs:platform/caching.md" in texte
    assert json.loads(json.dumps(r))["sources"]
