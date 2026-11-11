# -*- coding: utf-8 -*-
"""NR -- un manifeste de sauvegarde qui n'est pas un objet JSON ne casse pas le balayage.

Relecture Claude 2026-11-08 du commit P2 : `balayer_et_reconcilier` lit
`sandbox/sauvegardes_executeurs/<agent>/<tache>/manifeste.json` puis appelle `man.get(...)`.
Un manifeste valide mais non-dict (liste, chaine) levait AttributeError hors du try et
interrompait TOUT le balayage : les sauvegardes suivantes n'etaient jamais signalees.
Contrat : manifeste non-dict = journalise et saute, les autres sont traitees.
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _wt():
    spec = importlib.util.spec_from_file_location("forge_worktree_nr_manifeste", ROOT / "tools" / "forge_worktree.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_manifeste_liste_saute_les_autres_traitees(tmp_path, monkeypatch):
    sauv = tmp_path / "sandbox" / "sauvegardes_executeurs" / "AGENT_X"
    (sauv / "a_casse").mkdir(parents=True)
    (sauv / "a_casse" / "manifeste.json").write_text(json.dumps(["pas", "un", "dict"]), encoding="utf-8")
    (sauv / "b_bon").mkdir(parents=True)
    (sauv / "b_bon" / "manifeste.json").write_text(json.dumps({"fichiers": ["x.py"]}), encoding="utf-8")
    (tmp_path / "wt").mkdir()
    (tmp_path / "sandbox" / "reconciliateur_boucle.switch").write_text("1", encoding="utf-8")
    W = _wt()
    monkeypatch.setattr(W, "garde_ressources_au_rouge", lambda: False)
    notes = []
    res = W.balayer_et_reconcilier(
        root=tmp_path, wt_root=tmp_path / "wt", tasks_db=tmp_path / "absent.db", registre=set(),
        notifier=lambda *a, **k: notes.append(a), vivacite=lambda p, c: None, emettre=lambda t, p: None)
    taches = [l.get("tache") for l in res.get("lots", []) if l.get("action") == "sauvegarde_signalee"]
    assert taches == ["b_bon"], (taches, res)
