"""NR -- le parcours PAQUET de l'acceptation (owner 2026-10-13 : « fiabiliser completement le lancement fonctionnel
total de Nokido »). Le README avouait « the hub starts and serves from the wheel : not measured yet ».

Ce qui est garde :
  * `--paquet` (le point d'entree REEL, pas une fonction isolee) deroule le parcours du README dans l'ordre :
    venv, install, import hors clone, doctor, coffre, hub, /mcp mot pour mot, protocole, premier usage, arret,
    desinstallation -- et ecrit rapport_paquet.json ;
  * le hub du paquet recoit l'environnement d'un INCONNU : aucune variable LAFORGE_/NOKIDO_ du poste, un HOME a lui,
    un port dedie (jamais 8766, celui d'un hub deja vivant) ;
  * tools/list se compte en JSON simple ET en flux SSE ; une reponse sans outils compte 0, jamais « ok » ;
  * le workflow lance le parcours sur les trois systemes, l'entree passee par l'environnement (pas d'injection).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(60)

RACINE = Path(__file__).resolve().parents[2]
WORKFLOW = RACINE / ".github" / "workflows" / "installation-complete.yml"
ORDRE = ["_p_venv", "_p_install", "_p_hors_clone", "_p_composants", "_p_doctor", "_p_secrets", "_p_hub",
         "_p_mcp_doc", "_p_mcp_protocole", "_p_rag_sans_cle", "_p_premiere_requete_cli", "_p_premier_usage",
         "_p_arret", "_p_desinstallation"]


def _module():
    spec = importlib.util.spec_from_file_location("acceptance_paquet_nr",
                                                  RACINE / "tools" / "forge_install_acceptance.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.R.clear()
    return m


def test_le_point_d_entree_paquet_deroule_le_parcours_du_readme(monkeypatch, tmp_path):
    m = _module()
    vus: list = []
    for nom in ORDRE:
        monkeypatch.setattr(m, nom, lambda nom=nom: (vus.append(nom), m.R.__setitem__(
            nom, {"etat": "PASS", "detail": "simule", "duree_s": 0.0})))
    monkeypatch.setattr(m, "RUNTIME", tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(sys, "argv", ["forge_install_acceptance.py", "--paquet=nokido-agent==0.0.0"])
    assert m.main() == 0
    assert vus == ORDRE
    assert set(json.loads((tmp_path / "rapport_paquet.json").read_text(encoding="utf-8"))) == set(ORDRE)


def test_environnement_d_inconnu(monkeypatch):
    m = _module()
    monkeypatch.setenv("LAFORGE_ROOT", "C:/poste/du/dev")
    monkeypatch.setenv("NOKIDO_RAG_DB", "%NOKIDO_DATA%\embeddings.db")
    monkeypatch.setenv("PYTHONPATH", str(RACINE))
    env = m._env_p()
    assert not [k for k in env if k.upper().startswith(("LAFORGE_", "NOKIDO_")) and k != "LAFORGE_HUB_PORT"]
    assert "PYTHONPATH" not in env and env["PYTHONSAFEPATH"] == "1"
    assert env["LAFORGE_HUB_PORT"] == str(m.PORT_P) and m.PORT_P != 8766
    assert env["HOME"] == str(m.HOME_P) and env["USERPROFILE"] == str(m.HOME_P)
    assert m.HORS_P.resolve() != RACINE.resolve() and not m.HORS_P.resolve().is_relative_to(RACINE.resolve() / "tools")


@pytest.mark.parametrize("corps, attendu", [
    ('{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"a"},{"name":"b"}]}}', 2),
    ('event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"a"}]}}\n\n', 1),
    ('{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"Bad Request"}}', 0),
    ("Internal Server Error", 0),
])
def test_outils_comptes_en_json_et_en_sse(corps, attendu):
    assert _module().nb_outils(corps) == attendu


def test_le_premier_usage_est_mesure_pas_juge(monkeypatch):
    """Ce qu'un inconnu SANS cle doit obtenir de `ask` n'est pas tranche : MESURE (observer avant d'enforcer)."""
    m = _module()
    envoye: list = []
    monkeypatch.setattr(m, "_mcp", lambda corps, session=None: (envoye.append(corps), (500, None, "aucun fournisseur"))[1])
    m.R["paquet_hub"] = {"etat": "PASS"}
    m._p_premier_usage()
    assert m.R["paquet_premier_usage"]["etat"] == "MESURE" and "aucun fournisseur" in m.R["paquet_premier_usage"]["detail"]
    assert envoye[0]["params"]["name"] == "ask" and envoye[0]["params"]["arguments"]["provider"] == "auto"


def test_nokido_hub_sans_dependances_serveur_dit_quoi_installer(monkeypatch, capsys):
    """Mesure du 13/10 : `pip install nokido-agent` (CORE = client) puis `nokido-hub` -> traceback uvicorn."""
    import importlib.util as iu
    sys.path.insert(0, str(RACINE / "tools"))
    import nokido_hub_cli
    vrai = iu.find_spec
    monkeypatch.setattr(iu, "find_spec", lambda nom, *a, **k: None if nom == "uvicorn" else vrai(nom, *a, **k))
    assert nokido_hub_cli.main([]) == 2
    err = capsys.readouterr().err
    assert "uvicorn" in err and 'nokido-agent[organisme]' in err and 'nokido-agent[hub]' in err


@pytest.mark.parametrize("reponse, attendu", [
    ((200, None, 'data: {"result":{"content":[{"type":"text","text":"docs/wiki/01-Installation.md ..."}]}}'), "SERVI"),
    ((200, None, '{"result":{"content":[{"type":"text","text":"GATE_DENIED: ring 3 <= requis 2"}]}}'), "REFUSE"),
    ((200, None, '{"result":{"content":[],"isError": true}}'), "REFUSE"),
    ((None, None, "ConnectionRefusedError"), "ILLISIBLE"),
])
def test_appel_anonyme_mesure_pas_juge(monkeypatch, reponse, attendu):
    """Decision owner 13/10 : rien ne s'ouvre aux anonymes -- leur acces se MESURE, la porte est le CLI."""
    m = _module()
    envoye: list = []
    monkeypatch.setattr(m, "_mcp", lambda corps, session=None: (envoye.append(corps), reponse)[1])
    m.R["paquet_hub"] = {"etat": "PASS"}
    m._p_rag_sans_cle()
    assert m.R["paquet_rag_sans_cle"]["etat"] == "MESURE"
    assert m.R["paquet_rag_sans_cle"]["detail"].startswith(attendu)
    assert envoye[0]["params"]["name"] == "rag" and envoye[0]["params"]["arguments"]["action"] == "search"


@pytest.mark.parametrize("sortie, attendu", [
    ((0, "01-Installation.md -- How do I install Nokido with pip"), "PASS"),
    ((0, "GATE_DENIED: ring 3 <= requis 2 ... Installation"), "FAIL"),
    ((1, "Traceback ... Installation"), "FAIL"),
])
def test_premiere_requete_par_le_cli(monkeypatch, sortie, attendu):
    m = _module()
    lances: list = []
    monkeypatch.setattr(m, "_sh_p", lambda cmd, timeout=600: (lances.append([str(c) for c in cmd]), sortie)[1])
    m.R["paquet_hub"] = {"etat": "PASS"}
    m._p_premiere_requete_cli()
    assert m.R["paquet_premiere_requete_cli"]["etat"] == attendu
    assert lances[0][0].endswith(("nokido", "nokido.exe")) and lances[0][1:3] == ["hub", "rag"]


def test_bloc_pip_du_readme_suit_ce_que_la_version_sert():
    """0.20.10 ne declarait ni l'extra organisme ni nokido-composants : son bloc ne les annonce pas."""
    sys.path.insert(0, str(RACINE / "tools"))
    import forge_readme_pip as P
    ancien = P.rendre("nokido-agent", "0.20.10")
    assert "[organisme]" not in ancien and "nokido-composants" not in ancien
    neuf = P.rendre("nokido-agent", "0.20.11")
    for attendu in ('pip install "nokido-agent[organisme]==0.20.11"', "nokido-composants --tout", "nokido-doctor",
                    "nokido-hub"):
        assert attendu in neuf
    texte = "intro\n%s\nsuite\n" % P.bloc("nokido-agent", "0.20.11")
    assert P.coherence(texte)[0] == P.ALIGNE


def test_epinglages_embarques_dans_la_wheel():
    """Mesure du 13/10 : installe par pip, le doctor ne trouvait pas distribution/packs/*.toml et ne savait pas
    quoi telecharger (« NON EPINGLE »). Ils voyagent comme config/ : package-dir + graft."""
    pyproject = (RACINE / "pyproject.toml").read_text(encoding="utf-8")
    manifest = (RACINE / "MANIFEST.in").read_text(encoding="utf-8")
    assert '"nokido_agent.distribution" = "distribution"' in pyproject
    assert '"nokido_agent.distribution",' in pyproject
    assert "graft distribution" in manifest.splitlines()
    assert (RACINE / "distribution" / "packs" / "local-llm.toml").is_file()


def test_schema_de_la_base_embarque_sans_identite_des_auteurs():
    """Mesure du 13/10 : installe par pip, forge_db_bootstrap mourait en « seed dir absent » -- sans schema, le hub
    refusait tout (table des rangs et access_switches absentes, fail-closed)."""
    pyproject = (RACINE / "pyproject.toml").read_text(encoding="utf-8")
    manifest = (RACINE / "MANIFEST.in").read_text(encoding="utf-8").splitlines()
    assert '"nokido_agent.seed" = "seed"' in pyproject and '"nokido_agent.seed",' in pyproject
    assert "graft seed" in manifest and "exclude seed/commit_intel.jsonl" in manifest
    assert (RACINE / "seed" / "schema_base.sql").is_file()


@pytest.mark.parametrize("win", [True, False])
def test_arbre_arrete_meme_sans_psutil_sur_l_interpreteur_du_banc(monkeypatch, win):
    """Parcours paquet 3 OS du 13/10 : le banc tourne sur l'interpreteur du RUNNER, sans psutil -- « racine tuee
    seule », les services enfants survivaient. Sans psutil : taskkill /T sous Windows, pgrep -P ailleurs."""
    m = _module()
    monkeypatch.setitem(sys.modules, "psutil", None)          # import psutil -> ImportError
    monkeypatch.setattr(m, "WIN", win)
    lances, tues = [], []
    arbre = {"100": "101 102", "101": "103", "102": "", "103": ""}

    def faux_run(cmd, **_):
        lances.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": arbre.get(cmd[-1], "") if cmd[0] == "pgrep" else ""})()

    monkeypatch.setattr(m.subprocess, "run", faux_run)
    monkeypatch.setattr(m.os, "kill", lambda pid, sig: tues.append(pid))
    racine = type("P", (), {"pid": 100, "kill": lambda self: tues.append("racine")})()
    m._arreter_arbre(racine)
    if win:
        assert lances == [["taskkill", "/PID", "100", "/T", "/F"]] and tues == ["racine"]
    else:
        assert sorted(p for p in tues if p != "racine") == [101, 102, 103] and tues[-1] == "racine"


def test_workflow_lance_le_parcours_sur_trois_systemes_sans_injection():
    texte = WORKFLOW.read_text(encoding="utf-8")
    bloc = texte.split("\n  paquet:", 1)[1].split("\n  organisme:", 1)[0]
    for os_ in ("windows-latest", "ubuntu-24.04", "macos-latest"):
        assert os_ in bloc
    assert '--paquet=$SPEC_PAQUET' in bloc
    run = [l for l in bloc.splitlines() if l.strip().startswith("run:")]
    assert run and not any("${{" in l for l in run), "une entree de workflow interpolee dans un script = injection"
    assert "rapport_paquet.json" in bloc
