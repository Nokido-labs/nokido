# -*- coding: utf-8 -*-
"""NR 7/11 : (1) `task assign` accepte `contrat` -> marqueur [LIVRABLE_CONTRAT] dans la consigne, et AVERTIT (jamais ne
refuse) si une tache de code n'en porte pas ; (2) `read action=file` accepte offset/limit (lignes, 1-indexees), hors
bornes = message explicite, compatible si_etag. Mesure 7 jours tasks.db : 4 taches sur 324 portaient le marqueur."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app import forge_mcp_registry as mr  # noqa: E402


def test_contrat_ecrit_le_marqueur_lu_par_le_juge():
    from tools.forge_task_executor import _contrat_livrable
    desc, av = mr._poser_contrat_livrable("faire x", {"contrat": {"type": "fichier", "chemins": ["a.py"]}}, "code")
    assert "[LIVRABLE_CONTRAT]" in desc and av is None
    assert _contrat_livrable(desc) == {"type": "fichier", "chemins": ["a.py"]}


def test_contrat_chaine_simple_et_livrable_historique():
    d1, _ = mr._poser_contrat_livrable("x", {"contrat": "commit"}, "code")
    assert "commit" in d1
    d2, a2 = mr._poser_contrat_livrable("x", {"livrable": {"type": "aucun"}}, "code")
    assert "[LIVRABLE_CONTRAT]" in d2 and a2 is None


def test_tache_de_code_sans_contrat_avertit_sans_refuser():
    desc, av = mr._poser_contrat_livrable("modifier app/x.py", {}, "code")
    assert desc == "modifier app/x.py"
    assert av and "contrat" in av


def test_tache_hors_code_ne_dit_rien():
    desc, av = mr._poser_contrat_livrable("resume ceci", {}, "task_assign")
    assert desc == "resume ceci" and av is None


def test_contrat_invalide_avertit_et_n_ecrit_pas():
    desc, av = mr._poser_contrat_livrable("x", {"contrat": {"type": "zzz"}}, "code")
    assert "[LIVRABLE_CONTRAT]" not in desc and av


def test_schema_declare_contrat_et_fenetre():
    src = Path(mr.__file__).read_text(encoding="utf-8")
    assert '"contrat"' in src and '"offset"' in src


def _base_taches():
    import sqlite3

    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY)")
    c.execute("INSERT INTO tasks(id) VALUES ('t1')")
    return c


def test_derogation_critique_posee_pour_ring_1_seul():
    c = _base_taches()
    assert mr._poser_derogation_critique(c, "t1", {"allow_critical": True}, 1) is True
    assert c.execute("SELECT allow_critical FROM tasks WHERE id='t1'").fetchone()[0] == 1
    assert mr._poser_derogation_critique(c, "t1", {"allow_critical": True}, 1) is True


def test_derogation_critique_refusee_ring_2_et_absente_par_defaut():
    c = _base_taches()
    assert mr._poser_derogation_critique(c, "t1", {"allow_critical": True}, 2) is False
    assert mr._poser_derogation_critique(c, "t1", {}, 0) is False
    assert "allow_critical" not in [r[1] for r in c.execute("PRAGMA table_info(tasks)")]


def _lire(tmp_path, **kw):
    (tmp_path / "f.txt").write_text("\n".join(f"l{i}" for i in range(1, 11)), encoding="utf-8")
    reg = mr.ToolRegistry(root_dir=tmp_path)
    args = {"action": "file", "path": "f.txt", **kw}
    return asyncio.run(reg.handle_read(args, "CLAUDE", 0))


def test_read_offset_limit(tmp_path):
    out = _lire(tmp_path, offset=3, limit=2)
    assert "l3\nl4" in out and "l5" not in out and "l2" not in out
    assert "3-4" in out and "10" in out


def test_read_hors_bornes_explicite(tmp_path):
    out = _lire(tmp_path, offset=50)
    assert out.strip() and "10 lignes" in out


def test_read_sans_fenetre_inchange(tmp_path):
    assert _lire(tmp_path) == "\n".join(f"l{i}" for i in range(1, 11))


def test_read_fenetre_avec_si_etag(tmp_path):
    out = _lire(tmp_path, offset=1, limit=2, si_etag="0")
    assert "etag:" in out and "l1" in out
