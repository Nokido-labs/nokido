# -*- coding: utf-8 -*-
"""NR — `--texte` traverse la CLI jusqu'a `repondre` (point d'entree reel, pas seulement la fonction).

2026-09-29 : `repondre(client, pointer, intent, texte)` savait porter un compte rendu, mais la
CLI ne transmettait que l'intent et le pointeur : une reponse a un pair (claude.ai) partait sans
contenu lisible. Le drapeau est ajoute ; ce NR l'emprunte par `main()`, comme l'owner.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("forge_pair_quarantaine_nr", ROOT / "tools" / "forge_pair_quarantaine.py")
Q = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(Q)


def test_le_drapeau_texte_traverse_jusqu_a_repondre(monkeypatch):
    vus = {}

    def faux_repondre(client, pointer, intent="OK_DONE", texte=""):
        vus.update(client=client, pointer=pointer, intent=intent, texte=texte)
        return {"ok": True, "id": "apr_nr"}

    monkeypatch.setattr(Q, "repondre", faux_repondre)
    rc = Q.main(["--repondre", "client-nr", "--pointer", "commit:abc1234", "--texte", "compte rendu court"])
    assert rc == 0
    assert vus == {"client": "client-nr", "pointer": "commit:abc1234", "intent": "OK_DONE",
                   "texte": "compte rendu court"}, vus


def test_sans_texte_la_reponse_reste_valide(monkeypatch):
    vus = {}
    monkeypatch.setattr(Q, "repondre", lambda c, p, i="OK_DONE", t="": vus.update(t=t) or {"ok": True})
    assert Q.main(["--repondre", "client-nr", "--pointer", "commit:abc1234"]) == 0
    assert vus["t"] == ""
