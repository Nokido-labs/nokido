"""NR -- la garde CLOS est branchee sur l'ecrivain REEL du tableau noir (apply_fact_sync -> apply_fact).

Observation par defaut : un CLOS sans preuve est journalise (motif nomme) ET ecrit. NOKIDO_CLOS_GATE=enforce refuse.
"""
# pylint: disable=protected-access
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from nokido_agent.app import forge_swarm_blackboard as B  # noqa: E402


def _prep(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "_DB", tmp_path / "swarm.db")
    monkeypatch.setattr(B, "_writer_conn", None)
    B.init_db()
    journal = tmp_path / "refus.log"
    monkeypatch.setattr(B._keeper(), "CLOS_JOURNAL", journal)
    monkeypatch.delenv("NOKIDO_CLOS_GATE", raising=False)
    return journal


def _ecrit(texte, cat="roadmap"):
    return B.apply_fact_sync("architecture_rules", texte, category=cat, key="k_clos", ring=1, source="nr")


def _valeur():
    return [r["value"] for r in B.read_zone("architecture_rules") if r["key"] == "k_clos"]


def test_clos_sans_sha_journalise_et_ecrit(tmp_path, monkeypatch):
    journal = _prep(tmp_path, monkeypatch)
    assert _ecrit("[CLOS] fini")["ok"]
    assert _valeur() == ["[CLOS] fini"]
    assert "aucun sha" in journal.read_text(encoding="utf-8")


def test_clos_avec_preuve_aucune_ligne(tmp_path, monkeypatch):
    journal = _prep(tmp_path, monkeypatch)
    # safe.directory : sous le compte du bac a sable, le depot appartient a un autre utilisateur et
    # `git rev-parse` rendait VIDE (mesure 24/10) -- le test envoyait alors un CLOS sans sha.
    sha = subprocess.run(["git", "-c", "safe.directory=*", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                         text=True, errors="replace").stdout.strip()[:12]
    assert len(sha) == 12, "sha HEAD illisible : la preuve ne peut pas etre construite"
    txt = "[CLOS] %s tests/nr/test_roadmap_clos_exige_preuve_nr.py" % sha
    assert _ecrit(txt)["ok"]
    assert _valeur() == [txt]
    assert not journal.exists() or journal.read_text(encoding="utf-8") == ""


def test_hors_roadmap_non_garde(tmp_path, monkeypatch):
    journal = _prep(tmp_path, monkeypatch)
    assert _ecrit("[CLOS] fini", cat="autre")["ok"]
    assert not journal.exists()


def test_enforce_refuse(tmp_path, monkeypatch):
    journal = _prep(tmp_path, monkeypatch)
    monkeypatch.setenv("NOKIDO_CLOS_GATE", "enforce")
    r = _ecrit("[CLOS] fini")
    assert not r.get("ok") and "CLOS" in r.get("error", "")
    assert _valeur() == []
    assert journal.exists()
