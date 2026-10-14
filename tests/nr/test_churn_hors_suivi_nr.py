"""NR -- aucun ecrivain d'EXECUTION ne reecrit un fichier suivi par git (decision owner du 2026-10-14).

Mesure : l'arbre partage n'etait jamais propre -- le hook post-commit reecrivait docs/skills/nokido/SKILL.md apres
CHAQUE commit (et y accumulait des centaines de lignes vides), forge_backend_power reecrivait sandbox/backend_use_*.ts,
la campagne UI incrementait sandbox/ui_campaign/routes_instables.json a chaque passe. La CI refusait alors de rattacher
son verdict a un SHA. Le registre des routes RESTE suivi (exception mesuree du 17/09 : sans lui, le runner rendait un
faux vert sur une passe) -- seule sa LISTE l'est, les compteurs vivent dans une annexe ignoree.
"""
from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "tools"), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def test_gitignore_couvre_les_etats_d_execution_et_garde_l_exception_du_17_09():
    regles = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "sandbox/backend_use_*.ts" in regles and "docs/skills/nokido/JOURNAL_COMMITS.md" in regles
    assert "!sandbox/ui_campaign/routes_instables.json" in regles     # le runner doit voir la liste


def test_le_marqueur_de_backend_tombe_sous_la_regle():
    import forge_backend_power as B

    assert fnmatch.fnmatch("sandbox/" + B._use_marker("ollama").name, "sandbox/backend_use_*.ts")


def test_la_liste_suivie_ne_bouge_que_si_une_route_nouvelle_entre(tmp_path, monkeypatch):
    import forge_ui_campaign as C

    monkeypatch.setattr(C, "_REGISTRE_INSTABLES", tmp_path / "routes_instables.json")
    monkeypatch.setattr(C, "_COMPTEURS_INSTABLES", tmp_path / "routes_instables_compteurs.json")
    C._ecrire_registre({"/a": 3, "/b": 1})
    suivi = (tmp_path / "routes_instables.json").read_bytes()
    assert json.loads(suivi) == {"/a": 1, "/b": 1}
    C._ecrire_registre({"/a": 4, "/b": 2})                       # memes routes, compteurs differents
    assert (tmp_path / "routes_instables.json").read_bytes() == suivi
    assert C._lire_registre() == {"/a": 4, "/b": 2}               # les compteurs ne sont jamais perdus
    C._ecrire_registre({"/a": 4, "/b": 2, "/c": 1})               # une route NOUVELLE : la liste change
    assert json.loads((tmp_path / "routes_instables.json").read_text(encoding="utf-8")) == {"/a": 1, "/b": 1, "/c": 1}


def test_sans_annexe_le_runner_rejoue_quand_meme_toute_la_liste(tmp_path, monkeypatch):
    import forge_ui_campaign as C

    monkeypatch.setattr(C, "_REGISTRE_INSTABLES", tmp_path / "routes_instables.json")
    monkeypatch.setattr(C, "_COMPTEURS_INSTABLES", tmp_path / "absente.json")
    (tmp_path / "routes_instables.json").write_text(json.dumps({"/a": 1, "/b": 1}), encoding="utf-8")
    assert set(C.routes_a_rejouer([], C._lire_registre())) == {"/a", "/b"}


def test_le_journal_post_commit_va_en_annexe_sans_lignes_vides(tmp_path, monkeypatch):
    import forge_post_commit as P

    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "_get_commit_sha", lambda: "abc1234")
    monkeypatch.setattr(P, "_get_commit_msg", lambda: "fix(x): essai")
    (tmp_path / "app").mkdir()
    for _ in range(3):
        P.update_skill_md([tmp_path / "app" / "forge_x.py"])
    journal = (tmp_path / "docs" / "skills" / "nokido" / "JOURNAL_COMMITS.md").read_text(encoding="utf-8")
    assert journal.count("## Commit abc1234") == 3 and "\n\n\n" not in journal
    assert not (tmp_path / "docs" / "skills" / "nokido" / "SKILL.md").exists()
