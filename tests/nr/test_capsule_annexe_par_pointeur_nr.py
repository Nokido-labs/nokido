"""NR -- une capsule de pair porte des POINTEURS vers ses annexes, lues page par page selon le ring (owner 17/10).

Mesure 17/10 : derniere_capsule coupe toute sortie a MAX_SORTIE = 6 000 car. ; la capsule de relecture adverse (5 diffs)
en faisait ~43 000 -> par le connecteur, ses annexes arrivaient tronquees. Question owner : « les capsules ne peuvent pas
etre remplacees par un pointeur pour eviter la troncature ? » ; decision : pagination « selon le ring toujours a
respecter ». Contrat : pointeur `annexe:<capsule>/<nom>` CONFINE au dossier des capsules ; pages sous la coupe, sha256
du tout pour reassembler sans perte ; pair IDENTIFIE ; ring du pair <= ring_annexes de la capsule ; ring INCONNU = refus.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import forge_pair_mcp as P  # noqa: E402

CONTENU = "".join(chr(97 + i % 26) for i in range(12000)) + "\nfin zorglub"


def _capsule(tmp_path, monkeypatch, ring_pair=2, ring_annexes=2):
    monkeypatch.setattr(P, "dossier_capsules", lambda: tmp_path)
    (tmp_path / "c1.capsule.json").write_text(json.dumps({"ring_annexes": ring_annexes,
                                                          "annexes": ["annexe:c1/diff_a.txt"]}), encoding="utf-8")
    d = tmp_path / "c1" / "annexes"
    d.mkdir(parents=True)
    (d / "diff_a.txt").write_text(CONTENU, encoding="utf-8")
    monkeypatch.setattr(P, "_ring_du_pair", lambda client: ring_pair)


def test_une_annexe_se_lit_page_par_page_sans_perte(tmp_path, monkeypatch):
    _capsule(tmp_path, monkeypatch)
    premiere = P.lire_annexe("client-a", "annexe:c1/diff_a.txt", 0)
    assert premiere["ok"] and premiere["pages"] >= 3, premiere
    assert premiere["sha256"] == hashlib.sha256(CONTENU.encode("utf-8")).hexdigest()
    morceaux = []
    for i in range(premiere["pages"]):
        r = P.lire_annexe("client-a", "annexe:c1/diff_a.txt", i)
        assert len(json.dumps(r, ensure_ascii=False)) <= P.MAX_SORTIE, "une page doit passer SOUS la coupe"
        morceaux.append(r["contenu"])
    assert "".join(morceaux) == CONTENU


def test_un_pointeur_qui_sort_du_dossier_est_refuse(tmp_path, monkeypatch):
    _capsule(tmp_path, monkeypatch)
    for ref in ("annexe:../c1.capsule.json", "annexe:c1/../../x", "annexe:c1\\..\\x", "annexe:C:/Windows/win.ini",
                "fichier:c1/diff_a.txt", "annexe:c1/sous/dossier.txt"):
        r = P.lire_annexe("client-a", ref, 0)
        assert r["ok"] is False, (ref, r)


def test_un_ring_insuffisant_est_refuse(tmp_path, monkeypatch):
    _capsule(tmp_path, monkeypatch, ring_pair=3, ring_annexes=2)
    r = P.lire_annexe("client-a", "annexe:c1/diff_a.txt", 0)
    assert r["ok"] is False and "ring" in str(r).lower()


def test_un_ring_inconnu_est_refuse(tmp_path, monkeypatch):
    _capsule(tmp_path, monkeypatch, ring_pair=None)
    r = P.lire_annexe("client-a", "annexe:c1/diff_a.txt", 0)
    assert r["ok"] is False and "INCONNU" in str(r)


def test_une_page_hors_borne_le_dit(tmp_path, monkeypatch):
    _capsule(tmp_path, monkeypatch)
    r = P.lire_annexe("client-a", "annexe:c1/diff_a.txt", 99)
    assert r["ok"] is False and "page" in str(r).lower()


def test_l_outil_exige_un_pair_identifie():
    src = (ROOT / "tools" / "forge_pair_mcp.py").read_text(encoding="utf-8", errors="replace")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "construire_serveur")
    outil = next((n for n in ast.walk(fn) if isinstance(n, ast.AsyncFunctionDef) and n.name == "lire_annexe"), None)
    assert outil is not None, "outil MCP lire_annexe absent"
    assert "_au_nom_du_pair(" in ast.unparse(outil), "lecture d'annexe sans pair identifie"
