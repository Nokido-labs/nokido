"""NR 18/10 -- item p1_surface_regulable_reponse_graduee : reponse GRADUEE des organes neverSleep lourds.

Recon du 14/10 : tools/forge_coagulation.py::watch n'a AUCUN recepteur -- coagulate() toutes les 300 s quoi qu'il
arrive (30-96 Mo/s mesures), meme pendant qu'une tache prioritaire tient un bail. Forme retenue (compatible
neverSleep) : l'organe reste vivant et bat son pouls, mais DIFFERE sa passe lourde tant qu'un bail prioritaire est
ACTIF, et la reprend a l'expiration. Un seul helper au gestionnaire de ressources :
`forge_resource_manager.travail_differe(service) -> bool`, lu a chaque tour de boucle.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_resource_manager as frm  # noqa: E402


def _bail(dossier: Path, ttl_s: float, etat: str = "ACTIF", age_s: float = 0.0) -> None:
    cree = time.time() - age_s
    b = {"id": "bail_nr_%d" % int(cree), "principal": "CI_REFERENCE", "motif": "nr", "classe": "court",
         "ttl_s": ttl_s, "cree_le": cree, "etat": etat, "interrompus": [], "mode": "arme"}
    b["expire_le"] = cree + ttl_s
    (dossier / ("%s.json" % b["id"])).write_text(json.dumps(b), encoding="utf-8")


def _isoler(monkeypatch, tmp_path, arme=True):
    monkeypatch.setattr(frm, "_BAUX_DIR", tmp_path)
    monkeypatch.setattr(frm, "_bail_arme", lambda: arme)


def test_un_bail_actif_fait_differer_la_passe_lourde(monkeypatch, tmp_path):
    _isoler(monkeypatch, tmp_path)
    _bail(tmp_path, ttl_s=3600)
    assert frm.travail_differe("NokidoCoagulation") is True


def test_sans_bail_ou_bail_echu_le_travail_reprend(monkeypatch, tmp_path):
    _isoler(monkeypatch, tmp_path)
    assert frm.travail_differe("NokidoCoagulation") is False
    _bail(tmp_path, ttl_s=60, age_s=600)  # echu depuis 9 min
    assert frm.travail_differe("NokidoCoagulation") is False


def test_bail_en_observation_ne_differe_rien(monkeypatch, tmp_path):
    """Observer avant d'enforcer : bail non arme = journaliser ce qui aurait cede, jamais differer."""
    _isoler(monkeypatch, tmp_path, arme=False)
    _bail(tmp_path, ttl_s=3600)
    assert frm.travail_differe("NokidoCoagulation") is False


def test_la_coagulation_consulte_le_recepteur_a_chaque_tour():
    src = (ROOT / "tools" / "forge_coagulation.py").read_text(encoding="utf-8", errors="replace")
    debut = src.find("def watch(")
    assert debut >= 0, "watch() introuvable dans forge_coagulation.py"
    corps = src[debut:src.find("\ndef ", debut + 10)]
    assert "travail_differe(" in corps, "la boucle watch de la coagulation n'a toujours aucun recepteur de bail"
