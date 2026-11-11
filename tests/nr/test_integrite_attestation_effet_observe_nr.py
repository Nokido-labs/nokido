"""NR 7/11 : une attestation n'est accusee `high` que si le sha est etranger a la consigne ET qu'aucun livrable n'est observe.

Mesure du 7/11 (job_e0f6498bb5d5) : 19 `attestation_commit_anterieur` en high ; sur 12 relues, 11 citaient un sha
present EN CLAIR dans leur consigne (« CI de reference 50221f9ca ») et 11 portaient `[effet observe] commits produits :
1`. `_scan_false_attestations` ne reconnaissait un pointeur recopie que sous la forme `commit:<sha>`.
Regles : le texte de l'EXECUTEUR fait foi (tete `[effet observe] ... | <prose>`), jamais la prose de l'agent ; marqueur
absent = on ne conclut pas (UNKNOWN != NO) : le signal est garde tel quel, sans etre aggrave.
Chemin reel : `scan()`, sur une base de taches et une base de constats JETABLES (jamais la base vivante).
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from nokido_agent.app import forge_delivery_integrity as D  # noqa: E402

VIEUX = "2026-10-01T00:00:00+00:00"   # commit cite : anterieur a la creation de chaque tache
SHA = "50221f9ca"
EFFET = "[effet observe] commits produits : %s (aaaa111..bbbb222) ; fichiers non commites : 0"
OK = '{"intent":"OK_DONE","pointer_ref":"commit:%s"}'


def _scan(tmp_path, monkeypatch, lignes):
    db = tmp_path / "tasks.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE tasks (id TEXT, agent TEXT, created_at TEXT, status TEXT, description TEXT, "
                "result TEXT)")
    for tid, desc, res in lignes:
        con.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?)",
                    (tid, "AGENT", "2026-10-24T10:54:45", "done", desc, res))
    con.commit()
    con.close()
    monkeypatch.setattr(D, "TASKS_DB", db)
    monkeypatch.setattr(D, "DB", tmp_path / "constats.db")   # jamais la base partagee
    monkeypatch.setattr(D, "_git", lambda *a, **k: VIEUX)
    for nom in ("_scan_attestation_contredite", "_scan_stale_queue", "_scan_unpushed", "_scan_uncommitted",
                "_scan_submodule_drift", "_scan_ci_failures"):
        monkeypatch.setattr(D, nom, lambda: [])
    return {f["target"].split(":")[0]: (f["kind"], f["severity"]) for f in D.scan()["findings"]}


def test_sha_cite_en_clair_dans_la_consigne_n_est_pas_une_accusation(tmp_path, monkeypatch):
    out = _scan(tmp_path, monkeypatch, [
        ("job_clair", "Relire la CI de reference %s puis corriger" % SHA, "rapport\n" + OK % SHA),
        ("job_long", "base 50221f9ca7e3d1 (CI verte)", "rapport\n" + OK % "50221f9c"),
    ])
    assert out == {"job_clair": ("pointeur_spec_recopie", "low"), "job_long": ("pointeur_spec_recopie", "low")}


def test_livrable_observe_par_l_executeur_n_est_pas_une_accusation(tmp_path, monkeypatch):
    out = _scan(tmp_path, monkeypatch, [
        ("job_livre", "consigne sans sha", (EFFET % 1) + " | fait.\n" + OK % "ccccccc3")])
    assert out == {"job_livre": ("pointeur_spec_recopie", "low")}


def test_zero_commit_observe_reste_high_meme_sha_dans_la_consigne(tmp_path, monkeypatch):
    # job_af6dbf75 : sha dans la consigne, 0 commit observe -> vrai suspect, garde.
    out = _scan(tmp_path, monkeypatch, [
        ("job_vide", "reprendre %s" % SHA, (EFFET % 0) + " | fait.\n" + OK % SHA)])
    assert out == {"job_vide": ("attestation_commit_anterieur", "high")}


def test_marqueur_absent_garde_le_signal_sans_l_aggraver(tmp_path, monkeypatch):
    out = _scan(tmp_path, monkeypatch, [
        ("job_muet", "consigne sans sha", "fait.\n" + OK % "ddddddd4"),
        ("job_illisible", "consigne sans sha",
         "[effet observe] commits produits : ILLISIBLE (x..y) ; fichiers non commites : 0 | fait.\n" + OK % "eeeeeee5"),
    ])
    assert out == {"job_muet": ("attestation_commit_anterieur", "high"),
                   "job_illisible": ("attestation_commit_anterieur", "high")}


def test_la_prose_de_l_agent_ne_vaut_pas_constat_d_executeur(tmp_path, monkeypatch):
    # L'agent RECOPIE le marqueur dans sa prose : sans tete d'executeur, il ne prouve rien.
    out = _scan(tmp_path, monkeypatch, [
        ("job_prose", "consigne sans sha", "fait. " + (EFFET % 3) + "\n" + OK % "fffffff6"),
        # Tete d'executeur a 0, prose de l'agent qui pretend 2 : la tete fait foi.
        ("job_contredit", "consigne sans sha",
         (EFFET % 0) + " | fait. " + (EFFET % 2) + "\n" + OK % "aaaaaaa7"),
    ])
    assert out == {"job_prose": ("attestation_commit_anterieur", "high"),
                   "job_contredit": ("attestation_commit_anterieur", "high")}
