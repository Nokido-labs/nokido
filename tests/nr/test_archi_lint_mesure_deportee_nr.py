"""NR -- archi-lint juge une mesure DEPORTEE faite sous le compte owner (decision owner 18/10).

Cause mesuree le 18/10 : semgrep initialise sa telemetrie au demarrage (ca-certs, `CertOpenSystemStore(0, "ROOT")`,
lib/ca_certs.ml:87) et meurt sous les comptes du hub, sans profil utilisateur -- `--metrics=off` n'y change rien, la
1.172.0 non plus (essai job_1ecb7614640a), et les mainteneurs ne corrigeront pas (semgrep#11525). Le gate restait
ANERGIQUE depuis 49 j sur un domaine critique. Decision owner : semgrep tourne sous SON compte (tache planifiee),
`forge_archi_lint --ecrire-mesure` ecrit un rapport DATE, et la CI le juge s'il a moins de 7 j -- comme pip-audit.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ci_local as ci  # noqa: E402
import forge_archi_lint as al  # noqa: E402


def _semgrep_json(scannes, severites):
    return {"paths": {"scanned": ["f%d.py" % i for i in range(scannes)]},
            "results": [{"extra": {"severity": s}, "check_id": "r", "path": "x", "start": {"line": 1}}
                        for s in severites], "errors": []}


def _jour(decalage=0):
    return (dt.date.today() - dt.timedelta(days=decalage)).isoformat()


def test_resume_dit_le_verdict_et_refuse_zero_fichier():
    r = al.resume_mesure(_semgrep_json(3, ["ERROR", "WARNING"]), jour=_jour(), sha="abc")
    assert r["fichiers_scannes"] == 3 and r["findings"] == {"ERROR": 1, "WARNING": 1}
    assert r["ok"] is False and r["sha"] == "abc" and r["jour"] == _jour()
    assert al.resume_mesure(_semgrep_json(3, ["WARNING"]), jour=_jour(), sha="abc")["ok"] is True
    assert al.resume_mesure(_semgrep_json(0, []), jour=_jour(), sha="abc") is None, "0 fichier lu n'est pas une mesure"


def test_mesure_fraiche_ecrite_puis_jugee_par_la_ci(tmp_path):
    p = al.ecrire_mesure(al.resume_mesure(_semgrep_json(5, ["ERROR"]), jour=_jour(), sha="abc"), tmp_path)
    assert p.name == "archi_lint_%s.json" % _jour() and json.loads(p.read_text(encoding="utf-8"))["ok"] is False
    frais, ok, detail = ci._mesure_archi_lint_deportee(dossier=tmp_path)
    assert frais is True and ok is False and "deportee" in detail


def test_la_plus_recente_gagne_et_le_perime_se_dit(tmp_path):
    al.ecrire_mesure(al.resume_mesure(_semgrep_json(5, ["ERROR"]), jour=_jour(20), sha="v"), tmp_path)
    frais, ok, detail = ci._mesure_archi_lint_deportee(dossier=tmp_path)
    assert frais is False and ok is None and "perime" in detail
    al.ecrire_mesure(al.resume_mesure(_semgrep_json(5, []), jour=_jour(1), sha="n"), tmp_path)
    frais, ok, _ = ci._mesure_archi_lint_deportee(dossier=tmp_path)
    assert frais is True and ok is True


def test_absent_n_est_ni_frais_ni_vert(tmp_path):
    frais, ok, detail = ci._mesure_archi_lint_deportee(dossier=tmp_path / "rien")
    assert frais is False and ok is None and "aucun" in detail


def test_meme_perimetre_que_golden_rules():
    """1re mesure owner (18/10) : 158 findings dont une large part dans app/_attic (code archive), que golden-rules
    (memes six regles, moteur AST) EXCLUT. Deux moteurs pour les memes regles = un seul perimetre."""
    import forge_golden_rules_ast as gr

    assert "_attic" in gr._SKIP_DIRS
    assert set(al.EXCLUSIONS) >= {"_attic"}
    src = (ROOT / "tools" / "forge_archi_lint.py").read_text(encoding="utf-8")
    assert '"--exclude"' in src and "EXCLUSIONS" in src[src.index("def main"):]


def test_la_branche_semgrep_inutilisable_juge_la_mesure_deportee():
    """Chemin reel : la branche ou semgrep ne demarre pas sous ce compte appelle la mesure deportee et
    inscrit son verdict dans `results` (sinon le registre de vitalite ne voit jamais de verdict reel)."""
    src = (ROOT / "tools" / "ci_local.py").read_text(encoding="utf-8")
    bloc = src[src.index("# ── archi-lint Golden Rules"):src.index("# ── golden-rules cliquet")]
    assert "_mesure_archi_lint_deportee()" in bloc
    assert 'results.append(("archi-lint (Golden Rules)"' in bloc
