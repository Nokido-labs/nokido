# -*- coding: utf-8 -*-
"""NR -- `forge_pip_audit_mesure --tous-les-envs` : chaque env du poste, et ce qui n'a pas ete vu.

Mesure du 2026-10-12 : l'env des SERVICES (miniforge base, 835 paquets) portait 67 paquets
vulnerables invisibles -- Dependabot ne lit que les manifestes du depot, et ce producteur ne
decrivait que SON interpreteur. La phase 3 audite chaque env conda et `uv tool`.

Ce que ces tests tiennent :
- un env ILLISIBLE est un NON VU nomme, jamais un env sain ni un env oublie ;
- une mesure echouee n'ecrit AUCUN rapport (la regle du producteur, etendue aux envs) ;
- l'interpreteur auditeur est COUVERT par le rapport principal, pas audite deux fois ;
- les rapports d'env restent HORS du glob `pip_audit*` que lisent le gate et le reconcilier ;
- le drapeau traverse le VRAI point d'entree `main(argv)`, et le circadien le demande.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "forge_pip_audit_mesure.py"
JOUR = "2026-10-13"


def _module():
    spec = importlib.util.spec_from_file_location("forge_pip_audit_mesure_envs_nr", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _poste(tmp_path, monkeypatch, m, envs=("x",)):
    """Un faux poste : depot/sandbox, racine conda et ses envs, chacun son site-packages."""
    depot = tmp_path / "depot"
    (depot / "sandbox").mkdir(parents=True)
    monkeypatch.setattr(m, "ROOT", depot)
    monkeypatch.setattr(m, "SANDBOX", depot / "sandbox")
    monkeypatch.setattr(m, "CACHE", depot / "sandbox" / "pip_audit_cache")
    racine = tmp_path / "miniforge3"
    prefixes = [racine] + [racine / "envs" / n for n in envs]
    for p in prefixes:
        (p / "Lib" / "site-packages").mkdir(parents=True)
    (racine / "conda-meta").mkdir()
    monkeypatch.setattr(m, "_racine_conda", lambda: racine)
    monkeypatch.setattr(m, "_envs_conda", lambda r: (list(prefixes), None))
    signaux = []
    monkeypatch.setattr(m, "_publier_signal", lambda fait, jour: signaux.append(fait))
    return depot, racine, signaux


def _faux_pip_audit(vulns_par_env=None):
    """pip-audit simule : la cle est le NOM de l'env (dossier qui porte Lib/site-packages)."""
    vulns_par_env = vulns_par_env or {}

    def faux(cible, site=None):
        cle = Path(site).parent.parent.name if site else "principal"
        vulns = vulns_par_env.get(cle, [])
        Path(cible).write_text(json.dumps({"dependencies": [
            {"name": "paquet", "version": "1.0", "vulns": vulns},
            {"name": "autre", "version": "2.0", "vulns": []}]}), encoding="utf-8")
        return (1 if vulns else 0), ""
    return faux


def test_le_drapeau_traverse_le_point_d_entree(tmp_path, monkeypatch):
    m = _module()
    depot, _racine, signaux = _poste(tmp_path, monkeypatch, m)
    uv = tmp_path / "uv_tools"
    uv.mkdir()  # aucun outil installe : dossier VU et vide, pas un trou
    monkeypatch.setattr(m, "_sortie", _faux_pip_audit({"x": [{"id": "GHSA-test"}]}))
    jour = m._dt.date.today().isoformat()

    rc = m.main(["--tous-les-envs", "--uv-tools", str(uv)])

    assert rc == 0, "tout vu et mesure : rc 0 attendu (rc=%s)" % rc
    sb = depot / "sandbox"
    rapport_x = json.loads((sb / ("audit_envs_x_%s.json" % jour)).read_text(encoding="utf-8"))
    meta = rapport_x["_nokido_meta"]
    assert meta["portee"] == "SITE_PACKAGES_DE_CET_ENVIRONNEMENT"
    assert meta["n_avis"] == 1
    assert "interpreteur" not in meta, "un rapport d'env ne doit pas porter le nom de l'AUDITEUR"
    assert meta["interpreteur_auditeur"]
    assert (sb / ("audit_envs_base_%s.json" % jour)).exists()
    # Le gate et le reconcilier lisent `pip_audit*` : un rapport d'env n'y entre JAMAIS.
    assert sorted(p.name for p in sb.glob("pip_audit*.json")) == ["pip_audit_%s.json" % jour]
    assert not list(sb.glob("*.partiel")), "un .partiel parasite est reste"
    assert (sb / ("audit_envs_synthese_%s.json" % jour)).exists()
    assert signaux and signaux[0]["pointer_ref"].startswith("file:sandbox/audit_envs_synthese_")
    assert signaux[0]["envs_touches"] == {"x": 1}
    assert signaux[0]["non_vus"] == []


