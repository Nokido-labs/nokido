"""NR 20/10 -- le hook Stop « attente passive » ne lit que la FIN de la transcription, jamais le fichier entier.

Mesure du 20/10 (owner, colle de la sortie) : apres une longue session, `transcript.read_text()` levait MemoryError
(hook_stop_attente_passive.py:109) -- le garde etait DESARME en silence a chaque fin de tour (statut non bloquant),
et chargeait toute la transcription en RAM pour n'en garder que 400 lignes. Contrat : lecture bornee depuis la fin,
meme resultat que les 400 dernieres lignes, aucune lecture complete.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location("hook_stop_borne_nr", RACINE / "tools" / "hook_stop_attente_passive.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _transcription(tmp_path, n_bruit=3000):
    lignes = [json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "ancien %d " % i + "x" * 200}]}}) for i in range(n_bruit)]
    lignes.append(json.dumps({"type": "user", "message": {"role": "user", "content": "parole de l'owner"}}))
    lignes.append(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Monitor", "input": {}}, {"type": "text", "text": "dernier message"}]}}))
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return p


def test_aucune_lecture_complete_de_la_transcription(tmp_path, monkeypatch):
    m = _module()
    p = _transcription(tmp_path)

    def interdit(self, *a, **k):
        raise MemoryError("lecture complete de la transcription")

    monkeypatch.setattr(pathlib.Path, "read_text", interdit)
    assert m.dernier_message(p) == "dernier message"
    assert m.outils_du_tour(p) == ["Monitor"]


def test_la_premiere_ligne_coupee_par_le_budget_est_ecartee(tmp_path):
    m = _module()
    p = _transcription(tmp_path, n_bruit=50)
    lignes = m._dernieres_lignes(p, n=400, budget=4096)
    assert lignes, "rien lu"
    for l in lignes:
        json.loads(l)   # aucune ligne tronquee : la premiere, coupee au milieu, n'est pas rendue
    assert json.loads(lignes[-1])["message"]["content"][1]["text"] == "dernier message"
