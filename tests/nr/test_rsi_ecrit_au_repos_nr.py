# -*- coding: utf-8 -*-
"""NR (owner 3/11, option 1 « genere tout le temps, ecrit au repos ») : le RSI ne mute l'arbre qu'en sommeil.

Mesure : le juge (thymus) ecrit le candidat dans l'arbre VIVANT partage, teste, restaure, et laisse le fichier modifie
si le candidat survit -- a toute heure (demon a intervalle fixe, aucune garde de phase ni de RAM).
Physiologie (veille au RAG) : la consolidation se fait pendant le sommeil (reactivation hippocampique, Wilson &
McNaughton 1994, Science 265:676 ; redistribution hippocampe -> neocortex, fuseaux du sommeil, PMC7046449) et
INTEGRE la trace au cadre EXISTANT (arXiv 2602.04095) -> un candidat dont le fichier a change est perime.
Invariants : eveil = file d'attente, juge jamais appele ; sommeil (NREM1/NREM3) hors satiete = consolidation ;
phase illisible = pas de mutation (fail-closed) ; transe = cytokine a TTL (clairance), toujours eteinte en sortie.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "app", ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import forge_self_patcher as P  # noqa: E402


@pytest.fixture
def corps(monkeypatch, tmp_path):
    (tmp_path / "app").mkdir()
    cible = tmp_path / "app" / "forge_x.py"
    cible.write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "FILE_REPOS", tmp_path / "file_repos.jsonl")
    juges = []
    monkeypatch.setattr(P, "_submit_to_judge",
                        lambda ref, rel, new_text, desc, test_f2p=None: juges.append(rel) or {"verdict": "SURVIT"})
    etat = {"phase": "JOUR", "satiete": False, "cytokine": False}
    monkeypatch.setattr(P, "_phase_courante", lambda: etat["phase"])
    monkeypatch.setattr(P, "_ram_en_satiete", lambda: etat["satiete"])
    monkeypatch.setattr(P, "_cytokine_active", lambda: etat["cytokine"])
    return {"cible": cible, "juges": juges, "etat": etat}


def _file(corps_):
    f = P.FILE_REPOS
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []


def test_eveil_le_candidat_attend_en_file_et_l_arbre_reste_intact(corps):
    out = P._soumettre_ou_differer("proposal:a", "app/forge_x.py", "x = 2\n", "desc", None)
    assert out["verdict"] == "DIFFERE" and out["status"] == "DIFFERE_REPOS", out
    assert corps["juges"] == [] and corps["cible"].read_text(encoding="utf-8") == "x = 1\n"
    e = _file(corps)
    assert len(e) == 1 and e[0]["sha_source"] == hashlib.sha256(corps["cible"].read_bytes()).hexdigest()


def test_sommeil_consolide_la_file(corps):
    P._soumettre_ou_differer("proposal:a", "app/forge_x.py", "x = 2\n", "desc", None)
    corps["etat"]["phase"] = "NREM3"
    r = P.consolider()
    assert r["jugees"] == 1 and corps["juges"] == ["app/forge_x.py"] and _file(corps) == []


def test_fichier_change_depuis_la_generation_candidat_perime(corps):
    P._soumettre_ou_differer("proposal:a", "app/forge_x.py", "x = 2\n", "desc", None)
    corps["cible"].write_text("x = 3\n", encoding="utf-8")
    corps["etat"]["phase"] = "NREM1"
    r = P.consolider()
    assert r["perimees"] == 1 and r["jugees"] == 0 and corps["juges"] == [] and _file(corps) == []


def test_sommeil_mais_ram_en_satiete_reste_en_file(corps):
    corps["etat"].update(phase="NREM3", satiete=True)
    out = P._soumettre_ou_differer("proposal:a", "app/forge_x.py", "x = 2\n", "desc", None)
    assert out["verdict"] == "DIFFERE" and corps["juges"] == []
    assert P.consolider()["jugees"] == 0 and len(_file(corps)) == 1


def test_sommeil_hors_satiete_juge_tout_de_suite(corps):
    corps["etat"]["phase"] = "NREM3"
    out = P._soumettre_ou_differer("proposal:a", "app/forge_x.py", "x = 2\n", "desc", None)
    assert out["verdict"] == "SURVIT" and corps["juges"] == ["app/forge_x.py"]


def test_phase_illisible_pas_de_mutation(corps, monkeypatch):
    def _casse():
        raise RuntimeError("horloge illisible")
    monkeypatch.setattr(P, "_phase_courante", _casse)
    ok, raison = P._mutation_autorisee()
    assert ok is False and "illisible" in raison


def test_transe_cytokine_a_ttl_toujours_eteinte(monkeypatch):
    emises = []
    import types
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_endocrine",
                        types.SimpleNamespace(release=lambda h, level, **kw: emises.append((h, level, kw.get("ttl_s")))))
    monkeypatch.setattr(P, "_ram_en_satiete", lambda: False)
    monkeypatch.setattr(P, "consolider", lambda: {"jugees": 0})

    def _plante(dry_run=False):
        raise RuntimeError("cycle casse")
    monkeypatch.setattr(P, "run_once", _plante)
    with pytest.raises(RuntimeError):
        P.transe_de_guerison(dry_run=False, _dormir=lambda s: None)
    assert emises[0][0] == P.CYTOKINE_RSI and emises[0][1] > 0 and emises[0][2] and emises[0][2] > 0
    assert emises[-1][0] == P.CYTOKINE_RSI and emises[-1][1] == 0.0


def test_transe_abandonnee_si_la_ram_ne_redescend_pas(monkeypatch):
    import types
    emises = []
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_endocrine",
                        types.SimpleNamespace(release=lambda h, level, **kw: emises.append(level)))
    monkeypatch.setattr(P, "_ram_en_satiete", lambda: True)
    appels = []
    monkeypatch.setattr(P, "run_once", lambda dry_run=False: appels.append(1) or {})
    r = P.transe_de_guerison(dry_run=False, attente_max_s=30, pas_s=10, _dormir=lambda s: None)
    assert r["transe"] == "ABANDONNEE" and appels == [] and emises[-1] == 0.0


def test_la_soif_lit_la_cytokine(monkeypatch):
    import types

    import forge_epistemic_daemon as D
    monkeypatch.setitem(sys.modules, "nokido_agent.app.forge_endocrine",
                        types.SimpleNamespace(read=lambda h: 1.0 if h == "CYTOKINE_RSI" else 0.0))
    tendu, raison = D.ev.corps_sous_tension()
    assert tendu is True and "transe" in raison