def test_un_env_ILLISIBLE_est_un_non_vu_nomme(tmp_path, monkeypatch):
    m = _module()
    _depot, racine, _ = _poste(tmp_path, monkeypatch, m, envs=("x", "ferme"))
    ferme = os.path.normcase(str(racine / "envs" / "ferme" / "Lib" / "site-packages"))
    vrai = os.listdir

    def listdir(p="."):
        if os.path.normcase(str(p)) == ferme:
            raise PermissionError(13, "Acces refuse")
        return vrai(p)
    monkeypatch.setattr(m.os, "listdir", listdir)

    inv = m.envs_a_auditer(uv_tools=str(tmp_path / "absent"), ici=tmp_path / "ailleurs")

    assert "ferme" not in [e["nom"] for e in inv["cibles"]]
    nv = {e["nom"]: e for e in inv["non_vus"]}
    assert nv["ferme"]["etat"].startswith("ILLISIBLE"), (
        "un acces refuse lu comme une absence = un env jamais audite et jamais signale")
    assert nv["uv-tools"]["etat"] == "ABSENT", "le dossier uv introuvable doit etre DIT"


def test_une_mesure_echouee_n_ecrit_aucun_rapport_et_rend_3(tmp_path, monkeypatch):
    m = _module()
    depot, _racine, signaux = _poste(tmp_path, monkeypatch, m)
    uv = tmp_path / "uv"
    uv.mkdir()
    monkeypatch.setattr(m, "_sortie", lambda cible, site=None: (
        1, "requests.exceptions.ConnectionError: Max retries exceeded"))

    rc = m.tous_les_envs(JOUR, str(uv))

    assert rc == 3, "une mesure partielle ne sort jamais en rc 0"
    sb = depot / "sandbox"
    assert not list(sb.glob("audit_envs_x_*")) and not list(sb.glob("audit_envs_base_*")), (
        "un rapport d'env ecrit sans mesure se relirait comme « aucune vulnerabilite »")
    assert not list(sb.glob("*.partiel"))
    synth = json.loads((sb / ("audit_envs_synthese_%s.json" % JOUR)).read_text(encoding="utf-8"))
    assert {e["etat"] for e in synth["mesures"]} == {"NON_MESURE"}
    assert set(signaux[0]["non_vus"]) == {"base", "x"}


def test_l_interpreteur_auditeur_est_COUVERT_pas_audite_deux_fois(tmp_path, monkeypatch):
    m = _module()
    _depot, racine, _ = _poste(tmp_path, monkeypatch, m)
    inv = m.envs_a_auditer(uv_tools=str(tmp_path / "absent"), ici=racine / "envs" / "x")
    assert [e["nom"] for e in inv["couverts"]] == ["x"]
    assert "x" not in [e["nom"] for e in inv["cibles"]]


def test_les_outils_uv_sont_des_envs_et_les_fichiers_du_dossier_non(tmp_path, monkeypatch):
    m = _module()
    _poste(tmp_path, monkeypatch, m, envs=())
    uv = tmp_path / "uv"
    (uv / "aider-chat" / "Lib" / "site-packages").mkdir(parents=True)
    (uv / ".lock").write_text("", encoding="utf-8")
    inv = m.envs_a_auditer(uv_tools=str(uv), ici=tmp_path / "ailleurs")
    assert [e["nom"] for e in inv["cibles"] if e["type"] == "uv_tool"] == ["aider-chat"]
    assert not inv["non_vus"]


def test_le_circadien_demande_tous_les_envs(tmp_path, monkeypatch):
    for _p in (str(ROOT), str(ROOT / "app")):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import forge_circadian as C
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(C, "current_phase", lambda: C.Phase.NREM1)
    vieux = tmp_path / "pip_audit_2026-09-01.json"
    vieux.write_text("{}", encoding="utf-8")
    os.utime(vieux, (time.time() - 10 * 86400, time.time() - 10 * 86400))
    lance = []

    def _faux_lanceur(script, **kw):
        lance.append(kw)
        return {"job_id": "job_test"}

    res = C._mesurer_dependances_vulnerables(hist=tmp_path, lanceur=_faux_lanceur)
    assert res["pip_audit"] == "REQUESTED"
    args = lance[0].get("script_args") or ""
    assert "--tous-les-envs" in args, "le producteur nocturne n'audite que l'env du job"
    assert "pip_audit_history" in args
