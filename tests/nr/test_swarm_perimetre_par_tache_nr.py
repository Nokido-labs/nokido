"""NR : perimetre de lecture du swarm defini par la tache (fichiers pointes + cites), jamais un dossier."""
import sqlite3

import tools.forge_cli_swarm as sw


def _env(base, monkeypatch, description="rien"):
    root = base / "repo"
    (root / "tools").mkdir(parents=True)
    (root / "sandbox").mkdir()
    for n in ("pointe", "autre", "cite"):
        (root / "tools" / (n + ".py")).write_text("# %s\n" % n, encoding="utf-8")
    db = root / "sandbox" / "tasks.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, description TEXT, result TEXT)")
    con.execute("INSERT INTO tasks VALUES ('t1', ?, '')", (description,))
    con.commit()
    con.close()
    monkeypatch.setattr(sw, "ROOT", root)
    monkeypatch.setattr(sw, "TASKS_DB", db)
    monkeypatch.setattr(sw, "RACINES_LECTURE", [root / "sandbox" / "workspace", root / "docs"])
    return root


def _lire(autorises, chemin):
    return sw._outils_lecture(autorises)["lire_fichier"](chemin)


def test_fichier_pointe_lisible_autre_refuse(tmp_path, monkeypatch):
    root = _env(tmp_path, monkeypatch)
    aut = sw._perimetre_pointeurs([str(root / "tools" / "pointe.py")])
    assert "# pointe" in _lire(aut, str(root / "tools" / "pointe.py"))
    assert _lire(aut, str(root / "tools" / "autre.py")).startswith("refus")


def test_fichier_cite_par_tache_pointee(tmp_path, monkeypatch):
    cite = (tmp_path / "repo" / "tools" / "cite.py").as_posix()
    root = _env(tmp_path, monkeypatch, "voir %s et C:/Windows/system.ini" % cite)
    aut = sw._perimetre_pointeurs(["tasks.db:t1"])
    assert "# cite" in _lire(aut, str(root / "tools" / "cite.py"))
    assert _lire(aut, str(root / "tools" / "autre.py")).startswith("refus")
    assert not any("system.ini" in a for a in aut)


def test_traversee_refusee(tmp_path, monkeypatch):
    root = _env(tmp_path, monkeypatch)
    aut = sw._perimetre_pointeurs([str(root / "tools" / "pointe.py")])
    assert "refus" in _lire(aut, "tools/../tools/pointe.py")


def test_dossier_pointe_refuse(tmp_path, monkeypatch):
    root = _env(tmp_path, monkeypatch)
    aut = sw._perimetre_pointeurs([str(root / "tools")])
    assert aut == []
    assert _lire(aut, str(root / "tools" / "autre.py")).startswith("refus")


def test_fichier_designe_introuvable(tmp_path, monkeypatch):
    root = _env(tmp_path, monkeypatch)
    f = root / "tools" / "fantome.py"
    assert _lire([str(f.resolve())], str(f)) == "refus : fichier introuvable"
