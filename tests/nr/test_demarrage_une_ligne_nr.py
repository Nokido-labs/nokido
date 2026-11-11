# -*- coding: utf-8 -*-
"""NR owner 4/11 (« 16 % de contexte au demarrage ») : quand tout va bien, le hook de demarrage rend UNE ligne.

Regle de RULES_SHARED ; l'audit des prompts a constate banniere, resume, lecons, ancres et roadmap a chaque session. Le
detail reste accessible par `--detail`, et une alerte reelle passe toujours. Meme constat : les lecons etaient lues sans
encodage, donc en cp1252 sous Windows (« DÃ©claration » injecte au modele).
"""
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "tools")]
S = importlib.import_module("claude_session_start")


@pytest.fixture
def calme(monkeypatch):
    for nom, val in {
        "load_token": lambda: "", "_entree_hook": lambda: {}, "_oublier_rappels_si_compaction": lambda *_a: None,
        "section_audit": lambda *_a: None, "alerte_cout_reprise": lambda *_a: None, "alerte_file_owner": lambda *_a: "",
        "alerte_registre_owner": lambda: "",
        "alerte_prs_dependabot": lambda *_a: "", "fetch_unread_inbox": lambda **_k: [], "fetch_tasks_inbox": lambda **_k: [],
        "fetch_blackboard_inbox": lambda **_k: [], "fetch_postal_inbox": lambda **_k: [], "_load_seen": set,
        "_save_seen": lambda *_a: None, "refresh_symptom_index": lambda *_a, **_k: None,
        "recent_lessons": lambda *_a: "### une lecon", "recent_anchors": lambda *_a: "=== ancres", "roadmap_summary": lambda: "=== roadmap",
    }.items():
        monkeypatch.setattr(S, nom, val)
    monkeypatch.setattr(sys, "argv", ["claude_session_start.py"])


def _sortie(capsys):
    S.main()
    return [l for l in capsys.readouterr().out.splitlines() if l.strip()]


def test_tout_va_bien_une_seule_ligne(calme, capsys):
    lignes = _sortie(capsys)
    assert len(lignes) == 1, lignes
    assert "--detail" in lignes[0], "la ligne doit dire ou trouver le detail"


def test_le_detail_reste_accessible_sur_drapeau(calme, capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["claude_session_start.py", "--detail"])
    texte = "\n".join(_sortie(capsys))
    for attendu in ("Règles actives", "une lecon", "=== ancres", "=== roadmap"):
        assert attendu in texte


def test_une_alerte_reelle_passe_sans_drapeau(calme, capsys, monkeypatch):
    monkeypatch.setattr(S, "alerte_file_owner", lambda *_a: "[arbitrage] 2 dossiers en attente")
    monkeypatch.setattr(S, "section_audit", lambda *_a: "[audit-prompts] a faire")
    monkeypatch.setattr(S, "fetch_postal_inbox", lambda **_k: [{"id": "m1", "from": "AGY", "ts": "t", "preview": "bonjour"}])
    texte = "\n".join(_sortie(capsys))
    for attendu in ("[arbitrage]", "[audit-prompts]", "INBOX MULTI-CANAL", "bonjour"):
        assert attendu in texte
    assert "Règles actives" not in texte and "une lecon" not in texte


def test_une_alerte_du_registre_passe_et_rompt_le_calme(calme, capsys, monkeypatch):
    monkeypatch.setattr(S, "alerte_registre_owner", lambda: "[alertes owner] 1 en attente :\n  - [high] x : y")
    texte = "\n".join(_sortie(capsys))
    assert "[alertes owner] 1 en attente" in texte and "[demarrage] RAS" not in texte


def test_les_lecons_sont_lues_en_utf8(tmp_path):
    """Sous-processus en `-X utf8=0` : c'est l'environnement reel du hook. Dans un job en mode UTF-8, un test direct
    passait meme sans encodage explicite (faux vert mesure le 4/11)."""
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "lessons_learned.md").write_text("### [x] Déclaration du service\ncorps\n", encoding="utf-8")
    code = ("import sys, pathlib; sys.path[:0] = sys.argv[1:4]; import claude_session_start as S; "
            "S.ROOT = pathlib.Path(sys.argv[4]); print(ascii(S.recent_lessons(1200)))")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUTF8"}
    r = subprocess.run([sys.executable, "-X", "utf8=0", "-c", code, str(RACINE.parent), str(RACINE), str(RACINE / "tools"), str(tmp_path)],
                       capture_output=True, text=True, errors="replace", env=env, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    assert ascii("Déclaration") .strip("'") in r.stdout, r.stdout[-300:]


def test_la_banniere_porte_l_ordre_de_consultation_de_rules_shared():
    assert "query rag_fts" not in S.REGLES
    assert "forge_retrieval_sweep" in S.REGLES
