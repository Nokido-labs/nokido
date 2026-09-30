"""NR -- etape F du coffre (2026-09-28) : le superviseur tient ses jetons du COFFRE, et le DIT.

Mesure du jour : `supervisor.ts` charge deja, au demarrage et sous SYSTEM, ses jetons par le
guichet (`_loadVaultToEnv`, coffre reserve d'abord) -- ils ECRASENT ceux du registre NSSM,
redondants et lisibles par les comptes bac a sable. L'etape F retire ces valeurs de NSSM.
Mais le chargeur TAISAIT ses echecs (stderr jete, retour 0) : NSSM masquait un echec, qui
laisserait sinon le superviseur sans jeton (toute mutation refusee).

Contrats :
  1. l'extrait Python embarque, EXECUTE ici tel qu'il est dans supervisor.ts, rend un JSON
     `{"valeurs": ..., "erreur": ...}` : les valeurs presentes, la CAUSE d'un echec (type
     d'exception seul), rien sur stderr ;
  2. il couvre les noms que NSSM portait (maitre, secret JWT) et le jeton du superviseur ;
  3. le demarrage journalise le bilan par NOMS (charges, absents, erreur) et ALERTE si le
     jeton propre du superviseur manque.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
import pytest

# Timeout 120 s (audit stabilite CI, 2026-09-29) -- risque : sous-processus python x2 (l.58)
# Au-dela de 30 s, pytest-timeout (methode thread) tue TOUTE la session pytest sous Windows.
pytestmark = pytest.mark.timeout(120)

ROOT = Path(__file__).resolve().parents[2]
SUP = ROOT / "proxy_deno" / "core" / "supervisor.ts"


def _source() -> str:
    return SUP.read_text(encoding="utf-8")


# HERMETIQUE (mesure CI 36440801595, compte user) : sans `-I -S`, le sous-processus trouvait
# `forge_secrets` par l'ENVIRONNEMENT du runner (PYTHONPATH, site-packages, installation
# editable) et non par le dossier que l'extrait injecte -- « aucun guichet importable » ne
# pouvait donc pas echouer sur le runner, alors qu'il echoue en local. Seul le dossier `app`
# pose par l'extrait doit etre visible : c'est ce que le contrat teste.
PY_ISOLE = [sys.executable, "-I", "-S", "-c"]


def _extrait_python(dossier_app: Path, cles: list) -> str:
    m = re.search(r"function _loadVaultToEnv\(\).*?const py = `(.*?)`;", _source(), re.S)
    assert m, "extrait Python du chargeur introuvable"
    py = m.group(1)
    py = py.replace('${join(ROOT, "app").replaceAll("\\\\", "/")}', str(dossier_app).replace("\\", "/"))
    py = py.replace("${JSON.stringify(keys)}", json.dumps(cles))
    assert "${" not in py, "interpolation non resolue dans l'extrait"
    return py


def test_l_extrait_du_chargeur_rend_valeurs_et_cause_sans_rien_sur_stderr(tmp_path):
    (tmp_path / "forge_secrets.py").write_text(
        "def get_secret(k):\n"
        "    if k == 'CASSE':\n"
        "        raise PermissionError('refus de test')\n"
        "    return {'PRESENT': 'valeur-de-test'}.get(k)\n", encoding="utf-8")
    py = _extrait_python(tmp_path, ["PRESENT", "ABSENT", "CASSE"])
    r = subprocess.run(PY_ISOLE + [py], capture_output=True, text=True, errors="replace", timeout=60)
    d = json.loads(r.stdout.strip())
    ok = (d.get("valeurs"), d.get("erreur"), r.stderr.strip())
    assert ok == ({"PRESENT": "valeur-de-test"}, "get_secret: PermissionError", "")


def test_sans_guichet_importable_l_extrait_dit_pourquoi(tmp_path):
    py = _extrait_python(tmp_path / "vide", ["PRESENT"])
    r = subprocess.run(PY_ISOLE + [py], capture_output=True, text=True, errors="replace", timeout=60)
    d = json.loads(r.stdout.strip())
    ok = (d.get("valeurs"), (d.get("erreur") or "").startswith("import forge_secrets:"))
    assert ok == ({}, True)


def test_le_chargeur_couvre_ce_que_nssm_portait():
    bloc = re.search(r"function _loadVaultToEnv\(\).*?const keys = \[(.*?)\];", _source(), re.S).group(1)
    for nom in ("FORGE_MCP_TOKEN", "LAFORGE_JWT_SECRET", "LAFORGE_SUPERVISOR_TOKEN", "FORGE_TOKEN_SUPERVISOR"):
        assert f'"{nom}"' in bloc, nom


def test_le_demarrage_dit_le_bilan_par_noms_et_alerte_sans_jeton_propre():
    src = _source()
    ok = ("coffre: ${_VAULT_BILAN.charges.length} secret(s) charge(s)" in src,
          "_VAULT_BILAN.absents.join" in src, "_VAULT_BILAN.erreur" in src,
          '_VAULT_BILAN.charges.includes("LAFORGE_SUPERVISOR_TOKEN")' in src,
          'stderr: "null"' in src)
    assert ok == (True, True, True, True, True)
