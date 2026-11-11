# -*- coding: utf-8 -*-
"""NR (owner 3/11 « bilan de sante a 100 ») : les journaux d'organes sont DATES, et l'audit sait le lire.

Mesure du 3/11 : sur les 9 journaux actifs « sans horodatage », 3 etaient datés (`observed_at`, `horodatage`,
`generated_ts` en epoch) mais l'audit ne connaissait que la cle `ts` ; le videur porte son `ts` DANS le blob
chiffre (illisible par construction, pas sans date) ; loop_lag est fait de dumps faulthandler (C, non prefixables)
encadres d'un marqueur date. Les autres n'avaient vraiment aucune date : docker_boot_samples, success_oplog (jour
seul), la sortie standard du tray. Et un NR ecrivait ses journaux de test dans le VRAI sandbox/.
"""
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_health_diagnostic as H  # noqa: E402

_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _journal(root, rel, lignes):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return p


def _sans_date(root):
    return {u["path"] for u in H.audit_journal_timestamps(root)["undated"]}


def test_cles_de_date_epoch_reconnues(tmp_path):
    _journal(tmp_path, "sandbox/a.jsonl", [json.dumps({"observed_at": 1793725635.7, "x": i}) for i in range(5)])
    _journal(tmp_path, "sandbox/b.jsonl", [json.dumps({"horodatage": 1793725635.7}) for _ in range(5)])
    _journal(tmp_path, "logs/c.log", [json.dumps([{"generated_ts": 1793725635, "domain": "d"}]) for _ in range(5)])
    _journal(tmp_path, "logs/temoin.log", ["sans date %d" % i for i in range(5)])
    assert _sans_date(tmp_path) == {"logs/temoin.log"}   # temoin positif : un vrai sans-date reste compte


def test_journal_date_par_son_nom(tmp_path):
    _journal(tmp_path, "logs/nokido_20261031_141145.log", ["lancement sans date %d" % i for i in range(5)])
    _journal(tmp_path, "logs/nokido_temoin.log", ["lancement sans date %d" % i for i in range(5)])
    assert _sans_date(tmp_path) == {"logs/nokido_temoin.log"}


def test_journal_chiffre_declare_ecarte_et_compte(tmp_path):
    _journal(tmp_path, "sandbox/videur_identity.log", ["QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=|abc123" for _ in range(5)])
    r = H.audit_journal_timestamps(tmp_path)
    assert "sandbox/videur_identity.log" not in {u["path"] for u in r["undated"]}
    assert r["chiffres_dates_dedans"] == 1


def test_journal_par_blocs_date_par_son_marqueur(tmp_path):
    bloc = ['  File "x.py", line %d in f' % i for i in range(60)]
    _journal(tmp_path, "logs/loop_lag.log", (bloc + ["2026-11-03T18:00:00 [loop_lag] 1200 ms"]) * 3 + bloc[:30])
    assert "logs/loop_lag.log" not in _sans_date(tmp_path)


def test_journal_par_blocs_sans_marqueur_reste_sans_date(tmp_path):
    _journal(tmp_path, "logs/loop_lag.log", ['  File "x.py", line %d in f' % i for i in range(300)])
    assert "logs/loop_lag.log" in _sans_date(tmp_path)


def test_echantillon_de_boot_docker_date_et_anciens_conserves(tmp_path, monkeypatch):
    import forge_docker_keeper as K

    p = tmp_path / "docker_boot_samples.jsonl"
    p.write_text(json.dumps({"ram_pct": 50.0, "duration_s": 30.0}) + "\n", encoding="utf-8")
    monkeypatch.setattr(K, "BOOT_SAMPLES_PATH", p)
    K._record_boot_sample(42.0, 61.0)
    lignes = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lignes) == 2 and lignes[0] == {"ram_pct": 50.0, "duration_s": 30.0}   # l'ancien n'est pas re-date
    assert _ISO.search(lignes[1].get("ts", ""))
    assert K._load_boot_samples() == [(50.0, 30.0), (61.0, 42.0)]


def test_success_oplog_porte_l_horodatage_du_commit(tmp_path):
    import subprocess

    import forge_success_oplog as S

    # Depot temoin : le clone de la CI est superficiel, l'historique du depot n'y garantit aucun commit fix(.
    def git(*args):
        return subprocess.run(["git", "-c", "safe.directory=*", "-C", str(tmp_path), *args], capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=25, check=True).stdout.strip()

    git("init", "-q")
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    git("add", "f.txt")
    git("-c", "user.name=temoin", "-c", "user.email=temoin@example.invalid", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "fix(temoin): un correctif")
    sha = git("rev-parse", "HEAD")
    e = S.analyser_commit(sha, root=tmp_path)
    assert e is not None
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"])          # le champ historique ne change pas de forme
    assert _ISO.match(e["ts"]) and e["ts"].startswith(e["date"])


def test_flux_horodate_date_chaque_ligne():
    from forge_timecode import FluxHorodate

    brut = io.StringIO()
    f = FluxHorodate(brut)
    f.write("[tray] un\n[tray] de")
    f.write("ux\n")
    f.flush()
    lignes = brut.getvalue().splitlines()
    assert len(lignes) == 2
    assert all(_ISO.match(l) for l in lignes)
    assert lignes[1].endswith("[tray] deux")


def test_le_nr_du_logger_n_ecrit_plus_dans_le_vrai_sandbox():
    src = (ROOT / "tests" / "nr" / "test_new_tools_nr.py").read_text(encoding="utf-8")
    assert "sandbox/test_" not in src
