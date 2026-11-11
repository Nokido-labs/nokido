# -*- coding: utf-8 -*-
"""NR owner 4/11 (« le disque C sature en E/S ») : mesure job_6a31aad7ac58 -- le hub lit 61-65 Mo/s a ~15 000 ops/s
(pages SQLite de 4 Ko) en RAFALES, hors de toute requete (hub_io_par_requete muet) ; open_files/memory_maps illisibles
sous le compte des jobs. La sonde (tools/forge_hub_io_probe.py) detecte la rafale et la NOMME ; ce qu'elle ne peut
pas lire est ILLISIBLE, jamais vide."""
import importlib
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RACINE.parent), str(RACINE), str(RACINE / "tools")]
S = importlib.import_module("forge_hub_io_probe")


def test_rafale_detectee_sur_le_debit_et_bornee_dans_le_temps():
    ech = [(0, 0), (1, 1_000_000), (2, 66_000_000), (3, 130_000_000), (4, 131_000_000)]   # (t, octets lus cumules)
    r = S.rafales(ech, seuil_mo_s=20)
    assert r == [(1, 3)], "rafale = intervalle ou le debit depasse le seuil"
    assert S.rafales([(0, 0), (1, 5_000_000)], seuil_mo_s=20) == []


def test_ce_qui_est_illisible_est_dit_illisible():
    def _refus():
        raise PermissionError("acces refuse")
    assert S.lire_ou_illisible(_refus) == {"etat": "ILLISIBLE", "raison": "PermissionError: acces refuse"}
    assert S.lire_ou_illisible(lambda: []) == {"etat": "LU", "valeur": []}


def test_les_piles_qui_lisent_sortent_en_tete_et_les_autres_sont_comptees():
    brut = ["<module> (a.py:1);boucle (b.py:2);execute (c.py:3) 7",
            "<module> (a.py:1);attendre (b.py:9) 500",
            "<module> (a.py:1);_tick (d.py:4);read_text (pathlib.py:5);read (e.py:6) 3",
            "ligne illisible"]
    r = S.resumer_piles(brut, n=5)
    assert r["echantillons"] == 510
    assert r["illisibles"] == 1, "une ligne non comprise est comptee, jamais ignoree en silence"
    assert [p["n"] for p in r["lecteurs"]] == [7, 3], "seules les piles de lecture, les plus frequentes d'abord"
    assert "execute" in r["lecteurs"][0]["pile"]
    assert all("attendre" not in p["pile"] for p in r["lecteurs"])


def test_py_spy_absent_est_dit_illisible(monkeypatch):
    monkeypatch.setattr(S, "_py_spy", lambda: None)
    r = S.enregistrer(1234, 5)
    assert r["etat"] == "ILLISIBLE" and "py-spy" in r["raison"]


def test_gros_fichiers_d_abord():
    fichiers = [("a.log", 10), ("embeddings.db", 45_000_000_000), ("x.db-wal", 2_000_000)]
    assert [f for f, _ in S.gros_fichiers(fichiers, n=2)] == ["embeddings.db", "x.db-wal"]
