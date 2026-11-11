"""NR owner 9/11 : « si reprise de sessions à faire écris-moi systématiquement la procédure, ancre-le ».

Le hook qui propose une nouvelle session (seuil de transcription) doit exiger la procédure de reprise écrite à
l'owner, pas seulement l'état en mémoire.
"""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


def test_alerte_contexte_exige_la_procedure_de_reprise(tmp_path, monkeypatch):
    tick = importlib.import_module("claude_inbox_tick")
    monkeypatch.setenv("LAFORGE_SEUIL_CONTEXTE_JETONS", "1000")
    transcription = tmp_path / "session.jsonl"
    transcription.write_text(
        '{"type": "assistant", "message": {"usage": {"input_tokens": 4096, "output_tokens": 1}}}\n',
        encoding="utf-8")
    msg = tick._alerte_taille_contexte(str(transcription), "nr", etat_dir=tmp_path / "etat")
    assert "propose une nouvelle session" in msg
    assert "procédure de reprise" in msg
    assert "premier geste" in msg


def test_constante_procedure_nomme_les_elements_attendus():
    tick = importlib.import_module("claude_inbox_tick")
    for element in ("phrase à coller", "fiche à lire", "état prouvé", "premier geste", "décision"):
        assert element in tick._PROCEDURE_REPRISE
