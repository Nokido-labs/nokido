"""NR — triplets retrieval tires du journal des succes : ce qui est ecarte est DIT, rien ne fuit.

Chantier LoRA retrieval du 2026-09-27 : query_log n'a aucun positif (selected_chunk_id vide
120/120) ; le journal des succes (symptome -> fichiers du correctif) est la seule source de
pertinence propre a Nokido. forge_jepa_dataset --source oplog en tire des triplets.

Invariants :
- une entree INFIRME n'est jamais un positif (comptee) ;
- un fichier disparu ne produit pas de carte (compte) ; une entree sans fichier vivant est comptee ;
- split TEMPOREL : le held-out = les plus recentes ; un negatif du train ne vient JAMAIS du held-out ;
- le negatif n'est jamais un fichier du correctif ;
- un fichier CARREFOUR (touche par presque chaque entree, cas de tools/ci_local.py : 12,3 %
  des positifs du train le 27/09) n'est jamais positif, et il est NOMME au manifest ;
- le mode `traces` (defaut) reste le defaut ;
- CHEMIN REEL : `main(["--source", "oplog", ...])`.
Hermetique : oplog, racine et sorties dans tmp_path, sanitize coupe.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_jepa_dataset as ds  # noqa: E402


def _monde(tmp_path):
    racine = tmp_path / "depot"
    (racine / "tools").mkdir(parents=True)
    (racine / "docs").mkdir()
    (racine / "tools" / "wal.py").write_text('"""Checkpoint du WAL qui grossit."""\ndef checkpoint():\n    pass\n',
                                             encoding="utf-8")
    (racine / "tools" / "hub.py").write_text('"""Redemarrage du hub."""\nclass Hub:\n    pass\n', encoding="utf-8")
    (racine / "tools" / "rag.py").write_text('"""Recherche RAG hybride."""\n', encoding="utf-8")
    (racine / "docs" / "guide.md").write_text("# Guide des veilles\n", encoding="utf-8")
    entrees = [
        {"commit": "a1", "date": "2026-01-01", "symptome": "le WAL grossit sans checkpoint", "etat": "CONSTATE",
         "procedure": {"fichiers": ["tools/wal.py"]}},
        {"commit": "a2", "date": "2026-02-01", "symptome": "le hub ne redemarre pas", "etat": "PROUVE",
         "procedure": {"fichiers": ["tools/hub.py", "tools/disparu.py"]}},
        {"commit": "a3", "date": "2026-02-15", "symptome": "le WAL grossit encore", "etat": "INFIRME",
         "procedure": {"fichiers": ["tools/rag.py"]}},
        {"commit": "a4", "date": "2026-02-20", "symptome": "fichier retire depuis", "etat": "CONSTATE",
         "procedure": {"fichiers": ["tools/disparu.py"]}},
        {"commit": "a5", "date": "2026-02-25", "symptome": "recherche RAG hybride lente", "etat": "CONSTATE",
         "procedure": {"fichiers": ["tools/rag.py"]}},
        {"commit": "a6", "date": "2026-03-01", "symptome": "guide des veilles manquant", "etat": "CONSTATE",
         "procedure": {"fichiers": ["docs/guide.md"]}},
        {"commit": "a7", "date": "2026-03-02", "symptome": "", "etat": "CONSTATE",
         "procedure": {"fichiers": ["tools/wal.py"]}},
    ]
    oplog = tmp_path / "success_oplog.jsonl"
    oplog.write_text("\n".join(json.dumps(e) for e in entrees) + "\n{illisible\n", encoding="utf-8")
    return racine, oplog


def _lire(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_chemin_reel_cli_ecarts_dits_et_split_temporel(tmp_path):
    racine, oplog = _monde(tmp_path)
    out = tmp_path / "sortie"
    rc = ds.main(["--source", "oplog", "--oplog", str(oplog), "--root", str(racine),
                  "--out-dir", str(out), "--no-sanitize", "--holdout-frac", "0.25"])
    assert rc == 0
    m = json.loads((out / "manifest_oplog.json").read_text(encoding="utf-8"))
    assert m["entrees_lues"] == 8
    e = m["ecartees"]
    assert e["ligne_illisible"] == 1 and e["sans_symptome"] == 1
    assert e["infirme_jamais_positif"] == 1
    assert e["fichiers_sans_carte"] == 2 and e["entree_sans_fichier_vivant"] == 1
    assert m["entrees_retenues"] == 4  # a1, a2, a5, a6
    train, held = _lire(out / "oplog_train.jsonl"), _lire(out / "oplog_heldout.jsonl")
    assert [r["commit"] for r in held] == ["a6"]  # la plus recente
    assert {r["commit"] for r in train} == {"a1", "a2", "a5"}
    assert (m["train"], m["heldout"]) == (3, 1)


def test_infirme_jamais_positif_et_negatif_disjoint(tmp_path):
    racine, oplog = _monde(tmp_path)
    out = tmp_path / "sortie"
    ds.build_oplog(oplog, racine, out, sanitize=False, holdout_frac=0.25)
    recs = _lire(out / "oplog_train.jsonl") + _lire(out / "oplog_heldout.jsonl")
    assert all(r["etat"] != "INFIRME" for r in recs)
    for r in recs:
        assert r["negative"].split("\n", 1)[0] != r["positive"].split("\n", 1)[0]
    wal = next(r for r in recs if r["commit"] == "a1")
    assert wal["positive"].startswith("tools/wal.py\n") and "checkpoint" in wal["positive"]


def test_negatif_du_train_ne_vient_jamais_du_heldout(tmp_path):
    racine, oplog = _monde(tmp_path)
    out = tmp_path / "sortie"
    ds.build_oplog(oplog, racine, out, sanitize=False, holdout_frac=0.25)
    held_fichiers = {r["positive"].split("\n", 1)[0] for r in _lire(out / "oplog_heldout.jsonl")}
    for r in _lire(out / "oplog_train.jsonl"):
        assert r["negative"].split("\n", 1)[0] not in held_fichiers


def test_fichier_carrefour_jamais_positif_et_nomme(tmp_path):
    racine = tmp_path / "depot"
    (racine / "tools").mkdir(parents=True)
    (racine / "tools" / "ci.py").write_text('"""Liste des tests."""\n', encoding="utf-8")
    entrees = []
    for i in range(4):
        (racine / "tools" / f"m{i}.py").write_text(f'"""Module {i}."""\n', encoding="utf-8")
        entrees.append({"commit": f"c{i}", "date": f"2026-01-0{i + 1}", "symptome": f"symptome numero {i}",
                        "etat": "CONSTATE", "procedure": {"fichiers": ["tools/ci.py", f"tools/m{i}.py"]}})
    entrees.append({"commit": "c9", "date": "2026-01-09", "symptome": "seulement la liste",
                    "etat": "CONSTATE", "procedure": {"fichiers": ["tools/ci.py"]}})
    oplog = tmp_path / "oplog.jsonl"
    oplog.write_text("\n".join(json.dumps(e) for e in entrees) + "\n", encoding="utf-8")
    out = tmp_path / "sortie"
    m = ds.build_oplog(oplog, racine, out, sanitize=False, holdout_frac=0.0,
                       carrefour_frac=0.5, carrefour_min=3)
    assert m["fichiers_carrefour"] == {"tools/ci.py": 5}
    assert m["ecartees"]["fichiers_carrefour_retires"] == 5
    assert m["ecartees"]["entree_seulement_carrefour"] == 1
    recs = _lire(out / "oplog_train.jsonl")
    assert len(recs) == 4
    assert all(not r["positive"].startswith("tools/ci.py") for r in recs)


def test_carte_bornee_et_types_retenus(tmp_path):
    (tmp_path / "gros.py").write_text('"""' + "x" * 5000 + '"""\n', encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    assert len(ds._carte_fichier(tmp_path, "gros.py")) == ds.CARTE_MAX
    assert ds._carte_fichier(tmp_path, "image.png") is None
    assert ds._carte_fichier(tmp_path, "absent.py") is None


def test_traces_reste_le_mode_par_defaut(monkeypatch):
    appels = []
    monkeypatch.setattr(ds, "build", lambda *a, **k: appels.append("traces") or {})
    monkeypatch.setattr(ds, "build_oplog", lambda *a, **k: appels.append("oplog") or {})
    ds.main([])
    assert appels == ["traces"]
