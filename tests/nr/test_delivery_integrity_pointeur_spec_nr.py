"""NR 28/10 : `_scan_false_attestations` juge le pointeur de la DERNIERE enveloppe OK_DONE, pas un `commit:` en prose.

Cause mesuree le 28/10 sur 15 constats vivants (dette bug_delivery_integrity_faux_attestation_pointeur_spec) :
le premier `commit:` trouve n'importe ou dans le resultat etait juge. (A) l'agent recopiait le pointeur de la
consigne -> defaut de FORME (low), pas un mensonge prouve ; (B) un rapport « DEJA_FAIT (commit:<vieux sha>) »
citait la BONNE preuve d'anteriorite -> faux positif high. Le constat high reste pour une enveloppe OK_DONE qui
cite un sha anterieur DIFFERENT de celui de la consigne, consigne avec ou sans pointeur.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import forge_delivery_integrity as D  # noqa: E402

VIEUX = "2026-10-01T00:00:00+00:00"


def _base(tmp_path, monkeypatch, lignes):
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tasks (id TEXT, agent TEXT, created_at TEXT, status TEXT, description TEXT, "
                "result TEXT)")
    for i, (desc, res) in enumerate(lignes):
        con.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                    ("job_%d" % i, "AGENT", "2026-10-24T10:54:45", "done", desc, res))
    con.commit()
    con.close()
    monkeypatch.setattr(D, "TASKS_DB", db)
    monkeypatch.setattr(D, "_git", lambda *a, **k: VIEUX)
    return D._scan_false_attestations()


def test_pointeur_de_spec_recopie_est_low(tmp_path, monkeypatch):
    out = _base(tmp_path, monkeypatch, [(
        '{"intent":"REVIEW_FINDING","pointer_ref":"commit:dcd8de167"} RETOUR DE RELECTURE',
        'fait.\n{"intent":"OK_DONE","pointer_ref":"commit:dcd8de167"}')])
    assert [(f["kind"], f["severity"]) for f in out] == [("pointeur_spec_recopie", "low")]


def test_deja_fait_en_prose_n_est_pas_un_constat(tmp_path, monkeypatch):
    out = _base(tmp_path, monkeypatch, [(
        "Instruction des demandes owner",
        'demande_x : DEJA_FAIT (commit:110540b3, file:tools/x.py)\n'
        '{"intent":"OK_DONE","pointer_ref":"file:docs/rapport.md"}')])
    assert out == []


def test_sha_anterieur_different_reste_high(tmp_path, monkeypatch):
    out = _base(tmp_path, monkeypatch, [
        ('{"intent":"HANDOFF_NEXT","pointer_ref":"commit:aaaaaaa1"} consigne',
         '{"intent":"OK_DONE","pointer_ref":"commit:bbbbbbb2"}'),
        ("consigne sans pointeur", '{"intent":"OK_DONE","pointer_ref":"commit:ccccccc3"}')])
    assert [(f["kind"], f["severity"]) for f in out] == [("attestation_commit_anterieur", "high")] * 2


def test_enveloppe_echappee_est_lue(tmp_path, monkeypatch):
    out = _base(tmp_path, monkeypatch, [(
        "consigne", 'rapport\\n{\\"intent\\": \\"OK_DONE\\", \\"pointer_ref\\": \\"commit:ddddddd4\\"}')])
    assert [f["severity"] for f in out] == ["high"]


def test_commit_en_prose_sans_enveloppe_s_abstient(tmp_path, monkeypatch):
    out = _base(tmp_path, monkeypatch, [("consigne", "voir commit:eeeeeee5 pour le contexte")])
    assert out == []


def test_seule_la_derniere_enveloppe_compte(tmp_path, monkeypatch):
    out = _base(tmp_path, monkeypatch, [(
        '{"pointer_ref":"commit:fffffff6"}',
        '{"intent":"OK_DONE","pointer_ref":"commit:1111111a"} brouillon\n'
        '{"intent":"OK_DONE","pointer_ref":"commit:fffffff6"}')])
    assert [f["kind"] for f in out] == ["pointeur_spec_recopie"]
