"""NR -- les chemins machine des [vars] du superviseur sont DECOUVERTS a l'installation (2026-10-08).

Mesure sur VM neuve (Windows, Linux, macOS ; run 37816375828) : 0 des 60 services actifs ne tournait. Le dist publie
`[vars]` avec des chemins generises (`%USERPROFILE%/miniforge3/envs/laforge_py314/python.exe`) que personne ne
developpe, sans variante Linux/macOS : le hub ne demarrait pas (`launch failed -- NotFound`) et 33 services
l'attendaient (`dep :8766 not open yet`). Le poste de reference marche parce que SES chemins existent.

Garanties :
  * `vars_machine()` ne remplace JAMAIS une variable dont le chemin declare existe (poste de reference inchange) ;
  * les interpreteurs prennent celui ou Nokido est installe ; deno/llama viennent de la sonde a trois voies ;
    une variable introuvable est DITE (ABSENT), jamais inventee ;
  * `ecrire_vars_local()` ecrit un TOML valide, et rien du tout quand il n'y a rien a ecrire ;
  * `nokido-doctor --ecrire-vars` est le remede nomme ; le chargeur Deno fusionne le fichier, developpe `%NOM%`
    et DIT les chemins restes non resolus ; le fichier est ignore par git ;
  * la mesure de l'organisme ecrit les variables AVANT de lancer le superviseur, comme l'installeur.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _d in ("app", "tools"):
    _p = str(ROOT / _d)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import forge_install_prerequis as P  # noqa: E402

pytestmark = pytest.mark.timeout(60)


def test_le_developpement_suit_l_environnement(monkeypatch, tmp_path):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert P._developpe("%USERPROFILE%/miniforge3/python.exe") == "%s/miniforge3/python.exe" % tmp_path
    monkeypatch.delenv("USERPROFILE")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(P.Path, "home", classmethod(lambda cls: tmp_path))
    assert P._developpe("%USERPROFILE%/x") == "%s/x" % tmp_path, "hors Windows, USERPROFILE retombe sur HOME"
    assert P._developpe("%INCONNU_XYZ%/x") == "%INCONNU_XYZ%/x", "une variable inconnue reste visible, jamais vide"


def test_la_racine_generisee_se_developpe_comme_dans_le_chargeur(monkeypatch):
    monkeypatch.delenv("NOKIDO_ROOT", raising=False)
    monkeypatch.delenv("NOKIDO_WORKSPACE", raising=False)
    assert P._developpe("%NOKIDO_ROOT%/tools") == P.ROOT.as_posix() + "/tools"
    assert P._developpe("%NOKIDO_WORKSPACE%/netcfg") == P.ROOT.parent.as_posix() + "/netcfg"


def test_decisions_owner_du_08_10_dans_le_toml():
    """AGY par variables (depot EPINGLE, jamais ${ROOT} : piege laforge-cowork du 13/08) ; runner CI propre au poste."""
    import tomllib as _t
    with open(ROOT / "proxy_deno" / "core" / "services.toml", "rb") as f:
        doc = _t.load(f)
    svc = {s["name"]: s for s in doc["service"]}
    agy = svc["NokidoTaskExecutorAntigravity"]
    assert agy["cmd"] == "${PYTHON}" and agy["cwd"] == "${NOKIDO_DEPOT}"
    assert agy["args"][0] == "${NOKIDO_DEPOT}/tools/forge_task_executor.py"
    assert "NOKIDO_DEPOT" in doc["vars"]
    assert svc["NokidoCIRunner"].get("propre_au_poste") is True
    assert "propre_au_poste" in (ROOT / "proxy_deno" / "core" / "service_loader.ts").read_text(encoding="utf-8")


def test_vars_machine_ne_remplace_jamais_un_chemin_present(monkeypatch, tmp_path):
    present = tmp_path / "python.exe"
    present.write_text("")
    monkeypatch.setattr(P, "_vars_du_toml", lambda: {
        "ROOT": ".", "PYTHON": str(present), "PY314": "%USERPROFILE%/nulle_part/python.exe",
        "DENO": "%USERPROFILE%/nulle_part/deno.exe", "MYSTERE": str(tmp_path / "nulle_part" / "x.exe")})
    monkeypatch.setattr(P, "_sonde_binaire", lambda noms, usuels=(): (P.PRESENT, "PATH: /opt/deno/bin/deno"))
    out = P.vars_machine()
    assert "PYTHON" not in out and "ROOT" not in out, "un chemin present n'est jamais remplace"
    assert out["PY314"] == {"valeur": sys.executable.replace("\\", "/"), "etat": P.PRESENT,
                            "detail": "interpreteur ou Nokido est installe"}
    assert out["DENO"]["valeur"] == "/opt/deno/bin/deno" and out["DENO"]["etat"] == P.PRESENT
    assert out["MYSTERE"]["etat"] == P.ABSENT and out["MYSTERE"]["valeur"] is None


def test_le_dossier_qdrant_vient_de_la_build_extraite(monkeypatch, tmp_path):
    # 2026-10-09 : le binaire Qdrant etait code en dur (C:\tmp\qdrant_bin) ; sur VM neuve, NokidoQdrantServer mourait
    # « binaire absent » et EpistemicSoif attendait :6333 (mesure organisme 3).
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "_vars_du_toml", lambda: {"QDRANT_BIN": str(tmp_path / "nulle_part")})
    assert P.vars_machine()["QDRANT_BIN"]["etat"] == P.ABSENT, "un dossier sans binaire n'est jamais retenu"
    exe = tmp_path / "runtime" / "qdrant" / ("qdrant" + P._EXE)
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert P.vars_machine()["QDRANT_BIN"] == {"valeur": exe.parent.as_posix(), "etat": P.PRESENT,
                                              "detail": "build epinglee extraite"}
    toml = (ROOT / "proxy_deno" / "core" / "services.toml").read_text(encoding="utf-8")
    assert 'QDRANT_BIN  = "C:/tmp/qdrant_bin"' in toml, "valeur du poste de reference = l'ancien defaut"
    assert 'LAFORGE_QDRANT_BIN = "${QDRANT_BIN}"' in toml
    lanceur = (ROOT / "tools" / "forge_qdrant_server.py").read_text(encoding="utf-8")
    assert '"qdrant.exe" if os.name == "nt" else "qdrant"' in lanceur and "LOG.parent.mkdir" in lanceur


def test_qdrant_sans_config_reste_en_loopback_sans_telemetrie():
    # config.yaml du poste de reference : host loopback, telemetry_disabled (fiche chantier_qdrant_rag_2026-07-06).
    # Sans lui, Qdrant ecoute sur toutes les interfaces et envoie sa telemetrie : la machine neuve doit garder ces choix.
    import importlib.util
    spec = importlib.util.spec_from_file_location("forge_qdrant_server_nr", ROOT / "tools" / "forge_qdrant_server.py")
    q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(q)
    env = q.env_sans_config()
    assert env["QDRANT__SERVICE__HOST"] == "127.0.0.1" and env["QDRANT__TELEMETRY_DISABLED"] == "true"
    assert Path(env["QDRANT__STORAGE__STORAGE_PATH"]).parent == ROOT / "sandbox", "donnees = sandbox/, pas runtime/"


def test_ecrire_vars_local_ecrit_un_toml_valide_et_dit_les_absents(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "vars_machine", lambda: {
        "PY314": {"valeur": "C:/Users/a b/python.exe", "etat": P.PRESENT, "detail": "x"},
        "MYSTERE": {"valeur": None, "etat": P.ABSENT, "detail": "aucune sonde"}})
    cible = tmp_path / "config" / "vars.local.toml"
    bilan = P.ecrire_vars_local(cible)
    assert bilan["ecrit"] is True and bilan["ecrites"] == ["PY314"] and bilan["absentes"] == ["MYSTERE"]
    doc = tomllib.loads(cible.read_text(encoding="utf-8"))
    assert doc["vars"] == {"PY314": "C:/Users/a b/python.exe"}
    assert "MYSTERE" in cible.read_text(encoding="utf-8"), "l'absente est DITE en commentaire"


def test_rien_a_ecrire_ne_cree_aucun_fichier(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "vars_machine", lambda: {})
    cible = tmp_path / "vars.local.toml"
    assert P.ecrire_vars_local(cible)["ecrit"] is False and not cible.exists()


def test_doctor_expose_le_remede_ecrire_vars(monkeypatch, capsys):
    import nokido_doctor as D
    monkeypatch.setattr(D.P, "ecrire_vars_local", lambda chemin=None: {
        "ecrit": True, "chemin": "config/vars.local.toml", "ecrites": ["PYTHON"], "absentes": ["NETCFG_DIR"]})
    assert D.main(["--ecrire-vars"]) == 0
    sortie = capsys.readouterr().out
    assert "PYTHON" in sortie and "NETCFG_DIR" in sortie


def test_le_chargeur_fusionne_les_vars_machine_et_dit_les_non_resolues():
    src = (ROOT / "proxy_deno" / "core" / "service_loader.ts").read_text(encoding="utf-8")
    assert "config/vars.local.toml" in src, "le chargeur doit lire les chemins de la machine"
    assert "%([A-Za-z_][A-Za-z0-9_]*)%" in src, "le chargeur developpe la forme %NOM% du dist"
    assert "NON RESOLU" in src, "un chemin reste non resolu se DIT au journal"
    assert "_locales.empreinte" in src, "une edition du fichier machine invalide le cache du chargeur"


def test_le_fichier_machine_n_est_jamais_versionne():
    assert "config/vars.local.toml" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_le_superviseur_est_type_et_son_chargeur_execute_en_ci():
    """deno ne s'execute pas sous les comptes de service de ci_local : le typage et le chargeur sont verifies par la
    CI du poste (compte owner) et sur les VM -- jamais laisses a « la preuve viendra plus tard »."""
    prive = (ROOT / ".github" / "workflows" / "ci-selfhosted.yml").read_text(encoding="utf-8")
    vm = (ROOT / ".github" / "workflows" / "installation-complete.yml").read_text(encoding="utf-8")
    for texte in (prive, vm):
        assert "deno check proxy_deno/core/supervisor.ts" in texte
        assert "deno test -A proxy_deno/core/service_loader_test.ts" in texte
    assert "deno introuvable" in prive and "exit 1" in prive, "deno absent = echec dit, jamais un vert muet"
    test_ts = (ROOT / "proxy_deno" / "core" / "service_loader_test.ts").read_text(encoding="utf-8")
    assert "IDENTIQUES a l'ancienne resolution" in test_ts


def test_le_superviseur_prend_l_interpreteur_resolu_pour_ses_lanceurs_runas():
    """2e mesure VM (08/10) : `MINIFORGE` codait en dur l'interpreteur du poste de reference ; les 10 services runAs
    echouaient ailleurs. Il vient desormais de la variable PYTHON RESOLUE, le litteral n'etant plus qu'un repli."""
    sup = (ROOT / "proxy_deno" / "core" / "supervisor.ts").read_text(encoding="utf-8")
    assert "resoudreVars(defaultTomlPath(), { ROOT })?.PYTHON" in sup
    assert "const MINIFORGE = resoudreVars(" in sup, "plus aucun interpreteur runAs code en dur"
    wf = (ROOT / ".github" / "workflows" / "installation-complete.yml").read_text(encoding="utf-8")
    assert "logs/supervisor/" in wf, "les journaux des services expliquent les plantages au demarrage"


def test_la_mesure_de_l_organisme_ecrit_les_vars_avant_le_superviseur():
    src = (ROOT / "tools" / "forge_install_acceptance.py").read_text(encoding="utf-8")
    corps = src.split("def _organisme", 1)[1]
    assert "--ecrire-vars" in corps
    assert corps.index("--ecrire-vars") < corps.index("supervisor.ts")
