# -*- coding: utf-8 -*-
"""NR — le miroir du swarm bus ne doit plus payer une ouverture de fichier par evenement.

Mesure 2026-08-30 : `publish()` coutait 366 us, dont l'essentiel en `open`/`write`/
`close` du JSONL a CHAQUE evenement (630 us mesures isolement). Un item de travail
utile — parser un fichier en AST — coute ~6 us : un evenement coutait donc soixante
fois plus cher que le travail qu'il decrit, et le producteur payait cette I/O dans
son propre thread. Apres handle persistant : 10,3 us par publish, x35.

Le handle partage introduit un risque que l'ancienne version n'avait pas : deux
threads qui ecrivent en meme temps peuvent entrelacer leurs lignes. D'ou le verrou
dedie, et le test de concurrence ci-dessous qui le verrouille.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import forge_swarm_bus as B  # noqa: E402


def _rediriger(tmp_path, monkeypatch):
    """Isole le journal : jamais toucher sandbox/reflexion.jsonl depuis un test."""
    p = tmp_path / "reflexion.jsonl"
    monkeypatch.setattr(B, "_REFLEX_LOG", str(p))
    B._mirror_close()
    return p


def test_le_miroir_ecrit_bien_la_ligne(tmp_path, monkeypatch):
    p = _rediriger(tmp_path, monkeypatch)
    B.publish("essai", {"a": 1})
    B._mirror_close()
    lignes = p.read_text(encoding="utf-8").splitlines()
    assert len(lignes) == 1
    ev = json.loads(lignes[0])
    assert ev["kind"] == "essai" and ev["data"] == {"a": 1}


def test_le_handle_est_REUTILISE_entre_deux_publications(tmp_path, monkeypatch):
    """Le coeur du correctif : un seul open pour N evenements."""
    _rediriger(tmp_path, monkeypatch)
    B.publish("un")
    premier = B._mirror_fh
    assert premier is not None, "le handle doit rester ouvert apres un publish"
    B.publish("deux")
    assert B._mirror_fh is premier, "le fichier a ete rouvert : le gain est perdu"
    B._mirror_close()


def test_aucune_ligne_corrompue_sous_concurrence(tmp_path, monkeypatch):
    """Un handle partage sans verrou entrelace les writes -> JSON invalide."""
    p = _rediriger(tmp_path, monkeypatch)
    N, T = 200, 8

    def bosser(k):
        for i in range(N):
            B.publish("concurrent", {"th": k, "i": i, "bourrage": "y" * 200})

    fils = [threading.Thread(target=bosser, args=(k,)) for k in range(T)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    B._mirror_close()

    lignes = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lignes) == N * T, "%d lignes au lieu de %d" % (len(lignes), N * T)
    for l in lignes:
        json.loads(l)          # leve si une ligne est entrelacee


def test_le_miroir_ne_leve_JAMAIS_vers_le_producteur(tmp_path, monkeypatch):
    """Contrat historique : publish() est best-effort, il ne casse pas l'appelant."""
    monkeypatch.setattr(B, "_REFLEX_LOG", str(tmp_path / "sous" / "dossier" / "absent.jsonl"))
    B._mirror_close()
    B.publish("malgre_tout", {"x": 1})   # ne doit pas lever
    B._mirror_close()


def test_mirror_close_est_idempotent(tmp_path, monkeypatch):
    _rediriger(tmp_path, monkeypatch)
    B.publish("x")
    B._mirror_close()
    B._mirror_close()
    assert B._mirror_fh is None
