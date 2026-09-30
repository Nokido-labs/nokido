"""NR — l'outil anti-fuite d'export ne laisse plus passer ce qu'il trouve, et ne le recopie plus.

Mesure du 2026-09-29 (signalement d'une session d'audit, verifie dans le code) :
- l'audit de la phase C (tables de la liste blanche) etait calcule puis IGNORE par le code de sortie ;
- le controle final ne lisait que 1000 lignes par table : une fuite a la ligne 1001 sortait « PASS » ;
- chaque constat recopiait `val[:80]` -- les 80 premiers caracteres de la valeur contenant le secret --
  dans l'audit, dans `.audit.log` a cote de la base exportee, et a l'ecran en `--dry-run`.
La valeur de test est une adresse MAC fictive assemblee a l'execution (motif `macaddr`).
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_db_sanitize as S  # noqa: E402

_FRAGMENT = ":".join(["de", "ad"])


def _valeur():
    return "noeud " + ":".join(["de", "ad", "be", "ef", "00", "01"]) + " fin"


def _base(dossier: Path, table="notes", n=1500, position=1400) -> Path:
    dossier.mkdir(parents=True, exist_ok=True)
    db = dossier / "x.db"
    c = sqlite3.connect(db)
    c.execute('CREATE TABLE "%s" (id INTEGER PRIMARY KEY, txt TEXT)' % table)
    c.executemany('INSERT INTO "%s" VALUES (?, ?)' % table,
                  [(i, _valeur() if i == position else "texte %d" % i) for i in range(n)])
    c.commit()
    c.close()
    return db


def test_le_controle_final_lit_toutes_les_lignes(tmp_path):
    r = S.final_sanity_check(_base(tmp_path))
    assert r["passed"] is False, "une fuite a la ligne 1400 est passee : echantillon au lieu de toutes les lignes"
    assert r["final_issues"][0]["pattern"] == "macaddr"


def test_un_constat_ne_recopie_jamais_la_valeur(tmp_path):
    r = S.final_sanity_check(_base(tmp_path / "a"))
    assert _FRAGMENT not in repr(r)
    c = sqlite3.connect(_base(tmp_path / "b", table="system_rules"))
    try:
        rc = S.phase_C_audit_whitelist(c)
    finally:
        c.close()
    assert rc["ok"] is False and _FRAGMENT not in repr(rc)
    assert all(_FRAGMENT not in ligne for ligne in S._AUDIT_LINES), "l'audit recopie la valeur trouvee"


def test_en_public_la_phase_c_compte_dans_le_verdict():
    c_ko = {"ok": False, "whitelist_issues": [{}]}
    final_ok = {"passed": True, "final_issues": []}
    ok, motifs = S.verdict_export("public", c_ko, final_ok)
    assert ok is False and "phase C" in motifs[0]
    assert S.verdict_export("perso", c_ko, final_ok)[0] is True, "la sauvegarde privee n'est pas bloquee par C"
    assert S.verdict_export("public", {"ok": True, "whitelist_issues": []},
                            {"passed": False, "final_issues": [{}]})[0] is False


def test_le_dry_run_rend_un_echec_sans_afficher_la_valeur(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(S, "DB_SRC", _base(tmp_path, table="system_rules"))
    monkeypatch.setattr(sys, "argv", ["forge_db_sanitize.py", "--dry-run", "--mode", "public"])
    assert S.main() == 2
    assert _FRAGMENT not in capsys.readouterr().out
