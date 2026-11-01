"""NR : la soif pose un veto de sommeil BORNE pendant son examen, et le leve a la fin du cycle.

Mesure 26/10 (ordres du superviseur, UTC) : Hamilton reveillait NokidoEpistemicSoif puis la rendormait
~50 s plus tard (17:44:29Z->17:45:10Z, 17:54:32Z->17:55:29Z, 18:13:07Z->18:14:06Z) : l'examen, qui
reveille les piliers, n'avait pas le temps d'aboutir. Le veto (patron des executeurs, 2e63349f5) ne
couvre que l'acte : il est leve a la fin du cycle, examen fait, differe ou en echec.
"""
import sys
from pathlib import Path

_R = Path(__file__).resolve().parents[2]
for _p in (str(_R), str(_R / "tools"), str(_R / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_epistemic_daemon as ed  # noqa: E402
from nokido_agent.app import forge_resource_manager as rm  # noqa: E402  (le nom qu'emploie le demon)


def _espionner(monkeypatch):
    actes = []
    monkeypatch.setattr(rm, "poser_veto_sommeil",
                        lambda service, motif, duree_s=0: actes.append(("pose", service, duree_s)) or {"ok": True})
    monkeypatch.setattr(rm, "lever_veto_sommeil", lambda service: actes.append(("leve", service)) or True)
    return actes


def test_le_veto_est_pose_avant_le_reveil_des_piliers(monkeypatch):
    actes = _espionner(monkeypatch)
    monkeypatch.setattr(ed, "_reveiller_piliers", lambda: actes.append(("reveil",)) or (True, "ok"))
    assert ed._reveiller_piliers_sous_veto("demande manuelle") == (True, "ok")
    assert [a[0] for a in actes] == ["pose", "reveil"]
    assert actes[0][1] == ed.SERVICE_SOIF and 0 < actes[0][2] <= rm._VETO_SOMMEIL_MAX_S


def test_un_veto_impossible_n_empeche_pas_l_examen(monkeypatch):
    def casse(*a, **k):
        raise OSError("disque")

    monkeypatch.setattr(rm, "poser_veto_sommeil", casse)
    monkeypatch.setattr(ed, "_reveiller_piliers", lambda: (True, "ok"))
    assert ed._reveiller_piliers_sous_veto("echeance") == (True, "ok")


def test_le_cycle_leve_le_veto_meme_en_echec(monkeypatch, tmp_path):
    actes = _espionner(monkeypatch)
    monkeypatch.setattr(ed, "db_path", lambda: str(tmp_path / "e.db"))
    monkeypatch.setattr(ed, "_journal", lambda msg: None)
    monkeypatch.setattr(ed, "_beat", lambda *a, **k: None)

    def cycle_ko(conn):
        raise RuntimeError("pilier muet")

    monkeypatch.setattr(ed, "run_once", cycle_ko)
    assert ed.run(interval=60, once=True) == 4
    assert ("leve", ed.SERVICE_SOIF) in actes


def test_le_cycle_leve_le_veto_apres_un_examen(monkeypatch, tmp_path):
    actes = _espionner(monkeypatch)
    monkeypatch.setattr(ed, "db_path", lambda: str(tmp_path / "e.db"))
    monkeypatch.setattr(ed, "_journal", lambda msg: None)
    monkeypatch.setattr(ed, "_beat", lambda *a, **k: None)
    monkeypatch.setattr(ed, "run_once", lambda conn: {"examinees": 1, "gaps": 0, "veilles": 0,
                                                      "examen": "FAIT (demande manuelle)"})
    assert ed.run(interval=60, once=True) == 0
    assert ("leve", ed.SERVICE_SOIF) in actes


def test_les_nr_n_ecrivent_jamais_de_veto_dans_le_sandbox_vivant():
    """Mesure 26/10 20:34 : un pytest des NR de la soif a laisse sandbox/veto_sommeil/NokidoEpistemicSoif.json
    (motif « examen de la soif (nr) », pid du pytest mort) -- run_once pose le veto, seul run() le leve. Sous les
    NR, le repertoire des vetos est un temporaire (conftest), jamais celui que lit Hamilton."""
    vivant = (_R / "sandbox" / "veto_sommeil").resolve()
    assert rm._veto_dir().resolve() != vivant
    r = rm.poser_veto_sommeil("NR_SONDE_POLLUTION", "nr", 5)
    try:
        assert r.get("ok") and not (vivant / "NR_SONDE_POLLUTION.json").exists()
    finally:
        rm.lever_veto_sommeil("NR_SONDE_POLLUTION")


def test_lance_comme_le_demon_le_regulateur_est_importable(tmp_path):
    """Chemin REEL : `python tools/forge_epistemic_daemon.py` ne met que tools/ (+ ROOT) dans sys.path ;
    un `import forge_resource_manager` nu y echoue et le veto ne serait jamais pose (avale, journalise)."""
    import os
    import subprocess

    code = ("import sys; sys.path[:] = [r'%s'] + [p for p in sys.path if p not in ('', '.')]\n"
            "import forge_epistemic_daemon as d\n"
            "from nokido_agent.app import forge_resource_manager as r\n"
            "print(callable(r.poser_veto_sommeil) and callable(r.lever_veto_sommeil))") % (_R / "tools")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=25,  # sous le --timeout=30 de la suite (cliquet)
                       env=dict(os.environ, PYTHONNOUSERSITE="1"))
    assert r.returncode == 0, r.stderr[-400:]
    assert r.stdout.strip().endswith("True")
