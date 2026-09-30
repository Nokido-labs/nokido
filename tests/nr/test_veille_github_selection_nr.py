# -*- coding: utf-8 -*-
"""NR - ce que le rattrapage garde d'un depot GitHub (2026-09-05).

Mesure : `open-physiology/apinatomy-models`, 22 fichiers JSON de ~43 Ko -> 1 353
chunks ; `hxtorch`, 114 .py -> 917 chunks. L'ingesteur de depot ne connait ni le
cap veille (400 chunks/source) ni la difference prose/donnees. `_selection_github`
est une fonction PURE : ces tests ne touchent ni le reseau ni la base.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "app"))

bf = pytest.importorskip("forge_veille_backfill")


def _f(nom: str, n: int) -> tuple[str, str]:
    return (nom, "x" * n)


def test_un_fichier_de_donnees_volumineux_est_ecarte_et_compte():
    gardes, ecartes = bf._selection_github([
        _f("models/anatomy.json", 43_000),
        _f("package.json", 900),
        _f("README.md", 2_000),
    ])
    noms = [n for n, _ in gardes]
    assert "models/anatomy.json" not in noms
    assert "package.json" in noms, "un petit fichier de config reste utile"
    assert ecartes["donnees_volumineuses"] == 1


def test_le_budget_du_depot_suit_le_cap_veille():
    max_chunks = 10
    budget = max_chunks * bf._GH_CHARS_PAR_CHUNK
    fichiers = [_f(f"src/m{i}.py", 1_500) for i in range(20)]   # 30 000 chars > budget
    gardes, ecartes = bf._selection_github(fichiers, max_chunks=max_chunks)
    assert sum(len(t) for _, t in gardes) <= budget
    assert ecartes["cap_depot"] >= 1, "le cap doit DIRE ce qu'il ecarte"
    assert len(gardes) + ecartes["cap_depot"] == len(fichiers), "rien ne disparait sans etre compte"


def test_readme_et_docs_sont_servis_avant_le_code():
    gardes, _ = bf._selection_github([
        _f("src/big.py", 5_000),
        _f("docs/guide.md", 4_000),
        _f("README.md", 3_000),
        _f("src/small.py", 100),
    ], max_chunks=20)
    ordre = [n for n, _ in gardes]
    assert ordre[0] == "README.md"
    assert ordre[1] == "docs/guide.md"
    assert ordre.index("src/small.py") < ordre.index("src/big.py"), "le code par taille croissante"


def test_un_depot_qui_tient_dans_le_budget_passe_entier():
    fichiers = [_f("README.md", 1_000), _f("a.py", 2_000), _f("b.py", 2_000)]
    gardes, ecartes = bf._selection_github(fichiers, max_chunks=400)
    assert len(gardes) == 3
    assert ecartes == {"donnees_volumineuses": 0, "cap_depot": 0}


class _FauxIngesteur:
    """Simule forge_ingest_github_repo : `fetch` refuse par SystemExit comme le CLI."""
    DEFAULT_DOMAIN = "ext_repo"

    def __init__(self, refus_entier: str | None, docs=None):
        self.refus_entier = refus_entier
        self.docs = docs if docs is not None else [("docs/a.md", "x" * 500)]
        self.appels: list = []
        self.indexes: list = []

    def parse_slug(self, url):
        return ("owner", "repo")

    def fetch(self, owner, repo, ref, prefixe=None):
        self.appels.append(prefixe)
        if prefixe is None and self.refus_entier:
            raise SystemExit(self.refus_entier)
        return list(self.docs), {"ref": "main", "ecartes": {}}

    def index(self, fichiers, slug, domain):
        self.indexes.append((len(fichiers), slug, domain))
        return {"inserted": len(fichiers), "skipped_dedup": 0}


def _cand():
    return {"url": "https://github.com/owner/repo", "chunk_id": "watch_x", "len": 100, "theme": "t"}


class _Args:
    apply = False   # pas d'ecriture : on teste le comportement face au refus


def test_un_systemexit_trop_gros_declenche_le_repli_doc_seule(monkeypatch):
    faux = _FauxIngesteur("20000440 chars > cap 20000000 — depot trop gros")
    monkeypatch.setitem(sys.modules, "forge_ingest_github_repo", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_ingest_github_repo", faux)
    res = bf._process_github(_cand(), _Args())
    assert faux.appels == [None, "docs"], "le depot entier d'abord, puis la doc seule"
    assert res["status"] == "done", res
    assert any("repli" in l for l in res["log"])


def test_un_autre_refus_est_un_skip_propre_pas_une_mort(monkeypatch):
    faux = _FauxIngesteur("[ingest_repo] URL GitHub non reconnue")
    monkeypatch.setitem(sys.modules, "forge_ingest_github_repo", faux)
    monkeypatch.setitem(sys.modules, "nokido_agent.tools.forge_ingest_github_repo", faux)
    res = bf._process_github(_cand(), _Args())   # ne doit PAS lever SystemExit
    assert res["status"] == "skip"
    assert faux.appels == [None], "pas de repli doc sur un refus qui n'est pas 'trop gros'"


def test_une_ignoree_recente_ne_redevient_pas_candidate_avant_le_ttl():
    cands = [{"url": "https://github.com/a/b"}, {"url": "https://github.com/c/d"}]
    memo = {"https://github.com/a/b": {"raison": "depot trop gros", "ts": 1_000.0}}
    retenus, n = bf._filtrer_ignorees(cands, memo, ttl_s=3600, now=1_000.0 + 600)
    assert [c["url"] for c in retenus] == ["https://github.com/c/d"] and n == 1
    retenus, n = bf._filtrer_ignorees(cands, memo, ttl_s=3600, now=1_000.0 + 7200)
    assert len(retenus) == 2 and n == 0, "apres le TTL l'ignoree redevient candidate"


def test_la_memoire_des_ignorees_s_ecrit_et_se_relit(tmp_path):
    p = tmp_path / "ign.json"
    memo = {}
    bf._noter_ignoree(memo, "https://github.com/a/b", "gain insuffisant", chemin=p)
    relu = bf._charger_ignorees(p)
    assert relu["https://github.com/a/b"]["raison"] == "gain insuffisant"
    assert relu["https://github.com/a/b"]["ts"] > 0


def test_un_fichier_illisible_ne_bloque_pas_le_lot(tmp_path, capsys):
    p = tmp_path / "ign.json"
    p.write_text("{pas du json", encoding="utf-8")
    assert bf._charger_ignorees(p) == {}
    assert "ILLISIBLE" in capsys.readouterr().out, "un fichier illisible est DIT, pas avale"


def test_le_seuil_de_donnees_reste_reglable_sans_toucher_au_code(monkeypatch):
    # La constante est lue au chargement du module : on verifie qu'elle vient bien
    # de l'environnement (LAFORGE_VEILLE_GH_DATA_MAX), pas d'un litteral enterre.
    src = (ROOT / "tools" / "forge_veille_backfill.py").read_text(encoding="utf-8", errors="replace")
    assert 'environ.get("LAFORGE_VEILLE_GH_DATA_MAX"' in src
    assert 'environ.get("LAFORGE_VEILLE_MAX_CHUNKS"' in src
