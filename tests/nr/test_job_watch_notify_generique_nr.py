# -*- coding: utf-8 -*-
"""NR — le facteur de fin de job sait finir sur le TEMOIN EXTERNE, pas seulement sur un audit.

__FORGE_COLOR__ = "immunitaire/guard : non-regression de la notification de fin de job"

CE QUI A ETE PAYE (2026-09-06). `forge_job_watch_notify` existait, et servait exactement a
ca : observer un job deporte et notifier l'agent DANS SA BOUCLE a la fin. Il n'a pas ete
utilise de la soiree -- une dizaine de runs de CI locale ont ete suivis par polling manuel,
un appel toutes les cent secondes. Trois raisons, toutes reelles :

  1. il exigeait `--refined` et `--report`, propres a un audit swarm : un job de CI n'en
     produit aucun, donc la commande refusait de demarrer ;
  2. il ne terminait que sur `phase == "done"` dans le progress -- un signal que les jobs
     de CI n'ecrivent JAMAIS (ils ecrivent `etape`, et deposent un `.rc`). Un guetteur
     poste devant une porte que personne n'emprunte ;
  3. le parametre `notify_agent` de `run_job`, qui aurait du suffire, est accepte par le
     schema mais n'a EMIS AUCUN message : mesure du jour, job termine `rc=0`, zero ligne
     vers CLAUDE dans `agent_messages`. Un mecanisme present et non cable est une dette,
     jamais une securite.

Et le defaut etait DEJA consigne : la docstring de `forge_job_progress` note, au
2026-09-03, « un run de CI locale a ete suivi a l'aveugle, par polling du log_tail, alors
qu'un champ prevu pour ca existait ». La note n'a pas suffi -- d'ou ces tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_job_watch_notify as w  # noqa: E402


class _Args:
    def __init__(self, **kw):
        self.progress = kw.get("progress", "")
        self.refined = kw.get("refined")
        self.report = kw.get("report")
        self.rc = kw.get("rc")
        self.job = kw.get("job", "job_test")


def test_le_rc_absent_ne_vaut_pas_zero(tmp_path):
    """Trois etats : absent et illisible rendent None, jamais une valeur inventee."""
    assert w._lire_rc(None) is None
    assert w._lire_rc(str(tmp_path / "inexistant.rc")) is None
    f = tmp_path / "j.rc"
    f.write_text("0", encoding="utf-8")
    assert w._lire_rc(str(f)) == "0"
    f.write_text("1\n", encoding="utf-8")
    assert w._lire_rc(str(f)) == "1", "le retour doit etre nettoye de son saut de ligne"


def test_un_job_sans_audit_produit_quand_meme_un_resume(tmp_path):
    """`--refined` absent ne doit plus empecher le facteur de resumer."""
    prog = tmp_path / "p.json"
    prog.write_text('{"etape": "pytest (suite pure)"}', encoding="utf-8")
    rc = tmp_path / "j.rc"
    rc.write_text("0", encoding="utf-8")
    a = _Args(progress=str(prog), rc=str(rc), job="job_ci")
    texte = w._summary("rc", a)
    assert "VERT" in texte and "rc=0" in texte, texte
    assert "job_ci" in texte
    assert "pytest (suite pure)" in texte, "la derniere etape porte l'information utile"


def test_un_rc_non_nul_est_annonce_ROUGE(tmp_path):
    prog = tmp_path / "p.json"
    prog.write_text('{"etape": "duplication"}', encoding="utf-8")
    rc = tmp_path / "j.rc"
    rc.write_text("1", encoding="utf-8")
    texte = w._summary("rc", _Args(progress=str(prog), rc=str(rc)))
    assert "ROUGE" in texte and "rc=1" in texte, texte


def test_un_rc_INCONNU_est_dit_et_non_transforme_en_vert(tmp_path):
    """Le piege qui compte : « je n'ai pas pu lire » ne doit pas se lire « tout va bien »."""
    prog = tmp_path / "p.json"
    prog.write_text("{}", encoding="utf-8")
    texte = w._summary("rc", _Args(progress=str(prog), rc=None))
    assert "INCONNU" in texte, texte
    assert "VERT" not in texte


def test_le_resume_d_audit_reste_intact(tmp_path, monkeypatch):
    """La generalisation ne doit pas abimer le cas d'origine."""
    monkeypatch.setattr(w, "_count_verdicts", lambda _p: {
        "total": 5, "real": 2, "fp": 3, "unc": 0, "sevtxt": "high:2", "tops": ["X"]})
    a = _Args(progress=str(tmp_path / "p.json"), refined="r.jsonl", report="R.md")
    texte = w._summary("done", a)
    assert "Findings raffinés=5" in texte and "REELS=2" in texte
    assert "R.md" in texte


@pytest.mark.parametrize("option", ["--rc", "--refined", "--report"])
def test_les_options_du_facteur_restent_declarees(option):
    """Si `--rc` disparait, le facteur redevient aveugle aux jobs de CI."""
    src = (ROOT / "tools" / "forge_job_watch_notify.py").read_text(encoding="utf-8")
    assert f'"{option}"' in src, f"{option} a disparu de l'interface"


def test_la_fin_par_le_rc_est_bien_cablee_dans_la_boucle():
    """Une option declaree mais jamais consultee serait une dette, pas une capacite.

    C'est precisement ce qui a ete mesure sur `notify_agent` le meme jour : parametre
    accepte, aucun message emis.
    """
    import ast

    src = (ROOT / "tools" / "forge_job_watch_notify.py").read_text(encoding="utf-8")
    arbre = ast.parse(src)
    principale = next(n for n in ast.walk(arbre)
                      if isinstance(n, ast.FunctionDef) and n.name == "main")
    appels = [n for n in ast.walk(principale)
              if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_lire_rc"]
    assert appels, "_lire_rc doit etre APPELE dans la boucle, pas seulement defini"
