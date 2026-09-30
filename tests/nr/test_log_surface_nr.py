# -*- coding: utf-8 -*-
"""NR — le census de surface distingue ILLISIBLE d'ABSENT, et ICI de PARTOUT.

Ce garde protege la capacite a savoir CE QU'ON NE VOIT PAS. Owner, 2026-09-05 :
« sans ca on va passer notre temps a essayer de debugger en etant aveugle a toute la
surface ». Deux confusions rendraient le census pire qu'inutile, parce qu'elles
rassurent :

1. **ILLISIBLE lu comme ABSENT** — une source dont l'acces est refuse disparaitrait
   du decompte au lieu d'apparaitre comme un trou. C'est le defaut paye toute la
   journee : deux daemons morts dont la cause n'etait « nulle part ».
2. **« illisible ICI » lu comme « illisible PARTOUT »** — cela justifierait un
   elargissement d'ACL alors qu'il suffit de lire depuis un autre compte. Les trois
   comptes ont des angles morts COMPLEMENTAIRES, mesure : `LaForgeTrusted` echoue sur
   deux flux NSSM que `LaForgeSbxOffline` lit sans probleme.

Hermetique : aucun registre, aucun profil owner, aucune ACL touchee.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

ls = pytest.importorskip("forge_log_surface")


def test_fichier_absent_est_absent(tmp_path):
    assert ls._etat_fichier(tmp_path / "rien.log")["etat"] == ls.ABSENT


def test_fichier_lisible_porte_sa_taille_et_son_age(tmp_path):
    p = tmp_path / "a.log"
    p.write_text("x" * 50, encoding="utf-8")
    r = ls._etat_fichier(p)
    assert r["etat"] == ls.LISIBLE
    assert r["octets"] == 50 and "age_h" in r


def test_fichier_vide_reste_lisible(tmp_path):
    """Un canal capte mais muet n'est pas un canal absent."""
    p = tmp_path / "vide.log"
    p.write_text("", encoding="utf-8")
    r = ls._etat_fichier(p)
    assert r["etat"] == ls.LISIBLE and r.get("vide") is True


def test_acces_refuse_est_illisible_pas_absent(tmp_path, monkeypatch):
    """Le coeur du garde : un refus d'ouverture ne doit PAS disparaitre du compte."""
    import builtins

    p = tmp_path / "interdit.log"
    p.write_text("secret", encoding="utf-8")
    vrai_open = builtins.open

    def _open(f, *a, **k):
        if str(f) == str(p):
            raise PermissionError("refus simule")
        return vrai_open(f, *a, **k)

    # `open` est un builtin, pas un attribut du module : c'est `builtins` qu'il faut
    # patcher. Le filtre par chemin garde le reste du test lisible.
    monkeypatch.setattr(builtins, "open", _open)
    r = ls._etat_fichier(p)
    assert r["etat"] == ls.ILLISIBLE, "un acces refuse a ete lu comme absent"
    assert "raison" in r, "un ILLISIBLE sans raison ne s'instruit pas"


def test_un_dossier_lisible_nest_pas_illisible(tmp_path):
    """Sous Windows, `open()` sur un repertoire LEVE meme avec tous les droits.

    Mesure 2026-09-05, juste apres l'octroi des ACL : `.lmstudio`, `server-logs` et
    ses sous-dossiers mensuels ressortaient ILLISIBLES — le census accusait des
    chemins qu'il venait lui-meme d'ouvrir. Un dossier se teste par sa LISTABILITE.
    """
    d = tmp_path / "server-logs"
    d.mkdir()
    (d / "2026-09").mkdir()
    r = ls._etat_fichier(d)
    assert r["etat"] == ls.LISIBLE, "un dossier lisible classe ILLISIBLE"
    assert r.get("dossier") is True and r.get("entrees") == 1


def test_dossier_non_listable_reste_illisible(tmp_path, monkeypatch):
    d = tmp_path / "verrouille"
    d.mkdir()
    monkeypatch.setattr(ls.os, "listdir",
                        lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("x")))
    r = ls._etat_fichier(d)
    assert r["etat"] == ls.ILLISIBLE and "listdir" in r["raison"]


def _rapport(compte: str, etats: dict) -> dict:
    return {"compte_execution": compte,
            "familles": {"docker": {k: {"etat": v} for k, v in etats.items()}}}


def test_fusion_ne_reclame_pas_d_acl_si_un_compte_voit():
    """Illisible ICI mais lisible AILLEURS : aucune ACL a elargir."""
    r = ls.fusion([_rapport("A", {"x": ls.ILLISIBLE}),
                   _rapport("B", {"x": ls.LISIBLE})])
    assert r["lisibles_par_au_moins_un"] == 1
    assert r["candidats_acl"] == []


def test_fusion_signale_l_illisible_partout():
    r = ls.fusion([_rapport("A", {"x": ls.ILLISIBLE}),
                   _rapport("B", {"x": ls.ILLISIBLE})])
    assert len(r["candidats_acl"]) == 1
    assert r["candidats_acl"][0]["source"] == "docker::x"
    assert r["candidats_acl"][0]["par_compte"] == {"A": ls.ILLISIBLE, "B": ls.ILLISIBLE}


def test_fusion_ne_confond_pas_absent_et_illisible():
    """ABSENT partout n'est pas un probleme d'ACL : rien a accorder sur du vide."""
    r = ls.fusion([_rapport("A", {"x": ls.ABSENT}),
                   _rapport("B", {"x": ls.ABSENT})])
    assert r["absentes_partout"] == 1
    assert r["candidats_acl"] == []


def test_census_cible_les_familles_demandees():
    """Le ciblage existe parce que le depot (10681 fichiers) depasse le cap du canal
    `shell`, seul chemin vers `LaForgeSbxOnline`."""
    r = ls.census(profond=False, familles_voulues=["wsl"])
    assert set(r["familles"]) == {"wsl"}
    assert r["compte_execution"]
