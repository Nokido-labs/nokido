"""NR : l'observation du coffre cloisonne laisse une trace DURABLE, lisible hors du processus (owner 29/10).

Mesure du 29/10 : observer_lecture_cloisonnee disait « Journalise » mais ne remplissait qu'une liste EN MEMOIRE du
processus (OBSERVES_CLOISONNEMENT), perdue a sa fin : impossible de recenser QUI lirait un secret ring <= 3 depuis le
bac avant de passer au refus (« observer avant d'enforcer »). Ce NR tient : une lecture « aurait_refuse » ecrit UNE
ligne JSONL (cle, compte, script, pid, ts) SANS la valeur ; une cle hors genre identite n'ecrit rien ; un journal
inscriptible ne casse jamais la lecture.
"""
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE))
from app import forge_secrets as FS  # noqa: E402


def _bac(monkeypatch, tmp_path):
    j = tmp_path / "obs.jsonl"
    monkeypatch.setattr(FS, "_JOURNAL_OBSERVATIONS", j)
    monkeypatch.setattr(FS, "_compte_du_jeton", lambda: "LaForgeSbxOnline")
    monkeypatch.setenv("NOKIDO_COMPTES_BAC", "LaForgeSbxOffline,LaForgeSbxOnline")
    return j


def test_lecture_identite_depuis_le_bac_ecrit_une_ligne_sans_valeur(monkeypatch, tmp_path):
    j = _bac(monkeypatch, tmp_path)
    ok, raison = FS.observer_lecture_cloisonnee("FORGE_TOKEN_SWARM_LANCEUR")
    assert ok is True and raison.startswith("aurait_refuse")
    lignes = [json.loads(l) for l in j.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lignes) == 1
    L = lignes[0]
    assert L["cle"] == "FORGE_TOKEN_SWARM_LANCEUR" and L["compte"] == "LaForgeSbxOnline"
    assert {"script", "pid", "ts", "raison"} <= set(L)
    assert not ({"valeur", "value", "secret"} & set(L))


def test_cle_hors_identite_n_ecrit_rien(monkeypatch, tmp_path):
    j = _bac(monkeypatch, tmp_path)
    FS.observer_lecture_cloisonnee("GROQ_API_KEY")
    assert not j.exists() or not j.read_text(encoding="utf-8").strip()


def test_journal_impossible_ne_casse_pas_la_lecture(monkeypatch, tmp_path):
    _bac(monkeypatch, tmp_path)
    monkeypatch.setattr(FS, "_JOURNAL_OBSERVATIONS", tmp_path / "dossier_absent" / "x" / "obs.jsonl")
    (tmp_path / "dossier_absent").write_text("un fichier, pas un dossier", encoding="utf-8")
    ok, raison = FS.observer_lecture_cloisonnee("FORGE_TOKEN_SWARM_LANCEUR")
    assert ok is True and raison.startswith("aurait_refuse")
