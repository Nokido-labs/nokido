"""NR 19/10 -- le reconciliateur integre aussi une SAUVEGARDE d'executeur (sandbox/sauvegardes_executeurs/<agent>/<tache>/).

Mesure du 19/10 : d31564f96 sauve tout travail qu'aucun commit ne garde (OPENCODE_GPTOSS job_c67eb508, OPENCODE_NEMOTRON
job_d4e2061c : commits refuses par un faux rouge du scorecard, ou agent muet 300 s) -- mais rien ne savait l'INTEGRER :
la livraison mutation (1ad5425fd) a ete recopiee a la main bloc par bloc. Contrat de
`reconcilier_sauvegarde(dossier, fichiers_nommes, apply=False, ..., root=None)` :
  1. les fichiers du MANIFESTE x les fichiers NOMMES (memes regles que --commit : hors consigne ecartes et dits) ;
  2. dry-run par defaut : rien n'est ecrit ;
  3. un fichier nomme absent de la sauvegarde -> ABANDON avant toute ecriture ;
  4. apply : copie, `git add`, commit citant la tache d'origine ; commit refuse -> arbre remis a l'etat d'alpha ;
  5. la porte CLI `--sauvegarde DIR` existe (chemin reel).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


_JOURNAL_TEST = {}


def _module():
    spec = importlib.util.spec_from_file_location("forge_merge_gate_sauvegarde_nr", ROOT / "tools" / "forge_merge_gate.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(m)
    if "f" in _JOURNAL_TEST:
        m.JOURNAL_ARENE = _JOURNAL_TEST["f"]   # 19/10 : jamais le vrai journal de l'arene (faux constat fabrique)
    return m


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _journal_arene_isole(tmp_path):
    _JOURNAL_TEST["f"] = tmp_path / "arene.jsonl"
    yield
    _JOURNAL_TEST.clear()


def _sauvegarde(tmp_path, fichiers):
    d = tmp_path / "sauvegarde" / "OPENCODE_X" / "job_abc"
    for rel, texte in fichiers.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(texte, encoding="utf-8")
    (d / "manifeste.json").write_text(json.dumps({"tache": "job_abc", "agent": "OPENCODE_X",
                                                  "fichiers": sorted(fichiers)}), encoding="utf-8")
    return d


def _faux_git(appels, commit_rc=0):
    def faux(args, cwd=None):
        appels.append(list(args))
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return 0, "alpha", ""
        if args[:3] == ["diff", "--cached", "--quiet"]:
            return 1, "", ""
        if args[:2] == ["cat-file", "-e"]:
            return (0, "", "") if args[2] == "HEAD:app/a.py" else (1, "", "")
        if args and args[0] == "commit":
            return commit_rc, "", "" if commit_rc == 0 else "[gate] REFUS : test\n"
        return 0, "", ""
    return faux


def _depot(tmp_path):
    r = tmp_path / "depot"
    (r / "app").mkdir(parents=True)
    (r / "app" / "a.py").write_text("ANCIEN\n", encoding="utf-8")
    return r


def test_dry_run_n_ecrit_rien_et_ecarte_le_hors_consigne(tmp_path, monkeypatch):
    m = _module()
    appels = []
    monkeypatch.setattr(m, "_git", _faux_git(appels))
    d = _sauvegarde(tmp_path, {"app/a.py": "NEUF\n", "tools/x.py": "RESTE\n"})
    depot = _depot(tmp_path)
    r = m.reconcilier_sauvegarde(str(d), ["app/a.py"], apply=False, root=depot)
    assert r["plan"]["a_integrer"] == ["app/a.py"] and r["plan"]["hors_consigne"] == ["tools/x.py"]
    assert (depot / "app" / "a.py").read_text(encoding="utf-8") == "ANCIEN\n"
    assert not any(a and a[0] in ("add", "commit", "checkout") for a in appels)


def test_un_fichier_nomme_absent_de_la_sauvegarde_abandonne_avant_ecriture(tmp_path, monkeypatch):
    m = _module()
    monkeypatch.setattr(m, "_git", _faux_git([]))
    d = _sauvegarde(tmp_path, {"app/a.py": "NEUF\n"})
    (d / "app" / "a.py").unlink()
    depot = _depot(tmp_path)
    r = m.reconcilier_sauvegarde(str(d), ["app/a.py"], apply=True, root=depot)
    assert r["decision"].startswith("ABANDON") and r["applique"] is False
    assert (depot / "app" / "a.py").read_text(encoding="utf-8") == "ANCIEN\n"


def test_apply_copie_indexe_et_cite_la_tache(tmp_path, monkeypatch):
    m = _module()
    appels = []
    monkeypatch.setattr(m, "_git", _faux_git(appels))
    d = _sauvegarde(tmp_path, {"app/a.py": "NEUF\n", "docs/n.md": "RAPPORT\n"})
    depot = _depot(tmp_path)
    r = m.reconcilier_sauvegarde(str(d), ["app/a.py", "docs/n.md"], apply=True, agent="OPENCODE_X", sujet="lot",
                                 root=depot)
    assert r["applique"] is True, r
    assert (depot / "app" / "a.py").read_text(encoding="utf-8") == "NEUF\n"
    assert (depot / "docs" / "n.md").read_text(encoding="utf-8") == "RAPPORT\n"
    assert any(a[:1] == ["add"] and "docs/n.md" in a for a in appels), appels
    commit = [a for a in appels if a and a[0] == "commit"][0]
    assert any("job_abc" in x for x in commit), commit


def test_commit_refuse_remet_l_arbre(tmp_path, monkeypatch):
    m = _module()
    appels = []
    monkeypatch.setattr(m, "_git", _faux_git(appels, commit_rc=1))
    d = _sauvegarde(tmp_path, {"app/a.py": "NEUF\n", "docs/n.md": "RAPPORT\n"})
    r = m.reconcilier_sauvegarde(str(d), ["app/a.py", "docs/n.md"], apply=True, root=_depot(tmp_path))
    assert r["applique"] is False and "remis" in r["decision"]
    assert any(a[:2] == ["checkout", "HEAD"] for a in appels) and any(a and a[0] == "rm" for a in appels), appels


def test_un_dossier_relatif_se_lit_contre_la_racine(tmp_path, monkeypatch):
    """19/10 ~21 h 25, premier usage reel : « manifeste illisible (FileNotFoundError) » -- le chemin relatif etait lu
    contre le cwd du hub (meme faute que la liste --impacte, 045efbda8)."""
    m = _module()
    monkeypatch.setattr(m, "_git", _faux_git([]))
    depot = _depot(tmp_path)
    d = _sauvegarde(depot, {"app/a.py": "NEUF\n"})
    ailleurs = tmp_path / "cwd_du_hub"
    ailleurs.mkdir()
    monkeypatch.chdir(ailleurs)
    r = m.reconcilier_sauvegarde(str(d.relative_to(depot)), ["app/a.py"], apply=False, root=depot)
    assert r["decision"].startswith("DRY-RUN"), r


def test_la_porte_cli_sauvegarde_existe(tmp_path, monkeypatch, capsys):
    m = _module()
    monkeypatch.setattr(m, "_git", _faux_git([]))
    d = _sauvegarde(tmp_path, {"app/a.py": "NEUF\n"})
    monkeypatch.setattr(sys, "argv", ["forge_merge_gate.py", "--sauvegarde", str(d), "--fichiers", "app/a.py"])
    assert m.main() == 0
    assert "DRY-RUN" in capsys.readouterr().out
